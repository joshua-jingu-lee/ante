"""가상 계좌 체결의 durable 기록 (#2611).

VirtualExecutor 는 OrderFilledEvent 를 발행하기 전에 FillApplier.apply_direct_fill
로 trades·positions·position_history 를 기록한다. OrderTracker·outbox 는 거치지
않고 이벤트는 기존과 같은 빈키 직접 발행이다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ante.account.models import TradingMode
from ante.bot.providers.virtual import VirtualExecutor, VirtualPortfolioView
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderValidatedEvent,
)
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import FillOutbox
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from ante.treasury.treasury import Treasury
from tests.unit._readiness_gate_helpers import make_account, ready_registry

ACCT = "test"
BOT = "bot-v"
SYMBOL = "000001"
BUY_RATE = 0.00015
SELL_RATE = 0.00015 + 0.0023
BUY_COMMISSION = 70000 * BUY_RATE
SELL_COMMISSION = 71000 * SELL_RATE


def _account_service() -> Any:
    from unittest.mock import AsyncMock, MagicMock

    svc = MagicMock()
    svc.get = AsyncMock(
        return_value=make_account(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
    )
    return svc


class _Stack:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.position_history = PositionHistory(db)
        self.recorder = TradeRecorder(db, self.position_history)
        self.tracker = OrderTracker(db)
        self.outbox = FillOutbox(db)
        self.applier = FillApplier(
            db=db,
            order_tracker=self.tracker,
            position_history=self.position_history,
            eventbus=self.bus,
            outbox=self.outbox,
        )
        registry = ready_registry(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        self.treasury = Treasury(
            db,
            self.bus,
            account_id=ACCT,
            buy_commission_rate=BUY_RATE,
            sell_commission_rate=SELL_RATE,
            runtime_readiness=registry,
            broker_type="test",
            trading_mode=TradingMode.VIRTUAL,
        )
        self.executor = VirtualExecutor(
            eventbus=self.bus,
            runtime_readiness=registry,
            account_service=_account_service(),
            fill_applier=self.applier,
        )
        self.portfolio = VirtualPortfolioView(
            treasury=self.treasury,
            position_history=self.position_history,
            account_id=ACCT,
        )
        self.events: list[Any] = []

    async def start(self) -> None:
        await self.position_history.initialize()
        await self.recorder.initialize()
        self.recorder.subscribe(self.bus)
        await self.tracker.initialize()
        await self.outbox.initialize()
        await self.treasury.initialize()
        await self.treasury.set_account_balance(10_000_000.0)
        await self.treasury.allocate(BOT, 1_000_000.0)
        self.executor.register_bot(BOT)
        self.executor.subscribe()
        for cls in (OrderFilledEvent, OrderFailedEvent):
            self.bus.subscribe(cls, self.events.append, priority=-1000)

    def of(self, cls: type) -> list[Any]:
        return [e for e in self.events if isinstance(e, cls)]

    async def count(self, table: str) -> int:
        row = await self.db.fetch_one(f"SELECT COUNT(*) AS n FROM {table}")
        assert row is not None
        return int(row["n"])


def _validated(order_id: str, side: str, price: float) -> OrderValidatedEvent:
    return OrderValidatedEvent(
        account_id=ACCT,
        order_id=order_id,
        bot_id=BOT,
        strategy_id="strat-v",
        symbol=SYMBOL,
        side=side,
        quantity=1.0,
        price=price,
        order_type="limit",
        exchange="TEST",
    )


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "virtual_fill.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def stack(db) -> _Stack:
    s = _Stack(db)
    await s.start()
    return s


# ── T2: 가상 매수·매도 왕복이 거래 기록과 포지션에 남는다 ─────────────────


async def test_virtual_round_trip_is_recorded(stack: _Stack) -> None:
    await stack.bus.publish(_validated("ord-buy", "buy", 70000.0))
    await stack.bus.publish(_validated("ord-sell", "sell", 71000.0))

    assert stack.of(OrderFailedEvent) == []
    assert len(stack.of(OrderFilledEvent)) == 2

    trades = await stack.db.fetch_all(
        "SELECT trade_id, order_id, side, quantity, price, status, commission,"
        " account_id, exchange FROM trades ORDER BY timestamp, side"
    )
    by_side = {t["side"]: t for t in trades}
    assert len(trades) == 2
    assert {t["status"] for t in trades} == {"filled"}
    assert {t["account_id"] for t in trades} == {ACCT}
    assert {t["exchange"] for t in trades} == {"TEST"}
    assert by_side["buy"]["order_id"] == "ord-buy"
    assert by_side["buy"]["price"] == 70000.0
    assert by_side["buy"]["commission"] == pytest.approx(BUY_COMMISSION)
    assert by_side["sell"]["order_id"] == "ord-sell"
    assert by_side["sell"]["price"] == 71000.0
    assert by_side["sell"]["commission"] == pytest.approx(SELL_COMMISSION)

    position = await stack.db.fetch_one(
        "SELECT quantity, realized_pnl FROM positions WHERE bot_id = ? AND symbol = ?",
        (BOT, SYMBOL),
    )
    assert position is not None
    assert position["quantity"] == 0
    assert position["realized_pnl"] == pytest.approx(1000 - SELL_COMMISSION)

    history = await stack.db.fetch_all(
        "SELECT action, trade_id FROM position_history ORDER BY id"
    )
    assert [h["action"] for h in history] == ["buy", "sell"]
    assert history[1]["trade_id"] == by_side["sell"]["trade_id"]

    metrics = await PerformanceTracker(stack.db).calculate(account_id=ACCT, bot_id=BOT)
    assert metrics.total_trades == 1
    assert metrics.total_pnl == pytest.approx(1000 - SELL_COMMISSION)

    assert await stack.count("order_tracker") == 0
    assert await stack.count("fill_outbox") == 0

    budget = stack.treasury.get_budget(BOT)
    assert budget is not None
    assert budget.spent == pytest.approx(70000 + BUY_COMMISSION)
    assert budget.returned == pytest.approx(71000 - SELL_COMMISSION)
    assert budget.reserved == pytest.approx(0.0)


async def test_filled_event_is_unchanged_empty_key_direct_publish(
    stack: _Stack,
) -> None:
    await stack.bus.publish(_validated("ord-buy", "buy", 70000.0))

    (event,) = stack.of(OrderFilledEvent)
    assert event.fill_dedup_key == ""
    assert event.broker_order_id == "virtual-ord-buy"
    assert event.commission == pytest.approx(BUY_COMMISSION)
    row = await stack.db.fetch_one("SELECT timestamp FROM trades")
    assert row is not None
    assert event.timestamp is not None
    assert row["timestamp"] == event.timestamp.isoformat()


# ── T3: apply_direct_fill 단위 ───────────────────────────────────────────


def _direct(**overrides: Any) -> dict[str, Any]:
    from datetime import UTC, datetime

    kwargs: dict[str, Any] = {
        "account_id": ACCT,
        "order_id": "ord-1",
        "bot_id": BOT,
        "strategy_id": "strat-v",
        "symbol": SYMBOL,
        "side": "buy",
        "quantity": 2.0,
        "price": 70000.0,
        "commission": 21.0,
        "order_type": "limit",
        "exchange": "TEST",
        "timestamp": datetime(2026, 11, 23, 1, 0, tzinfo=UTC),
    }
    kwargs.update(overrides)
    return kwargs


async def test_direct_fill_is_idempotent_per_order_id(stack: _Stack) -> None:
    first = await stack.applier.apply_direct_fill(**_direct())
    second = await stack.applier.apply_direct_fill(**_direct())

    assert first is True
    assert second is False
    assert await stack.count("trades") == 1
    assert await stack.count("position_history") == 1
    position = await stack.db.fetch_one("SELECT quantity FROM positions")
    assert position is not None
    assert position["quantity"] == 2.0


async def test_direct_fill_trade_id_is_deterministic(tmp_path) -> None:
    trade_ids: list[str] = []
    for name in ("a.db", "b.db"):
        database = Database(str(tmp_path / name))
        await database.connect()
        try:
            s = _Stack(database)
            await s.start()
            await s.applier.apply_direct_fill(**_direct())
            row = await database.fetch_one("SELECT trade_id FROM trades")
            assert row is not None
            trade_ids.append(row["trade_id"])
        finally:
            await database.close()
    assert trade_ids[0] == trade_ids[1]


async def test_direct_fill_rolls_back_when_position_update_fails(
    stack: _Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(record: Any) -> None:
        raise RuntimeError("position write failed")

    monkeypatch.setattr(stack.position_history, "on_trade", _boom)

    with pytest.raises(RuntimeError, match="position write failed"):
        await stack.applier.apply_direct_fill(**_direct())

    assert await stack.count("trades") == 0
    assert await stack.count("position_history") == 0


async def test_direct_fill_publishes_nothing(
    stack: _Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    published: list[Any] = []

    async def _spy(event: Any) -> None:
        published.append(event)

    monkeypatch.setattr(stack.bus, "publish", _spy)

    assert await stack.applier.apply_direct_fill(**_direct()) is True
    assert published == []
    assert await stack.count("fill_outbox") == 0
    assert await stack.count("order_tracker") == 0


@pytest.mark.parametrize("failure", [RuntimeError, asyncio.CancelledError])
async def test_direct_fill_rollback_leaves_position_cache_unchanged(
    stack: _Stack, monkeypatch: pytest.MonkeyPatch, failure: type[BaseException]
) -> None:
    """#2819: 이력 저장 실패·커밋 전 취소로 롤백되면 캐시에도 포지션이 없다."""

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise failure

    monkeypatch.setattr(stack.position_history, "_save_history", _boom)

    with pytest.raises(failure):
        await stack.applier.apply_direct_fill(**_direct())

    assert await stack.count("positions") == 0
    assert stack.position_history.get_positions_sync(BOT, account_id=ACCT) == []

    monkeypatch.undo()
    assert await stack.applier.apply_direct_fill(**_direct()) is True
    cached = stack.position_history.get_positions_sync(BOT, account_id=ACCT)
    assert [(p.symbol, p.quantity) for p in cached] == [(SYMBOL, 2.0)]


@pytest.mark.parametrize("account_id", ["", "default"])
async def test_direct_fill_rejects_invalid_account_id(
    stack: _Stack, account_id: str
) -> None:
    from ante.account.errors import InvalidAccountIdError

    with pytest.raises(InvalidAccountIdError):
        await stack.applier.apply_direct_fill(**_direct(account_id=account_id))
    assert await stack.count("trades") == 0


@pytest.mark.parametrize(
    "overrides",
    [
        {"quantity": 0.0},
        {"quantity": -1.0},
        {"price": 0.0},
        {"price": -100.0},
        {"quantity": float("nan")},
        {"quantity": float("inf")},
        {"price": float("nan")},
        {"price": float("inf")},
        {"order_id": ""},
    ],
)
async def test_direct_fill_rejects_invalid_input(
    stack: _Stack, overrides: dict[str, Any]
) -> None:
    with pytest.raises(ValueError):
        await stack.applier.apply_direct_fill(**_direct(**overrides))
    assert await stack.count("trades") == 0
    assert await stack.count("position_history") == 0


async def test_empty_order_id_does_not_swallow_later_fills(stack: _Stack) -> None:
    for _ in range(2):
        with pytest.raises(ValueError):
            await stack.applier.apply_direct_fill(**_direct(order_id=""))
    assert await stack.applier.apply_direct_fill(**_direct(order_id="ord-2"))
    assert await stack.count("trades") == 1


# ── T6: on_fill 안의 연쇄 주문(재진입) ───────────────────────────────────


async def test_reentrant_order_from_fill_handler_is_recorded(stack: _Stack) -> None:
    chained = False

    async def _on_fill(event: Any) -> None:
        nonlocal chained
        if isinstance(event, OrderFilledEvent) and event.side == "buy" and not chained:
            chained = True
            await stack.bus.publish(_validated("ord-sell", "sell", 71000.0))

    stack.bus.subscribe(OrderFilledEvent, _on_fill, priority=0)

    await asyncio.wait_for(
        stack.bus.publish(_validated("ord-buy", "buy", 70000.0)), timeout=5.0
    )

    assert chained is True
    assert stack.of(OrderFailedEvent) == []
    assert sorted(e.side for e in stack.of(OrderFilledEvent)) == ["buy", "sell"]
    trades = await stack.db.fetch_all("SELECT side FROM trades")
    assert sorted(t["side"] for t in trades) == ["buy", "sell"]
    history = await stack.db.fetch_all("SELECT action FROM position_history")
    assert sorted(h["action"] for h in history) == ["buy", "sell"]
    position = await stack.db.fetch_one("SELECT quantity FROM positions")
    assert position is not None
    assert position["quantity"] == 0


# ── T7: 기록 실패는 주문 실패로 끝난다(fail-closed) ───────────────────────


async def test_record_failure_fails_order_closed(
    stack: _Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(**kwargs: Any) -> bool:
        raise RuntimeError("disk full")

    monkeypatch.setattr(stack.applier, "apply_direct_fill", _boom)

    await stack.bus.publish(_validated("ord-buy", "buy", 70000.0))

    failed = stack.of(OrderFailedEvent)
    assert len(failed) == 1
    assert failed[0].order_id == "ord-buy"
    assert failed[0].error_message == "virtual_fill_record_failed"
    assert stack.of(OrderFilledEvent) == []
    budget = stack.treasury.get_budget(BOT)
    assert budget is not None
    assert budget.reserved == pytest.approx(0.0)
    assert budget.spent == pytest.approx(0.0)
    assert budget.available == pytest.approx(1_000_000.0)
    assert stack.portfolio.get_positions(BOT) == {}
    assert stack.portfolio.get_balance(BOT)["available"] == pytest.approx(1_000_000.0)


async def test_duplicate_order_id_skips_portfolio_and_publish(stack: _Stack) -> None:
    approved = OrderApprovedEvent(
        account_id=ACCT,
        order_id="ord-dup",
        bot_id=BOT,
        strategy_id="strat-v",
        symbol=SYMBOL,
        side="buy",
        quantity=1.0,
        price=70000.0,
        order_type="limit",
        exchange="TEST",
    )
    await stack.bus.publish(approved)
    await stack.bus.publish(approved)

    assert len(stack.of(OrderFilledEvent)) == 1
    assert await stack.count("trades") == 1
    assert stack.portfolio.get_positions(BOT)[SYMBOL]["quantity"] == 1.0


async def test_without_fill_applier_records_nothing_and_warns(
    db, caplog: pytest.LogCaptureFixture
) -> None:
    s = _Stack(db)
    s.executor = VirtualExecutor(
        eventbus=s.bus,
        runtime_readiness=ready_registry(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        ),
        account_service=_account_service(),
    )
    await s.start()

    with caplog.at_level("WARNING", logger="ante.bot.providers.virtual"):
        await s.bus.publish(_validated("ord-buy", "buy", 70000.0))

    assert len(s.of(OrderFilledEvent)) == 1
    assert await s.count("trades") == 0
    assert await s.count("positions") == 0
    assert s.portfolio.get_positions(BOT) == {}
    assert any("fill_applier" in r.getMessage() for r in caplog.records)


# ── #3068: 봇의 보유를 넘는 가상 매도는 체결 없이 실패로 끝난다 ─────────────

INSUFFICIENT = "virtual_insufficient_holdings"


def _order(
    order_id: str,
    side: str,
    price: float,
    quantity: float,
    *,
    order_type: str = "limit",
    reason: str = "",
) -> OrderValidatedEvent:
    return OrderValidatedEvent(
        account_id=ACCT,
        order_id=order_id,
        bot_id=BOT,
        strategy_id="strat-v",
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        price=price,
        order_type=order_type,
        exchange="TEST",
        reason=reason,
    )


async def _ledger(stack: _Stack) -> dict[str, Any]:
    budget = stack.treasury.get_budget(BOT)
    assert budget is not None
    row = await stack.db.fetch_one(
        "SELECT available, returned FROM bot_budgets WHERE bot_id = ?", (BOT,)
    )
    assert row is not None
    positions = await stack.db.fetch_all(
        "SELECT quantity, avg_entry_price, realized_pnl FROM positions"
    )
    history = await stack.db.fetch_all("SELECT action, quantity FROM position_history")
    filled = await stack.db.fetch_all(
        "SELECT side, quantity FROM trades WHERE status = 'filled'"
    )
    return {
        "mem": (budget.available, budget.returned),
        "db": (row["available"], row["returned"]),
        "positions": [dict(p) for p in positions],
        "history": [dict(h) for h in history],
        "filled": [dict(t) for t in filled],
    }


async def _assert_rejected_unchanged(
    stack: _Stack, before: dict[str, Any], order_id: str
) -> None:
    (failed,) = stack.of(OrderFailedEvent)
    assert failed.order_id == order_id
    assert failed.error_message == INSUFFICIENT
    assert failed.error_code == ""
    assert stack.of(OrderFilledEvent) == []
    assert await _ledger(stack) == before
    rows = await stack.db.fetch_all(
        "SELECT reason FROM trades WHERE status = 'failed' AND side = 'sell'"
    )
    assert [r["reason"] for r in rows] == [INSUFFICIENT]


async def test_sell_without_holdings_fails_without_side_effects(
    stack: _Stack,
) -> None:
    before = await _ledger(stack)

    await stack.bus.publish(_order("ord-sell", "sell", 10_000.0, 10.0))

    await _assert_rejected_unchanged(stack, before, "ord-sell")


async def test_sell_above_holdings_fails_and_keeps_position(stack: _Stack) -> None:
    await stack.bus.publish(_order("ord-buy", "buy", 10_000.0, 5.0))
    before = await _ledger(stack)
    stack.events.clear()

    await stack.bus.publish(_order("ord-sell", "sell", 10_000.0, 10.0))

    await _assert_rejected_unchanged(stack, before, "ord-sell")
    assert [p["quantity"] for p in before["positions"]] == [5.0]


@pytest.mark.parametrize(
    ("order_type", "reason"),
    [("market", "stop_triggered: stop-1"), ("limit", "liquidation: bot stop")],
)
async def test_stop_and_liquidation_sells_above_holdings_fail_alike(
    stack: _Stack, order_type: str, reason: str
) -> None:
    before = await _ledger(stack)

    await stack.bus.publish(
        _order("ord-sell", "sell", 10_000.0, 3.0, order_type=order_type, reason=reason)
    )

    await _assert_rejected_unchanged(stack, before, "ord-sell")


async def test_overlapping_sells_of_full_holding_fill_only_one(stack: _Stack) -> None:
    await stack.bus.publish(_order("ord-buy", "buy", 10_000.0, 10.0))
    stack.events.clear()

    await asyncio.gather(
        stack.bus.publish(_order("ord-sell-a", "sell", 10_000.0, 10.0)),
        stack.bus.publish(_order("ord-sell-b", "sell", 10_000.0, 10.0)),
    )

    assert len(stack.of(OrderFilledEvent)) == 1
    (failed,) = stack.of(OrderFailedEvent)
    assert failed.error_message == INSUFFICIENT
    position = await stack.db.fetch_one("SELECT quantity FROM positions")
    assert position is not None
    assert position["quantity"] == 0
    sells = await stack.db.fetch_all(
        "SELECT quantity FROM trades WHERE status = 'filled' AND side = 'sell'"
    )
    assert [s["quantity"] for s in sells] == [10.0]
    budget = stack.treasury.get_budget(BOT)
    assert budget is not None
    assert budget.returned == pytest.approx(100_000.0 * (1 - SELL_RATE))


async def test_sell_within_holdings_still_fills_whole_quantity(stack: _Stack) -> None:
    await stack.bus.publish(_order("ord-buy", "buy", 10_000.0, 10.0))
    stack.events.clear()

    await stack.bus.publish(_order("ord-sell", "sell", 10_000.0, 10.0))

    assert stack.of(OrderFailedEvent) == []
    (filled,) = stack.of(OrderFilledEvent)
    assert filled.quantity == 10.0
    position = await stack.db.fetch_one("SELECT quantity FROM positions")
    assert position is not None
    assert position["quantity"] == 0


async def test_overflowing_sell_without_holdings_keeps_budget_finite(
    stack: _Stack,
) -> None:
    before = await _ledger(stack)

    await stack.bus.publish(_order("ord-sell", "sell", 1e200, 1e200))

    await _assert_rejected_unchanged(stack, before, "ord-sell")
    budget = stack.treasury.get_budget(BOT)
    assert budget is not None
    assert budget.available == before["mem"][0]


async def test_direct_fill_raises_on_sell_above_holdings(stack: _Stack) -> None:
    from ante.trade.fill_applier import InsufficientHoldingsError

    assert FillApplier.InsufficientHoldingsError is InsufficientHoldingsError
    with pytest.raises(InsufficientHoldingsError):
        await stack.applier.apply_direct_fill(**_direct(side="sell"))

    assert await stack.count("trades") == 0
    assert await stack.count("positions") == 0
    assert await stack.count("position_history") == 0


async def test_direct_fill_replay_of_settled_sell_stays_idempotent(
    stack: _Stack,
) -> None:
    assert await stack.applier.apply_direct_fill(**_direct()) is True
    sell = _direct(order_id="ord-s", side="sell")
    assert await stack.applier.apply_direct_fill(**sell) is True

    assert await stack.applier.apply_direct_fill(**sell) is False
    assert await stack.count("trades") == 2


async def test_holdings_lookup_failure_ends_as_record_failure(
    stack: _Stack, monkeypatch: pytest.MonkeyPatch
) -> None:
    await stack.bus.publish(_order("ord-buy", "buy", 10_000.0, 10.0))
    stack.events.clear()

    async def _boom(*args: Any, **kwargs: Any) -> dict[str, Any]:
        raise RuntimeError("positions read failed")

    monkeypatch.setattr(stack.position_history, "get_current", _boom)

    await stack.bus.publish(_order("ord-sell", "sell", 10_000.0, 10.0))

    (failed,) = stack.of(OrderFailedEvent)
    assert failed.error_message == "virtual_fill_record_failed"
    sells = await stack.db.fetch_all(
        "SELECT 1 FROM trades WHERE status = 'filled' AND side = 'sell'"
    )
    assert sells == []


async def test_fractional_sells_compare_without_tolerance(stack: _Stack) -> None:
    """알려진 한계: 부동소수 누적으로 마지막 소수 매도가 거부될 수 있다."""
    from ante.trade.fill_applier import InsufficientHoldingsError

    assert await stack.applier.apply_direct_fill(**_direct(quantity=0.3))
    for n in range(2):
        assert await stack.applier.apply_direct_fill(
            **_direct(order_id=f"s{n}", side="sell", quantity=0.1)
        )
    with pytest.raises(InsufficientHoldingsError):
        await stack.applier.apply_direct_fill(
            **_direct(order_id="s2", side="sell", quantity=0.1)
        )

    for n in range(3):
        assert await stack.applier.apply_direct_fill(
            **_direct(order_id=f"b{n}", symbol="000002", quantity=0.1)
        )
    assert await stack.applier.apply_direct_fill(
        **_direct(order_id="s-all", symbol="000002", side="sell", quantity=0.3)
    )
