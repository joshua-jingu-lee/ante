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
import logging
from abc import abstractmethod
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from ante.broker.base import BrokerAdapter
from ante.broker.circuit_breaker import CircuitBreaker
from ante.broker.error_codes import (
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

# 주문 관련 tr_id (재시도 횟수 분류용)
_ORDER_TR_IDS = frozenset(
    {
        "VTTC0802U",
        "TTTC0802U",  # 매수
        "VTTC0801U",
        "TTTC0311U",  # 매도
        "VTTC0803U",
        "TTTC0803U",  # 취소
    }
)

# 인증 경로
_AUTH_PATH = "/oauth2/tokenP"


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
        self.is_paper: bool = config.get("is_paper", False)
        self._eventbus = eventbus

        # API 엔드포인트
        if self.is_paper:
            self.base_url = "https://openapivts.koreainvestment.com:29443"
            self.websocket_url = "ws://ops.koreainvestment.com:21000"
        else:
            self.base_url = "https://openapi.koreainvestment.com:9443"
            self.websocket_url = "ws://ops.koreainvestment.com:31000"

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
        """API 응답 처리 (에러 분류 포함)."""
        if response.status != 200:
            text = await response.text()
            retryable = is_retryable_http_status(response.status)
            raise APIError(
                f"HTTP {response.status}: {text}",
                status_code=response.status,
                retryable=retryable,
            )

        result = await response.json()
        rt_cd = result.get("rt_cd", "")
        if rt_cd != "0":
            msg_cd = result.get("msg_cd", "")
            msg1 = result.get("msg1", "Unknown")
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

        조율만 담당하며, 에러 분류는 KISErrorClassifier,
        재시도 전략은 KISRetryHandler에 위임한다.
        """
        self._circuit_breaker.check()
        await self._ensure_authenticated()
        await self._rate_limit_wait()

        max_retries = self._get_max_retries(url, tr_id)
        timeout = self._timeout_order if tr_id in _ORDER_TR_IDS else self._timeout_query
        headers = self._get_headers(tr_id)
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
    ) -> dict[str, Any]:
        """단일 HTTP 요청 실행 (타임아웃 적용)."""
        async with asyncio.timeout(timeout):
            if method == "GET":
                async with self._session.get(
                    url, headers=headers, params=params
                ) as resp:
                    return await self._handle_response(resp)
            else:
                async with self._session.post(
                    url, headers=headers, json=json_data
                ) as resp:
                    return await self._handle_response(resp)

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
        """보유 포지션 조회."""
        tr_id = "VTTC8434R" if self.is_paper else "TTTC8434R"
        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        result = await self._request("GET", url, tr_id, params=self._balance_params())

        positions = []
        for item in result.get("output1", []):
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
            tr_id = "VTTC0802U" if self.is_paper else "TTTC0802U"
        else:
            tr_id = "VTTC0801U" if self.is_paper else "TTTC0311U"

        url = f"{self.base_url}/uapi/domestic-stock/v1/trading/order-cash"
        order_data = self._build_order_data(symbol, side, quantity, order_type, price)

        result = await self._request("POST", url, tr_id, json_data=order_data)
        broker_order_id = result["output"]["ODNO"]
        logger.info(
            "주문 접수: %s %s %s %.0f주 → %s",
            side,
            order_type,
            symbol,
            quantity,
            broker_order_id,
        )
        return broker_order_id

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
        """주문 취소."""
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
        await self._request("POST", url, tr_id, json_data=cancel_data)
        logger.info("주문 취소 성공: %s", order_id)
        return True

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회."""
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
        result = await self._request("GET", url, tr_id, params=params)

        for order in result.get("output", []):
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
        """미체결 주문 목록 조회."""
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
        result = await self._request("GET", url, tr_id, params=params)

        orders = []
        for order in result.get("output", []):
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
        """주문/체결 이력 조회."""
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

        result = await self._request("GET", url, tr_id, params=params)
        history = []
        for item in result.get("output1", []):
            history.append(
                {
                    "order_id": item.get("odno", ""),
                    "symbol": item.get("pdno", ""),
                    "side": "buy" if item.get("sll_buy_dvsn_cd") == "02" else "sell",
                    "quantity": float(item.get("ord_qty", 0)),
                    "filled_quantity": float(item.get("tot_ccld_qty", 0)),
                    "price": float(item.get("ord_unpr", 0)),
                    "status": "filled"
                    if float(item.get("tot_ccld_qty", 0)) > 0
                    else "pending",
                    "timestamp": item.get("ord_dt", ""),
                }
            )
        return history


# ── 하위호환 별칭 ─────────────────────────────────────
# 기존 코드에서 KISAdapter를 참조하는 곳이 있으므로 별칭을 유지한다.
KISAdapter = KISDomesticAdapter
