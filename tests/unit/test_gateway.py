"""API Gateway 모듈 단위 테스트."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderCancelEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderSubmittedEvent,
)
from ante.gateway import (
    APIGateway,
    APIRequest,
    LiveDataProvider,
    RateLimitConfig,
    RateLimiter,
    RequestPriority,
    RequestQueue,
    ResponseCache,
)

# ── RateLimiter ────────────────────────────────────


class TestRateLimiter:
    async def test_acquire_within_limit(self):
        """제한 내 요청은 즉시 통과."""
        limiter = RateLimiter(RateLimitConfig(max_requests=5, window_seconds=60))
        for _ in range(5):
            await limiter.acquire()
        assert limiter.pending_count == 5

    async def test_acquire_blocks_at_limit(self):
        """제한 초과 시 대기."""
        limiter = RateLimiter(RateLimitConfig(max_requests=2, window_seconds=0.1))
        await limiter.acquire()
        await limiter.acquire()

        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # 일부 대기 발생

    async def test_pending_count(self):
        """윈도우 내 요청 수 추적."""
        limiter = RateLimiter(RateLimitConfig(max_requests=10, window_seconds=60))
        assert limiter.pending_count == 0
        await limiter.acquire()
        assert limiter.pending_count == 1


# ── ResponseCache ──────────────────────────────────


class TestResponseCache:
    def test_set_and_get(self):
        """캐시 저장 및 조회."""
        cache = ResponseCache()
        cache.set("key1", {"price": 50000}, ttl=60)
        assert cache.get("key1") == {"price": 50000}

    def test_get_expired(self):
        """만료된 캐시는 None."""
        cache = ResponseCache()
        cache.set("key1", "data", ttl=0.001)
        import time

        time.sleep(0.01)
        assert cache.get("key1") is None

    def test_get_nonexistent(self):
        """존재하지 않는 키는 None."""
        cache = ResponseCache()
        assert cache.get("nonexistent") is None

    def test_invalidate_pattern(self):
        """패턴 매칭 무효화."""
        cache = ResponseCache()
        cache.set("price:005930", 50000, ttl=60)
        cache.set("price:000660", 30000, ttl=60)
        cache.set("balance", 1000000, ttl=60)

        cache.invalidate("price")
        assert cache.get("price:005930") is None
        assert cache.get("price:000660") is None
        assert cache.get("balance") == 1000000

    def test_invalidate_all(self):
        """전체 캐시 초기화."""
        cache = ResponseCache()
        cache.set("key1", "a", ttl=60)
        cache.set("key2", "b", ttl=60)

        cache.invalidate()
        assert cache.size == 0

    def test_make_key(self):
        """캐시 키 생성."""
        cache = ResponseCache()
        key = cache.make_key("price", {"symbol": "005930", "market": "J"})
        assert "price" in key
        assert "005930" in key

    def test_size(self):
        """캐시 크기."""
        cache = ResponseCache()
        assert cache.size == 0
        cache.set("k1", "v1", ttl=60)
        cache.set("k2", "v2", ttl=60)
        assert cache.size == 2


# ── RequestQueue ───────────────────────────────────


class TestRequestQueue:
    async def test_priority_ordering(self):
        """우선순위 순서로 요청 꺼냄."""
        q = RequestQueue()
        await q.put(
            APIRequest(priority=RequestPriority.PRICE, method="GET", endpoint="/price")
        )
        await q.put(
            APIRequest(priority=RequestPriority.ORDER, method="POST", endpoint="/order")
        )
        await q.put(
            APIRequest(
                priority=RequestPriority.BALANCE, method="GET", endpoint="/balance"
            )
        )

        req1 = await q.get()
        req2 = await q.get()
        req3 = await q.get()
        assert req1.endpoint == "/order"  # ORDER=0 최우선
        assert req2.endpoint == "/balance"  # BALANCE=10
        assert req3.endpoint == "/price"  # PRICE=20

    async def test_fifo_same_priority(self):
        """동일 우선순위는 FIFO."""
        q = RequestQueue()
        await q.put(
            APIRequest(priority=RequestPriority.PRICE, method="GET", endpoint="/price1")
        )
        await q.put(
            APIRequest(priority=RequestPriority.PRICE, method="GET", endpoint="/price2")
        )

        req1 = await q.get()
        req2 = await q.get()
        assert req1.endpoint == "/price1"
        assert req2.endpoint == "/price2"

    async def test_put_returns_future(self):
        """put은 Future를 반환."""
        q = RequestQueue()
        future = await q.put(
            APIRequest(priority=RequestPriority.PRICE, method="GET", endpoint="/price")
        )
        assert isinstance(future, asyncio.Future)

    async def test_empty_and_qsize(self):
        """비어있는지 확인 및 크기."""
        q = RequestQueue()
        assert q.empty() is True
        assert q.qsize == 0

        await q.put(
            APIRequest(priority=RequestPriority.PRICE, method="GET", endpoint="/p")
        )
        assert q.empty() is False
        assert q.qsize == 1

    def test_request_priority_values(self):
        """RequestPriority 값."""
        assert RequestPriority.ORDER < RequestPriority.ORDER_CANCEL
        assert RequestPriority.ORDER_CANCEL < RequestPriority.BALANCE
        assert RequestPriority.BALANCE < RequestPriority.PRICE
        assert RequestPriority.PRICE < RequestPriority.HISTORY


# ── APIGateway ─────────────────────────────────────


class TestAPIGateway:
    @pytest.fixture
    def broker(self):
        b = AsyncMock()
        b.get_current_price = AsyncMock(return_value=50000.0)
        b.get_positions = AsyncMock(
            return_value=[{"symbol": "005930", "quantity": 100}]
        )
        b.get_account_balance = AsyncMock(return_value={"cash": 5000000.0})
        b.place_order = AsyncMock(return_value="BROKER_ORD_001")
        b.cancel_order = AsyncMock(return_value=True)
        return b

    @pytest.fixture
    def account_service(self, broker):
        svc = AsyncMock()
        svc.get_broker = AsyncMock(return_value=broker)
        return svc

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def gateway(self, account_service, eventbus):
        gw = APIGateway(
            account_service=account_service,
            eventbus=eventbus,
            rate_config=RateLimitConfig(max_requests=100, window_seconds=60),
        )
        gw.start()
        return gw

    async def test_get_current_price(self, gateway, broker):
        """현재가 조회 — account_id 기반 브로커 라우팅."""
        price = await gateway.get_current_price("005930", account_id="acc-001")
        assert price == 50000.0
        broker.get_current_price.assert_called_once_with("005930")

    async def test_get_current_price_cached(self, gateway, broker):
        """현재가 캐시 적중 — 동일 account_id는 캐시 공유."""
        await gateway.get_current_price("005930", account_id="acc-001")
        await gateway.get_current_price("005930", account_id="acc-001")
        assert broker.get_current_price.call_count == 1

    async def test_get_current_price_different_accounts(
        self, gateway, broker, account_service
    ):
        """서로 다른 account_id는 캐시가 분리된다."""
        await gateway.get_current_price("005930", account_id="acc-001")
        await gateway.get_current_price("005930", account_id="acc-002")
        assert broker.get_current_price.call_count == 2

    async def test_get_positions(self, gateway, broker):
        """포지션 조회 — account_id로 라우팅."""
        positions = await gateway.get_positions(account_id="acc-001")
        assert len(positions) == 1
        assert positions[0]["symbol"] == "005930"

    async def test_get_positions_cached_per_account(self, gateway, broker):
        """포지션 캐시가 account_id별로 분리된다."""
        await gateway.get_positions(account_id="acc-001")
        await gateway.get_positions(account_id="acc-001")
        assert broker.get_positions.call_count == 1

        await gateway.get_positions(account_id="acc-002")
        assert broker.get_positions.call_count == 2

    async def test_get_account_balance(self, gateway, broker):
        """잔고 조회 — account_id로 라우팅."""
        balance = await gateway.get_account_balance(account_id="acc-001")
        assert balance["cash"] == 5000000.0

    async def test_get_account_balance_cached_per_account(self, gateway, broker):
        """잔고 캐시가 account_id별로 분리된다."""
        await gateway.get_account_balance(account_id="acc-001")
        await gateway.get_account_balance(account_id="acc-001")
        assert broker.get_account_balance.call_count == 1

        await gateway.get_account_balance(account_id="acc-002")
        assert broker.get_account_balance.call_count == 2

    async def test_submit_order(self, gateway, broker):
        """주문 제출 — account_id로 라우팅."""
        order_id = await gateway.submit_order(
            bot_id="bot1",
            symbol="005930",
            side="buy",
            quantity=10,
            account_id="acc-001",
        )
        assert order_id == "BROKER_ORD_001"
        broker.place_order.assert_called_once()

    async def test_cancel_order(self, gateway, broker):
        """주문 취소 — account_id로 라우팅."""
        result = await gateway.cancel_order("ORD001", account_id="acc-001")
        assert result is True
        broker.cancel_order.assert_called_once_with("ORD001")

    async def test_rate_limiter_per_account(self, gateway):
        """계좌별 독립 rate limiter 생성."""
        rl1 = gateway._get_rate_limiter("acc-001")
        rl2 = gateway._get_rate_limiter("acc-002")
        rl1_again = gateway._get_rate_limiter("acc-001")
        assert rl1 is not rl2
        assert rl1 is rl1_again

    async def test_account_service_get_broker_called(self, gateway, account_service):
        """AccountService.get_broker()가 호출된다."""
        await gateway.get_current_price("005930", account_id="acc-001")
        account_service.get_broker.assert_called_with("acc-001")


# ── APIGateway EventBus 통합 ──────────────────────


class TestAPIGatewayEvents:
    @pytest.fixture
    def broker(self):
        b = AsyncMock()
        b.place_order = AsyncMock(return_value="BROKER_ORD_001")
        b.cancel_order = AsyncMock(return_value=True)
        return b

    @pytest.fixture
    def account_service(self, broker):
        svc = AsyncMock()
        svc.get_broker = AsyncMock(return_value=broker)
        return svc

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    async def gateway(self, account_service, eventbus):
        gw = APIGateway(
            account_service=account_service,
            eventbus=eventbus,
            rate_config=RateLimitConfig(max_requests=100, window_seconds=60),
        )
        gw.start()
        return gw

    async def test_order_approved_submits_with_account_id(
        self, gateway, eventbus, broker, account_service
    ):
        """OrderApprovedEvent → account_id로 브로커 라우팅 → OrderSubmittedEvent."""
        received = []
        eventbus.subscribe(OrderSubmittedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                account_id="acc-001",
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                reserved_amount=500000.0,
            )
        )

        assert len(received) == 1
        assert received[0].broker_order_id == "BROKER_ORD_001"
        assert received[0].order_id == "ord1"
        assert received[0].account_id == "acc-001"
        account_service.get_broker.assert_called_with("acc-001")

    async def test_order_approved_failure(
        self, gateway, eventbus, broker, account_service
    ):
        """주문 제출 실패 → OrderFailedEvent에 account_id 포함."""
        broker.place_order = AsyncMock(side_effect=RuntimeError("broker error"))

        received = []
        eventbus.subscribe(OrderFailedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                account_id="acc-001",
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                reserved_amount=500000.0,
            )
        )

        assert len(received) == 1
        assert "broker error" in received[0].error_message
        assert received[0].account_id == "acc-001"
        assert received[0].error_code == ""

    async def test_order_failure_with_api_error_code(
        self, gateway, eventbus, broker, account_service
    ):
        """APIError 주문 실패 → error_code 전달."""
        from ante.broker.exceptions import APIError

        broker.place_order = AsyncMock(
            side_effect=APIError(
                "잔고 부족",
                status_code=500,
                error_code="APBK0919",
                retryable=False,
            )
        )

        received: list[OrderFailedEvent] = []
        eventbus.subscribe(OrderFailedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                account_id="acc-001",
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                reserved_amount=500000.0,
            )
        )

        assert len(received) == 1
        assert received[0].error_code == "APBK0919"
        assert "잔고 부족" in received[0].error_message

    async def test_order_cancel_event_with_account_id(
        self, gateway, eventbus, broker, account_service
    ):
        """OrderCancelEvent → account_id로 브로커 선택 → OrderCancelledEvent."""
        received = []
        eventbus.subscribe(OrderCancelledEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderCancelEvent(
                account_id="acc-001",
                bot_id="bot1",
                strategy_id="s1",
                order_id="ord1",
                reason="test cancel",
            )
        )

        assert len(received) == 1
        assert received[0].order_id == "ord1"
        assert received[0].reason == "test cancel"
        assert received[0].account_id == "acc-001"
        account_service.get_broker.assert_called_with("acc-001")

    async def test_order_filled_invalidates_account_cache(
        self, gateway, eventbus, broker
    ):
        """체결 시 해당 account_id 범위 내 캐시만 무효화."""
        # acc-001 캐시
        gateway._cache.set("acc-001:balance", {"cash": 5000000}, ttl=60)
        gateway._cache.set("acc-001:positions", [], ttl=60)
        gateway._cache.set("acc-001:price:005930", 50000, ttl=60)
        # acc-002 캐시 (영향 받지 않아야 함)
        gateway._cache.set("acc-002:balance", {"cash": 3000000}, ttl=60)
        gateway._cache.set("acc-002:positions", [{"symbol": "000660"}], ttl=60)

        await eventbus.publish(
            OrderFilledEvent(
                account_id="acc-001",
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
            )
        )

        # acc-001 캐시 무효화 확인
        assert gateway._cache.get("acc-001:balance") is None
        assert gateway._cache.get("acc-001:positions") is None
        assert gateway._cache.get("acc-001:price:005930") is None
        # acc-002 캐시 유지 확인
        assert gateway._cache.get("acc-002:balance") == {"cash": 3000000}
        assert gateway._cache.get("acc-002:positions") == [{"symbol": "000660"}]


# ── LiveDataProvider ───────────────────────────────


class TestLiveDataProvider:
    async def test_get_current_price(self):
        """LiveDataProvider 현재가 조회."""
        mock_gateway = AsyncMock()
        mock_gateway.get_current_price = AsyncMock(return_value=50000.0)

        provider = LiveDataProvider(mock_gateway)
        price = await provider.get_current_price("005930")
        assert price == 50000.0
        mock_gateway.get_current_price.assert_called_once_with("005930")

    async def test_get_ohlcv_delegates_to_gateway_without_store(self):
        """ParquetStore 미주입 시 gateway.get_ohlcv()를 호출한다."""
        mock_gateway = AsyncMock()
        mock_gateway.get_ohlcv = AsyncMock(return_value=[{"close": 50000.0}])
        provider = LiveDataProvider(mock_gateway)
        result = await provider.get_ohlcv("005930")
        assert result == [{"close": 50000.0}]
        mock_gateway.get_ohlcv.assert_called_once_with(
            "005930", timeframe="1d", limit=100
        )

    async def test_get_ohlcv_reads_from_parquet_store(self):
        """ParquetStore에 데이터가 있으면 ParquetStore에서 읽는다."""
        import polars as pl

        mock_gateway = AsyncMock()
        mock_store = MagicMock()
        df = pl.DataFrame(
            {
                "timestamp": ["2026-01-01"],
                "open": [49000.0],
                "high": [51000.0],
                "low": [48500.0],
                "close": [50000.0],
                "volume": [1000],
            }
        )
        mock_store.read = MagicMock(return_value=df)

        provider = LiveDataProvider(mock_gateway, parquet_store=mock_store)
        result = await provider.get_ohlcv("005930", timeframe="1d", limit=50)

        assert len(result) == 1
        assert result[0]["close"] == 50000.0
        mock_store.read.assert_called_once_with("005930", "1d", limit=50)
        mock_gateway.get_ohlcv.assert_not_called()

    async def test_get_ohlcv_fallback_to_gateway_when_store_empty(self):
        """ParquetStore에 데이터가 없으면 APIGateway로 폴백한다."""
        import polars as pl

        mock_gateway = AsyncMock()
        mock_gateway.get_ohlcv = AsyncMock(return_value=[{"close": 50000.0}])
        mock_store = MagicMock()
        mock_store.read = MagicMock(return_value=pl.DataFrame())

        provider = LiveDataProvider(mock_gateway, parquet_store=mock_store)
        result = await provider.get_ohlcv("005930")

        assert result == [{"close": 50000.0}]
        mock_store.read.assert_called_once()
        mock_gateway.get_ohlcv.assert_called_once()

    async def test_get_ohlcv_fallback_to_gateway_on_store_error(self):
        """ParquetStore 읽기 실패 시 APIGateway로 폴백한다."""
        mock_gateway = AsyncMock()
        mock_gateway.get_ohlcv = AsyncMock(return_value=[{"close": 50000.0}])
        mock_store = MagicMock()
        mock_store.read = MagicMock(side_effect=Exception("parquet read error"))

        provider = LiveDataProvider(mock_gateway, parquet_store=mock_store)
        result = await provider.get_ohlcv("005930")

        assert result == [{"close": 50000.0}]
        mock_gateway.get_ohlcv.assert_called_once()

    async def test_get_indicator_returns_empty_when_no_ohlcv(self):
        """OHLCV 데이터 없을 때 빈 dict 반환."""
        mock_gateway = AsyncMock()
        mock_gateway.get_ohlcv = AsyncMock(return_value=[])
        provider = LiveDataProvider(mock_gateway)
        result = await provider.get_indicator("005930", "sma")
        assert result == {}
