"""data.go.kr 주식시세 API 소스 어댑터.

getStockPriceInfo 단일 호출로 OHLCV + 거래대금 + 시가총액 + 상장주식수를 동시 확보.
날짜별 전종목 조회 방식을 사용하며, 페이지네이션과 에러 코드 처리를 담당한다.

API 레퍼런스: docs/references/external-apis/data-go-kr-stock-price-api.md
"""

from __future__ import annotations

import asyncio
import logging
import random
from enum import StrEnum
from typing import Any

import aiohttp

from ante.feed.sources.base import RateLimiter

logger = logging.getLogger(__name__)

# ── API 상수 (API 스펙 종속, 하드코딩) ─────────────────────

BASE_URL = (
    "https://apis.data.go.kr/1160100/service"
    "/GetStockSecuritiesInfoService/getStockPriceInfo"
)
TPS_LIMIT = 25.0  # 실제 30 tps, 여유분 확보
DAILY_LIMIT = 10_000
NUM_OF_ROWS = 1000
REQUEST_TIMEOUT = 30  # 초

# 재시도 불가 HTTP status (spec 09-failure-recovery: 즉시 스킵/실패 로그).
# 재시도 가능(408/429/5xx/timeout/연결 오류)은 이 집합 밖이라 기존대로 재시도된다.
_NON_RETRYABLE_HTTP_STATUS = frozenset({400, 401, 403, 404, 422})


# ── 에러 분류 ──────────────────────────────────────────────


class ErrorAction(StrEnum):
    """API 에러 코드에 따른 행동 분류."""

    OK = "ok"
    RETRY = "retry"
    RETRY_ONCE = "retry_once"
    SKIP = "skip"
    DAILY_LIMIT = "daily_limit"
    CRITICAL = "critical"


# data.go.kr resultCode → 행동 매핑
_ERROR_CODE_MAP: dict[str, ErrorAction] = {
    "00": ErrorAction.OK,
    "01": ErrorAction.RETRY,  # APPLICATION_ERROR
    "10": ErrorAction.SKIP,  # INVALID_REQUEST_PARAMETER_ERROR
    "12": ErrorAction.SKIP,  # NO_OPENAPI_SERVICE_ERROR
    "20": ErrorAction.SKIP,  # SERVICE_ACCESS_DENIED_ERROR
    "22": ErrorAction.DAILY_LIMIT,  # LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR
    "30": ErrorAction.CRITICAL,  # SERVICE_KEY_IS_NOT_REGISTERED_ERROR
    "31": ErrorAction.CRITICAL,  # DEADLINE_HAS_EXPIRED_ERROR
    "32": ErrorAction.SKIP,  # UNREGISTERED_IP_ERROR
    "99": ErrorAction.RETRY_ONCE,  # UNKNOWN_ERROR (spec: 1회 재시도 후 스킵)
}


def classify_error(result_code: str) -> ErrorAction:
    """resultCode를 행동으로 분류한다."""
    return _ERROR_CODE_MAP.get(result_code, ErrorAction.RETRY)


# ── 예외 ──────────────────────────────────────────────────


class DataGoKrError(Exception):
    """data.go.kr API 에러 기본 예외."""

    pass


class DailyLimitExceededError(DataGoKrError):
    """일일 호출 한도 초과."""

    pass


class CriticalApiError(DataGoKrError):
    """서비스키 미등록/만료 등 복구 불가능 에러."""

    pass


# ── DataGoKrSource ────────────────────────────────────────


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

    async def fetch(self, date: str, **kwargs: Any) -> list[dict]:
        """DataSource 프로토콜 구현. fetch_by_date에 위임한다.

        Args:
            date: 수집 대상 날짜 (YYYY-MM-DD 형식).
            **kwargs: 미사용.

        Returns:
            수집된 레코드 딕셔너리 목록.
        """
        return await self.fetch_by_date(date)

    async def fetch_by_date(self, date: str) -> list[dict]:
        """해당 날짜 전 종목 데이터를 수집한다.

        날짜별 전종목 조회 방식으로 페이지네이션을 처리한다.
        1일 = ~2,400건 (KOSPI+KOSDAQ) → 약 3페이지 (numOfRows=1000).

        Args:
            date: 수집 대상 날짜 (YYYY-MM-DD 형식).

        Returns:
            수집된 레코드 딕셔너리 목록.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 시.
            CriticalApiError: 서비스키 미등록/만료 등 복구 불가능 에러.
            DataGoKrError: 빈 페이지인데 totalCount 미달(부분 수집) 시.
        """
        # YYYY-MM-DD → YYYYMMDD (API 요청 형식)
        bas_dt = date.replace("-", "")
        all_items: list[dict] = []
        page_no = 1

        own_session = self._session is None
        session = self._session or aiohttp.ClientSession()

        try:
            while True:
                # 일일 한도 확인
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

                # 페이지네이션 종료 조건
                if len(all_items) >= total_count:
                    break
                if len(items) == 0:
                    # 빈 페이지인데 total_count 미달 → 부분 수집 이상 (fail-loud)
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
        """서비스키 유효성을 경량 요청 1회로 검증한다 (#2046).

        가장 싼 기존 요청 패턴(getStockPriceInfo 1페이지, numOfRows=1)을
        더미 기준일자로 1회 호출한다. data.go.kr은 서비스키를 우선
        평가하므로, 키가 유효하면 ``00``(정상) 또는 다른 비인증 에러가
        돌아오고, 키가 미등록/만료면 ``30/31`` 인증 에러(CRITICAL)가
        돌아온다.

        3-state를 반환한다:
            * ``(True, None)``  — 유효 (키가 수락됨).
            * ``(False, 사유)`` — 인증 실패 (CRITICAL 에러 코드).
            * ``(None, 사유)``  — 검증 불가 (네트워크 예외/타임아웃).

        offline·타임아웃 등 네트워크 예외는 unknown으로 흡수하며 예외를
        전파하지 않는다. config check가 오프라인에서도 hang/실패 없이
        graceful하게 동작하도록 보장한다.

        Returns:
            (valid, reason) 튜플. valid는 True/False/None.
        """
        # 인증 평가만을 위한 최소 더미 파라미터(서비스키 검증이 우선 수행됨).
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
            logger.info("data.go.kr 키 검증 불가 (네트워크): %s", exc)
            return None, f"검증 불가 (네트워크): {exc}"
        finally:
            if own_session:
                await session.close()

        result_code, result_msg = self._extract_result_code(data)
        action = classify_error(result_code)

        if action == ErrorAction.CRITICAL:
            return False, f"인증 실패 (code={result_code}): {result_msg}"
        # OK / 그 외(키는 수락됨) → 유효.
        return True, None

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        bas_dt: str,
        page_no: int,
    ) -> tuple[list[dict], int]:
        """단일 페이지를 조회한다.

        Args:
            session: aiohttp 세션.
            bas_dt: 기준일자 (YYYYMMDD).
            page_no: 페이지 번호.

        Returns:
            (item 목록, totalCount) 튜플.

        Raises:
            DailyLimitExceededError: 일일 한도 초과 에러 코드.
            CriticalApiError: 복구 불가능 에러 코드.
            DataGoKrError: 재시도 소진 후 최종 실패.
        """
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
            # 실제 HTTP 요청 시도(_do_request) 직전에 카운트한다.
            # 성공/실패와 무관하게 모든 attempt를 반영하여 일일 한도 추적이
            # 실패·재시도 시도를 누락하지 않도록 한다 (#2106). 1 attempt = 1 increment.
            self._rate_limiter.increment_daily()

            try:
                data = await asyncio.wait_for(
                    self._do_request(session, params),
                    timeout=REQUEST_TIMEOUT,
                )
            except (TimeoutError, aiohttp.ClientError) as exc:
                # 재시도 불가 HTTP status(400/401/403/404/422)는 즉시 실패
                # 처리한다 (spec 09-failure-recovery, #2026). body 에러 코드의
                # SKIP 액션과 동일하게 error 로그 + DataGoKrError raise.
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
                    exc,
                    delay,
                )
                await asyncio.sleep(delay)
                continue

            # HTTP 200이지만 body에 에러 코드가 있을 수 있음
            result_code, result_msg = self._extract_result_code(data)
            action = classify_error(result_code)

            if action == ErrorAction.OK:
                return self._extract_items(data)

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

            # RETRY / RETRY_ONCE
            last_error = DataGoKrError(f"API 에러 (code={result_code}): {result_msg}")
            # RETRY_ONCE(99 UNKNOWN_ERROR)는 최대 1회만 재시도한다
            # (spec 05-data-sources: 1회 재시도 후 스킵 = 총 2회 호출, #2027).
            # attempt>=1이면 더 이상 재시도하지 않고 최종 실패로 떨어진다.
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
                # 1회 재시도 cap 도달 → 최종 실패로 즉시 종료(추가 attempt 생략).
                break

        # 재시도 소진
        msg = f"data.go.kr 요청 최종 실패: basDt={bas_dt}, pageNo={page_no}"
        logger.error(msg)
        raise DataGoKrError(msg) from last_error

    async def _do_request(
        self,
        session: aiohttp.ClientSession,
        params: dict[str, str],
    ) -> dict:
        """HTTP GET 요청을 보내고 JSON 응답을 반환한다."""
        async with session.get(self._base_url, params=params) as resp:
            resp.raise_for_status()
            return await resp.json(content_type=None)

    @staticmethod
    def _extract_result_code(data: dict) -> tuple[str, str]:
        """응답에서 resultCode와 resultMsg를 추출한다.

        Args:
            data: JSON 응답 딕셔너리.

        Returns:
            (resultCode, resultMsg) 튜플.
        """
        header = data.get("response", {}).get("header", {})
        result_code = str(header.get("resultCode", "99"))
        result_msg = str(header.get("resultMsg", "UNKNOWN"))
        return result_code, result_msg

    @staticmethod
    def _extract_items(data: dict) -> tuple[list[dict], int]:
        """응답에서 item 목록과 totalCount를 추출한다.

        Args:
            data: JSON 응답 딕셔너리.

        Returns:
            (item 목록, totalCount) 튜플.
        """
        body = data.get("response", {}).get("body", {})
        total_count = int(body.get("totalCount", 0))
        items_wrapper = body.get("items", {})

        if not items_wrapper:
            return [], total_count

        items = items_wrapper.get("item", [])
        # 단일 item인 경우 list로 감싸기
        if isinstance(items, dict):
            items = [items]

        return items, total_count

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
