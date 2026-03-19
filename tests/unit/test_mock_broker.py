"""MockBrokerAdapter 단위 테스트."""

from __future__ import annotations

import pytest

from ante.broker.exceptions import BrokerError, OrderNotFoundError
from ante.broker.mock import FillMode, MockBrokerAdapter


@pytest.fixture
def broker() -> MockBrokerAdapter:
    """기본 설정의 MockBrokerAdapter."""
    return MockBrokerAdapter({"initial_cash": 10_000_000, "default_price": 50_000})


@pytest.fixture
def partial_broker() -> MockBrokerAdapter:
    """부분 체결 모드 브로커."""
    return MockBrokerAdapter(
        {
            "fill_mode": "partial",
            "partial_fill_ratio": 0.5,
            "initial_cash": 10_000_000,
            "default_price": 50_000,
        }
    )


@pytest.fixture
def delayed_broker() -> MockBrokerAdapter:
    """지연 체결 모드 브로커."""
    return MockBrokerAdapter(
        {
            "fill_mode": "delayed",
            "delay_seconds": 0.01,
            "initial_cash": 10_000_000,
            "default_price": 50_000,
        }
    )


@pytest.fixture
def reject_broker() -> MockBrokerAdapter:
    """주문 거부 모드 브로커."""
    return MockBrokerAdapter({"fill_mode": "reject"})


# ── 연결 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_disconnect(broker: MockBrokerAdapter) -> None:
    """connect/disconnect 시 is_connected 상태가 변경된다."""
    assert not broker.is_connected
    await broker.connect()
    assert broker.is_connected
    await broker.disconnect()
    assert not broker.is_connected


# ── 즉시 체결 (IMMEDIATE) ─────────────────────────────


@pytest.mark.asyncio
async def test_immediate_buy_order(broker: MockBrokerAdapter) -> None:
    """즉시 체결 모드에서 매수 주문이 전량 체결된다."""
    order_id = await broker.place_order("005930", "buy", 10)

    status = await broker.get_order_status(order_id)
    assert status["status"] == "filled"
    assert status["filled_quantity"] == 10
    assert status["symbol"] == "005930"
    assert status["side"] == "buy"


@pytest.mark.asyncio
async def test_immediate_buy_updates_balance(broker: MockBrokerAdapter) -> None:
    """매수 후 현금이 감소하고 포지션이 생성된다."""
    initial_balance = await broker.get_account_balance()
    initial_cash = initial_balance["cash"]

    await broker.place_order("005930", "buy", 10)

    balance = await broker.get_account_balance()
    assert balance["cash"] < initial_cash

    positions = await broker.get_positions()
    assert len(positions) == 1
    assert positions[0]["symbol"] == "005930"
    assert positions[0]["quantity"] == 10


@pytest.mark.asyncio
async def test_immediate_sell_order(broker: MockBrokerAdapter) -> None:
    """매수 후 매도 시 포지션이 감소하고 현금이 증가한다."""
    await broker.place_order("005930", "buy", 10)
    cash_after_buy = (await broker.get_account_balance())["cash"]

    await broker.place_order("005930", "sell", 5)

    balance = await broker.get_account_balance()
    assert balance["cash"] > cash_after_buy

    positions = await broker.get_positions()
    assert positions[0]["quantity"] == 5


@pytest.mark.asyncio
async def test_sell_without_position_raises(broker: MockBrokerAdapter) -> None:
    """포지션 없이 매도 시 BrokerError가 발생한다."""
    with pytest.raises(BrokerError, match="매도할 포지션 없음"):
        await broker.place_order("005930", "sell", 10)


@pytest.mark.asyncio
async def test_sell_exceeding_quantity_raises(broker: MockBrokerAdapter) -> None:
    """보유 수량 초과 매도 시 BrokerError가 발생한다."""
    await broker.place_order("005930", "buy", 5)
    with pytest.raises(BrokerError, match="보유 수량 부족"):
        await broker.place_order("005930", "sell", 10)


# ── 부분 체결 (PARTIAL) ──────────────────────────────


@pytest.mark.asyncio
async def test_partial_fill(partial_broker: MockBrokerAdapter) -> None:
    """부분 체결 모드에서 설정 비율만큼만 체결된다."""
    order_id = await partial_broker.place_order("005930", "buy", 10)

    status = await partial_broker.get_order_status(order_id)
    assert status["status"] == "partially_filled"
    assert status["filled_quantity"] == 5.0  # 10 * 0.5


@pytest.mark.asyncio
async def test_partial_fill_position(partial_broker: MockBrokerAdapter) -> None:
    """부분 체결 시 체결된 수량만 포지션에 반영된다."""
    await partial_broker.place_order("005930", "buy", 10)

    positions = await partial_broker.get_positions()
    assert positions[0]["quantity"] == 5.0


# ── 지연 체결 (DELAYED) ──────────────────────────────


@pytest.mark.asyncio
async def test_delayed_fill(delayed_broker: MockBrokerAdapter) -> None:
    """지연 체결 모드에서도 최종적으로 전량 체결된다."""
    order_id = await delayed_broker.place_order("005930", "buy", 10)

    status = await delayed_broker.get_order_status(order_id)
    assert status["status"] == "filled"
    assert status["filled_quantity"] == 10


# ── 주문 거부 (REJECT) ───────────────────────────────


@pytest.mark.asyncio
async def test_reject_mode(reject_broker: MockBrokerAdapter) -> None:
    """주문 거부 모드에서 BrokerError가 발생한다."""
    with pytest.raises(BrokerError, match="Mock 주문 거부"):
        await reject_broker.place_order("005930", "buy", 10)


# ── 주문 관리 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_pending_order(partial_broker: MockBrokerAdapter) -> None:
    """부분 체결된 주문을 취소할 수 있다."""
    order_id = await partial_broker.place_order("005930", "buy", 10)

    result = await partial_broker.cancel_order(order_id)
    assert result is True

    status = await partial_broker.get_order_status(order_id)
    assert status["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_filled_order_returns_false(broker: MockBrokerAdapter) -> None:
    """이미 체결된 주문 취소 시 False를 반환한다."""
    order_id = await broker.place_order("005930", "buy", 10)

    result = await broker.cancel_order(order_id)
    assert result is False


@pytest.mark.asyncio
async def test_cancel_nonexistent_order_raises(broker: MockBrokerAdapter) -> None:
    """존재하지 않는 주문 취소 시 OrderNotFoundError가 발생한다."""
    with pytest.raises(OrderNotFoundError):
        await broker.cancel_order("nonexistent")


@pytest.mark.asyncio
async def test_get_pending_orders(partial_broker: MockBrokerAdapter) -> None:
    """미체결 주문 목록을 조회할 수 있다."""
    await partial_broker.place_order("005930", "buy", 10)
    await partial_broker.place_order("000660", "buy", 5)

    pending = await partial_broker.get_pending_orders()
    assert len(pending) == 2


# ── 잔고 조회 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_initial_balance(broker: MockBrokerAdapter) -> None:
    """초기 잔고가 설정 값과 일치한다."""
    balance = await broker.get_account_balance()
    assert balance["cash"] == 10_000_000
    assert balance["total_assets"] == 10_000_000
    assert balance["stock_value"] == 0


@pytest.mark.asyncio
async def test_balance_after_trades(broker: MockBrokerAdapter) -> None:
    """매매 후 total_assets가 수수료만큼 감소한다."""
    initial = await broker.get_account_balance()

    await broker.place_order("005930", "buy", 10)
    after = await broker.get_account_balance()

    # stock_value = 10 * 50000 = 500000
    assert after["stock_value"] == 500_000
    # total_assets는 수수료만큼 초기보다 감소
    assert after["total_assets"] < initial["total_assets"]


# ── 가격 설정 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_custom_price(broker: MockBrokerAdapter) -> None:
    """종목별 현재가를 설정할 수 있다."""
    broker.set_price("005930", 70_000)
    price = await broker.get_current_price("005930")
    assert price == 70_000


@pytest.mark.asyncio
async def test_default_price() -> None:
    """prices 딕셔너리에 없는 종목은 default_price를 반환한다."""
    b = MockBrokerAdapter({"default_price": 30_000})
    assert await b.get_current_price("999999") == 30_000


# ── 체결 모드 동적 변경 ──────────────────────────────


@pytest.mark.asyncio
async def test_set_fill_mode(broker: MockBrokerAdapter) -> None:
    """테스트 중 체결 모드를 동적으로 변경할 수 있다."""
    broker.set_fill_mode(FillMode.PARTIAL)
    order_id = await broker.place_order("005930", "buy", 10)
    status = await broker.get_order_status(order_id)
    assert status["status"] == "partially_filled"


# ── 기타 조회 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_instruments(broker: MockBrokerAdapter) -> None:
    """종목 마스터 데이터를 반환한다."""
    instruments = await broker.get_instruments()
    assert len(instruments) >= 1
    assert instruments[0]["symbol"] == "005930"


@pytest.mark.asyncio
async def test_get_commission_info(broker: MockBrokerAdapter) -> None:
    """수수료 정보를 반환한다."""
    info = broker.get_commission_info()
    assert info.commission_rate == 0.00015
    assert info.sell_tax_rate == 0.0023


@pytest.mark.asyncio
async def test_order_history(broker: MockBrokerAdapter) -> None:
    """주문 이력을 조회할 수 있다."""
    await broker.place_order("005930", "buy", 10)
    await broker.place_order("000660", "buy", 5)

    history = await broker.get_order_history()
    assert len(history) == 2


@pytest.mark.asyncio
async def test_health_check(broker: MockBrokerAdapter) -> None:
    """health_check가 True를 반환한다."""
    assert await broker.health_check() is True


@pytest.mark.asyncio
async def test_multiple_buys_avg_price(broker: MockBrokerAdapter) -> None:
    """동일 종목 추가 매수 시 평균단가가 올바르게 계산된다."""
    broker.set_price("005930", 50_000)
    await broker.place_order("005930", "buy", 10, price=50_000)

    broker.set_price("005930", 60_000)
    await broker.place_order("005930", "buy", 10, price=60_000)

    positions = await broker.get_positions()
    assert positions[0]["quantity"] == 20
    assert positions[0]["avg_price"] == 55_000  # (50000*10 + 60000*10) / 20
