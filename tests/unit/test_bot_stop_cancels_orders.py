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
from ante.bot.manager import StopCleanup
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
ACCT2 = "acc-two"
SWEEP_TITLE = "계좌 정지 — 주문 정리 결과"
SWEEP_FAILED_TITLE = "계좌 정지 — 주문 정리 실패, 직접 확인 필요"
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
        self.gate: asyncio.Event | None = None

    async def cancel_order(self, broker_order_id: str) -> bool:
        self.calls.append(broker_order_id)
        if self.gate is not None:
            await self.gate.wait()
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
        elif event.title == SWEEP_TITLE:
            self.log.append(("sweep", event))
        elif event.title == SWEEP_FAILED_TITLE:
            self.log.append(("sweep_failed", event))

    def events(self, name: str) -> list[Any]:
        return [e for n, e in self.log if n == name]

    def names(self) -> list[str]:
        return [n for n, _ in self.log]

    async def make_bot(
        self,
        bot_id: str = BOT,
        strategy_cls: type[Strategy] = Idle,
        account_id: str = ACCT,
        **cfg: Any,
    ):
        ctx = StrategyContext(
            bot_id=bot_id,
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        cfg.setdefault("auto_restart", False)
        config = BotConfig(
            bot_id=bot_id, strategy_id="s1", account_id=account_id, **cfg
        )
        return await self.manager.create_bot(config, strategy_cls, ctx)

    async def seed(
        self,
        order_id: str,
        bot_id: str = BOT,
        *,
        side: str = "buy",
        qty: float = 10,
        account_id: str = ACCT,
    ) -> None:
        await self.tracker.open(
            order_id=order_id,
            account_id=account_id,
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

    async def register_stop(
        self, bot_id: str = BOT, *, stop_price: float = 9_000.0, account_id: str = ACCT
    ):
        return await self.stops.register(
            order_id=f"req-{bot_id}",
            bot_id=bot_id,
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=5.0,
            order_type="stop",
            stop_price=stop_price,
            account_id=account_id,
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
    await _drain_cleanups(r)
    for bot in list(r.manager._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(r.manager.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


async def _drain_cleanups(rig: Rig) -> None:
    for _ in range(10):
        tasks = list(rig.manager._suspension_cleanups.values())
        if not tasks:
            return
        await asyncio.wait_for(asyncio.gather(*tasks), timeout=5.0)
        assert all(t.exception() is None for t in tasks)
    raise AssertionError("계좌 정지 정리 태스크가 끝나지 않았다")


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


@pytest.mark.parametrize("state", ["running", "stopped", "error", "running-failing"])
async def test_delete_bot_cancels_before_liquidation(rig: Rig, state: str) -> None:
    if state == "running-failing":
        rig.broker.result = False
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
    if state == "running-failing":
        assert names.index("cancel_failed") < names.index("request")
        assert await rig.status("ord-1") == "open"
    else:
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
    await _drain_cleanups(rig)

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


@pytest.mark.parametrize("restart_before_cleanup", [False, True])
async def test_stop_bot_result_is_not_mixed_with_earlier_stop(
    rig: Rig, restart_before_cleanup: bool
) -> None:
    bot = await _running(rig)
    await rig.seed("ord-1")
    await rig.bus.publish(AccountSuspendedEvent(account_id=ACCT, reason="halt"))
    await _drain_cleanups(rig)
    assert bot.status == BotStatus.STOPPED
    assert await rig.status("ord-1") == "cancelled"

    await rig.manager.start_bot(BOT)
    if restart_before_cleanup:

        async def _restart(event: object) -> None:
            if isinstance(event, BotStoppedEvent) and bot.status == BotStatus.STOPPED:
                await bot.start()

        rig.bus.subscribe(BotStoppedEvent, _restart, priority=90)
    cleanup = await rig.manager.stop_bot(BOT)

    if restart_before_cleanup:
        assert cleanup is None
    else:
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


# ── 리뷰 후속: 순서·재시작·조회 실패·서식·finally ──────


async def test_stop_order_expires_before_cancel_wait(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _running(rig)
    await rig.seed("ord-1")
    await rig.register_stop(BOT, stop_price=9_000.0)
    monkeypatch.setattr(rig.stops, "_is_in_session", lambda order, now: True)
    original = rig.broker.cancel_order

    async def _tick_then_cancel(broker_order_id: str) -> bool:
        await rig.stops.on_price_update("005930", 8_000.0, account_id=ACCT)
        return await original(broker_order_id)

    rig.broker.cancel_order = _tick_then_cancel  # type: ignore[method-assign]

    await rig.manager.stop_bot(BOT)

    assert rig.events("request") == []
    assert [e.reason for e in rig.events("stop_expired")] == ["bot_stopped"]
    assert await rig.status("ord-1") == "cancelled"


async def test_restart_during_cleanup_leaves_new_generation(rig: Rig) -> None:
    await _running(rig)
    await rig.seed("ord-1")
    await rig.seed("ord-2")
    old_stop = await rig.register_stop(BOT)
    original = rig.broker.cancel_order
    new_stop: list[str] = []

    async def _restart_then_cancel(broker_order_id: str) -> bool:
        if not new_stop:
            await rig.manager.start_bot(BOT)
            await rig.seed("ord-new")
            new_stop.append(await rig.register_stop(BOT))
        return await original(broker_order_id)

    rig.broker.cancel_order = _restart_then_cancel  # type: ignore[method-assign]

    cleanup = await rig.manager.stop_bot(BOT)

    bot = rig.manager.get_bot(BOT)
    assert bot is not None and bot.status == BotStatus.RUNNING
    assert [e.stop_order_id for e in rig.events("stop_expired")] == [old_stop]
    assert rig.stops.get_order(new_stop[0]) in rig.stops.active_orders
    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-2") == "open"
    assert await rig.status("ord-new") == "open"
    assert cleanup is not None
    assert (cleanup.cancelled, cleanup.failed) == (1, 0)


async def test_open_order_lookup_failure_is_reported(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _running(rig)

    async def _boom(account_id: str) -> list[Any]:
        raise RuntimeError("db down")

    monkeypatch.setattr(rig.tracker, "get_open_orders", _boom)

    cleanup = await rig.manager.stop_bot(BOT)

    assert cleanup is not None and cleanup.lookup_failed
    [note] = rig.events("notify")
    assert "열린 주문 조회 실패 — 직접 확인 필요" in note.message


def test_summary_price_format_has_no_exponent() -> None:
    orders = (
        SimpleNamespace(symbol="005930", side="sell", stop_price=1_050_000.0),
        SimpleNamespace(symbol="AAPL", side="buy", stop_price=12.35),
    )
    lines = StopCleanup(stop_orders=orders).summary_lines()  # type: ignore[arg-type]

    assert "- 005930 sell stop 1,050,000" in lines
    assert "- AAPL buy stop 12.35" in lines


async def test_cleanup_error_still_closes_channel_and_clears_suppression(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[tuple[str, str]] = []
    rig.manager._signal_channel_registry = SimpleNamespace(  # type: ignore[assignment]
        close_bot=lambda bot_id, reason: closed.append((bot_id, reason))
    )
    await _running(rig)

    async def _boom(bot_id: str, reason: str) -> list[Any]:
        raise RuntimeError("expire failed")

    monkeypatch.setattr(rig.stops, "expire_for_bot", _boom)

    await rig.manager.stop_bot(BOT, suppress_notification=True)

    assert closed == [(BOT, "bot_stopped")]
    assert BOT not in rig.manager._suppress_notification_bot_ids
    assert rig.events("notify") == []


# ── 계좌 정지: 백그라운드 정리 (#3050) ──────────────


def _suspend(account_id: str = ACCT) -> AccountSuspendedEvent:
    return AccountSuspendedEvent(account_id=account_id, reason="halt")


async def _bot_in(rig: Rig, bot_id: str, state: str, account_id: str = ACCT) -> Any:
    strategy_cls = Failing if state == "error" else Idle
    bot = await rig.make_bot(bot_id, strategy_cls, account_id=account_id)
    if state == "created":
        return bot
    await rig.manager.start_bot(bot_id)
    if state == "error":
        await _wait_status(bot, BotStatus.ERROR)
    elif state == "stopped":
        await rig.manager.stop_bot(bot_id)
    return bot


async def _wait_calls(rig: Rig, count: int = 1) -> None:
    for _ in range(500):
        if len(rig.broker.calls) >= count:
            return
        await asyncio.sleep(0.005)
    raise AssertionError(f"브로커 취소 호출이 {count}건이 되지 않았다")


def _cancel_ids(rig: Rig) -> list[str]:
    return sorted(e.order_id for e in rig.events("cancel"))


def test_open_order_statuses_match_tracker_definition() -> None:
    from ante.bot.manager import _OPEN_ORDER_STATUSES
    from ante.trade.order_tracker import OPEN_STATUSES

    assert _OPEN_ORDER_STATUSES == {str(s) for s in OPEN_STATUSES}


def test_order_cancel_event_is_built_only_in_request_cancel() -> None:
    import ast

    import ante.bot.manager as manager_module

    tree = ast.parse(Path(manager_module.__file__).read_text(encoding="utf-8"))
    owners: list[str] = []

    def _visit(node: ast.AST, owner: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = owner
            if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef):
                name = child.name
            if (
                isinstance(child, ast.Call)
                and isinstance(child.func, ast.Name)
                and child.func.id == "OrderCancelEvent"
            ):
                owners.append(name)
            _visit(child, name)

    _visit(tree, "<module>")

    assert owners == ["_request_cancel"]


async def test_suspend_returns_before_broker_and_expires_stops_at_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _bot_in(rig, OTHER, "error")
    bot = await _running(rig)
    await rig.seed("ord-run")
    await rig.seed("ord-err", bot_id=OTHER)
    run_stop = await rig.register_stop(BOT)
    err_stop = await rig.register_stop(OTHER)
    rig.broker.gate = asyncio.Event()
    monkeypatch.setattr(rig.stops, "_is_in_session", lambda order, now: True)

    await asyncio.wait_for(rig.bus.publish(_suspend()), timeout=1.0)

    assert bot.status == BotStatus.STOPPED
    expired = sorted((e.stop_order_id, e.reason) for e in rig.events("stop_expired"))
    assert expired == sorted(
        [(run_stop, "account_suspended"), (err_stop, "account_suspended")]
    )
    assert rig.stops.active_orders == []
    await rig.stops.on_price_update("005930", 8_000.0, account_id=ACCT)
    assert rig.events("request") == []
    assert await rig.status("ord-run") == "open"

    await _wait_calls(rig)
    rig.broker.gate.set()
    await _drain_cleanups(rig)

    assert _cancel_ids(rig) == ["ord-err", "ord-run"]
    assert {e.reason for e in rig.events("cancel")} == {"account_suspended"}
    assert await rig.status("ord-run") == "cancelled"
    assert await rig.status("ord-err") == "cancelled"


async def test_suspend_cleans_every_bot_state_and_orphans_only_in_account(
    rig: Rig,
) -> None:
    await _bot_in(rig, "bot-err", "error")
    await _bot_in(rig, "bot-stp", "stopped")
    await _bot_in(rig, "bot-new", "created")
    await _bot_in(rig, "bot-far", "error", account_id=ACCT2)
    await _bot_in(rig, "bot-run", "running")
    stops = {}
    for bot_id in ("bot-run", "bot-err", "bot-stp", "bot-new"):
        await rig.seed(f"ord-{bot_id}", bot_id=bot_id)
        stops[bot_id] = await rig.register_stop(bot_id)
    await rig.seed("ord-ghost", bot_id="ghost")
    await rig.seed("ord-far", bot_id="bot-far", account_id=ACCT2)
    far_stop = await rig.register_stop("bot-far", account_id=ACCT2)
    rig.log.clear()

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert _cancel_ids(rig) == sorted(
        ["ord-bot-run", "ord-bot-err", "ord-bot-stp", "ord-bot-new", "ord-ghost"]
    )
    assert sorted(e.stop_order_id for e in rig.events("stop_expired")) == sorted(
        stops.values()
    )
    assert {e.reason for e in rig.events("stop_expired")} == {"account_suspended"}
    assert await rig.status("ord-far") == "open"
    assert [o.stop_order_id for o in rig.stops.active_orders] == [far_stop]
    far = rig.manager.get_bot("bot-far")
    assert far is not None and far.status == BotStatus.ERROR
    [sweep] = rig.events("sweep")
    assert sweep.level == "info"
    assert sweep.category == "system"
    assert f"`{ACCT}`" in sweep.message
    assert "미체결 주문 취소: 5건 (실패 0건)" in sweep.message
    assert "스탑 주문 만료: 4건" in sweep.message
    assert "취소하지 않고 남긴" not in sweep.message


@pytest.mark.parametrize("stays_running", [False, True])
async def test_bot_whose_stop_raises_is_still_cleaned(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, stays_running: bool
) -> None:
    from ante.bot.bot import _transition_status

    bot = await _running(rig)
    await rig.seed("ord-1")
    stop_id = await rig.register_stop(BOT)
    real_stop = bot.stop

    async def _broken_stop() -> None:
        if not stays_running:
            _transition_status(bot, BotStatus.STOPPING)
        raise RuntimeError("stop broke")

    monkeypatch.setattr(bot, "stop", _broken_stop)

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert rig.manager._suspending_bot_ids == set()
    if not stays_running:
        assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
        assert [e.stop_order_id for e in rig.events("stop_expired")] == [stop_id]
        return
    assert rig.events("cancel") == []
    monkeypatch.setattr(bot, "stop", real_stop)
    cleanup = await rig.manager.stop_bot(BOT)
    assert cleanup is not None and cleanup.cancelled == 1
    assert [e.reason for e in rig.events("cancel")] == ["bot_stopped"]


@pytest.mark.parametrize(
    ("broken", "error"),
    [
        ("_expire_bot_orders", RuntimeError("subscriber broke")),
        ("_suspend_bot", RuntimeError("subscriber broke")),
        ("_suspend_bot", asyncio.CancelledError()),
    ],
)
async def test_subscriber_failure_still_starts_cleanup(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, broken: str, error: BaseException
) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")

    async def _boom(*args: Any) -> Any:
        raise error

    monkeypatch.setattr(rig.manager, broken, _boom)

    if isinstance(error, asyncio.CancelledError):
        with pytest.raises(asyncio.CancelledError):
            await rig.bus.publish(_suspend())
    else:
        await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-1") == "cancelled"


@pytest.mark.parametrize("result", [True, False])
async def test_manual_stop_during_suspend_cleanup_skips_in_flight_order(
    rig: Rig, result: bool
) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    rig.broker.result = result
    rig.broker.gate = asyncio.Event()
    await rig.bus.publish(_suspend())
    await _wait_calls(rig)

    cleanup = await asyncio.wait_for(rig.manager.stop_bot(BOT), timeout=1.0)
    rig.broker.gate.set()
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert cleanup is not None
    assert (cleanup.cancelled, cleanup.failed, cleanup.skipped) == (0, 0, 1)
    [note] = rig.events("notify")
    assert "취소하지 않고 남긴 열린 주문: 1건" in note.message
    [sweep] = rig.events("sweep")
    if result:
        assert "미체결 주문 취소: 1건 (실패 0건)" in sweep.message
    else:
        assert "미체결 주문 취소: 0건 (실패 1건)" in sweep.message
        assert sweep.level == "warning"
        assert await rig.status("ord-1") == "open"


async def test_suspend_during_manual_stop_cancel_skips_in_flight_order(
    rig: Rig,
) -> None:
    await _running(rig)
    await rig.seed("ord-1")
    rig.broker.gate = asyncio.Event()
    manual = asyncio.create_task(rig.manager.stop_bot(BOT))
    await _wait_calls(rig)

    await asyncio.wait_for(rig.bus.publish(_suspend()), timeout=1.0)
    await _drain_cleanups(rig)
    rig.broker.gate.set()
    cleanup = await asyncio.wait_for(manual, timeout=5.0)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert cleanup is not None and cleanup.cancelled == 1
    [sweep] = rig.events("sweep")
    assert "취소하지 않고 남긴 열린 주문: 1건" in sweep.message
    assert sweep.level == "warning"


async def test_delete_during_suspend_cleanup_skips_in_flight_order(rig: Rig) -> None:
    await _bot_in(rig, BOT, "stopped")
    await rig.seed("ord-1")
    rig.broker.gate = asyncio.Event()
    await rig.bus.publish(_suspend())
    await _wait_calls(rig)

    await asyncio.wait_for(rig.manager.delete_bot(BOT), timeout=1.0)
    rig.broker.gate.set()
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-1") == "cancelled"


async def test_suspended_bot_notification_has_no_cleanup_lines(rig: Rig) -> None:
    await _running(rig)
    await rig.seed("ord-1")
    await rig.register_stop(BOT)

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    [note] = rig.events("notify")
    assert note.message == f"봇 `{BOT}` 중지 완료"
    [sweep] = rig.events("sweep")
    assert "미체결 주문 취소: 1건 (실패 0건)" in sweep.message
    assert "스탑 주문 만료: 1건" in sweep.message


async def test_suspend_with_nothing_to_clean_sends_no_result(rig: Rig) -> None:
    await _bot_in(rig, BOT, "created")
    await rig.seed("ord-far", account_id=ACCT2)

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert rig.events("cancel") == []
    assert rig.events("sweep") == []


async def test_running_and_deleting_rows_are_skipped_and_reported(rig: Rig) -> None:
    deleting = await _bot_in(rig, "bot-del", "error")
    await _bot_in(rig, "bot-err", "error")
    later = await _bot_in(rig, "bot-later", "stopped")
    await rig.seed("ord-err", bot_id="bot-err")
    await rig.seed("ord-del", bot_id="bot-del")
    await rig.seed("ord-later", bot_id="bot-later")
    rig.manager._deleting_bots.add(deleting)
    original = rig.broker.cancel_order

    async def _restart_then_cancel(broker_order_id: str) -> bool:
        if later.status != BotStatus.RUNNING:
            await rig.manager.start_bot("bot-later")
        return await original(broker_order_id)

    rig.broker.cancel_order = _restart_then_cancel  # type: ignore[method-assign]

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)
    rig.manager._deleting_bots.discard(deleting)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-err"]
    assert await rig.status("ord-del") == "open"
    assert await rig.status("ord-later") == "open"
    [sweep] = rig.events("sweep")
    assert sweep.level == "warning"
    skipped_line = (
        "취소하지 않고 남긴 열린 주문: 2건 "
        "(다른 정리가 취소 중이거나 실행·삭제 중인 봇)"
    )
    assert skipped_line in sweep.message.splitlines()


async def test_skipped_only_still_sends_result(rig: Rig) -> None:
    deleting = await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    rig.manager._deleting_bots.add(deleting)

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)
    rig.manager._deleting_bots.discard(deleting)

    assert rig.events("cancel") == []
    [sweep] = rig.events("sweep")
    assert "취소하지 않고 남긴 열린 주문: 1건" in sweep.message


async def test_overlapping_suspend_reruns_once_in_the_same_task(rig: Rig) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    gate = asyncio.Event()
    results = [False, True]

    async def _fail_then_cancel(broker_order_id: str) -> bool:
        rig.broker.calls.append(broker_order_id)
        await gate.wait()
        return results.pop(0)

    rig.broker.cancel_order = _fail_then_cancel  # type: ignore[method-assign]
    await rig.bus.publish(_suspend())
    [task] = rig.manager._suspension_cleanups.values()
    await _wait_calls(rig)

    await rig.bus.publish(_suspend())
    await rig.bus.publish(_suspend())

    assert list(rig.manager._suspension_cleanups.values()) == [task]
    gate.set()
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1", "ord-1"]
    assert await rig.status("ord-1") == "cancelled"
    assert len(rig.events("sweep")) == 2
    assert rig.manager._suspension_rerun == {}


async def test_cleanup_exception_sends_critical_alert_and_logs(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await _bot_in(rig, BOT, "error")

    async def _boom(*args: Any) -> Any:
        raise RuntimeError("sweep broke")

    monkeypatch.setattr(rig.manager, "_sweep_account", _boom)

    with caplog.at_level("ERROR", logger="ante.bot.manager"):
        await rig.bus.publish(_suspend())
        await _drain_cleanups(rig)

    [alert] = rig.events("sweep_failed")
    assert alert.level == "critical"
    assert alert.category == "system"
    assert f"`{ACCT}`" in alert.message
    assert any(
        r.exc_info and "sweep broke" in str(r.exc_info[1]) for r in caplog.records
    )
    assert rig.manager._suspension_cleanups == {}


async def test_failed_alert_publish_is_only_logged(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    await _bot_in(rig, BOT, "error")

    async def _boom(*args: Any) -> Any:
        raise RuntimeError("sweep broke")

    monkeypatch.setattr(rig.manager, "_sweep_account", _boom)
    real_publish = rig.bus.publish

    async def _publish(event: Any) -> None:
        if isinstance(event, NotificationEvent) and event.title == SWEEP_FAILED_TITLE:
            raise RuntimeError("alert broke")
        await real_publish(event)

    monkeypatch.setattr(rig.bus, "publish", _publish)

    with caplog.at_level("ERROR", logger="ante.bot.manager"):
        await rig.bus.publish(_suspend())
        await _drain_cleanups(rig)

    messages = {str(r.exc_info[1]) for r in caplog.records if r.exc_info}
    assert {"sweep broke", "alert broke"} <= messages


async def test_publish_failure_releases_in_flight_order(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    real_publish = rig.bus.publish
    failures = [RuntimeError("publish broke")]

    async def _publish(event: Any) -> None:
        if isinstance(event, OrderCancelEvent) and failures:
            raise failures.pop()
        await real_publish(event)

    monkeypatch.setattr(rig.bus, "publish", _publish)

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert rig.manager._cancelling_order_ids == set()
    assert len(rig.events("sweep_failed")) == 1
    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-1") == "cancelled"


async def test_result_lookup_failure_releases_in_flight_order(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    real_get = rig.tracker.get
    seen: list[str] = []

    async def _get(order_id: str) -> Any:
        seen.append(order_id)
        if len(seen) == 3:
            raise RuntimeError("lookup broke")
        return await real_get(order_id)

    monkeypatch.setattr(rig.tracker, "get", _get)
    rig.broker.result = False

    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert rig.manager._cancelling_order_ids == set()
    [sweep] = rig.events("sweep")
    assert "실패 1건" in sweep.message
    rig.broker.result = True
    cleanup = await rig.manager.stop_bot(BOT)

    assert cleanup is not None and cleanup.cancelled == 1
    assert [e.order_id for e in rig.events("cancel")] == ["ord-1", "ord-1"]


async def test_failed_task_clears_rerun_and_next_suspend_runs_once(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _bot_in(rig, BOT, "error")
    gate = asyncio.Event()
    runs: list[int] = []
    real_sweep = rig.manager._sweep_account

    async def _sweep(*args: Any) -> Any:
        runs.append(1)
        if len(runs) == 1:
            await gate.wait()
            raise RuntimeError("sweep broke")
        return await real_sweep(*args)

    monkeypatch.setattr(rig.manager, "_sweep_account", _sweep)
    await rig.bus.publish(_suspend())
    await asyncio.sleep(0)
    await rig.bus.publish(_suspend())
    assert ACCT in rig.manager._suspension_rerun
    gate.set()
    await _drain_cleanups(rig)

    assert len(runs) == 1
    assert rig.manager._suspension_rerun == {}
    assert rig.manager._suspension_cleanups == {}
    await rig.bus.publish(_suspend())
    await _drain_cleanups(rig)

    assert len(runs) == 2


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled"])
async def test_cleanup_registry_is_empty_after_any_end(
    rig: Rig, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    rig.broker.result = False
    if outcome == "failure":
        monkeypatch.setattr(
            rig.manager, "_notify_sweep", AsyncMock(side_effect=RuntimeError("x"))
        )
    if outcome == "cancelled":
        rig.broker.gate = asyncio.Event()
    await rig.bus.publish(_suspend())
    [first] = rig.manager._suspension_cleanups.values()
    if outcome == "cancelled":
        await _wait_calls(rig)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        rig.broker.gate.set()
    else:
        await _drain_cleanups(rig)

    assert rig.manager._suspension_cleanups == {}
    assert rig.manager._suspension_rerun == {}
    assert rig.manager._cancelling_order_ids == set()
    monkeypatch.undo()
    rig.broker.result = True
    await rig.bus.publish(_suspend())
    [second] = rig.manager._suspension_cleanups.values()
    assert second is not first
    await _drain_cleanups(rig)
    assert await rig.status("ord-1") == "cancelled"


async def test_stop_all_cancels_and_awaits_cleanup(rig: Rig) -> None:
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    rig.broker.gate = asyncio.Event()
    await rig.bus.publish(_suspend())
    [task] = rig.manager._suspension_cleanups.values()
    await _wait_calls(rig)

    await asyncio.wait_for(rig.manager.stop_all(), timeout=1.0)

    assert task.cancelled()
    assert rig.manager._suspension_cleanups == {}
    rig.broker.gate.set()


# ── 계좌 정지: AccountService 경유 ─────────────────


async def _accounts(rig: Rig, *account_ids: str) -> Any:
    from ante.account.models import Account
    from ante.account.service import AccountService

    service = AccountService(rig.db, rig.bus)
    await service.initialize()
    for account_id in account_ids:
        await service.create(
            Account(
                account_id=account_id,
                name="테스트",
                exchange="TEST",
                currency="KRW",
                broker_type="test",
                credentials={"app_key": "test", "app_secret": "test"},
            )
        )
    return service


def _fail_status_write(
    monkeypatch: pytest.MonkeyPatch, service: Any, account_id: str
) -> None:
    real_execute = service._db.execute

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if "SET status" in " ".join(sql.split()) and params[-1] == account_id:
            raise RuntimeError("디스크 오류")
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)


async def test_unpersisted_suspend_cancels_and_resend_retries(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ante.account.errors import AccountSuspendNotPersistedError

    service = await _accounts(rig, ACCT)
    await _bot_in(rig, BOT, "error")
    await rig.seed("ord-1")
    rig.broker.result = False

    with monkeypatch.context() as m:
        _fail_status_write(m, service, ACCT)
        with pytest.raises(AccountSuspendNotPersistedError):
            await service.suspend(ACCT, reason="킬 스위치", suspended_by="admin")
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1"]
    assert await rig.status("ord-1") == "open"
    rig.broker.result = True
    await service.suspend(ACCT, reason="킬 스위치", suspended_by="admin")
    await _drain_cleanups(rig)

    assert [e.order_id for e in rig.events("cancel")] == ["ord-1", "ord-1"]
    assert await rig.status("ord-1") == "cancelled"


async def test_system_halt_failure_on_one_account_does_not_block_other(
    rig: Rig, monkeypatch: pytest.MonkeyPatch
) -> None:
    from ante.account.errors import AccountSuspendAllFailedError

    service = await _accounts(rig, ACCT, ACCT2)
    await _bot_in(rig, BOT, "error")
    await _bot_in(rig, OTHER, "error", account_id=ACCT2)
    await rig.seed("ord-1")
    await rig.seed("ord-2", bot_id=OTHER, account_id=ACCT2)
    _fail_status_write(monkeypatch, service, ACCT)

    with pytest.raises(AccountSuspendAllFailedError):
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")
    await _drain_cleanups(rig)

    assert _cancel_ids(rig) == ["ord-1", "ord-2"]
    assert await rig.status("ord-1") == "cancelled"
    assert await rig.status("ord-2") == "cancelled"
