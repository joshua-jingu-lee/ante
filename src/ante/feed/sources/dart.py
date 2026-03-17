"""DART OpenAPI 소스 어댑터.

DART API에서 상장기업 재무제표(매출, 순이익, 자본총계 등)를 수집한다.
고유번호(corp_code) 매핑, 다중회사 배치 호출(fnlttMultiAcnt),
Rate Limiting, 에러 코드 처리를 담당한다.

API 레퍼런스: docs/references/dashboard/dart-openapi.md
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import random
import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

import aiohttp

from ante.feed.sources.base import RateLimiter

logger = logging.getLogger(__name__)

# -- API 상수 (API 스펙 종속, 하드코딩) --------------------------------

BASE_URL = "https://opendart.fss.or.kr/api"
TPS_LIMIT = 10.0  # 보수적 설정
DAILY_LIMIT = 20_000
BATCH_SIZE = 100  # fnlttMultiAcnt 최대 100개 회사
REQUEST_TIMEOUT = 60  # 다중회사 응답이 커질 수 있으므로 넉넉하게

# 보고서 코드 매핑
REPRT_CODES: dict[str, str] = {
    "11013": "1분기보고서",
    "11012": "반기보고서",
    "11014": "3분기보고서",
    "11011": "사업보고서",
}


# -- 에러 분류 ---------------------------------------------------------


class ErrorAction(StrEnum):
    """DART API 에러 코드에 따른 행동 분류."""

    OK = "ok"
    NO_DATA = "no_data"
    RETRY = "retry"
    SKIP = "skip"
    DAILY_LIMIT = "daily_limit"
    CRITICAL = "critical"


_ERROR_CODE_MAP: dict[str, ErrorAction] = {
    "000": ErrorAction.OK,
    "010": ErrorAction.CRITICAL,  # 등록되지 않은 키
    "011": ErrorAction.CRITICAL,  # 사용할 수 없는 키
    "012": ErrorAction.CRITICAL,  # 접근할 수 없는 IP
    "013": ErrorAction.NO_DATA,  # 조회된 데이터 없음
    "014": ErrorAction.SKIP,  # 파일 존재하지 않음
    "020": ErrorAction.DAILY_LIMIT,  # 요청 제한 초과
    "021": ErrorAction.SKIP,  # 조회 가능 회사 개수 초과 (구현 버그)
    "100": ErrorAction.SKIP,  # 부적절한 필드 값
    "101": ErrorAction.SKIP,  # 부적절한 접근
    "800": ErrorAction.RETRY,  # 시스템 점검 중
    "900": ErrorAction.RETRY,  # 정의되지 않은 오류
    "901": ErrorAction.CRITICAL,  # 개인정보 보유기간 만료
}


def classify_error(status: str) -> ErrorAction:
    """DART status 코드를 행동으로 분류한다."""
    return _ERROR_CODE_MAP.get(status, ErrorAction.RETRY)


# -- 예외 --------------------------------------------------------------


class DARTError(Exception):
    """DART API 에러 기본 예외."""

    pass


class DailyLimitExceededError(DARTError):
    """일일 호출 한도 초과."""

    pass


class CriticalApiError(DARTError):
    """키 미등록/만료 등 복구 불가능 에러."""

    pass


# -- DARTSource --------------------------------------------------------


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

    async def fetch(self, date: str, **kwargs: Any) -> list[dict]:
        """DataSource 프로토콜 구현.

        DART는 날짜별 수집이 아니라 연도+분기별 수집이므로,
        kwargs에서 corp_codes, year, reprt_code를 받아 fetch_financial에 위임한다.

        Args:
            date: 미사용 (프로토콜 호환).
            **kwargs: corp_codes, year, reprt_code.

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

        Args:
            save_path: 매핑 결과를 저장할 JSON 파일 경로.
                None이면 저장하지 않고 딕셔너리만 반환.

        Returns:
            corp_code -> stock_code 매핑 딕셔너리.
                예: {"00126380": "005930", ...}

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

        self._rate_limiter.increment_daily()

        # ZIP 해제 및 XML 파싱
        corp_code_map = self._parse_corp_code_zip(zip_bytes)

        logger.info(
            "DART 고유번호 수집 완료: 상장사 %d개",
            len(corp_code_map),
        )

        # 파일 저장
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
    ) -> list[dict]:
        """다중회사 주요계정(fnlttMultiAcnt) API를 배치 호출한다.

        corp_codes를 100개씩 나누어 호출하며,
        Rate Limiting과 에러 코드 처리를 수행한다.

        Args:
            corp_codes: DART 고유번호 목록.
            year: 사업연도 (4자리, 예: "2024").
            reprt_code: 보고서 코드 (11013/11012/11014/11011).

        Returns:
            수집된 재무제표 레코드 딕셔너리 목록.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 시.
            CriticalApiError: 인증키 에러 시.
        """
        all_items: list[dict] = []

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            # 100개씩 배치 분할
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

    # -- 내부 메서드 ---------------------------------------------------

    async def _download_corp_code_zip(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str],
    ) -> bytes:
        """고유번호 ZIP 파일을 다운로드한다.

        Returns:
            ZIP 파일 바이트.

        Raises:
            DARTError: 다운로드 실패 시.
            CriticalApiError: JSON 에러 응답 시.
        """
        last_error: Exception | None = None

        for attempt in range(self._max_retries):
            await self._rate_limiter.acquire()

            try:
                async with asyncio.timeout(REQUEST_TIMEOUT):
                    async with session.get(url, params=params) as resp:
                        content_type = resp.content_type or ""

                        # ZIP 바이너리 응답
                        if "zip" in content_type or "octet-stream" in content_type:
                            return await resp.read()

                        # JSON 에러 응답 (키 오류 등)
                        if "json" in content_type or "text" in content_type:
                            body = await resp.text()
                            try:
                                data = json.loads(body)
                                status = str(data.get("status", "900"))
                                message = str(data.get("message", ""))
                            except json.JSONDecodeError:
                                status = "900"
                                message = body[:200]

                            action = classify_error(status)

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
                last_error = exc

            if attempt < self._max_retries - 1:
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "DART corpCode 다운로드 실패 (attempt=%d/%d): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        msg = "DART 고유번호 ZIP 다운로드 최종 실패"
        logger.error(msg)
        raise DARTError(msg) from last_error

    @staticmethod
    def _parse_corp_code_zip(zip_bytes: bytes) -> dict[str, str]:
        """ZIP 바이트에서 corp_code -> stock_code 매핑을 추출한다.

        stock_code가 비어있는 비상장사는 필터링한다.

        Args:
            zip_bytes: corpCode.xml ZIP 파일 바이트.

        Returns:
            corp_code -> stock_code 매핑.
        """
        corp_code_map: dict[str, str] = {}

        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            # ZIP 내 첫 번째 파일(XML) 읽기
            xml_name = zf.namelist()[0]
            with zf.open(xml_name) as xml_file:
                tree = ElementTree.parse(xml_file)
                root = tree.getroot()

                for elem in root.iter("list"):
                    corp_code = elem.findtext("corp_code", "").strip()
                    stock_code = elem.findtext("stock_code", "").strip()

                    # 비상장사 필터링 (stock_code가 비어있거나 공백)
                    if corp_code and stock_code:
                        corp_code_map[corp_code] = stock_code

        return corp_code_map

    async def _fetch_multi_acnt(
        self,
        session: aiohttp.ClientSession,
        corp_codes: list[str],
        year: str,
        reprt_code: str,
    ) -> list[dict]:
        """fnlttMultiAcnt API를 호출한다.

        Args:
            session: aiohttp 세션.
            corp_codes: 고유번호 목록 (최대 100개).
            year: 사업연도.
            reprt_code: 보고서 코드.

        Returns:
            재무제표 레코드 목록.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 에러 코드.
            CriticalApiError: 인증키 에러 코드.
            DARTError: 재시도 소진 후 최종 실패.
        """
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

            try:
                data = await asyncio.wait_for(
                    self._do_request(session, url, params),
                    timeout=REQUEST_TIMEOUT,
                )
                self._rate_limiter.increment_daily()
            except (TimeoutError, aiohttp.ClientError) as exc:
                last_error = exc
                delay = self._backoff_delay(attempt)
                logger.warning(
                    "DART fnlttMultiAcnt 요청 실패 "
                    "(attempt=%d/%d): %s. %.1f초 후 재시도",
                    attempt + 1,
                    self._max_retries,
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # 에러 코드 처리
            status = str(data.get("status", "900"))
            message = str(data.get("message", ""))
            action = classify_error(status)

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

            # RETRY
            last_error = DARTError(f"DART API 에러 (status={status}): {message}")
            if attempt < self._max_retries - 1:
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

        msg = f"DART fnlttMultiAcnt 요청 최종 실패: year={year}, reprt={reprt_code}"
        logger.error(msg)
        raise DARTError(msg) from last_error

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        url: str,
        params: dict[str, str],
    ) -> dict:
        """HTTP GET 요청을 보내고 JSON 응답을 반환한다."""
        async with session.get(url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @staticmethod
    def _extract_list(data: dict) -> list[dict]:
        """DART 응답에서 list 배열을 추출한다.

        Args:
            data: JSON 응답 딕셔너리.

        Returns:
            재무제표 레코드 목록.
        """
        items = data.get("list", [])
        if isinstance(items, dict):
            items = [items]
        return items

    @staticmethod
    def _backoff_delay(attempt: int, base: float = 1.0, cap: float = 60.0) -> float:
        """Exponential Backoff + Full Jitter 대기 시간을 계산한다.

        Args:
            attempt: 현재 시도 인덱스 (0-based).
            base: 기본 대기 시간 (초).
            cap: 최대 대기 시간 (초).

        Returns:
            대기 시간 (초).
        """
        return random.uniform(0, min(cap, base * (2**attempt)))
