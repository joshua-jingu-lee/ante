"""한국투자증권 (KIS) Open API 어댑터.

KIS REST API + WebSocket을 통해 주문, 조회, 실시간 스트리밍을 처리한다.
실행 시 aiohttp 패키지가 필요하다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
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


class KISAdapter(BrokerAdapter):
    """한국투자증권 Open API 어댑터."""

    def __init__(
        self,
        config: dict[str, Any],
        eventbus: EventBus | None = None,
    ) -> None:
        config.setdefault("exchange", "KRX")
        super().__init__(config)

        self.app_key: str = config["app_key"]
        self.app_secret: str = config["app_secret"]
        self.account_no: str = config["account_no"]
        self.is_paper: bool = config.get("is_paper", False)
        self._commission_rate: float = config.get("commission_rate", 0.00015)
        self._sell_tax_rate: float = config.get("sell_tax_rate", 0.0023)
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

    @property
    def circuit_breaker(self) -> CircuitBreaker:
        """Circuit breaker 접근자."""
        return self._circuit_breaker

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
        """API 요청 공통 래퍼 (circuit breaker + 재시도 + 타임아웃)."""
        # [1] Circuit Breaker 확인
        self._circuit_breaker.check()

        await self._ensure_authenticated()
        await self._rate_limit_wait()

        max_retries = self._get_max_retries(url, tr_id)
        timeout = self._timeout_query
        if tr_id in _ORDER_TR_IDS:
            timeout = self._timeout_order

        headers = self._get_headers(tr_id)
        last_error: Exception | None = None

        for attempt in range(max_retries + 1):
            try:
                # [2] API 호출 (타임아웃 적용)
                async with asyncio.timeout(timeout):
                    if method == "GET":
                        async with self._session.get(
                            url, headers=headers, params=params
                        ) as resp:
                            result = await self._handle_response(resp)
                    else:
                        async with self._session.post(
                            url, headers=headers, json=json_data
                        ) as resp:
                            result = await self._handle_response(resp)

                # 성공
                self._circuit_breaker.record_success()
                return result

            except CircuitOpenError:
                raise
            except TimeoutError:
                last_error = APIError(
                    f"타임아웃 ({timeout:.0f}초 초과)",
                    retryable=True,
                )
                self._circuit_breaker.record_failure()
                if attempt < max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "API 타임아웃 [%s] 재시도 %d/%d (%.1f초 후)",
                        tr_id,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
            except (ConnectionError, OSError) as e:
                last_error = APIError(str(e), retryable=True)
                self._circuit_breaker.record_failure()
                if attempt < max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "네트워크 오류 [%s] 재시도 %d/%d (%.1f초 후): %s",
                        tr_id,
                        attempt + 1,
                        max_retries,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
                    continue
            except RateLimitError as e:
                last_error = e
                self._circuit_breaker.record_failure()
                if attempt < max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "Rate limit [%s] 재시도 %d/%d (%.1f초 후)",
                        tr_id,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
            except APIError as e:
                last_error = e
                if not e.retryable:
                    # permanent 에러 → 즉시 실패 (circuit breaker에 기록하지 않음)
                    raise
                self._circuit_breaker.record_failure()
                if attempt < max_retries:
                    wait = self._backoff_base * (2**attempt)
                    logger.warning(
                        "API 오류 [%s] 재시도 %d/%d (%.1f초 후): %s",
                        tr_id,
                        attempt + 1,
                        max_retries,
                        wait,
                        e,
                    )
                    await asyncio.sleep(wait)
                    continue
            except AuthenticationError:
                raise

        # 모든 재시도 소진
        raise last_error  # type: ignore[misc]

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

    # ── 실시간 스트리밍 (구현 예정) ────────────────

    async def realtime_price_stream(
        self, symbols: list[str]
    ) -> AsyncIterator[dict[str, Any]]:
        """실시간 가격 스트리밍. WebSocket 연동 Phase에서 구현."""
        raise NotImplementedError("실시간 가격 스트리밍은 추후 구현")
        yield {}  # type: ignore[misc]

    async def realtime_order_stream(self) -> AsyncIterator[dict[str, Any]]:
        """실시간 주문 체결 스트리밍. WebSocket 연동 Phase에서 구현."""
        raise NotImplementedError("실시간 주문 스트리밍은 추후 구현")
        yield {}  # type: ignore[misc]

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
        """KIS 수수료율 정보 반환."""
        return CommissionInfo(
            commission_rate=self._commission_rate,
            sell_tax_rate=self._sell_tax_rate,
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
