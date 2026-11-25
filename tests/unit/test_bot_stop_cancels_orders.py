"""봇 정지가 그 봇의 미체결 주문을 취소하고 스탑 주문을 만료시킨다 (#3049).

실제 ``EventBus``·``OrderTracker``(DB)·``APIGateway``(취소 경로)·``StopOrderManager``
위에서 정지 종류별로 취소 여부를 고정한다. 브로커만 가짜다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ante.bot import BotConfig, BotManager, BotStatus
from ante.broker.fill_scheduler import business_date_kst
from ante.core import Database, clock
from ante.eventbus import EventBus
from ante.eventbus.events import (
    AccountSuspendedEvent,
    BotStartedEvent,
    BotStopEvent,
    BotStoppedEvent,
    NotificationEvent,
    OrderCancelEvent,
    OrderCancelFailedEvent,
    OrderCancelledEvent,
    OrderRequestEvent,
    StopOrderExpiredEvent,
)
from ante.gateway import APIGateway
from ante.gateway.stop_order import StopOrderManager
from ante.main import _subscribe_order_tracker
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)
from ante.strategy.base import Signal
from ante.strategy.registry import StrategyRegistry
from ante.trade.fill_applier import FillApplier
from ante.trade.order_tracker import OrderTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from ante.treasury import Treasury

ACCT = "acc-test"
BOT = "bot-a"
OTHER = "bot-b"


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class Idle(Strategy):
    meta = StrategyMeta(name="idle", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class Failing(Strategy):
    meta = StrategyMeta(name="failing", version="1.0.0", description="test")

    async def on_step(self, context):
        raise RuntimeError("boom")


class Overflowing(Strategy):
    meta = StrategyMeta(name="overflow", version="1.0.0", description="test")

    async def on_step(self, context):
        return [Signal(symbol="005930", side="buy", quantity=1.0)] * 2


class QueueThenBlock(Strategy):
    """첫 스텝에서 취소 액션을 쌓고 끝나지 않는다. 다음 세대의 스텝은 빈 목록."""

    meta = StrategyMeta(name="queue", version="1.0.0", description="test")
    calls = 0

    async def on_step(self, context):
        type(self).calls += 1
        if type(self).calls == 1:
            self.ctx.cancel_order("ord-strategy", reason="strategy-action")
            await asyncio.Event().wait()
        return []


class QueueThenFail(Strategy):
    """첫 스텝에서 취소 액션을 쌓고 예외로 ERROR 전이. 다음 세대는 빈 목록."""

    meta = StrategyMeta(name="queue-fail", version="1.0.0", description="test")
    calls = 0

    async def on_step(self, context):
        type(self).calls += 1
        if type(self).calls == 1:
            self.ctx.cancel_order("ord-strategy", reason="strategy-action")
            raise RuntimeError("boom")
        return []


class FakeBroker:
    """취소 결과를 고를 수 있는 가짜 브로커. 응답 전에 여러 번 await 한다."""

    def __init__(self) -> None:
        self.result: Any = True
        self.calls: list[str] = []
        self.completed: list[str] = []

    async def cancel_order(self, broker_order_id: str) -> bool:
        self.calls.append(broker_order_id)
        for _ in range(3):
            await asyncio.sleep(0.001)
        self.completed.append(broker_order_id)
        if isinstance(self.result, Exception):
            raise self.result
        return bool(self.result)


class Rig:
    def __init__(self, db: Database, tmp_path: Path) -> None:
        self.db = db
        self.tmp_path = tmp_path
        self.bus = EventBus()
        self.tracker = OrderTracker(db=db)
        self.broker = FakeBroker()
        self.trade_service = SimpleNamespace(get_positions=AsyncMock(return_value=[]))
        self.log: list[tuple[str, Any]] = []

    async def setup(self) -> None:
        await self.tracker.initialize()
        _subscribe_order_tracker(self.bus, self.tracker)
        account_service = SimpleNamespace(
            get_broker=AsyncMock(return_value=self.broker)
        )
        self.gateway = APIGateway(
            account_service=account_service,  # type: ignore[arg-type]
            eventbus=self.bus,
            order_tracker=self.tracker,
        )
        self.gateway.start()
        self.stops = StopOrderManager(eventbus=self.bus)
        self.stops.start()
        self.manager = BotManager(
            eventbus=self.bus,
            db=self.db,
            order_tracker=self.tracker,
            trade_service=self.trade_service,  # type: ignore[arg-type]
        )
        await self.manager.initialize()
        self.manager.set_stop_order_manager(self.stops)
        for event_type, name in (
            (OrderCancelEvent, "cancel"),
            (OrderCancelledEvent, "cancelled"),
            (OrderCancelFailedEvent, "cancel_failed"),
            (StopOrderExpiredEvent, "stop_expired"),
            (OrderRequestEvent, "request"),
            (BotStartedEvent, "started"),
        ):
            self.bus.subscribe(event_type, self._recorder(name), priority=100)
        self.bus.subscribe(NotificationEvent, self._on_notification)

    def _recorder(self, name: str):
        async def _record(event: object) -> None:
            self.log.append((name, event))

        return _record

    async def _on_notification(self, event: object) -> None:
        assert isinstance(event, NotificationEvent)
        if event.title == "봇 중지":
            self.log.append(("notify", event))

    def events(self, name: str) -> list[Any]:
        return [e for n, e in self.log if n == name]

    def names(self) -> list[str]:
        return [n for n, _ in self.log]

    async def make_bot(
        self, bot_id: str = BOT, strategy_cls: type[Strategy] = Idle, **cfg: Any
    ):
        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        cfg.setdefault("auto_restart", False)
        config = BotConfig(bot_id=bot_id, strategy_id="s1", account_id=ACCT, **cfg)
        return await self.manager.create_bot(config, strategy_cls, ctx)

    async def seed(
        self, order_id: str, bot_id: str = BOT, *, side: str = "buy", qty: float = 10
    ) -> None:
        await self.tracker.open(
            order_id=order_id,
            account_id=ACCT,
            bot_id=bot_id,
            strategy_id="s1",
            broker_order_id=f"bk-{order_id}",
            symbol="005930",
            side=side,
            order_type="limit",
            ordered_qty=qty,
            submitted_date=business_date_kst(clock.now(UTC)),
            order_price=10_000.0,
        )

    async def status(self, order_id: str) -> str:
        record = await self.tracker.get(order_id)
        assert record is not None
        return record.status

    async def register_stop(self, bot_id: str = BOT, *, stop_price: float = 9_000.0):
        return await self.stops.register(
            order_id=f"req-{bot_id}",
            bot_id=bot_id,
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=5.0,
            order_type="stop",
            stop_price=stop_price,
            account_id=ACCT,
        )


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "stop.db"))
    await database.connect()
    yield database
    try:
        await asyncio.wait_for(database.close(), timeout=5.0)
    except TimeoutError:
        pass


@pytest.fixture
async def rig(db: Database, tmp_path: Path):
    r = Rig(db, tmp_path)
    await r.setup()
    yield r
    for bot in list(r.manager._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(r.manager.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


async def _wait_status(bot: Any, status: BotStatus) -> None:
    for _ in range(500):
        if bot.status == status:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"봇 상태가 {status}가 되지 않았다: {bot.status}")


async def _running(rig: Rig, strategy_cls: type[Strategy] = Idle, **cfg: Any):
    bot = await rig.make_bot(strategy_cls=strategy_cls, **cfg)
    await rig.manager.start_bot(BOT)
    return bot


async def _errored(rig: Rig):
    bot = await _running(rig, Failing)
    await _wait_status(bot, BotStatus.ERROR)
    return bot


# ── 정지 종류별 취소 여부 ─────────────────────────


async def test_stop_bot_cancels_open_order(rig: Rig) -> None:
    await _running(rig)
    await rig.seed("ord-1")

    cleanup = await rig.manager.stop_bot(BOT)

    cancels = rig.events("cancel")
    assert [(e.order_id, e.reason, e.bot_id) for e in cancels] == [
        ("ord-1", "bot_stopped", BOT)
    ]
    assert rig.broker.completed == ["bk-ord-1"]
    assert await rig.status("ord-1") == "cancelled"
    assert cleanup is not None
    assert (cleanup.cancelled, cleanup.failed) == (1, 0)


async def test_stop_bot_from_error_cancels(rig: Rig) -> None:
    await _errored(rig)
    await rig.seed("ord-1")

    await rig.manager.stop_bot(BOT)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-1") == "cancelled"


async def test_rule_bot_stop_event_cancels(rig: Rig) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")

    await rig.bus.publish(BotStopEvent(account_id=ACCT, bot_id=BOT, reason="rule"))

    assert bot.status == BotStatus.STOPPED
    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]


async def test_assign_strategy_cancels_before_restart(rig: Rig) -> None:
    source = (
        "from ante.strategy import Strategy, StrategyMeta\n\n\n"
        "class S2(Strategy):\n"
        '    meta = StrategyMeta(name="s2", version="1.0.0", description="t")\n\n'
        "    async def on_step(self, context):\n"
        "        return []\n"
    )
    path = rig.tmp_path / "s2.py"
    path.write_text(source, encoding="utf-8")
    registry = StrategyRegistry(rig.db)
    await registry.initialize()
    meta = StrategyMeta(name="s2", version="1.0.0", description="t")
    s2 = (await registry.register(path, meta)).strategy_id
    bot = await _running(rig)
    await rig.seed("ord-1")
    rig.log.clear()

    await rig.manager.assign_strategy(BOT, s2)

    assert bot.status == BotStatus.RUNNING
    names = rig.names()
    assert names.count("cancel") == 1
    assert names.index("cancelled") < names.index("started")
    assert await rig.status("ord-1") == "cancelled"


@pytest.mark.parametrize("state", ["running", "stopped", "error"])
async def test_delete_bot_cancels_before_liquidation(rig: Rig, state: str) -> None:
    if state == "error":
        await _errored(rig)
    else:
        await _running(rig)
    if state == "stopped":
        await rig.manager.stop_bot(BOT)
    await rig.seed("ord-1")
    rig.trade_service.get_positions.return_value = [
        SimpleNamespace(symbol="005930", quantity=3.0, account_id=ACCT, exchange="KRX")
    ]
    rig.log.clear()

    await rig.manager.delete_bot(BOT, handle_positions="liquidate")

    names = rig.names()
    assert names.count("cancel") == 1
    assert names.index("cancelled") < names.index("request")
    assert await rig.status("ord-1") == "cancelled"


async def test_self_stop_completes_broker_cancel(rig: Rig) -> None:
    bot = await rig.make_bot(strategy_cls=Overflowing, max_signals_per_step=1)
    bot._max_consecutive_failures = 1
    await rig.seed("ord-1")
    await rig.register_stop()

    await rig.manager.start_bot(BOT)
    task = bot._task
    assert task is not None
    await asyncio.wait_for(asyncio.shield(task), timeout=5.0)

    assert not task.cancelled()
    assert bot.status == BotStatus.STOPPED
    assert rig.broker.completed == ["bk-ord-1"]
    assert await rig.status("ord-1") == "cancelled"
    assert [e.reason for e in rig.events("stop_expired")] == ["bot_stopped"]
    assert len(rig.events("notify")) == 1


async def test_account_suspension_of_running_bot_cancels(rig: Rig) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")

    await rig.bus.publish(AccountSuspendedEvent(account_id=ACCT, reason="halt"))

    assert bot.status == BotStatus.STOPPED
    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]


async def test_stop_all_does_not_cancel(rig: Rig) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")
    stop_id = await rig.register_stop()

    await rig.manager.stop_all()

    assert bot.status == BotStatus.STOPPED
    assert rig.events("cancel") == []
    assert rig.events("stop_expired") == []
    assert rig.stops.get_order(stop_id) in rig.stops.active_orders
    assert await rig.status("ord-1") == "open"
    assert len(rig.events("notify")) == 1


async def test_error_transition_does_not_cancel(rig: Rig) -> None:
    await rig.make_bot(strategy_cls=Failing)
    await rig.seed("ord-1")
    stop_id = await rig.register_stop()

    bot = rig.manager.get_bot(BOT)
    assert bot is not None
    await rig.manager.start_bot(BOT)
    await _wait_status(bot, BotStatus.ERROR)
    await asyncio.sleep(0.05)

    assert rig.events("cancel") == []
    assert rig.events("stop_expired") == []
    assert rig.stops.get_order(stop_id) in rig.stops.active_orders
    assert await rig.status("ord-1") == "open"


# ── 대상 범위 ──────────────────────────────────


async def test_targets_only_own_open_orders_from_db(rig: Rig) -> None:
    await rig.make_bot(OTHER)
    await _running(rig)
    await rig.seed("ord-mine")
    await rig.seed("ord-other", bot_id=OTHER)
    await rig.seed("ord-done")
    await rig.tracker.mark_terminal("ord-done", "rejected")
    rig.tracker._open_cache.clear()

    await rig.manager.stop_bot(BOT)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-mine"]
    assert await rig.status("ord-other") == "open"
    assert await rig.status("ord-done") == "rejected"


async def test_stop_orders_expire_once_and_do_not_trigger(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await rig.make_bot(OTHER)
    await _running(rig)
    mine = await rig.register_stop(BOT)
    other = await rig.register_stop(OTHER)

    cleanup = await rig.manager.stop_bot(BOT)

    expired = rig.events("stop_expired")
    assert [(e.stop_order_id, e.reason) for e in expired] == [(mine, "bot_stopped")]
    assert cleanup is not None
    assert [o.stop_order_id for o in cleanup.stop_orders] == [mine]
    assert [o.stop_order_id for o in rig.stops.active_orders] == [other]

    monkeypatch.setattr(rig.stops, "_is_in_session", lambda order, now: True)
    rig.log.clear()
    await rig.stops.on_price_update("005930", 8_000.0, account_id=ACCT)

    assert [e.bot_id for e in rig.events("request")] == [OTHER]


# ── 실패·알림 ──────────────────────────────────


@pytest.mark.parametrize("result", [False, RuntimeError("broker down")])
async def test_cancel_failure_does_not_fail_stop(rig: Rig, result: Any) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")
    rig.broker.result = result

    cleanup = await rig.manager.stop_bot(BOT)

    assert bot.status == BotStatus.STOPPED
    assert cleanup is not None
    assert (cleanup.cancelled, cleanup.failed) == (0, 1)
    assert await rig.status("ord-1") == "open"
    assert len(rig.events("cancel_failed")) == 1
    [note] = rig.events("notify")
    assert "실패 1건" in note.message


async def test_notification_after_cleanup_with_counts(rig: Rig) -> None:
    await _running(rig)
    await rig.seed("ord-1")
    await rig.seed("ord-2")
    await rig.seed("ord-3")
    await rig.register_stop(stop_price=68_000.0)

    async def _fail_third(broker_order_id: str) -> bool:
        rig.broker.calls.append(broker_order_id)
        await asyncio.sleep(0)
        return broker_order_id != "bk-ord-3"

    rig.broker.cancel_order = _fail_third  # type: ignore[method-assign]

    await rig.manager.stop_bot(BOT)

    names = rig.names()
    assert names.count("notify") == 1
    notify_at = names.index("notify")
    assert all(
        i < notify_at
        for i, n in enumerate(names)
        if n in ("cancel", "cancelled", "cancel_failed", "stop_expired")
    )
    [note] = rig.events("notify")
    assert f"`{BOT}`" in note.message
    assert "미체결 주문 취소: 2건 (실패 1건)" in note.message
    assert "스탑 주문 만료: 1건" in note.message
    assert "005930 sell stop 68,000" in note.message


async def test_suppressed_notification_still_cancels(rig: Rig) -> None:
    await _running(rig)
    await rig.seed("ord-1")

    cleanup = await rig.manager.stop_bot(BOT, suppress_notification=True)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert rig.events("notify") == []
    assert cleanup is not None
    assert cleanup.cancelled == 1


async def test_stop_bot_result_is_not_mixed_with_earlier_stop(rig: Rig) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")
    await rig.bus.publish(AccountSuspendedEvent(account_id=ACCT, reason="halt"))
    assert bot.status == BotStatus.STOPPED

    await rig.manager.start_bot(BOT)
    cleanup = await rig.manager.stop_bot(BOT)

    assert cleanup is not None
    assert (cleanup.cancelled, cleanup.failed, cleanup.stop_orders) == (0, 0, ())


async def test_restarted_before_cleanup_skips(rig: Rig) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")

    async def _restart(event: object) -> None:
        if isinstance(event, BotStoppedEvent) and bot.status == BotStatus.STOPPED:
            await bot.start()

    rig.bus.subscribe(BotStoppedEvent, _restart, priority=90)

    cleanup = await rig.manager.stop_bot(BOT)

    assert bot.status == BotStatus.RUNNING
    assert cleanup is None
    assert rig.events("cancel") == []
    assert await rig.status("ord-1") == "open"


# ── 대기 액션 ──────────────────────────────────


async def test_cancelling_stop_drops_pending_actions(rig: Rig) -> None:
    QueueThenBlock.calls = 0
    bot = await _running(rig, QueueThenBlock)
    for _ in range(100):
        if bot._ctx._pending_actions:
            break
        await asyncio.sleep(0.01)
    assert bot._ctx._pending_actions

    await rig.manager.stop_bot(BOT)
    await rig.manager.start_bot(BOT)
    for _ in range(100):
        if QueueThenBlock.calls >= 2:
            break
        await asyncio.sleep(0.01)
    await asyncio.sleep(0.05)

    assert QueueThenBlock.calls >= 2
    assert [e.reason for e in rig.events("cancel")] == []


async def test_error_transition_keeps_pending_actions(rig: Rig) -> None:
    QueueThenFail.calls = 0
    bot = await _running(rig, QueueThenFail)
    await _wait_status(bot, BotStatus.ERROR)

    await rig.manager.resume_bot(BOT)
    for _ in range(100):
        if rig.events("cancel"):
            break
        await asyncio.sleep(0.01)

    assert [e.reason for e in rig.events("cancel")] == ["strategy-action"]


# ── 예약과 늦은 체결 ────────────────────────────


async def _treasury(rig: Rig) -> Treasury:
    treasury = Treasury(
        db=rig.db,
        eventbus=rig.bus,
        account_id=ACCT,
        buy_commission_rate=0.0,
        sell_commission_rate=0.0,
        order_tracker=rig.tracker,
    )
    await treasury.initialize()
    await treasury.set_account_balance(1_000_000.0)
    await treasury.allocate(BOT, 1_000_000.0)
    assert await treasury.reserve_for_order(BOT, "ord-1", 100_000.0)
    return treasury


@pytest.mark.parametrize(
    ("result", "reservations"),
    [(True, {}), (False, {"ord-1": 100_000.0})],
)
async def test_reservation_follows_cancel_result(
    rig: Rig, result: bool, reservations: dict[str, float]
) -> None:
    treasury = await _treasury(rig)
    await _running(rig)
    await rig.seed("ord-1")
    rig.broker.result = result

    await rig.manager.stop_bot(BOT)

    assert treasury.get_reservations(BOT) == reservations
    budget = treasury.get_budget(BOT)
    assert budget is not None
    assert budget.reserved == sum(reservations.values())


async def test_late_fill_after_stop_cancel_is_applied(rig: Rig) -> None:
    treasury = await _treasury(rig)
    ph = PositionHistory(rig.db)
    await ph.initialize()
    await TradeRecorder(rig.db, ph).initialize()
    applier = FillApplier(
        db=rig.db, order_tracker=rig.tracker, position_history=ph, eventbus=rig.bus
    )
    await _running(rig)
    await rig.seed("ord-1")

    await rig.manager.stop_bot(BOT)
    assert await rig.status("ord-1") == "cancelled"

    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="bk-ord-1",
        observed_cumulative=4.0,
        avg_price=10_000.0,
        submitted_date=business_date_kst(clock.now(UTC)),
    )

    assert delta == 4.0
    assert await rig.status("ord-1") == "cancelled"
    position = await ph.get_current(BOT, "005930", account_id=ACCT)
    assert position["quantity"] == 4.0
    budget = treasury.get_budget(BOT)
    assert budget is not None
    assert budget.spent == 40_000.0
