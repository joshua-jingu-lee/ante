"""DART OpenAPI 소스 어댑터."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Any, cast
from xml.etree import ElementTree

import aiohttp

from ante.feed.sources.base import (
    RateLimiter,
    describe_source_error,
    redact_source_text,
)

logger = logging.getLogger(__name__)


BASE_URL = "https://opendart.fss.or.kr/api"
TPS_LIMIT = 10.0
DAILY_LIMIT = 20_000
BATCH_SIZE = 100
REQUEST_TIMEOUT = 60

_NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})

REPRT_CODES: dict[str, str] = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}


class ErrorAction(StrEnum):
    """DART API 에러 코드에 따른 행동 분류."""

    OK = "ok"
    NO_DATA = "no_data"
    RETRY = "retry"
    RETRY_ONCE = "retry_once"
    SKIP = "skip"
    DAILY_LIMIT = "daily_limit"
    CRITICAL = "critical"


_ERROR_CODE_MAP: dict[str, ErrorAction] = {
    "000": ErrorAction.OK,
    "010": ErrorAction.CRITICAL,
    "011": ErrorAction.CRITICAL,
    "012": ErrorAction.CRITICAL,
    "013": ErrorAction.NO_DATA,
    "014": ErrorAction.SKIP,
    "020": ErrorAction.DAILY_LIMIT,
    "021": ErrorAction.SKIP,
    "100": ErrorAction.SKIP,
    "101": ErrorAction.SKIP,
    "800": ErrorAction.RETRY,
    "900": ErrorAction.RETRY_ONCE,
    "901": ErrorAction.CRITICAL,
}


def classify_error(status: str) -> ErrorAction:
    """DART status 코드를 행동으로 분류한다."""
    return _ERROR_CODE_MAP.get(status, ErrorAction.RETRY)


class DARTError(Exception):
    """DART API 에러 기본 예외."""

    pass


class DailyLimitExceededError(DARTError):
    """일일 호출 한도 초과."""

    pass


class CriticalApiError(DARTError):
    """키 미등록/만료 등 복구 불가능 에러."""

    pass


class DARTSource:
    """DART OpenAPI 소스 어댑터.

    fetch_corp_codes()로 고유번호 매핑을 확보한 후,
    fetch_financial()로 다중회사 재무제표를 배치 수집한다.
    """

    def __init__(
        self,
        api_key: str,
        rate_limiter: RateLimiter | None = None,
        session: aiohttp.ClientSession | None = None,
        *,
        max_retries: int = 3,
        base_url: str = BASE_URL,
    ) -> None:
        """DARTSource를 초기화한다.

        Args:
            api_key: DART OpenAPI 인증키 (40자리).
            rate_limiter: Rate Limiter 인스턴스. None이면 기본값 생성.
            session: aiohttp 세션. None이면 호출 시 생성.
            max_retries: 최대 재시도 횟수.
            base_url: API 기본 URL.
        """
        self._api_key = api_key
        self._rate_limiter = rate_limiter or RateLimiter(
            tps_limit=TPS_LIMIT, daily_limit=DAILY_LIMIT
        )
        self._session = session
        self._max_retries = max_retries
        self._base_url = base_url

    @property
    def rate_limiter(self) -> RateLimiter:
        """Rate Limiter 인스턴스."""
        return self._rate_limiter

    async def fetch(self, date: str, **kwargs: Any) -> list[dict[str, Any]]:
        """DataSource 프로토콜 구현.

        DART는 날짜별 수집이 아니라 연도+분기별 수집이므로,
        kwargs에서 corp_codes, year, reprt_code를 받아 fetch_financial에 위임한다.

        Returns:
            수집된 레코드 딕셔너리 목록.
        """
        corp_codes = kwargs.get("corp_codes", [])
        year = kwargs.get("year", "")
        reprt_code = kwargs.get("reprt_code", "")
        if not corp_codes or not year or not reprt_code:
            return []
        return await self.fetch_financial(corp_codes, year, reprt_code)

    async def fetch_corp_codes(
        self,
        save_path: Path | None = None,
    ) -> dict[str, str]:
        """DART 고유번호 ZIP을 다운로드하고 파싱한다.

        ZIP 내 XML에서 상장사(stock_code 비어있지 않은)만 추출하여
        corp_code -> stock_code 매핑을 반환한다.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 시.
            CriticalApiError: 인증키 에러 시.
            DARTError: 다운로드 실패 시.
        """
        if self._rate_limiter.is_daily_limit_reached():
            msg = f"일일 한도 90% 도달 ({self._rate_limiter.daily_count}/{DAILY_LIMIT})"
            logger.critical(msg)
            raise DailyLimitExceededError(msg)

        url = f"{self._base_url}/corpCode.xml"
        params = {"crtfc_key": self._api_key}

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            zip_bytes = await self._download_corp_code_zip(session, url, params)
        finally:
            if own_session:
                await session.close()

        corp_code_map = self._parse_corp_code_zip(zip_bytes)

        logger.info(
            "DART 고유번호 수집 완료: 상장사 %d개",
            len(corp_code_map),
        )

        if save_path is not None:
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_text(
                json.dumps(corp_code_map, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info("고유번호 매핑 저장: %s", save_path)

        return corp_code_map

    async def fetch_financial(
        self,
        corp_codes: list[str],
        year: str,
        reprt_code: str,
    ) -> list[dict[str, Any]]:
        """다중회사 주요계정(fnlttMultiAcnt) API를 배치 호출한다.

        corp_codes를 100개씩 나누어 호출하며,
        Rate Limiting과 에러 코드 처리를 수행한다.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 시.
            CriticalApiError: 인증키 에러 시.
        """
        all_items: list[dict[str, Any]] = []

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            for batch_start in range(0, len(corp_codes), BATCH_SIZE):
                batch = corp_codes[batch_start : batch_start + BATCH_SIZE]

                if self._rate_limiter.is_daily_limit_reached():
                    msg = (
                        f"일일 한도 90% 도달 "
                        f"({self._rate_limiter.daily_count}/{DAILY_LIMIT})"
                    )
                    logger.critical(msg)
                    raise DailyLimitExceededError(msg)

                items = await self._fetch_multi_acnt(session, batch, year, reprt_code)
                all_items.extend(items)

                logger.debug(
                    "DART 배치 수집: year=%s reprt=%s batch=%d~%d items=%d",
                    year,
                    reprt_code,
                    batch_start,
                    batch_start + len(batch),
                    len(items),
                )
        finally:
            if own_session:
                await session.close()

        reprt_name = REPRT_CODES.get(reprt_code, reprt_code)
        logger.info(
            "DART 재무제표 수집 완료: year=%s reprt=%s(%s) records=%d",
            year,
            reprt_code,
            reprt_name,
            len(all_items),
        )
        return all_items

    async def validate_credentials(self) -> tuple[bool | None, str | None]:
        """API 키 유효성을 경량 요청 1회로 검증한다.

        offline·타임아웃 등 네트워크 예외는 unknown으로 흡수하며 예외를
        전파하지 않는다. config check가 오프라인에서도 hang/실패 없이
        graceful하게 동작하도록 보장한다.

        Returns:
            (valid, reason) 튜플. valid는 True/False/None.
        """
        url = f"{self._base_url}/fnlttMultiAcnt.json"
        params = {
            "crtfc_key": self._api_key,
            "corp_code": "00000000",
            "bsns_year": "2024",
            "reprt_code": "11011",
        }

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            await self._rate_limiter.acquire()
            self._rate_limiter.increment_daily()
            data = await asyncio.wait_for(
                self._do_request(session, url, params),
                timeout=REQUEST_TIMEOUT,
            )
        except (TimeoutError, aiohttp.ClientError) as exc:
            reason = describe_source_error(exc, self._api_key)
            logger.info("DART 키 검증 불가 (네트워크): %s", reason)
            return None, f"검증 불가 (네트워크): {reason}"
        finally:
            if own_session:
                await session.close()

        status = str(data.get("status", "900"))
        message = str(data.get("message", ""))
        action = classify_error(status)
        status = redact_source_text(status, self._api_key)
        message = redact_source_text(message, self._api_key)

        if action == ErrorAction.CRITICAL:
            return False, f"인증 실패 (status={status}): {message}"
        return True, None

    async def _download_corp_code_zip(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str],
    ) -> bytes:
        """고유번호 ZIP 파일을 다운로드한다."""
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire()
            self._rate_limiter.increment_daily()

            action = ErrorAction.RETRY

            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    async with session.get(url, params=params) as resp:
                        content_type = resp.content_type or ""

                        if "zip" in content_type or "octet-stream" in content_type:
                            return await resp.read()

                        if "json" in content_type or "text" in content_type:
                            body = ""
                            data: Any = None
                            try:
                                body = await resp.text()
                                data = json.loads(body)
                            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                                body = body or str(exc)
                            detail = redact_source_text(body, self._api_key)[:200]
                            status, message = self._response_status(data, detail)

                            action = classify_error(status)
                            status = redact_source_text(status, self._api_key)
                            message = redact_source_text(message, self._api_key)

                            if action == ErrorAction.CRITICAL:
                                msg = f"DART 인증 에러 (status={status}): {message}"
                                logger.critical(msg)
                                raise CriticalApiError(msg)
                            if action == ErrorAction.DAILY_LIMIT:
                                msg = f"DART 일일 한도 초과: {message}"
                                logger.critical(msg)
                                raise DailyLimitExceededError(msg)

                            last_error = DARTError(
                                f"DART 에러 (status={status}): {message}"
                            )
                        else:
                            resp.raise_for_status()
                            return await resp.read()

            except (TimeoutError, aiohttp.ClientError) as exc:
                if (
                    isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status in _NON_RETRYABLE_HTTP_STATUS
                ):
                    msg = f"DART 재시도 불가 HTTP 에러 (status={exc.status})"
                    logger.error(msg)
                    raise DARTError(msg) from exc
                last_error = exc

            retry_cap = 1 if action == ErrorAction.RETRY_ONCE else self._max_retries - 1
            if attempt < retry_cap:
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "DART corpCode 다운로드 실패 (attempt=%d/%d): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    describe_source_error(last_error, self._api_key),
                    delay,
                )
                await asyncio.sleep(delay)
            elif action == ErrorAction.RETRY_ONCE:
                break

        msg = "DART 고유번호 ZIP 다운로드 최종 실패"
        logger.error(msg)
        raise DARTError(msg) from last_error

    @staticmethod
    def _parse_corp_code_zip(zip_bytes: bytes) -> dict[str, str]:
        """ZIP 바이트에서 corp_code -> stock_code 매핑을 추출한다."""
        corp_code_map: dict[str, str] = {}

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            xml_name = zf.namelist()[0]
            with zf.open(xml_name) as xml_file:
                tree = ElementTree.parse(xml_file)
                root = tree.getroot()

                for elem in root.iter("list"):
                    corp_code = elem.findtext("corp_code", "").strip()
                    stock_code = elem.findtext("stock_code", "").strip()

                    if corp_code and stock_code:
                        corp_code_map[corp_code] = stock_code

        return corp_code_map

    async def _fetch_multi_acnt(
        self,
        session: aiohttp.ClientSession,
        corp_codes: list[str],
        year: str,
        reprt_code: str,
    ) -> list[dict[str, Any]]:
        """fnlttMultiAcnt API를 호출한다."""
        url = f"{self._base_url}/fnlttMultiAcnt.json"
        params = {
            "crtfc_key": self._api_key,
            "corp_code": ",".join(corp_codes),
            "bsns_year": year,
            "reprt_code": reprt_code,
        }

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire()
            self._rate_limiter.increment_daily()

            try:
                data, decode_error = await self._request_decoded(session, url, params)
            except (TimeoutError, aiohttp.ClientError) as exc:
                if (
                    isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status in _NON_RETRYABLE_HTTP_STATUS
                ):
                    msg = (
                        f"DART 재시도 불가 HTTP 에러 (status={exc.status}): "
                        f"year={year}, reprt={reprt_code}"
                    )
                    logger.error(msg)
                    raise DARTError(msg) from exc
                last_error = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "DART fnlttMultiAcnt 요청 실패 "
                    "(attempt=%d/%d): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    describe_source_error(exc, self._api_key),
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            status, message = self._response_status(data, decode_error)
            action = classify_error(status)
            status = redact_source_text(status, self._api_key)
            message = redact_source_text(message, self._api_key)

            if action == ErrorAction.OK:
                return self._extract_list(data)

            if action == ErrorAction.NO_DATA:
                logger.debug(
                    "DART 데이터 없음: year=%s reprt=%s corps=%d",
                    year,
                    reprt_code,
                    len(corp_codes),
                )
                return []

            if action == ErrorAction.DAILY_LIMIT:
                msg = f"DART 일일 한도 초과: {message}"
                logger.critical(msg)
                raise DailyLimitExceededError(msg)

            if action == ErrorAction.CRITICAL:
                msg = f"DART 복구 불가능 에러 (status={status}): {message}"
                logger.critical(msg)
                raise CriticalApiError(msg)

            if action == ErrorAction.SKIP:
                msg = f"DART 재시도 불가 에러 (status={status}): {message}"
                logger.error(msg)
                raise DARTError(msg)

            last_error = DARTError(f"DART API 에러 (status={status}): {message}")
            retry_cap = 1 if action == ErrorAction.RETRY_ONCE else self._max_retries - 1
            if attempt < retry_cap:
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "DART API 에러 (attempt=%d/%d, status=%s): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    status,
                    message,
                    delay,
                )
                await asyncio.sleep(delay)
            elif action == ErrorAction.RETRY_ONCE:
                break

        msg = f"DART fnlttMultiAcnt 요청 최종 실패: year={year}, reprt={reprt_code}"
        logger.error(msg)
        raise DARTError(msg) from last_error

    async def _request_decoded(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str],
    ) -> tuple[Any, str | None]:
        """요청해 응답을 돌려주고, 본문 디코드 실패는 (None, 사유)로 바꾼다."""
        try:
            data = await asyncio.wait_for(
                self._do_request(session, url, params),
                timeout=REQUEST_TIMEOUT,
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, redact_source_text(str(exc), self._api_key)[:200]
        return data, None

    @staticmethod
    def _response_status(data: Any, detail: str | None) -> tuple[str, str]:
        """응답의 status를 구하고, 해석할 수 없는 응답은 900으로 둔다."""
        if isinstance(data, dict):
            return str(data.get("status", "900")), str(data.get("message", ""))
        return "900", detail or f"객체가 아닌 응답: {type(data).__name__}"

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """HTTP GET 요청을 보내고 JSON 응답을 반환한다."""
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return cast("dict[str, Any]", await resp.json(content_type=None))

    @staticmethod
    def _extract_list(data: dict[str, Any]) -> list[dict[str, Any]]:
        """DART 응답에서 list 배열을 추출한다."""
        items = data.get("list", [])
        if items is None:
            msg = f"DART 응답의 list가 null이다 (status={data.get('status')})"
            logger.error(msg)
            raise DARTError(msg)
        if isinstance(items, dict):
            items = [items]
        return cast("list[dict[str, Any]]", items)

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
        """Exponential Backoff + Full Jitter 대기 시간을 계산한다."""
        return random.uniform(0, min(cap, base * (2**attempt)))
