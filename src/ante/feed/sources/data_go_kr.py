"""data.go.kr 주식시세 API 소스 어댑터."""

from __future__ import annotations

import asyncio
import json
import logging
import random
from enum import StrEnum
from typing import Any, cast

import aiohttp

from ante.feed.sources.base import (
    RateLimiter,
    describe_source_error,
    redact_source_text,
)

logger = logging.getLogger(__name__)


BASE_URL = (
    "https://apis.data.go.kr/1160100/service"
    "/GetStockSecuritiesInfoService/getStockPriceInfo"
)
TPS_LIMIT = 25.0
DAILY_LIMIT = 10_000
NUM_OF_ROWS = 1000
REQUEST_TIMEOUT = 30

_NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})


class ErrorAction(StrEnum):
    """API 에러 코드에 따른 행동 분류."""

    OK = "ok"
    RETRY = "retry"
    RETRY_ONCE = "retry_once"
    SKIP = "skip"
    DAILY_LIMIT = "daily_limit"
    CRITICAL = "critical"


_ERROR_CODE_MAP: dict[str, ErrorAction] = {
    "00": ErrorAction.OK,
    "01": ErrorAction.RETRY,
    "10": ErrorAction.SKIP,
    "12": ErrorAction.SKIP,
    "20": ErrorAction.SKIP,
    "22": ErrorAction.DAILY_LIMIT,
    "30": ErrorAction.CRITICAL,
    "31": ErrorAction.CRITICAL,
    "32": ErrorAction.SKIP,
    "99": ErrorAction.RETRY_ONCE,
}


def classify_error(result_code: str) -> ErrorAction:
    """resultCode를 행동으로 분류한다."""
    return _ERROR_CODE_MAP.get(result_code, ErrorAction.RETRY)


class DataGoKrError(Exception):
    """data.go.kr API 에러 기본 예외."""

    pass


class DailyLimitExceededError(DataGoKrError):
    """일일 호출 한도 초과."""

    pass


class CriticalApiError(DataGoKrError):
    """서비스키 미등록/만료 등 복구 불가능 에러."""

    pass


class DataGoKrSource:
    """data.go.kr 주식시세 API 소스 어댑터.

    fetch_by_date(date)로 해당 날짜 전 종목 데이터를 수집한다.
    페이지네이션, Rate Limiting, 에러 코드 처리를 담당한다.
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
        """DataGoKrSource를 초기화한다.

        Args:
            api_key: data.go.kr 공공데이터포털 서비스키 (디코딩된 원본).
            rate_limiter: Rate Limiter 인스턴스. None이면 기본값 생성.
            session: aiohttp 세션. None이면 fetch 시 생성.
            max_retries: 최대 재시도 횟수.
            base_url: API 엔드포인트 URL.
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
        """DataSource 프로토콜 구현. fetch_by_date에 위임한다.

        Args:
            date: 수집 대상 날짜 (YYYY-MM-DD 형식).
            **kwargs: 미사용.

        Returns:
            수집된 레코드 딕셔너리 목록.
        """
        return await self.fetch_by_date(date)

    async def fetch_by_date(self, date: str) -> list[dict[str, Any]]:
        """해당 날짜 전 종목 데이터를 수집한다.

        Args:
            date: 수집 대상 날짜 (YYYY-MM-DD 형식).

        Raises:
            DailyLimitExceededError: 일일 한도 초과 시.
            CriticalApiError: 서비스키 미등록/만료 등 복구 불가능 에러.
            DataGoKrError: 빈 페이지인데 totalCount 미달(부분 수집) 시.
        """
        bas_dt = date.replace("-", "")
        all_items: list[dict[str, Any]] = []
        page_no = 1

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            while True:
                if self._rate_limiter.is_daily_limit_reached():
                    msg = (
                        f"일일 한도 90% 도달 "
                        f"({self._rate_limiter.daily_count}/{DAILY_LIMIT})"
                    )
                    logger.critical(msg)
                    raise DailyLimitExceededError(msg)

                items, total_count = await self._fetch_page(session, bas_dt, page_no)
                all_items.extend(items)

                logger.debug(
                    "data.go.kr 수집: date=%s page=%d items=%d total=%d",
                    date,
                    page_no,
                    len(items),
                    total_count,
                )

                if len(all_items) >= total_count:
                    break
                if len(items) == 0:
                    msg = (
                        f"부분 수집 감지: date={date} "
                        f"collected={len(all_items)} total={total_count} "
                        f"(page={page_no} 빈 페이지)"
                    )
                    logger.error(msg)
                    raise DataGoKrError(msg)

                page_no += 1
        finally:
            if own_session:
                await session.close()

        logger.info("data.go.kr 수집 완료: date=%s records=%d", date, len(all_items))
        return all_items

    async def validate_credentials(self) -> tuple[bool | None, str | None]:
        """서비스키 유효성을 경량 요청 1회로 검증한다.

        offline·타임아웃 등 네트워크 예외는 unknown으로 흡수하며 예외를
        전파하지 않는다. config check가 오프라인에서도 hang/실패 없이
        graceful하게 동작하도록 보장한다.

        Returns:
            (valid, reason) 튜플. valid는 True/False/None.
        """
        params = {
            "serviceKey": self._api_key,
            "numOfRows": "1",
            "pageNo": "1",
            "resultType": "json",
            "basDt": "20240102",
        }

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            await self._rate_limiter.acquire()
            self._rate_limiter.increment_daily()
            data = await asyncio.wait_for(
                self._do_request(session, params),
                timeout=REQUEST_TIMEOUT,
            )
        except (TimeoutError, aiohttp.ClientError) as exc:
            reason = describe_source_error(exc, self._api_key)
            logger.info("data.go.kr 키 검증 불가 (네트워크): %s", reason)
            return None, f"검증 불가 (네트워크): {reason}"
        finally:
            if own_session:
                await session.close()

        result_code, result_msg = self._extract_result_code(data)
        action = classify_error(result_code)
        result_code = redact_source_text(result_code, self._api_key)
        result_msg = redact_source_text(result_msg, self._api_key)

        if action == ErrorAction.CRITICAL:
            return False, f"인증 실패 (code={result_code}): {result_msg}"
        return True, None

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        bas_dt: str,
        page_no: int,
    ) -> tuple[list[dict[str, Any]], int]:
        """단일 페이지를 조회한다."""
        params = {
            "serviceKey": self._api_key,
            "numOfRows": str(NUM_OF_ROWS),
            "pageNo": str(page_no),
            "resultType": "json",
            "basDt": bas_dt,
        }

        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire()
            self._rate_limiter.increment_daily()

            try:
                data, decode_error = await self._request_decoded(session, params)
            except (TimeoutError, aiohttp.ClientError) as exc:
                if (
                    isinstance(exc, aiohttp.ClientResponseError)
                    and exc.status in _NON_RETRYABLE_HTTP_STATUS
                ):
                    msg = (
                        f"재시도 불가 HTTP 에러 (status={exc.status}): "
                        f"basDt={bas_dt}, pageNo={page_no}"
                    )
                    logger.error(msg)
                    raise DataGoKrError(msg) from exc
                last_error = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "data.go.kr 요청 실패 (attempt=%d/%d): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    describe_source_error(exc, self._api_key),
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            result_code, result_msg = self._response_code(data, decode_error)
            action = classify_error(result_code)
            result_code = redact_source_text(result_code, self._api_key)
            result_msg = redact_source_text(result_msg, self._api_key)

            if action == ErrorAction.OK:
                return self._extract_page(data)

            if action == ErrorAction.DAILY_LIMIT:
                msg = f"일일 한도 초과: {result_msg}"
                logger.critical(msg)
                raise DailyLimitExceededError(msg)

            if action == ErrorAction.CRITICAL:
                msg = f"복구 불가능 에러 (code={result_code}): {result_msg}"
                logger.critical(msg)
                raise CriticalApiError(msg)

            if action == ErrorAction.SKIP:
                msg = f"재시도 불가 에러 (code={result_code}): {result_msg}"
                logger.error(msg)
                raise DataGoKrError(msg)

            last_error = DataGoKrError(f"API 에러 (code={result_code}): {result_msg}")
            retry_cap = 1 if action == ErrorAction.RETRY_ONCE else self._max_retries - 1
            if attempt < retry_cap:
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "data.go.kr API 에러 (attempt=%d/%d, code=%s):"
                    " %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    result_code,
                    result_msg,
                    delay,
                )
                await asyncio.sleep(delay)
            elif action == ErrorAction.RETRY_ONCE:
                break

        msg = f"data.go.kr 요청 최종 실패: basDt={bas_dt}, pageNo={page_no}"
        logger.error(msg)
        raise DataGoKrError(msg) from last_error

    async def _request_decoded(
        self,
        session: aiohttp.ClientSession,
        params: dict[str, str],
    ) -> tuple[Any, str | None]:
        """요청해 응답을 돌려주고, 본문 디코드 실패는 (None, 사유)로 바꾼다."""
        try:
            data = await asyncio.wait_for(
                self._do_request(session, params),
                timeout=REQUEST_TIMEOUT,
            )
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            return None, redact_source_text(str(exc), self._api_key)[:200]
        return data, None

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        params: dict[str, str],
    ) -> dict[str, Any]:
        """HTTP GET 요청을 보내고 JSON 응답을 반환한다."""
        async with session.get(self._base_url, params=params) as resp:
            resp.raise_for_status()
            return cast("dict[str, Any]", await resp.json(content_type=None))

    @classmethod
    def _response_code(cls, data: Any, detail: str | None) -> tuple[str, str]:
        """응답의 resultCode를 구하고, 해석할 수 없는 응답은 99로 둔다."""
        if isinstance(data, dict):
            return cls._extract_result_code(data)
        return "99", detail or f"객체가 아닌 응답: {type(data).__name__}"

    @staticmethod
    def _extract_result_code(data: dict[str, Any]) -> tuple[str, str]:
        """응답에서 resultCode와 resultMsg를 추출한다."""
        header = data.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", "99"))
        result_msg = str(header.get("resultMsg", "UNKNOWN"))
        return result_code, result_msg

    def _extract_page(self, data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """``_extract_items`` 의 변환 실패 문구에서 API 키를 가린다."""
        try:
            return self._extract_items(data)
        except ValueError as exc:
            message = self._redacted_total_error(data) or str(exc)
            raise ValueError(redact_source_text(message, self._api_key)) from None

    def _redacted_total_error(self, data: dict[str, Any]) -> str | None:
        """가린 totalCount를 다시 변환한 실패 문구(실패하지 않으면 None)."""
        raw = data.get("response", {}).get("body", {}).get("totalCount")
        if not isinstance(raw, str):
            return None
        try:
            int(redact_source_text(raw, self._api_key))
        except ValueError as exc:
            return str(exc)
        return None

    @staticmethod
    def _extract_items(data: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
        """응답에서 item 목록과 totalCount를 추출한다."""
        body = data.get("response", {}).get("body", {})
        total_count = int(body.get("totalCount", 0))
        items_wrapper = body.get("items", {})

        if not items_wrapper:
            return [], total_count

        items = items_wrapper.get("item", [])
        if isinstance(items, dict):
            items = [items]

        return items, total_count

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
        """Exponential Backoff + Full Jitter 대기 시간을 계산한다."""
        return random.uniform(0, min(cap, base * (2**attempt)))
