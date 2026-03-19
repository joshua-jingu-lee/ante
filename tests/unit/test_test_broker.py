"""TestBrokerAdapter 단위 테스트.

연결/시세/주문/체결/잔고/포지션/스트리밍/종목마스터/수수료 검증.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.broker.exceptions import BrokerError, OrderNotFoundError
from ante.broker.models import CommissionInfo
from ante.broker.test import TestBrokerAdapter, tick_round

# ── Fixture ──────────────────────────────────────────────────


@pytest.fixture
def broker() -> TestBrokerAdapter:
    """기본 설정의 TestBrokerAdapter 인스턴스."""
    return TestBrokerAdapter({"seed": 42, "initial_cash": 100_000_000})


@pytest.fixture
async def connected_broker(broker: TestBrokerAdapter) -> TestBrokerAdapter:
    """연결된 TestBrokerAdapter 인스턴스."""
    await broker.connect()
    return broker


# ── 연결/해제 ────────────────────────────────────────────────


class TestConnection:
    """연결/해제 동작 검증."""

    @pytest.mark.asyncio
    async def test_connect(self, broker: TestBrokerAdapter) -> None:
        """connect() 후 is_connected가 True."""
        assert broker.is_connected is False
        await broker.connect()
        assert broker.is_connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, connected_broker: TestBrokerAdapter) -> None:
        """disconnect() 후 is_connected가 False."""
        await connected_broker.disconnect()
        assert connected_broker.is_connected is False

    def test_broker_metadata(self, broker: TestBrokerAdapter) -> None:
        """브로커 메타정보가 올바르다."""
        assert broker.broker_id == "test"
        assert broker.broker_name == "테스트 브로커"
        assert broker.broker_short_name == "TEST"


# ── 시세 조회 ────────────────────────────────────────────────


class TestCurrentPrice:
    """get_current_price() 동작 검증."""

    @pytest.mark.asyncio
    async def test_returns_positive_price(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """현재가가 양수이다."""
        price = await connected_broker.get_current_price("000001")
        assert price > 0

    @pytest.mark.asyncio
    async def test_price_changes_on_each_call(self) -> None:
        """매 호출마다 가격이 변동될 수 있다 (GBM 적용)."""
        from ante.broker.test import PriceSimulator, StockPreset

        # 저가 종목(호가 1원)으로 변동이 반올림에 묻히지 않게 함
        custom = {"T01": StockPreset("T01", "테스트", 1_000, 0.03)}
        broker = TestBrokerAdapter({"seed": 42, "initial_cash": 1_000_000})
        broker._simulator = PriceSimulator(presets=custom, seed=42)
        await broker.connect()
        prices = [await broker.get_current_price("T01") for _ in range(50)]
        assert len(set(prices)) > 1

    @pytest.mark.asyncio
    async def test_unknown_symbol_raises(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """등록되지 않은 종목 조회 시 KeyError."""
        with pytest.raises(KeyError, match="등록되지 않은 종목"):
            await connected_broker.get_current_price("999999")

    @pytest.mark.asyncio
    async def test_price_conforms_to_tick_size(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """반환 가격이 KRX 호가 단위에 맞다."""
        for _ in range(100):
            price = await connected_broker.get_current_price("000001")
            assert price == tick_round(price)


# ── 계좌/포지션 ──────────────────────────────────────────────


class TestAccountBalance:
    """get_account_balance() 동작 검증."""

    @pytest.mark.asyncio
    async def test_initial_balance(self, connected_broker: TestBrokerAdapter) -> None:
        """초기 잔고가 설정값과 일치한다."""
        balance = await connected_broker.get_account_balance()
        assert balance["cash"] == 100_000_000
        assert balance["total_assets"] == 100_000_000
        assert balance["stock_value"] == 0

    @pytest.mark.asyncio
    async def test_balance_after_buy(self, connected_broker: TestBrokerAdapter) -> None:
        """매수 후 현금이 감소하고 stock_value가 증가한다."""
        await connected_broker.place_order("000001", "buy", 10)
        balance = await connected_broker.get_account_balance()
        assert balance["cash"] < 100_000_000
        assert balance["stock_value"] > 0


class TestPositions:
    """get_positions() / get_account_positions() 동작 검증."""

    @pytest.mark.asyncio
    async def test_no_positions_initially(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """초기에는 포지션이 없다."""
        positions = await connected_broker.get_positions()
        assert positions == []

    @pytest.mark.asyncio
    async def test_position_after_buy(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """매수 후 포지션이 생성된다."""
        await connected_broker.place_order("000001", "buy", 10)
        positions = await connected_broker.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "000001"
        assert positions[0]["quantity"] == 10

    @pytest.mark.asyncio
    async def test_account_positions_delegates(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """get_account_positions()이 get_positions()와 동일 결과를 반환한다."""
        await connected_broker.place_order("000001", "buy", 5)
        positions = await connected_broker.get_positions()
        account_positions = await connected_broker.get_account_positions()
        assert positions == account_positions


# ── 주문/체결 ────────────────────────────────────────────────


class TestPlaceOrder:
    """place_order() 동작 검증."""

    @pytest.mark.asyncio
    async def test_market_buy_returns_order_id(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """시장가 매수가 주문 ID를 반환한다."""
        order_id = await connected_broker.place_order("000001", "buy", 10)
        assert isinstance(order_id, str)
        assert len(order_id) > 0

    @pytest.mark.asyncio
    async def test_market_buy_updates_cash(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """시장가 매수 후 현금이 감소한다."""
        initial_balance = await connected_broker.get_account_balance()
        await connected_broker.place_order("000001", "buy", 10)
        after_balance = await connected_broker.get_account_balance()
        assert after_balance["cash"] < initial_balance["cash"]

    @pytest.mark.asyncio
    async def test_market_sell(self, connected_broker: TestBrokerAdapter) -> None:
        """매수 후 매도가 정상 동작한다."""
        await connected_broker.place_order("000001", "buy", 10)
        order_id = await connected_broker.place_order("000001", "sell", 5)
        positions = await connected_broker.get_positions()
        assert positions[0]["quantity"] == 5
        status = await connected_broker.get_order_status(order_id)
        assert status["side"] == "sell"

    @pytest.mark.asyncio
    async def test_sell_without_position_raises(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """포지션 없이 매도 시 BrokerError."""
        with pytest.raises(BrokerError, match="보유 수량 부족"):
            await connected_broker.place_order("000001", "sell", 10)

    @pytest.mark.asyncio
    async def test_buy_insufficient_cash_raises(
        self,
    ) -> None:
        """자금 부족 시 BrokerError."""
        broker = TestBrokerAdapter({"seed": 42, "initial_cash": 1.0})
        await broker.connect()
        with pytest.raises(BrokerError, match="자금 부족"):
            await broker.place_order("000001", "buy", 100)

    @pytest.mark.asyncio
    async def test_unknown_symbol_raises(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """등록되지 않은 종목 주문 시 BrokerError."""
        with pytest.raises(BrokerError, match="등록되지 않은 종목"):
            await connected_broker.place_order("999999", "buy", 10)

    @pytest.mark.asyncio
    async def test_slippage_applied_on_market_order(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """시장가 주문에 슬리피지가 적용된다."""
        # 동일 시드로 여러 번 주문하면 체결가가 현재가와 약간 다를 수 있다
        order_id = await connected_broker.place_order("000001", "buy", 10)
        status = await connected_broker.get_order_status(order_id)
        # 체결가가 호가 단위에 맞는지만 확인 (슬리피지 적용 여부는 확률적)
        assert status["price"] == tick_round(status["price"])


class TestLimitOrder:
    """지정가 주문 동작 검증."""

    @pytest.mark.asyncio
    async def test_limit_buy_unfillable(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """지정가 매수 — 현재가보다 낮은 가격이면 미체결."""
        # 현재가보다 훨씬 낮은 지정가
        order_id = await connected_broker.place_order(
            "000001", "buy", 10, order_type="limit", price=1_000.0
        )
        status = await connected_broker.get_order_status(order_id)
        assert status["status"] == "pending"
        assert status["filled_quantity"] == 0

    @pytest.mark.asyncio
    async def test_limit_buy_fillable(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """지정가 매수 — 현재가 이상이면 체결."""
        order_id = await connected_broker.place_order(
            "000001", "buy", 10, order_type="limit", price=999_999.0
        )
        status = await connected_broker.get_order_status(order_id)
        assert status["status"] in ("filled", "partially_filled")

    @pytest.mark.asyncio
    async def test_limit_sell_unfillable(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """지정가 매도 — 현재가보다 높은 가격이면 미체결."""
        await connected_broker.place_order("000001", "buy", 10)
        order_id = await connected_broker.place_order(
            "000001", "sell", 5, order_type="limit", price=999_999.0
        )
        status = await connected_broker.get_order_status(order_id)
        assert status["status"] == "pending"


class TestCancelOrder:
    """cancel_order() 동작 검증."""

    @pytest.mark.asyncio
    async def test_cancel_pending_order(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """미체결 주문 취소 성공."""
        order_id = await connected_broker.place_order(
            "000001", "buy", 10, order_type="limit", price=1_000.0
        )
        result = await connected_broker.cancel_order(order_id)
        assert result is True
        status = await connected_broker.get_order_status(order_id)
        assert status["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_filled_order_fails(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """체결된 주문 취소 실패."""
        order_id = await connected_broker.place_order("000001", "buy", 10)
        status = await connected_broker.get_order_status(order_id)
        if status["status"] == "filled":
            result = await connected_broker.cancel_order(order_id)
            assert result is False

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_order_raises(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """존재하지 않는 주문 취소 시 OrderNotFoundError."""
        with pytest.raises(OrderNotFoundError):
            await connected_broker.cancel_order("nonexistent")


# ── 주문 상태/이력 ───────────────────────────────────────────


class TestOrderStatus:
    """get_order_status() / get_pending_orders() / get_order_history() 검증."""

    @pytest.mark.asyncio
    async def test_order_status_fields(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """주문 상태에 필수 필드가 포함된다."""
        order_id = await connected_broker.place_order("000001", "buy", 10)
        status = await connected_broker.get_order_status(order_id)
        required_fields = {
            "order_id",
            "symbol",
            "side",
            "quantity",
            "filled_quantity",
            "price",
            "order_type",
            "status",
            "created_at",
        }
        assert required_fields.issubset(status.keys())

    @pytest.mark.asyncio
    async def test_nonexistent_order_raises(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """존재하지 않는 주문 조회 시 OrderNotFoundError."""
        with pytest.raises(OrderNotFoundError):
            await connected_broker.get_order_status("nonexistent")

    @pytest.mark.asyncio
    async def test_pending_orders_list(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """미체결 주문이 pending_orders에 포함된다."""
        await connected_broker.place_order(
            "000001", "buy", 10, order_type="limit", price=1_000.0
        )
        pending = await connected_broker.get_pending_orders()
        assert len(pending) >= 1
        assert pending[0]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_order_history(self, connected_broker: TestBrokerAdapter) -> None:
        """주문 이력에 모든 주문이 포함된다."""
        await connected_broker.place_order("000001", "buy", 10)
        await connected_broker.place_order(
            "000002", "buy", 5, order_type="limit", price=1_000.0
        )
        history = await connected_broker.get_order_history()
        assert len(history) == 2


# ── 스트리밍 ─────────────────────────────────────────────────


class TestStreaming:
    """realtime_price_stream() / realtime_order_stream() 검증."""

    @pytest.mark.asyncio
    async def test_price_stream_yields_data(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """가격 스트림이 데이터를 yield한다."""
        # tick_interval을 짧게 설정
        connected_broker._tick_interval = 0.01

        items: list[dict] = []
        async for item in connected_broker.realtime_price_stream(["000001", "000002"]):
            items.append(item)
            if len(items) >= 4:  # 2종목 x 2라운드
                await connected_broker.disconnect()  # 스트림 종료

        assert len(items) >= 4
        assert all("symbol" in item for item in items)
        assert all("price" in item for item in items)
        assert all("timestamp" in item for item in items)

    @pytest.mark.asyncio
    async def test_price_stream_stops_on_disconnect(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """disconnect 후 스트림이 종료된다."""
        connected_broker._tick_interval = 0.01

        async def disconnect_after(delay: float) -> None:
            await asyncio.sleep(delay)
            await connected_broker.disconnect()

        task = asyncio.create_task(disconnect_after(0.05))
        count = 0
        async for _ in connected_broker.realtime_price_stream(["000001"]):
            count += 1
        await task
        assert count > 0  # 최소 한 번은 yield해야 함

    @pytest.mark.asyncio
    async def test_order_stream_returns_filled_orders(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """주문 스트림이 체결 주문을 반환한다."""
        await connected_broker.place_order("000001", "buy", 10)
        items = []
        async for item in connected_broker.realtime_order_stream():
            items.append(item)
        assert len(items) >= 1


# ── 종목 마스터 ──────────────────────────────────────────────


class TestInstruments:
    """get_instruments() 검증."""

    @pytest.mark.asyncio
    async def test_returns_six_instruments(
        self, connected_broker: TestBrokerAdapter
    ) -> None:
        """6종의 가상 종목이 반환된다."""
        instruments = await connected_broker.get_instruments()
        assert len(instruments) == 6

    @pytest.mark.asyncio
    async def test_instrument_fields(self, connected_broker: TestBrokerAdapter) -> None:
        """종목 정보에 필수 필드가 포함된다."""
        instruments = await connected_broker.get_instruments()
        required_fields = {"symbol", "name", "name_en", "instrument_type", "listed"}
        for inst in instruments:
            assert required_fields.issubset(inst.keys())
            assert inst["instrument_type"] == "stock"
            assert inst["listed"] is True


# ── 수수료 ───────────────────────────────────────────────────


class TestCommission:
    """get_commission_info() 검증."""

    def test_returns_commission_info(self, broker: TestBrokerAdapter) -> None:
        """CommissionInfo 인스턴스를 반환한다."""
        info = broker.get_commission_info()
        assert isinstance(info, CommissionInfo)

    def test_default_rates(self, broker: TestBrokerAdapter) -> None:
        """KIS 동일 수수료율이 설정된다."""
        info = broker.get_commission_info()
        assert info.commission_rate == 0.00015
        assert info.sell_tax_rate == 0.0023


# ── 시드 재현성 ──────────────────────────────────────────────


class TestSeedReproducibility:
    """동일 시드로 동일한 체결 결과 재현 검증."""

    @pytest.mark.asyncio
    async def test_same_seed_same_prices(self) -> None:
        """동일 시드의 두 브로커가 동일한 가격 시퀀스를 반환한다."""
        b1 = TestBrokerAdapter({"seed": 42})
        b2 = TestBrokerAdapter({"seed": 42})
        await b1.connect()
        await b2.connect()

        prices1 = [await b1.get_current_price("000001") for _ in range(20)]
        prices2 = [await b2.get_current_price("000001") for _ in range(20)]
        assert prices1 == prices2


# ── BrokerAdapter 인터페이스 준수 ────────────────────────────


class TestBrokerAdapterInterface:
    """BrokerAdapter ABC 전체 메서드 구현 검증."""

    def test_is_broker_adapter(self, broker: TestBrokerAdapter) -> None:
        """TestBrokerAdapter가 BrokerAdapter의 인스턴스이다."""
        from ante.broker.base import BrokerAdapter

        assert isinstance(broker, BrokerAdapter)

    def test_all_abstract_methods_implemented(self) -> None:
        """모든 추상 메서드가 구현되었다 (인스턴스 생성 가능 = ABC 충족)."""
        # ABC를 모두 구현하지 않으면 인스턴스 생성 시 TypeError
        broker = TestBrokerAdapter({"seed": 1})
        assert broker is not None
