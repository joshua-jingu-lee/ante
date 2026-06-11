"""한국투자증권 (KIS) Open API 어댑터.

KIS REST API를 통해 주문, 조회를 처리한다.
실행 시 aiohttp 패키지가 필요하다.

계층 구조:
    BrokerAdapter (ABC)
    └── KISBaseAdapter (ABC) — KIS 공통 레이어 (인증, HTTP, 에러 처리)
        └── KISDomesticAdapter — 국내주식 전용
"""

from __future__ import annotations

import asyncio
import json
import logging
from abc import abstractmethod
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ante.broker.base import BrokerAdapter
from ante.broker.circuit_breaker import CircuitBreaker
from ante.broker.error_codes import (
    PERMANENT_MSG_CODES,
    TRANSIENT_MSG_CODES,
    get_error_message,
    is_retryable_http_status,
    is_retryable_msg_code,
)
from ante.broker.exceptions import (
    APIError,
    AuthenticationError,
    CircuitOpenError,
    OrderNotFoundError,
    RateLimitError,
)
from ante.broker.fill_scheduler import business_date_kst
from ante.broker.models import CommissionInfo

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# ── API 유형별 설정 ───────────────────────────────────

# 최대 재시도 횟수
DEFAULT_MAX_RETRIES_ORDER = 3
DEFAULT_MAX_RETRIES_QUERY = 2
DEFAULT_MAX_RETRIES_AUTH = 2

# 타임아웃 (초)
DEFAULT_TIMEOUT_ORDER = 10
DEFAULT_TIMEOUT_QUERY = 5
DEFAULT_TIMEOUT_AUTH = 10

# Backoff
DEFAULT_BACKOFF_BASE = 1.0

# Circuit Breaker
DEFAULT_CB_FAILURE_THRESHOLD = 5
DEFAULT_CB_RECOVERY_TIMEOUT = 60

# KIS 연속조회(CTX_AREA) 페이지네이션
# 응답 헤더 tr_cont 값: "F"/"M" = 다음 페이지 있음, "D"/"E" = 마지막 페이지.
_TR_CONT_HAS_NEXT = frozenset({"F", "M"})
# 무한 루프 방지용 최대 페이지 수 안전 상한.
DEFAULT_MAX_PAGINATION_PAGES = 100

# 주문 관련 tr_id (재시도 횟수 분류용)
_ORDER_TR_IDS = frozenset(
    {
        "VTTC0012U",
        "TTTC0012U",  # 매수
        "VTTC0011U",
        "TTTC0011U",  # 매도
        "VTTC0803U",
        "TTTC0803U",  # 취소
    }
)

# 거래소ID구분코드(EXCG_ID_DVSN_CD) 기본값.
# 에픽 #2354 일관성 목표의 공유 단일 출처 — order-cash(#2344) 외 후속 이슈
# (inquire-daily-ccld #2349 등)가 재사용할 예정이다. 국내 KRX 주문 기본값으로,
# NXT/SOR 등 다른 거래소 라우팅은 현재 미지원(요구 발생 시 config 표면화는 후속).
DEFAULT_EXCG_ID_DVSN_CD = "KRX"

# 인증 경로
_AUTH_PATH = "/oauth2/tokenP"

# 취소(order-rvsecncl) 시 전송할 KRX_FWDG_ORD_ORGNO 캐시 상한.
# 어댑터 인스턴스(=계좌)당 미체결 주문 수를 넉넉히 덮으면서 무한 증가를 막는다.
# 초과 시 가장 오래된 항목부터 제거(LRU 근사: insertion-order eviction).
_KRX_FWDG_ORGNO_CACHE_MAXLEN = 1024


class KISErrorClassifier:
    """KIS API 에러를 분류하여 재시도/즉시실패/서킷브레이크를 결정한다."""

    @staticmethod
    def classify(error: Exception) -> tuple[bool, bool]:
        """에러를 분류하여 (retryable, record_cb_failure) 튜플을 반환한다.

        Returns:
            retryable: 재시도 가능 여부
            record_cb_failure: circuit breaker에 실패 기록 여부
        """
        if isinstance(error, (CircuitOpenError, AuthenticationError)):
            return False, False
        if isinstance(error, TimeoutError):
            return True, True
        if isinstance(error, (ConnectionError, OSError)):
            return True, True
        if isinstance(error, RateLimitError):
            return True, True
        if isinstance(error, APIError):
            if not error.retryable:
                return False, False
            return True, True
        # 알 수 없는 에러는 재시도하지 않음
        return False, False

    @staticmethod
    def to_api_error(error: Exception, timeout: float) -> Exception:
        """네트워크/타임아웃 에러를 APIError로 래핑한다."""
        if isinstance(error, TimeoutError):
            return APIError(f"타임아웃 ({timeout:.0f}초 초과)", retryable=True)
        if isinstance(error, (ConnectionError, OSError)):
            return APIError(str(error), retryable=True)
        return error

    @staticmethod
    def log_label(error: Exception) -> str:
        """에러 종류별 로그 라벨 반환."""
        if isinstance(error, TimeoutError):
            return "API 타임아웃"
        if isinstance(error, (ConnectionError, OSError)):
            return "네트워크 오류"
        if isinstance(error, RateLimitError):
            return "Rate limit"
        return "API 오류"


class KISRetryHandler:
    """지수 백오프 기반 재시도 전략을 관리한다."""

    def __init__(self, backoff_base: float = DEFAULT_BACKOFF_BASE) -> None:
        self._backoff_base = backoff_base

    def backoff_delay(self, attempt: int) -> float:
        """attempt 번째 시도의 백오프 대기 시간(초)."""
        return self._backoff_base * (2**attempt)

    def should_retry(self, attempt: int, max_retries: int) -> bool:
        """재시도 여부 결정."""
        return attempt < max_retries

    async def wait_and_log(
        self,
        attempt: int,
        max_retries: int,
        tr_id: str,
        error: Exception,
    ) -> None:
        """백오프 대기 후 로그를 남긴다."""
        wait = self.backoff_delay(attempt)
        label = KISErrorClassifier.log_label(error)
        detail = (
            f": {error}"
            if not isinstance(error, (TimeoutError, RateLimitError))
            else ""
        )
        logger.warning(
            "%s [%s] 재시도 %d/%d (%.1f초 후)%s",
            label,
            tr_id,
            attempt + 1,
            max_retries,
            wait,
            detail,
        )
        await asyncio.sleep(wait)


# ── KISBaseAdapter — KIS 공통 레이어 ─────────────────────


class KISBaseAdapter(BrokerAdapter):
    """KIS Open API 공통 레이어 (인증, HTTP, 에러 처리, 재시도, 서킷브레이커).

    국내/해외 공통 로직을 추상화하는 중간 계층.
    시장별 서브클래스(KISDomesticAdapter, KISOverseasAdapter)가 이를 상속한다.
    """

    def __init__(
        self,
        config: dict[str, Any],
        eventbus: EventBus | None = None,
    ) -> None:
        super().__init__(config)

        self.app_key: str = config["app_key"]
        self.app_secret: str = config["app_secret"]
        self.account_no: str = config["account_no"]
        self.is_paper: bool = config.get("is_paper", True)
        self._eventbus = eventbus

        # API 엔드포인트
        if self.is_paper:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.websocket_url = "ws://ops.koreainvestment.com:31000"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.websocket_url = "ws://ops.koreainvestment.com:21000"

        # 인증
        self.access_token: str | None = None
        self.token_expires_at: datetime | None = None

        # HTTP 세션
        self._session: Any = None

        # Rate limiting
        self._request_times: list[datetime] = []
        self._rate_limit_per_minute: int = 5 if self.is_paper else 20

        # ── 재시도 설정 ────────────────────────────────
        self._max_retries_order: int = config.get(
            "retry.max_retries_order", DEFAULT_MAX_RETRIES_ORDER
        )
        self._max_retries_query: int = config.get(
            "retry.max_retries_query", DEFAULT_MAX_RETRIES_QUERY
        )
        self._max_retries_auth: int = config.get(
            "retry.max_retries_auth", DEFAULT_MAX_RETRIES_AUTH
        )
        self._backoff_base: float = config.get(
            "retry.backoff_base_seconds", DEFAULT_BACKOFF_BASE
        )

        # ── 타임아웃 설정 ──────────────────────────────
        self._timeout_order: float = config.get("timeout.order", DEFAULT_TIMEOUT_ORDER)
        self._timeout_query: float = config.get("timeout.query", DEFAULT_TIMEOUT_QUERY)
        self._timeout_auth: float = config.get("timeout.auth", DEFAULT_TIMEOUT_AUTH)

        # ── Circuit Breaker ────────────────────────────
        cb_threshold = config.get(
            "circuit_breaker.failure_threshold", DEFAULT_CB_FAILURE_THRESHOLD
        )
        cb_timeout = config.get(
            "circuit_breaker.recovery_timeout", DEFAULT_CB_RECOVERY_TIMEOUT
        )
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=cb_threshold,
            recovery_timeout=cb_timeout,
            eventbus=eventbus,
            name="kis",
        )

        # ── 재시도 핸들러 ─────────────────────────────
        self._retry_handler = KISRetryHandler(backoff_base=self._backoff_base)

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Circuit breaker 접근자."""
        return self._circuit_breaker

    # ── 연결 ───────────────────────────────────────

    async def connect(self) -> None:
        """KIS API 연결 및 인증."""
        try:
            import aiohttp
        except ImportError as e:
            raise ImportError("aiohttp 패키지가 필요합니다: pip install aiohttp") from e

        self._session = aiohttp.ClientSession()
        await self._authenticate()
        self.is_connected = True
        logger.info("KIS API 연결 완료 (모의투자: %s)", self.is_paper)

    async def disconnect(self) -> None:
        """연결 해제."""
        if self._session:
            await self._session.close()
            self._session = None
        self.is_connected = False
        logger.info("KIS API 연결 해제")

    # ── 인증 ───────────────────────────────────────

    async def _authenticate(self) -> None:
        """OAuth2 접근 토큰 발급."""
        url = f"{self.base_url}/oauth2/tokenP"
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.app_secret,
        }

        timeout = self._get_timeout(url)
        async with asyncio.timeout(timeout):
            async with self._session.post(
                url, json=data, headers={"content-type": "application/json"}
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    raise AuthenticationError(
                        f"인증 실패 (HTTP {response.status}): {text}"
                    )

                result = await response.json()
                self.access_token = result["access_token"]
                self.token_expires_at = datetime.now(UTC) + timedelta(hours=24)
                logger.info("KIS 토큰 발급 완료")

    async def _ensure_authenticated(self) -> None:
        """토큰 유효성 확인 및 재발급."""
        if (
            not self.access_token
            or not self.token_expires_at
            or datetime.now(UTC) >= self.token_expires_at - timedelta(minutes=5)
        ):
            await self._authenticate()

    # ── Rate Limiting ──────────────────────────────

    async def _rate_limit_wait(self) -> None:
        """Rate limit 준수 대기."""
        now = datetime.now(UTC)
        cutoff = now - timedelta(minutes=1)
        self._request_times = [t for t in self._request_times if t > cutoff]

        if len(self._request_times) >= self._rate_limit_per_minute:
            oldest = min(self._request_times)
            wait_seconds = 60 - (now - oldest).total_seconds()
            if wait_seconds > 0:
                logger.debug("Rate limit 대기: %.1f초", wait_seconds)
                await asyncio.sleep(wait_seconds)

        self._request_times.append(now)

    # ── 타임아웃 / 재시도 설정 ─────────────────────

    def _get_timeout(self, url: str) -> float:
        """URL 기반 타임아웃 결정."""
        if _AUTH_PATH in url:
            return self._timeout_auth
        return self._timeout_order  # 주문/조회 기본값

    def _get_max_retries(self, url: str, tr_id: str) -> int:
        """API 유형별 최대 재시도 횟수."""
        if _AUTH_PATH in url:
            return self._max_retries_auth
        if tr_id in _ORDER_TR_IDS:
            return self._max_retries_order
        return self._max_retries_query

    # ── 헤더/응답 처리 ─────────────────────────────

    def _get_headers(self, tr_id: str = "") -> dict[str, str]:
        """API 요청 헤더 구성."""
        return {
            "Content-Type": "application/json",
            "authorization": f"Bearer {self.access_token}",
            "appKey": self.app_key,
            "appSecret": self.app_secret,
            "tr_id": tr_id,
            "custtype": "P",
        }

    async def _handle_response(self, response: Any) -> dict[str, Any]:
        """API 응답 처리 (에러 분류 포함).

        HTTP status != 200이면서 응답 body에 KIS business payload(``rt_cd`` /
        ``msg_cd``)가 함께 들어오는 경우 broker business error로 승격해
        ``APIError.error_code``에 ``msg_cd``를 보존한다.

        retryable 우선순위 (#1338):
            1. ``msg_cd`` ∈ ``PERMANENT_MSG_CODES`` → ``False`` (강제).
            2. HTTP status가 non-retryable(401/403/404/422 등) → ``False`` (강제).
            3. ``msg_cd`` ∈ ``TRANSIENT_MSG_CODES`` → ``True``.
            4. 그 외 unknown msg_cd는 HTTP status retryable에 따른다.

        JSON 파싱 실패, ``rt_cd`` 부재, ``rt_cd == "0"`` 등 KIS payload로
        판정되지 않는 경우는 generic ``HTTP <status>: <text>``로 fallback한다.
        """
        if response.status != 200:
            text = await response.text()
            if isinstance(text, bytes):
                text = text.decode("utf-8", errors="replace")
            retryable = is_retryable_http_status(response.status)
            msg_cd = ""
            msg1 = ""
            try:
                payload = json.loads(text) if text else {}
                if isinstance(payload, dict) and payload.get("rt_cd", "") not in (
                    "",
                    "0",
                ):
                    msg_cd = str(payload.get("msg_cd", ""))
                    msg1 = str(payload.get("msg1", text))
            except (ValueError, TypeError):
                pass
            if msg_cd:
                # msg1이 빈 문자열/공백이면 get_error_message(msg_cd)로 폴백해
                # error_message가 비어 있지 않도록 보장한다 (#2324). 이 분기는
                # msg_cd truthy일 때만 실행되므로 폴백은 항상 의미 있는 값이다.
                msg1 = str(payload.get("msg1") or "").strip()
                if not msg1:
                    msg1 = get_error_message(msg_cd)
                # retryable 우선순위 (#1338, Codex Plan Review v2):
                # 1. PERMANENT_MSG_CODES → false 강제.
                # 2. HTTP non-retryable (auth/client) → false 강제.
                # 3. TRANSIENT_MSG_CODES → true.
                # 4. 기본은 HTTP retryable.
                if msg_cd in PERMANENT_MSG_CODES:
                    retryable = False
                elif not is_retryable_http_status(response.status):
                    retryable = False
                elif msg_cd in TRANSIENT_MSG_CODES:
                    retryable = True
                # else: HTTP 기준 retryable 유지
                raise APIError(
                    f"KIS API Error [{msg_cd}]: {msg1}",
                    error_code=msg_cd,
                    status_code=response.status,
                    retryable=retryable,
                )
            raise APIError(
                f"HTTP {response.status}: {text}",
                status_code=response.status,
                retryable=retryable,
            )

        result = await response.json()
        rt_cd = result.get("rt_cd", "")
        if rt_cd != "0":
            msg_cd = result.get("msg_cd", "")
            # msg1이 빈 문자열/공백이면 get_error_message(msg_cd)로 폴백해
            # error_message가 비어 있지 않도록 보장한다 (#2324).
            msg1 = str(result.get("msg1") or "").strip()
            if not msg1:
                msg1 = get_error_message(msg_cd)
            retryable = is_retryable_msg_code(msg_cd)
            raise APIError(
                f"KIS API Error [{msg_cd}]: {msg1}",
                error_code=msg_cd,
                retryable=retryable,
            )
        return result

    async def _request(
        self,
        method: str,
        url: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃).

        body dict만 반환한다. 주문 접수/취소 등 비페이지 호출자가 사용하며,
        응답 ``tr_cont`` 헤더가 필요한 연속조회 경로는 ``_request_with_cont``
        를 사용한다.

        조율만 담당하며, 에러 분류는 KISErrorClassifier,
        재시도 전략은 KISRetryHandler에 위임한다.
        """
        body, _ = await self._request_with_cont(
            method, url, tr_id, params=params, json_data=json_data
        )
        return body

    async def _request_with_cont(
        self,
        method: str,
        url: str,
        tr_id: str,
        params: dict[str, str] | None = None,
        json_data: dict[str, Any] | None = None,
        cont_header: str = "",
    ) -> tuple[dict[str, Any], str]:
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃).

        ``(body, tr_cont)`` 튜플을 반환하는 페이지네이션 전용 저수준 변형.
        circuit-breaker / 재시도 / rate-limit / 타임아웃 정책을 ``_request``
        와 **동일하게 공유**한다 (로직 중복 금지). ``cont_header`` 는 KIS 연속
        조회 요청 헤더 ``tr_cont`` 값("" 최초 / "N" 다음)이며, 반환 두 번째
        값은 응답 헤더 ``tr_cont`` ("F"/"M"=다음 있음 / "D"/"E"=마지막)이다.
        """
        self._circuit_breaker.check()
        await self._ensure_authenticated()
        await self._rate_limit_wait()

        max_retries = self._get_max_retries(url, tr_id)
        timeout = self._timeout_order if tr_id in _ORDER_TR_IDS else self._timeout_query
        headers = self._get_headers(tr_id)
        if cont_header:
            headers["tr_cont"] = cont_header
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                result = await self._send_http(
                    method, url, headers, params, json_data, timeout
                )
                self._circuit_breaker.record_success()
                return result
            except Exception as e:
                retryable, record_failure = KISErrorClassifier.classify(e)
                if not retryable:
                    raise
                last_error = KISErrorClassifier.to_api_error(e, timeout)
                if record_failure:
                    self._circuit_breaker.record_failure()
                if self._retry_handler.should_retry(attempt, max_retries):
                    await self._retry_handler.wait_and_log(
                        attempt, max_retries, tr_id, e
                    )
                    continue

        raise last_error  # type: ignore[misc]

    async def _send_http(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, str] | None,
        json_data: dict[str, Any] | None,
        timeout: float,
    ) -> tuple[dict[str, Any], str]:
        """단일 HTTP 요청 실행 (타임아웃 적용).

        ``(body, tr_cont)`` 튜플을 반환한다. ``tr_cont`` 는 KIS 연속조회 응답
        헤더이며, 헤더가 없으면 빈 문자열이다. GET/POST 양쪽 모두 헤더를
        캡처하되 의미 있는 값은 GET 조회 경로에서만 사용된다.
        """
        async with asyncio.timeout(timeout):
            if method == "GET":
                async with self._session.get(
                    url, headers=headers, params=params
                ) as resp:
                    body = await self._handle_response(resp)
                    return body, resp.headers.get("tr_cont", "")
            else:
                async with self._session.post(
                    url, headers=headers, json=json_data
                ) as resp:
                    body = await self._handle_response(resp)
                    return body, resp.headers.get("tr_cont", "")

    async def _request_paginated(
        self,
        method: str,
        url: str,
        tr_id: str,
        base_params: dict[str, str],
        row_key: str,
    ) -> list[dict[str, Any]]:
        """KIS 연속조회(CTX_AREA + tr_cont)를 따라 전 페이지 행을 누적한다.

        ``base_params`` 는 첫 페이지 요청 파라미터이며 ``CTX_AREA_FK100`` /
        ``CTX_AREA_NK100`` 은 빈 문자열로 시작한다(호출자가 전달). ``row_key``
        로 지정한 단일 행 리스트(예: ``"output1"`` / ``"output"``)만 누적하며,
        ``output2`` 같은 summary/metadata 는 누적하지 않는다.

        연속 규약:
            - 최초 요청: 요청 헤더 ``tr_cont`` = "" + cursor = "".
            - 응답 헤더 ``tr_cont`` 가 "F"/"M" 이면 body 의 ``ctx_area_fk100`` /
              ``ctx_area_nk100`` 를 다음 요청 ``CTX_AREA_FK100`` /
              ``CTX_AREA_NK100`` 로 넣고 요청 헤더 ``tr_cont`` = "N" 로 재호출.
            - "D"/"E"(또는 그 외) 이면 마지막 페이지로 보고 종료.

        가드:
            - "F"/"M" 인데 다음 cursor 가 비어 있으면 무한루프/누락을 막기 위해
              ``logger.warning`` 후 중단(잔여 페이지 누락 가능성 surface).
            - 최대 페이지 수(``DEFAULT_MAX_PAGINATION_PAGES``) 도달 시
              ``logger.warning`` 후 중단.
        """
        rows: list[dict[str, Any]] = []
        params = dict(base_params)
        cont_header = ""

        for page in range(1, DEFAULT_MAX_PAGINATION_PAGES + 1):
            body, tr_cont = await self._request_with_cont(
                method, url, tr_id, params=params, cont_header=cont_header
            )
            page_rows = body.get(row_key) or []
            rows.extend(page_rows)

            if tr_cont not in _TR_CONT_HAS_NEXT:
                # "D"/"E" 또는 헤더 부재 → 마지막 페이지.
                break

            next_fk = str(body.get("ctx_area_fk100", "") or "").strip()
            next_nk = str(body.get("ctx_area_nk100", "") or "").strip()
            if not next_fk and not next_nk:
                logger.warning(
                    "KIS 연속조회 cursor 누락 [%s] tr_cont=%s page=%d "
                    "(잔여 페이지 누락 가능)",
                    tr_id,
                    tr_cont,
                    page,
                )
                break

            params["CTX_AREA_FK100"] = next_fk
            params["CTX_AREA_NK100"] = next_nk
            cont_header = "N"
        else:
            logger.warning(
                "KIS 연속조회 최대 페이지(%d) 도달 [%s] (잔여 페이지 누락 가능)",
                DEFAULT_MAX_PAGINATION_PAGES,
                tr_id,
            )

        return rows

    # ── 서브클래스 확장 포인트 ──────────────────────

    @abstractmethod
    async def get_account_balance(self) -> dict[str, float]:
        """계좌 잔고 조회."""
        ...

    @abstractmethod
    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회."""
        ...

    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        ...

    @abstractmethod
    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수."""
        ...

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소."""
        ...

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회."""
        ...

    @abstractmethod
    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        ...

    @abstractmethod
    async def get_account_positions(self) -> list[dict[str, Any]]:
        """대사용 보유 잔고 조회."""
        ...

    @abstractmethod
    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회."""
        ...

    @abstractmethod
    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """종목 마스터 데이터 조회."""
        ...

    @abstractmethod
    def get_commission_info(self) -> CommissionInfo:
        """수수료율 정보 반환."""
        ...


# ── KISDomesticAdapter — 국내주식 전용 ────────────────────


class KISDomesticAdapter(KISBaseAdapter):
    """한국투자증권 국내주식 전용 어댑터.

    KISBaseAdapter를 상속하여 국내주식 API 경로, 주문 파라미터,
    시세 조회, 수수료 등 국내 전용 로직을 구현한다.
    """

    broker_id: str = "kis-domestic"
    broker_name: str = "한국투자증권 국내"
    broker_short_name: str = "KIS"

    def __init__(
        self,
        config: dict[str, Any],
        eventbus: EventBus | None = None,
    ) -> None:
        config.setdefault("exchange", "KRX")
        config.setdefault("currency", "KRW")
        super().__init__(config, eventbus)

        # 수수료율 (buy/sell 분리)
        self._buy_commission_rate: float = config.get(
            "buy_commission_rate",
            config.get("commission_rate", 0.00015),
        )
        self._sell_commission_rate: float = config.get(
            "sell_commission_rate",
            # 하위호환: commission_rate + sell_tax_rate
            config.get("commission_rate", 0.00015)
            + config.get("sell_tax_rate", 0.0018),
        )

        # order-cash 응답에서 캡처한 KRX_FWDG_ORD_ORGNO 캐시 (#2345).
        # 취소(order-rvsecncl)는 원주문별 한국거래소전송주문조직번호를 전송해야
        # 한다. place_order 성공 응답의 output.KRX_FWDG_ORD_ORGNO(non-empty)를
        # (값, 제출 KST 영업일)로 broker_order_id(ODNO)에 매핑해 둔다. cancel_order
        # 는 순수 dict 조회(네트워크 없음)로 이를 주입한다.
        #
        # scope: 어댑터 인스턴스(=계좌, gateway._get_broker(account_id))당 분리.
        #   추가로 KIS odno 는 영업일 재사용 가능(OrderTracker 문서)하므로 캐시
        #   값에 제출 영업일을 함께 두고 취소 시 영업일 불일치면 miss 로 처리한다.
        # bounded: OrderedDict + maxlen 으로 무한 증가/stale 누적을 막는다.
        # known-limitation: in-process 한정(재기동 시 소실 → miss=필드 생략, 안전).
        self._krx_fwdg_orgno_cache: OrderedDict[str, tuple[str, str]] = OrderedDict()

    # ── 계좌 정보 조회 ─────────────────────────────

    def _balance_params(self) -> dict[str, str]:
        """잔고 조회 공통 파라미터."""
        return {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "01",
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

    async def get_account_balance(self) -> dict[str, float]:
        """계좌 잔고 조회."""
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        result = await self._request("GET", url, tr_id, params=self._balance_params())

        info = result["output2"][0] if result.get("output2") else {}
        return {
            "cash": float(info.get("dnca_tot_amt", 0)),
            "total_assets": float(info.get("tot_evlu_amt", 0)),
            "purchase_amount": float(info.get("pchs_amt_smtl_amt", 0)),
            "eval_amount": float(info.get("evlu_amt_smtl_amt", 0)),
            "total_profit_loss": float(info.get("evlu_pfls_smtl_amt", 0)),
            "purchasable_amount": float(info.get("psbl_sbst_amt", 0)),
        }

    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회 (CTX_AREA 연속조회로 전 페이지 누적)."""
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        rows = await self._request_paginated(
            "GET", url, tr_id, self._balance_params(), row_key="output1"
        )

        positions = []
        for item in rows:
            qty = float(item.get("hldg_qty", 0))
            if qty > 0:
                positions.append(
                    {
                        "symbol": item["pdno"],
                        "name": item.get("prdt_name", ""),
                        "quantity": qty,
                        "avg_price": float(item.get("pchs_avg_pric", 0)),
                        "current_price": float(item.get("prpr", 0)),
                        "eval_amount": float(item.get("evlu_amt", 0)),
                        "profit_loss": float(item.get("evlu_pfls_amt", 0)),
                        "profit_loss_rate": float(item.get("evlu_erng_rt", 0)),
                    }
                )
        return positions

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        tr_id = "FHKST01010100"
        url = f"{self.base_url}/uapi/domestic-stock/v1/quotations/inquire-price"
        params = {
            "fid_cond_mrkt_div_code": "J",
            "fid_input_iscd": self.normalize_symbol(symbol),
        }
        result = await self._request("GET", url, tr_id, params=params)
        return float(result["output"]["stck_prpr"])

    # ── 주문 처리 ──────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수. KIS는 stop order 미지원."""
        if order_type in ("stop", "stop_limit"):
            raise ValueError(
                f"KIS does not support {order_type} orders natively. "
                "Use StopOrderManager for stop order emulation."
            )

        if side == "buy":
            tr_id = "VTTC0012U" if self.is_paper else "TTTC0012U"
        else:
            tr_id = "VTTC0011U" if self.is_paper else "TTTC0011U"

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        order_data = self._build_order_data(symbol, side, quantity, order_type, price)

        result = await self._request("POST", url, tr_id, json_data=order_data)
        output = result["output"]
        broker_order_id = output["ODNO"]
        # 취소 시 전송할 KRX_FWDG_ORD_ORGNO 를 order-cash 응답에서 직접 캡처한다
        # (#2345). 공식 order-cash 결과 컬럼(chk_order_cash.py)에 ODNO/ORD_TMD 와
        # 함께 KRX_FWDG_ORD_ORGNO 가 정의되어 있다. 응답 구조 변동에 방어적으로
        # 대응하기 위해 .get() 으로 읽고, non-empty 일 때만 캐시한다(오값 전송 금지).
        self._cache_krx_fwdg_orgno(broker_order_id, output.get("KRX_FWDG_ORD_ORGNO"))
        logger.info(
            "주문 접수: %s %s %s %.0f주 → %s",
            side,
            order_type,
            symbol,
            quantity,
            broker_order_id,
        )
        return broker_order_id

    def _cache_krx_fwdg_orgno(self, broker_order_id: str, orgno: str | None) -> None:
        """order-cash 응답의 KRX_FWDG_ORD_ORGNO 를 제출 영업일과 함께 캐시 (#2345).

        non-empty 값만 저장한다. broker_order_id(ODNO) 키로 (값, 제출 KST 영업일)
        을 매핑하며, bounded(OrderedDict + maxlen)로 무한 증가를 막는다.
        취소 시 cancel_order 가 영업일 일치 여부까지 확인해 주입한다.
        """
        if not orgno:
            # 응답에 필드가 없거나 빈 값이면 캐시하지 않는다 → 취소 시 miss(생략).
            return
        cache = self._krx_fwdg_orgno_cache
        cache[broker_order_id] = (orgno, business_date_kst())
        cache.move_to_end(broker_order_id)
        while len(cache) > _KRX_FWDG_ORGNO_CACHE_MAXLEN:
            cache.popitem(last=False)

    def _build_order_data(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None,
    ) -> dict[str, str]:
        """KIS 주문 데이터 구성."""
        data = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "PDNO": self.normalize_symbol(symbol),
            "ORD_DVSN": self._map_order_type(order_type),
            "ORD_QTY": str(int(quantity)),
            "ORD_UNPR": "0",
            # 거래소ID구분코드 — KIS 공식 order-cash 현행 계약의 필수 필드(#2344).
            # 공식 order_cash.py 가 excg_id_dvsn_cd 누락 시 ValueError 로 가드한다.
            # market/limit·side 무관 공통(국내 KRX 기본).
            "EXCG_ID_DVSN_CD": DEFAULT_EXCG_ID_DVSN_CD,
        }
        if order_type == "limit" and price is not None:
            data["ORD_UNPR"] = str(int(price))
        return data

    def _map_order_type(self, order_type: str) -> str:
        """KIS ORD_DVSN 코드 매핑."""
        mapping = {
            "market": "01",
            "limit": "00",
            "conditional": "02",
            "best": "03",
            "priority": "04",
        }
        return mapping.get(order_type, "01")

    def _map_order_status(self, status_code: str) -> str:
        """KIS 주문 상태 코드 매핑."""
        mapping = {
            "10": "pending",
            "11": "confirmed",
            "20": "partial_filled",
            "30": "filled",
            "40": "cancelled",
            "50": "rejected",
        }
        return mapping.get(status_code, "unknown")

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소.

        취소(order-rvsecncl) body 에 원주문별 ``KRX_FWDG_ORD_ORGNO``
        (한국거래소전송주문조직번호)를 전송한다(#2345). 값은 place_order 시
        order-cash 응답에서 캡처해 둔 인메모리 캐시에서 가져오며, 순수 dict
        조회로 네트워크/추가 조회를 하지 않는다. 캐시 miss 또는 제출 영업일
        불일치(odno 재사용 등) 시에는 필드를 생략한다(기존 동작 유지).
        """
        tr_id = "VTTC0803U" if self.is_paper else "TTTC0803U"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-rvsecncl"
        cancel_data = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "ORGN_ODNO": order_id,
            "ORD_DVSN": "01",
            "RVSE_CNCL_DVSN_CD": "02",
            "ORD_QTY": "0",
            "ORD_UNPR": "0",
            "QTY_ALL_ORD_YN": "Y",
        }
        cached = self._krx_fwdg_orgno_cache.get(order_id)
        if cached is not None and cached[1] == business_date_kst():
            cancel_data["KRX_FWDG_ORD_ORGNO"] = cached[0]
        else:
            logger.debug(
                "취소 KRX_FWDG_ORD_ORGNO 생략: %s (cache=%s)",
                order_id,
                "miss" if cached is None else "stale-date",
            )
        await self._request("POST", url, tr_id, json_data=cancel_data)
        logger.info("주문 취소 성공: %s", order_id)
        return True

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회 (CTX_AREA 연속조회로 전 페이지 확보 후 검색)."""
        tr_id = "VTTC8036R" if self.is_paper else "TTTC8036R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "1",
            "INQR_DVSN_2": "0",
        }
        orders = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output"
        )

        for order in orders:
            if order.get("odno") == order_id:
                return {
                    "order_id": order["odno"],
                    "symbol": order.get("pdno", ""),
                    "side": "buy" if order.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(order.get("ord_qty", 0)),
                    "filled_quantity": float(order.get("tot_ccld_qty", 0)),
                    "remaining_quantity": float(order.get("rmn_qty", 0)),
                    "status": self._map_order_status(order.get("ord_stat_cd", "")),
                    "price": float(order.get("ord_unpr", 0)) or None,
                    "avg_fill_price": float(order.get("avg_prvs", 0)) or None,
                }

        raise OrderNotFoundError(f"Order {order_id} not found")

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회 (CTX_AREA 연속조회로 전 페이지 누적)."""
        tr_id = "VTTC8036R" if self.is_paper else "TTTC8036R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
            "INQR_DVSN_1": "1",
            "INQR_DVSN_2": "0",
        }
        rows = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output"
        )

        orders = []
        for order in rows:
            orders.append(
                {
                    "order_id": order.get("odno", ""),
                    "symbol": order.get("pdno", ""),
                    "side": "buy" if order.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(order.get("ord_qty", 0)),
                    "filled_quantity": float(order.get("tot_ccld_qty", 0)),
                    "remaining_quantity": float(order.get("rmn_qty", 0)),
                    "status": self._map_order_status(order.get("ord_stat_cd", "")),
                }
            )
        return orders

    # ── 종목 마스터 ────────────────────────────────────

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """KIS API에서 종목 마스터 데이터 조회 (코스피 + 코스닥)."""
        instruments: list[dict[str, Any]] = []

        # 코스피(J) + 코스닥(Q)
        market_codes = [("J", "KOSPI"), ("Q", "KOSDAQ")]
        for mrkt_code, market_name in market_codes:
            try:
                items = await self._fetch_stock_list(mrkt_code)
                for item in items:
                    inst_type = self._classify_instrument_type(
                        item.get("std_pdno", ""),
                        item.get("prdt_name", ""),
                        item.get("rprs_mrkt_kor_name", market_name),
                    )
                    instruments.append(
                        {
                            "symbol": item.get("std_pdno", ""),
                            "name": item.get("prdt_name", ""),
                            "name_en": item.get("prdt_eng_name", ""),
                            "instrument_type": inst_type,
                            "listed": True,
                        }
                    )
                logger.info("KIS 종목 조회 완료: %s %d건", market_name, len(items))
            except Exception:
                logger.warning("KIS %s 종목 조회 실패", market_name, exc_info=True)

        return instruments

    # 마스터 파일 다운로드 설정 (KIS 공식 방식)
    _MASTER_FILES: dict[str, dict[str, str | int]] = {
        "J": {
            "url": "https://new.real.download.dws.co.kr/common/master/kospi_code.mst.zip",
            "filename": "kospi_code.mst",
            "tail_len": 228,
        },
        "Q": {
            "url": "https://new.real.download.dws.co.kr/common/master/kosdaq_code.mst.zip",
            "filename": "kosdaq_code.mst",
            "tail_len": 222,
        },
    }

    async def _fetch_stock_list(self, mrkt_code: str) -> list[dict[str, Any]]:
        """KIS 마스터 파일 다운로드로 종목 목록 조회.

        기존 CTPF1702R API가 404를 반환하여, KIS 공식 마스터 파일
        다운로드 방식으로 대체 (koreainvestment/open-trading-api 참조).
        """
        import io
        import zipfile

        config = self._MASTER_FILES.get(mrkt_code)
        if config is None:
            raise ValueError(f"지원하지 않는 시장 코드: {mrkt_code}")

        url = str(config["url"])
        filename = str(config["filename"])
        tail_len = int(config["tail_len"])

        async with self._session.get(url) as resp:
            resp.raise_for_status()
            zip_data = await resp.read()

        with zipfile.ZipFile(io.BytesIO(zip_data)) as zf:
            raw = zf.read(filename)

        items: list[dict[str, Any]] = []
        for line in raw.decode("cp949").splitlines():
            if not line.strip():
                continue
            part1 = line[: len(line) - tail_len]
            short_code = part1[0:9].strip()
            name = part1[21:].strip()

            if len(short_code) == 6 and short_code.isdigit():
                items.append(
                    {
                        "std_pdno": short_code,
                        "prdt_name": name,
                        "prdt_eng_name": "",
                    }
                )

        return items

    @staticmethod
    def _classify_instrument_type(symbol: str, name: str, market: str) -> str:
        """종목명/코드 기반 instrument_type 분류."""
        name_upper = name.upper()
        if "ETF" in name_upper or "KODEX" in name_upper or "TIGER" in name_upper:
            return "etf"
        if "ETN" in name_upper:
            return "etn"
        return "stock"

    # ── 수수료 ────────────────────────────────────────

    def get_commission_info(self) -> CommissionInfo:
        """KIS 국내 수수료율 정보 반환."""
        return CommissionInfo(
            buy_commission_rate=self._buy_commission_rate,
            sell_commission_rate=self._sell_commission_rate,
        )

    # ── 대사용 조회 ────────────────────────────────

    async def get_account_positions(self) -> list[dict[str, Any]]:
        """대사용 보유 잔고 조회."""
        positions = await self.get_positions()
        return [
            {
                "symbol": p["symbol"],
                "quantity": p["quantity"],
                "avg_price": p["avg_price"],
            }
            for p in positions
        ]

    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회 (CTX_AREA 연속조회로 전 페이지 누적 후 fold)."""
        tr_id = "VTTC8001R" if self.is_paper else "TTTC8001R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"

        now = datetime.now(UTC)
        params = {
            "CANO": self.account_no[:8],
            "ACNT_PRDT_CD": self.account_no[8:10],
            "INQR_STRT_DT": from_date or (now - timedelta(days=7)).strftime("%Y%m%d"),
            "INQR_END_DT": to_date or now.strftime("%Y%m%d"),
            "SLL_BUY_DVSN_CD": "00",
            "INQR_DVSN": "00",
            "PDNO": "",
            "CCLD_DVSN": "00",
            "ORD_GNO_BRNO": "",
            "ODNO": "",
            "INQR_DVSN_3": "00",
            "INQR_DVSN_1": "",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": "",
        }

        rows = await self._request_paginated(
            "GET", url, tr_id, params, row_key="output1"
        )
        return self._fold_order_history(rows)

    @staticmethod
    def _fold_order_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """inquire-daily-ccld ``output1`` 행을 (odno, 영업일)별로 fold.

        KIS ``output1`` 은 조회 구분에 따라 주문별 누적 1행 또는 부분체결별 다행이
        올 수 있다 (#1946 R1-4). 같은 ``odno`` + ``ord_dt`` 행을 하나로 접되:

        - ``filled_quantity`` = 누적 체결수량 ``tot_ccld_qty`` 의 **max**
          (누적 행이면 마지막 값, 부분체결 행이면 단조 증가하므로 max 가 안전).
        - ``price`` = **실체결가** = ``tot_ccld_amt`` / ``tot_ccld_qty``
          (체결금액/체결수량). ``tot_ccld_amt`` 가 없으면 ``avg_prvs``(평균체결가),
          그것도 없으면 ``ord_unpr``(주문가) 순으로 fallback. 주문가(``ord_unpr``)를
          체결가로 쓰던 기존 매핑을 교정한다.

        ``broker_order_id``(odno) / 누적 체결qty / avg price / 영업일(ord_dt) 을
        반환에 포함해 FillApplier 의 ``(account_id, broker_order_id, submitted_date)``
        조회와 누적 체결 advance 를 가능하게 한다.
        """
        folded: dict[tuple[str, str], dict[str, Any]] = {}
        for item in rows:
            odno = str(item.get("odno", ""))
            ord_dt = str(item.get("ord_dt", ""))
            if not odno:
                continue
            cum_qty = float(item.get("tot_ccld_qty", 0) or 0)
            ccld_amt = float(item.get("tot_ccld_amt", 0) or 0)
            avg_prvs = float(item.get("avg_prvs", 0) or 0)
            ord_unpr = float(item.get("ord_unpr", 0) or 0)
            # 실체결가 우선순위: 체결금액/체결수량 → 평균체결가 → 주문가.
            if cum_qty > 0 and ccld_amt > 0:
                fill_price = ccld_amt / cum_qty
            elif avg_prvs > 0:
                fill_price = avg_prvs
            else:
                fill_price = ord_unpr

            key = (odno, ord_dt)
            existing = folded.get(key)
            if existing is None or cum_qty >= existing["filled_quantity"]:
                # 누적 체결qty 가 더 크거나 같은(최신) 행으로 갱신.
                folded[key] = {
                    "order_id": odno,
                    "symbol": item.get("pdno", ""),
                    "side": "buy" if item.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(item.get("ord_qty", 0) or 0),
                    "filled_quantity": cum_qty,
                    "price": fill_price,
                    "status": "filled" if cum_qty > 0 else "pending",
                    "timestamp": ord_dt,
                }
        return list(folded.values())


# ── 하위호환 별칭 ─────────────────────────────────────
# 기존 코드에서 KISAdapter를 참조하는 곳이 있으므로 별칭을 유지한다.
KISAdapter = KISDomesticAdapter
