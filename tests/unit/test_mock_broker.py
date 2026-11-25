"""MockBrokerAdapter 단위 테스트."""

from __future__ import annotations

import json
from pathlib import Path

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
async def test_delayed_order_is_pending_until_history_is_read(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """지연 모드의 주문은 주문 이력이 읽히기 전에는 체결되지 않는다."""
    order_id = await delayed_broker.place_order("005930", "buy", 10)

    status = await delayed_broker.get_order_status(order_id)
    assert status["status"] == "pending"
    assert status["filled_quantity"] == 0
    assert await delayed_broker.get_positions() == []
    assert (await delayed_broker.get_account_balance())["cash"] == 10_000_000
    assert await delayed_broker.get_pending_orders() != []


@pytest.mark.asyncio
async def test_delayed_fill_on_second_history_call(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """기본 delay_polls=2: 주문 뒤 두 번째 주문 이력 조회에서 전량 체결된다."""
    order_id = await delayed_broker.place_order("005930", "buy", 10)

    (first,) = await delayed_broker.get_order_history()
    assert (first["order_id"], first["filled_quantity"]) == (order_id, 0)
    assert first["status"] == "pending"
    assert await delayed_broker.get_positions() == []

    (second,) = await delayed_broker.get_order_history()
    assert second["filled_quantity"] == 10
    assert second["status"] == "filled"
    positions = await delayed_broker.get_positions()
    assert [(p["symbol"], p["quantity"]) for p in positions] == [("005930", 10)]
    assert (await delayed_broker.get_account_balance())["cash"] < 10_000_000

    (third,) = await delayed_broker.get_order_history()
    assert third["filled_quantity"] == 10
    assert (await delayed_broker.get_positions())[0]["quantity"] == 10


@pytest.mark.asyncio
async def test_delayed_fill_with_one_poll() -> None:
    """delay_polls=1이면 주문 뒤 첫 주문 이력 조회에서 체결된다."""
    adapter = MockBrokerAdapter(
        {"fill_mode": "delayed", "delay_polls": 1, "default_price": 50_000}
    )
    order_id = await adapter.place_order("005930", "buy", 3)

    (first,) = await adapter.get_order_history()
    assert (first["order_id"], first["filled_quantity"]) == (order_id, 3)


@pytest.mark.asyncio
async def test_delayed_order_cancelled_before_fill_never_fills(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """체결이 보이기 전에 취소된 주문은 뒤의 조회에서도 체결되지 않는다."""
    order_id = await delayed_broker.place_order("005930", "buy", 10)
    await delayed_broker.get_order_history()
    assert await delayed_broker.cancel_order(order_id) is True

    for _ in range(3):
        (item,) = await delayed_broker.get_order_history()
        assert item["filled_quantity"] == 0
        assert item["status"] == "cancelled"
    assert await delayed_broker.get_positions() == []
    assert (await delayed_broker.get_account_balance())["cash"] == 10_000_000


@pytest.mark.asyncio
async def test_delayed_orders_count_their_own_calls(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """주문마다 자기가 접수된 뒤의 조회 횟수를 센다."""
    early = await delayed_broker.place_order("005930", "buy", 1)
    await delayed_broker.get_order_history()
    late = await delayed_broker.place_order("005930", "buy", 2)

    filled = {
        i["order_id"]: i["filled_quantity"]
        for i in await delayed_broker.get_order_history()
    }
    assert filled == {early: 1, late: 0}

    filled = {
        i["order_id"]: i["filled_quantity"]
        for i in await delayed_broker.get_order_history()
    }
    assert filled == {early: 1, late: 2}


@pytest.mark.asyncio
async def test_failed_immediate_sell_leaves_ledger_untouched(
    broker: MockBrokerAdapter,
) -> None:
    """#2943: 보유 초과 즉시 매도가 실패하면 현금·포지션·주문 목록이 그대로다."""
    await broker.place_order("005930", "buy", 5)
    cash = (await broker.get_account_balance())["cash"]
    positions = await broker.get_positions()
    history = await broker.get_order_history()
    pending = await broker.get_pending_orders()

    with pytest.raises(BrokerError, match="보유 수량 부족"):
        await broker.place_order("005930", "sell", 10)

    assert (await broker.get_account_balance())["cash"] == cash
    assert await broker.get_positions() == positions
    assert len(await broker.get_order_history()) == len(history)
    assert await broker.get_pending_orders() == pending


@pytest.mark.asyncio
async def test_partial_sell_validates_filled_quantity(
    partial_broker: MockBrokerAdapter,
) -> None:
    """#2943: 부분 모드의 매도는 체결될 수량으로 보유를 검증한다."""
    await partial_broker.place_order("005930", "buy", 10)

    order_id = await partial_broker.place_order("005930", "sell", 10)

    status = await partial_broker.get_order_status(order_id)
    assert (status["status"], status["filled_quantity"]) == ("partially_filled", 5)
    assert await partial_broker.get_positions() == []


@pytest.mark.asyncio
async def test_failed_delayed_sell_leaves_ledger_untouched() -> None:
    """#2943: 지연 매도의 체결이 실패하면 장부가 그대로이고 주문은 pending이다."""
    adapter = MockBrokerAdapter(
        {"fill_mode": "delayed", "delay_polls": 1, "default_price": 50_000}
    )
    await adapter.place_order("005930", "buy", 5)
    await adapter.get_order_history()
    cash = (await adapter.get_account_balance())["cash"]
    positions = await adapter.get_positions()
    sell_id = await adapter.place_order("005930", "sell", 10)

    with pytest.raises(BrokerError, match="보유 수량 부족"):
        await adapter.get_order_history()

    assert (await adapter.get_account_balance())["cash"] == cash
    assert await adapter.get_positions() == positions
    status = await adapter.get_order_status(sell_id)
    assert (status["status"], status["filled_quantity"]) == ("pending", 0)
    history = await adapter.get_order_history()
    assert len(history) == 2


@pytest.mark.asyncio
async def test_delayed_order_keeps_mode_at_submission(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """#2943: 접수 뒤 체결 모드가 바뀌어도 지연 주문은 전량 체결된다."""
    order_id = await delayed_broker.place_order("005930", "buy", 10)
    delayed_broker.set_fill_mode(FillMode.PARTIAL)

    await delayed_broker.get_order_history()
    (item,) = await delayed_broker.get_order_history()

    assert (item["order_id"], item["status"]) == (order_id, "filled")
    assert item["filled_quantity"] == 10


@pytest.mark.asyncio
async def test_delayed_market_order_fills_at_submission_price(
    delayed_broker: MockBrokerAdapter,
) -> None:
    """#2943: 지연 시장가 주문은 접수 때의 가격으로 체결된다."""
    await delayed_broker.place_order("005930", "buy", 10)
    delayed_broker.set_price("005930", 90_000)

    await delayed_broker.get_order_history()
    await delayed_broker.get_order_history()

    spent = 10_000_000 - (await delayed_broker.get_account_balance())["cash"]
    expected = 10 * 50_000
    assert spent == expected + delayed_broker.get_commission_info().calculate(
        "buy", expected
    )


@pytest.mark.parametrize("value", [0, -1, True, False, 1.0, 2.5, "2", None])
def test_delay_polls_must_be_positive_int(value: object) -> None:
    """delay_polls가 1 이상의 정수가 아니면 생성자의 BrokerError다."""
    with pytest.raises(BrokerError, match="delay_polls"):
        MockBrokerAdapter({"fill_mode": "delayed", "delay_polls": value})


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
async def test_modify_pending_order_updates_price(
    partial_broker: MockBrokerAdapter,
) -> None:
    """#2391: 미체결 주문 정정 → 가격 갱신 + True 반환."""
    order_id = await partial_broker.place_order(
        "005930", "buy", 10, "limit", price=50000
    )

    result = await partial_broker.modify_order(
        order_id, quantity=10, price=45000, order_type="limit"
    )
    assert result is True

    status = await partial_broker.get_order_status(order_id)
    assert status["price"] == 45000


@pytest.mark.asyncio
async def test_modify_filled_order_returns_false(broker: MockBrokerAdapter) -> None:
    """#2391: 이미 체결된 주문 정정 시 False."""
    order_id = await broker.place_order("005930", "buy", 10, "limit", price=50000)

    result = await broker.modify_order(order_id, price=45000)
    assert result is False


@pytest.mark.asyncio
async def test_modify_nonexistent_order_raises(broker: MockBrokerAdapter) -> None:
    """#2391: 존재하지 않는 주문 정정 시 OrderNotFoundError."""
    with pytest.raises(OrderNotFoundError):
        await broker.modify_order("nonexistent", price=45000)


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
async def test_get_buyable_cash_based(broker: MockBrokerAdapter) -> None:
    """get_buyable: 보유 현금 기반 산정 — 금액=cash, 수량=floor(cash/단가) (#2384)."""
    # default_price=50_000, cash=10_000_000 → qty=200
    result = await broker.get_buyable("005930")
    assert result["order_buyable_amount"] == 10_000_000.0
    assert result["max_buyable_amount"] == 10_000_000.0
    assert result["order_cash"] == 10_000_000.0
    assert result["order_buyable_qty"] == 200.0
    assert result["max_buyable_qty"] == 200.0


@pytest.mark.asyncio
async def test_get_buyable_explicit_price(broker: MockBrokerAdapter) -> None:
    """get_buyable: price 명시 시 그 단가로 수량 계산 (#2384)."""
    # cash=10_000_000, price=70_000 → qty=floor(142.85...)=142
    result = await broker.get_buyable("005930", price=70_000)
    assert result["order_buyable_qty"] == 142.0


@pytest.mark.asyncio
async def test_get_buyable_zero_price_qty_zero() -> None:
    """get_buyable: 단가 0이면 수량 0.0 (division-by-zero 방지) (#2384)."""
    b = MockBrokerAdapter({"initial_cash": 10_000_000, "default_price": 0})
    result = await b.get_buyable("999999")
    assert result["order_buyable_qty"] == 0.0
    assert result["max_buyable_qty"] == 0.0
    assert result["order_buyable_amount"] == 10_000_000.0


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


@pytest.mark.asyncio
async def test_default_price_without_config_is_50000() -> None:
    """prices_file이 없고 default_price도 없으면 기본값 50,000이다."""
    assert await MockBrokerAdapter({}).get_current_price("999999") == 50_000


# ── 가격 파일 (prices_file) ──────────────────────────


def _write_prices(tmp_path: Path, content: str) -> str:
    path = tmp_path / "prices.json"
    path.write_text(content, encoding="utf-8")
    return str(path)


@pytest.mark.asyncio
async def test_prices_file_supplies_prices(tmp_path: Path) -> None:
    """파일의 종목 가격이 조회된다."""
    path = _write_prices(
        tmp_path, json.dumps({"prices": {"000001": 72000, "000002": 160000.5}})
    )
    b = MockBrokerAdapter({"prices_file": path})
    assert await b.get_current_price("000001") == 72000
    assert await b.get_current_price("000002") == 160000.5


@pytest.mark.asyncio
async def test_prices_file_default_price_for_missing_symbol(tmp_path: Path) -> None:
    """파일에 없는 종목은 파일의 default_price다."""
    path = _write_prices(
        tmp_path, json.dumps({"prices": {"000001": 72000}, "default_price": 1234})
    )
    b = MockBrokerAdapter({"prices_file": path})
    assert await b.get_current_price("999999") == 1234


@pytest.mark.asyncio
async def test_prices_file_missing_symbol_without_default_raises(
    tmp_path: Path,
) -> None:
    """파일에 없는 종목은 default_price가 없으면 조회가 BrokerError다."""
    path = _write_prices(tmp_path, json.dumps({"prices": {"000001": 72000}}))
    b = MockBrokerAdapter({"prices_file": path})
    with pytest.raises(BrokerError):
        await b.get_current_price("999999")


@pytest.mark.asyncio
async def test_prices_file_empty_prices_with_default_is_valid(tmp_path: Path) -> None:
    """빈 prices와 default_price만 있는 파일은 유효하다."""
    path = _write_prices(tmp_path, json.dumps({"prices": {}, "default_price": 1000}))
    b = MockBrokerAdapter({"prices_file": path})
    assert await b.get_current_price("000001") == 1000


@pytest.mark.asyncio
async def test_prices_file_read_once_at_construction(tmp_path: Path) -> None:
    """파일은 생성 때 한 번 읽고 이후 바뀌어도 다시 읽지 않는다."""
    path = _write_prices(tmp_path, json.dumps({"prices": {"000001": 72000}}))
    b = MockBrokerAdapter({"prices_file": path})
    _write_prices(tmp_path, json.dumps({"prices": {"000001": 1}}))
    assert await b.get_current_price("000001") == 72000


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("not json", id="broken-json"),
        pytest.param("", id="empty-file"),
        pytest.param("[]", id="not-object"),
        pytest.param('{"prices": {}, "extra": 1}', id="unknown-key"),
        pytest.param('{"default_price": 1000}', id="missing-prices"),
        pytest.param('{"prices": []}', id="prices-not-object"),
        pytest.param('{"prices": {"000001": 0}}', id="zero"),
        pytest.param('{"prices": {"000001": -1}}', id="negative"),
        pytest.param('{"prices": {"000001": true}}', id="true"),
        pytest.param('{"prices": {"000001": "100"}}', id="string"),
        pytest.param('{"prices": {"000001": null}}', id="null"),
        pytest.param('{"prices": {"000001": NaN}}', id="nan"),
        pytest.param('{"prices": {"000001": Infinity}}', id="infinity"),
        pytest.param('{"prices": {"000001": -Infinity}}', id="neg-infinity"),
        pytest.param('{"prices": {"000001": 1e400}}', id="float-overflow"),
        pytest.param('{"prices": {"000001": 1' + "0" * 400 + "}}", id="int-overflow"),
        pytest.param('{"prices": {}, "default_price": 0}', id="default-zero"),
        pytest.param('{"prices": {}, "default_price": false}', id="default-false"),
        pytest.param('{"prices": {}, "default_price": NaN}', id="default-nan"),
    ],
)
def test_prices_file_invalid_content_raises_on_construction(
    tmp_path: Path, content: str
) -> None:
    """형식에 맞지 않는 가격 파일은 생성자의 BrokerError다."""
    path = _write_prices(tmp_path, content)
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": path})


def test_prices_file_relative_path_raises(tmp_path: Path) -> None:
    """상대 경로는 생성자의 BrokerError다."""
    _write_prices(tmp_path, json.dumps({"prices": {}}))
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": "prices.json"})


def test_prices_file_not_found_raises(tmp_path: Path) -> None:
    """없는 파일은 생성자의 BrokerError다."""
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": str(tmp_path / "absent.json")})


def test_prices_file_directory_raises(tmp_path: Path) -> None:
    """디렉토리 경로는 생성자의 BrokerError다."""
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": str(tmp_path)})


@pytest.mark.parametrize("value", [None, 1, True], ids=["none", "int", "bool"])
def test_prices_file_non_string_raises(value: object) -> None:
    """문자열이 아닌 prices_file은 생성자의 BrokerError다."""
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": value})


@pytest.mark.parametrize(
    "extra",
    [{"prices": {"000001": 1}}, {"default_price": 1}, {"prices": {}}],
    ids=["prices", "default_price", "empty-prices"],
)
def test_prices_file_with_config_prices_raises(
    tmp_path: Path, extra: dict[str, object]
) -> None:
    """prices_file과 prices 또는 default_price를 함께 주면 BrokerError다."""
    path = _write_prices(tmp_path, json.dumps({"prices": {"000001": 72000}}))
    with pytest.raises(BrokerError):
        MockBrokerAdapter({"prices_file": path, **extra})


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
    assert info.buy_commission_rate == 0.00015
    assert info.sell_commission_rate == 0.00195


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


# ── side 거부 (#3056) ─────────────────────────────────

_INVALID_SIDES = ["BUY", "hold", "", None, ["buy"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("fill_mode", ["immediate", "delayed"])
@pytest.mark.parametrize("side", _INVALID_SIDES)
async def test_invalid_side_rejected_without_side_effects(
    fill_mode: str, side: object
) -> None:
    """buy·sell이 아닌 side는 체결·주문 저장 전에 BrokerError로 거부된다."""
    broker = MockBrokerAdapter(
        {
            "fill_mode": fill_mode,
            "delay_polls": 1,
            "initial_cash": 10_000_000,
            "default_price": 50_000,
        }
    )
    await broker.place_order("005930", "buy", 10)
    await broker.get_order_history()
    positions = await broker.get_positions()
    assert positions[0]["quantity"] == 10
    balance = await broker.get_account_balance()
    orders = dict(broker._orders)
    polls = dict(broker._polls_left)

    with pytest.raises(BrokerError):
        await broker.place_order("005930", side, 3)  # type: ignore[arg-type]

    assert await broker.get_positions() == positions
    assert await broker.get_account_balance() == balance
    assert broker._orders == orders
    assert broker._polls_left == polls
