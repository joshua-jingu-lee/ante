"""봇 상태 전이의 특성 테스트 (#2699).

``BotManager``·``Bot`` 의 공개 API로 이전 상태를 만들고, 상태를 쓰는 메서드가
지금 어떤 이전 상태를 거부하고(예외 종류와 전체 메시지), 무엇을 그대로 두고
(no-op), 어떤 다음 상태로 보내는지(메모리 값과 DB 저장값)를 잠근다.

이전 상태는 공개 API로 만든다.

- ``created``: ``create_bot``
- ``running``: ``start_bot``
- ``stopped``: ``start_bot`` 뒤 ``stop_bot``
- ``error``: ``on_step`` 이 실패하는 전략으로 ``start_bot`` 하고 실행 루프가
  끝나기를 기다린다(``auto_restart=False`` 라 재시작 태스크가 생기지 않는다)
- ``stopping``: ``start_bot`` 으로 실행 중인 봇(루프 태스크와 전략이 살아 있다)의
  상태만 ``stopping`` 으로 직접 대입한다. 공개 API로는 닿지 않는다(#2697: ``on_stop``
  이 실패해도 정지는 ``stopped`` 로 끝난다). DB의 오래된 행과 정지가 취소되는 경로가
  아직 이 상태에 닿는다
- ``deleted``: ``delete_bot`` 뒤의 객체

실행 루프의 대기는 ``ante.bot.bot`` 의 ``asyncio.sleep`` 을 대역으로 바꿔 실제
시간을 기다리지 않는다. 재시작 대기는 ``ante.bot.manager._cooldown_sleep`` 을
대역으로 바꾼다. 각 사례 끝에 남은 태스크를 모두 정리한다.

기대값은 모두 리터럴(상태 문자열, 예외 종류와 전체 메시지, 이벤트 이름과
건수)이다.

뒤쪽은 전이표가 리터럴로 적은 23쌍과 같은지, 전이 함수가 6×6=36쌍 전부에서
표대로 바꾸거나 거부하는지 본다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ante.bot import BotConfig, BotManager
from ante.bot.bot import Bot, _transition_status
from ante.bot.cold_path import cold_path_remove_bot
from ante.bot.config import BOT_STATUS_TRANSITIONS, BotStatus
from ante.bot.exceptions import BotError, BotNotFoundError, BotStateConflict
from ante.bot.manager import BOT_SCHEMA, StopCleanup
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    AccountSuspendedEvent,
    BotErrorEvent,
    BotStartedEvent,
    BotStepCompletedEvent,
    BotStoppedEvent,
)
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Signal,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

BOT_ID = "bot-2699"
INTERVAL = 17
IDLE_INTERVAL = 600

_real_sleep = asyncio.sleep


class _FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):  # type: ignore[override]
        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):  # type: ignore[override]
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):  # type: ignore[override]
        return {}


class _FakePortfolio(PortfolioView):
    def get_positions(self, bot_id):  # type: ignore[override]
        return {}

    def get_balance(self, bot_id):  # type: ignore[override]
        return {"total": 1.0, "available": 1.0}


class _FakeOrders(OrderView):
    def get_open_orders(self, bot_id):  # type: ignore[override]
        return []


class _Steady(Strategy):
    meta = StrategyMeta(name="steady", version="1.0.0", description="#2699")

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.stop_calls = 0

    async def on_step(self, context):  # type: ignore[override]
        return []

    def on_stop(self) -> None:
        self.stop_calls += 1


class _FailingStop(_Steady):
    def on_stop(self) -> None:
        self.stop_calls += 1
        raise RuntimeError("on_stop failed")


class _FailingStep(_Steady):
    async def on_step(self, context):  # type: ignore[override]
        raise RuntimeError("on_step failed")


class _NeverReturns(_Steady):
    async def on_step(self, context):  # type: ignore[override]
        await asyncio.Event().wait()
        return []


class _Overflow(_Steady):
    async def on_step(self, context):  # type: ignore[override]
        return [
            Signal(symbol="005930", side="buy", quantity=1.0, reason="a"),
            Signal(symbol="005930", side="buy", quantity=1.0, reason="b"),
        ]


class _OverflowFailingStop(_Overflow):
    def on_stop(self) -> None:
        self.stop_calls += 1
        raise RuntimeError("on_stop failed")


_LIFECYCLE_EVENTS = (BotStartedEvent, BotStoppedEvent, BotErrorEvent)
_LOOP_EVENTS = (*_LIFECYCLE_EVENTS, BotStepCompletedEvent)


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    async def interval_sleep(delay: float) -> None:
        await _real_sleep(0 if delay == INTERVAL else delay)

    async def no_cooldown(seconds: float) -> None:
        await _real_sleep(0)

    monkeypatch.setattr("ante.bot.bot.asyncio.sleep", interval_sleep)
    monkeypatch.setattr("ante.bot.manager._cooldown_sleep", no_cooldown)


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


def _record(eventbus: EventBus, event_types: tuple[type, ...]) -> list[str]:
    seen: list[str] = []

    async def record(event: object) -> None:
        seen.append(type(event).__name__)

    for event_type in event_types:
        eventbus.subscribe(event_type, record)
    return seen


@pytest.fixture
def events(eventbus: EventBus) -> list[str]:
    return _record(eventbus, _LIFECYCLE_EVENTS)


@pytest.fixture
def loop_events(eventbus: EventBus) -> list[str]:
    return _record(eventbus, _LOOP_EVENTS)


@pytest.fixture
def ctx() -> StrategyContext:
    return StrategyContext(
        bot_id=BOT_ID,
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolio(),
        order_view=_FakeOrders(),
    )


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(str(tmp_path / "state-2699.db"))
    await database.connect()
    yield database
    await asyncio.wait_for(database.close(), timeout=5.0)


async def _drain(bots: list[Bot], tasks: list[asyncio.Task[None]]) -> None:
    pending = [t for t in tasks if not t.done()]
    pending += [b._task for b in bots if b._task is not None and not b._task.done()]
    pending += [
        t
        for t in asyncio.all_tasks()
        if t.get_name().startswith("bot_") and not t.done() and t not in pending
    ]
    for task in pending:
        task.cancel()
    if pending:
        await asyncio.wait(pending, timeout=5.0)


@pytest.fixture
async def manager(eventbus: EventBus, db: Database) -> AsyncIterator[BotManager]:
    m = BotManager(eventbus=eventbus, db=db)
    await m.initialize()
    created: list[Bot] = []
    original = m.create_bot

    async def tracking_create(*args: Any, **kwargs: Any) -> Bot:
        bot = await original(*args, **kwargs)
        created.append(bot)
        return bot

    m.create_bot = tracking_create  # type: ignore[method-assign]
    yield m
    tasks = [*m._restart_tasks.values(), *m._restart_reset_tasks.values()]
    await _drain(created, tasks)
    assert all(b._task is None or b._task.done() for b in created)


async def _create(
    manager: BotManager,
    ctx: StrategyContext,
    strategy_cls: type[Strategy] = _Steady,
    *,
    bot_id: str = BOT_ID,
) -> Bot:
    config = BotConfig(
        bot_id=bot_id,
        strategy_id=f"strat-{bot_id}",
        account_id="acc-test",
        interval_seconds=IDLE_INTERVAL,
        auto_restart=False,
    )
    return await manager.create_bot(config, strategy_cls, ctx)


async def _wait_loop(bot: Bot) -> None:
    assert bot._task is not None
    await asyncio.wait_for(bot._task, timeout=5.0)


async def _enter(manager: BotManager, ctx: StrategyContext, prior: str) -> Bot:
    if prior == "created":
        return await _create(manager, ctx)
    if prior == "running":
        bot = await _create(manager, ctx)
        await manager.start_bot(BOT_ID)
        return bot
    if prior == "stopped":
        bot = await _create(manager, ctx)
        await manager.start_bot(BOT_ID)
        await manager.stop_bot(BOT_ID)
        return bot
    if prior == "error":
        bot = await _create(manager, ctx, _FailingStep)
        await manager.start_bot(BOT_ID)
        await _wait_loop(bot)
        return bot
    if prior == "stopping":
        bot = await _create(manager, ctx)
        await manager.start_bot(BOT_ID)
        assert bot._task is not None and not bot._task.done()
        assert bot.strategy is not None
        bot.status = BotStatus.STOPPING
        return bot
    if prior == "deleted":
        bot = await _create(manager, ctx)
        await manager.delete_bot(BOT_ID)
        return bot
    raise AssertionError(prior)


async def _db_status(db: Database, bot_id: str = BOT_ID) -> str | None:
    row = await db.fetch_one("SELECT status FROM bots WHERE bot_id = ?", (bot_id,))
    return None if row is None else row["status"]


@pytest.mark.parametrize(
    "prior", ["created", "running", "stopping", "stopped", "error", "deleted"]
)
async def test_entering_each_prior_state(manager, ctx, prior):
    bot = await _enter(manager, ctx, prior)
    assert bot.status.value == prior


# ── 거부 경로 ───────────────────────────────────────────────────


async def test_start_bot_rejects_running(manager, ctx, events):
    bot = await _enter(manager, ctx, "running")
    before = list(events)
    with pytest.raises(BotStateConflict) as exc:
        await manager.start_bot(BOT_ID)
    assert type(exc.value) is BotStateConflict
    assert str(exc.value) == "이미 실행 중인 봇입니다: bot-2699 (상태: running)"
    assert bot.status.value == "running"
    assert events == before


@pytest.mark.parametrize(
    ("prior", "message"),
    [
        ("running", "이미 실행 중인 봇입니다: bot-2699"),
        ("created", "재개할 수 없는 상태입니다: bot-2699 (현재: created)"),
        ("stopping", "재개할 수 없는 상태입니다: bot-2699 (현재: stopping)"),
    ],
)
async def test_resume_bot_rejects(manager, ctx, events, prior, message):
    bot = await _enter(manager, ctx, prior)
    before = list(events)
    with pytest.raises(BotError) as exc:
        await manager.resume_bot(BOT_ID)
    assert type(exc.value) is BotError
    assert str(exc.value) == message
    assert bot.status.value == prior
    assert events == before


@pytest.mark.parametrize("prior", ["created", "stopping", "stopped"])
async def test_stop_bot_rejects(manager, ctx, events, prior):
    bot = await _enter(manager, ctx, prior)
    before = list(events)
    with pytest.raises(BotStateConflict) as exc:
        await manager.stop_bot(BOT_ID)
    assert type(exc.value) is BotStateConflict
    assert str(exc.value) == f"중지할 수 없는 상태입니다: bot-2699 (현재: {prior})"
    assert bot.status.value == prior
    assert events == before


# ── no-op 경로 ──────────────────────────────────────────────────


@pytest.mark.parametrize("prior", ["created", "stopping", "stopped", "deleted"])
async def test_bot_stop_is_a_no_op(manager, ctx, events, prior):
    bot = await _enter(manager, ctx, prior)
    stopped_at = bot.stopped_at
    stop_calls = getattr(bot.strategy, "stop_calls", None)
    before = list(events)

    assert await bot.stop() is None

    assert bot.status.value == prior
    assert bot.stopped_at == stopped_at
    assert getattr(bot.strategy, "stop_calls", None) == stop_calls
    assert events == before


@pytest.mark.parametrize("prior", ["created", "running", "stopping", "stopped"])
async def test_restart_after_cooldown_does_not_start(manager, ctx, events, prior):
    bot = await _enter(manager, ctx, prior)
    strategy = bot.strategy
    generation = bot._generation
    before = list(events)

    await manager._restart_after_cooldown(BOT_ID)

    assert bot.status.value == prior
    assert bot.strategy is strategy
    assert bot._generation == generation
    assert events == before


async def test_restart_after_cooldown_skips_bot_deleted_while_waiting(
    manager, ctx, events, monkeypatch
):
    bot = await _enter(manager, ctx, "error")
    strategy = bot.strategy
    generation = bot._generation

    async def delete_while_waiting(seconds: float) -> None:
        await manager.delete_bot(BOT_ID)

    monkeypatch.setattr("ante.bot.manager._cooldown_sleep", delete_while_waiting)
    before = list(events)

    await manager._restart_after_cooldown(BOT_ID)

    assert bot.status.value == "deleted"
    assert bot.strategy is strategy
    assert bot._generation == generation
    assert events == before


async def test_restart_after_cooldown_starts_error_bot(manager, ctx, events):
    bot = await _enter(manager, ctx, "error")
    generation = bot._generation
    before = list(events)

    await manager._restart_after_cooldown(BOT_ID)

    assert bot.status.value == "running"
    assert bot._generation == generation + 1
    assert events[len(before) :][:1] == ["BotStartedEvent"]


# ── 허용 경로: 관리자 메서드 ────────────────────────────────────


@pytest.mark.parametrize("prior", ["created", "stopped", "error", "stopping"])
async def test_start_bot_moves_to_running(manager, ctx, events, db, prior):
    bot = await _enter(manager, ctx, prior)
    before = len(events)

    assert await manager.start_bot(BOT_ID) is None

    assert bot.status.value == "running"
    assert events[before:].count("BotStartedEvent") == 1
    assert events[before:][0] == "BotStartedEvent"
    assert await _db_status(db) == "created"


@pytest.mark.parametrize("prior", ["stopped", "error"])
async def test_resume_bot_moves_to_running(manager, ctx, events, db, prior):
    bot = await _enter(manager, ctx, prior)
    before = len(events)

    assert await manager.resume_bot(BOT_ID) is None

    assert bot.status.value == "running"
    assert bot.error_message is None
    assert events[before:][0] == "BotStartedEvent"
    assert events[before:].count("BotStartedEvent") == 1
    assert await _db_status(db) == "created"


@pytest.mark.parametrize("prior", ["running", "error"])
async def test_stop_bot_moves_to_stopped(manager, ctx, events, db, prior):
    bot = await _enter(manager, ctx, prior)
    before = len(events)

    assert await manager.stop_bot(BOT_ID) == StopCleanup()

    assert bot.status.value == "stopped"
    assert bot.stopped_at is not None
    assert events[before:] == ["BotStoppedEvent"]
    assert bot.strategy is not None
    assert bot.strategy.stop_calls == 1  # type: ignore[attr-defined]
    assert await _db_status(db) == "created"


_OTHER_STRATEGY_SOURCE = """
from ante.strategy import Strategy, StrategyMeta


class OtherStrategy(Strategy):
    meta = StrategyMeta(name="strat-other", version="1.0.0", description="test")

    async def on_step(self, context):
        return []
"""


async def _register_other(db: Database, tmp_path: Path) -> str:
    from ante.strategy.registry import StrategyRegistry

    filepath = tmp_path / "strat_other.py"
    filepath.write_text(_OTHER_STRATEGY_SOURCE, encoding="utf-8")
    registry = StrategyRegistry(db)
    await registry.initialize()
    meta = StrategyMeta(name="strat-other", version="1.0.0", description="test")
    return (await registry.register(filepath, meta)).strategy_id


async def test_assign_strategy_on_running_restarts(manager, ctx, events, db, tmp_path):
    other = await _register_other(db, tmp_path)
    bot = await _enter(manager, ctx, "running")
    generation = bot._generation
    before = len(events)

    assert await manager.assign_strategy(BOT_ID, other) is None

    assert bot.status.value == "running"
    assert bot._generation == generation + 1
    assert events[before:] == ["BotStoppedEvent", "BotStartedEvent"]
    assert await _db_status(db) == "created"


@pytest.mark.parametrize("hard", [False, True], ids=["soft", "hard"])
@pytest.mark.parametrize(
    "prior", ["created", "stopped", "error", "stopping", "running"]
)
async def test_delete_bot_moves_to_deleted(manager, ctx, db, prior, hard):
    bot = await _enter(manager, ctx, prior)

    assert await manager.delete_bot(BOT_ID, hard=hard) is None

    assert bot.status.value == "deleted"
    assert manager.get_bot(BOT_ID) is None
    assert [b["bot_id"] for b in manager.list_bots()] == []
    if hard:
        assert await _db_status(db) is None
    else:
        assert await _db_status(db) == "deleted"


async def test_delete_bot_on_running_publishes_stop(manager, ctx, events):
    await _enter(manager, ctx, "running")
    before = len(events)

    await manager.delete_bot(BOT_ID)

    assert events[before:] == ["BotStoppedEvent"]


# ── 허용 경로: 실행 루프 ────────────────────────────────────────


def _bot(eventbus: EventBus, ctx: StrategyContext, strategy_cls, **overrides) -> Bot:
    values: dict[str, Any] = {
        "bot_id": BOT_ID,
        "strategy_id": "strat-loop",
        "account_id": "acc-test",
        "interval_seconds": INTERVAL,
    }
    values.update(overrides)
    return Bot(
        config=BotConfig(**values),
        strategy_cls=strategy_cls,
        ctx=ctx,
        eventbus=eventbus,
    )


async def test_on_step_failure_moves_to_error(eventbus, ctx, loop_events):
    bot = _bot(eventbus, ctx, _FailingStep)
    await bot.start()
    await _wait_loop(bot)

    assert bot.status.value == "error"
    assert bot.error_message == "on_step failed"
    assert loop_events == ["BotStartedEvent", "BotStepCompletedEvent", "BotErrorEvent"]


async def test_consecutive_timeouts_move_to_error(eventbus, ctx, loop_events):
    bot = _bot(eventbus, ctx, _NeverReturns)
    bot.config.step_timeout_seconds = 0
    await bot.start()
    await _wait_loop(bot)

    assert bot.status.value == "error"
    assert bot.error_message == "연속 타임아웃 한도 초과 (3/3)"
    assert loop_events == [
        "BotStartedEvent",
        "BotStepCompletedEvent",
        "BotStepCompletedEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
    ]


async def test_consecutive_signal_overflow_moves_to_stopped(eventbus, ctx, loop_events):
    bot = _bot(eventbus, ctx, _Overflow, max_signals_per_step=1)
    await bot.start()
    assert bot._task is not None
    await asyncio.wait({bot._task}, timeout=5.0)

    assert bot._task.done()
    assert bot.status.value == "stopped"
    assert bot.strategy is not None
    assert bot.strategy.stop_calls == 1  # type: ignore[attr-defined]
    assert loop_events == [
        "BotStartedEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStoppedEvent",
    ]


async def test_failing_self_stop_moves_to_stopped(eventbus, ctx, loop_events, caplog):
    bot = _bot(eventbus, ctx, _OverflowFailingStop, max_signals_per_step=1)
    seen: list[str] = []

    async def record_status(event: object) -> None:
        seen.append(bot.status.value)

    eventbus.subscribe(BotErrorEvent, record_status)
    with caplog.at_level(logging.WARNING, logger="ante.bot.bot"):
        await bot.start()
        assert bot._task is not None
        await asyncio.wait({bot._task}, timeout=5.0)

    assert bot._task.done()
    assert bot.status.value == "stopped"
    assert bot.stopped_at is not None
    assert bot.error_message is None
    assert bot.strategy is not None
    assert bot.strategy.stop_calls == 1  # type: ignore[attr-defined]
    assert seen == ["running", "running", "running"]
    assert loop_events == [
        "BotStartedEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
        "BotStoppedEvent",
    ]
    logged = [(r.levelname, r.getMessage()) for r in caplog.records]
    assert ("ERROR", "on_stop 실패 — 정지는 마친다: bot-2699") in logged
    assert (
        "WARNING",
        "루프 예외 무시: 봇 bot-2699 상태 stopped (정지 완료) — on_stop failed",
    ) in logged
    assert all(m != "봇 오류: bot-2699" for _, m in logged)


async def test_restart_after_timeout_error_counts_failures_from_zero(
    eventbus, ctx, loop_events
):
    bot = _bot(eventbus, ctx, _NeverReturns)
    bot.config.step_timeout_seconds = 0
    await bot.start()
    await _wait_loop(bot)
    assert bot.status.value == "error"

    await bot.start()
    await _wait_loop(bot)

    second_run = loop_events[
        len(loop_events) - loop_events[::-1].index("BotStartedEvent") :
    ]
    assert bot.status.value == "error"
    assert bot.error_message == "연속 타임아웃 한도 초과 (3/3)"
    assert second_run == [
        "BotStepCompletedEvent",
        "BotStepCompletedEvent",
        "BotStepCompletedEvent",
        "BotErrorEvent",
    ]


async def test_restart_after_signal_overflow_stop_counts_failures_from_zero(
    eventbus, ctx, loop_events
):
    bot = _bot(eventbus, ctx, _Overflow, max_signals_per_step=1)
    await bot.start()
    await _wait_loop(bot)
    assert bot.status.value == "stopped"

    await bot.start()
    await _wait_loop(bot)

    second_run = loop_events[
        len(loop_events) - loop_events[::-1].index("BotStartedEvent") :
    ]
    assert loop_events.count("BotStartedEvent") == 2
    assert bot.status.value == "stopped"
    assert second_run == [
        *["BotStepCompletedEvent", "BotErrorEvent"] * 3,
        "BotStoppedEvent",
    ]


# ── 정지의 on_stop 실패 (#2697) ─────────────────────────────────


class _RecordingRules:
    def __init__(self) -> None:
        self.removed: list[str] = []

    def remove_strategy_rules(self, strategy_id: str) -> None:
        self.removed.append(strategy_id)


async def test_stop_bot_finishes_stop_when_on_stop_fails(manager, ctx, events, db):
    rules = _RecordingRules()
    manager._rule_engine = rules
    bot = await _create(manager, ctx, _FailingStop)
    await manager.start_bot(BOT_ID)
    before = len(events)

    with pytest.raises(RuntimeError) as exc:
        await manager.stop_bot(BOT_ID)

    assert type(exc.value) is RuntimeError
    assert str(exc.value) == "on_stop failed"
    assert bot.status.value == "stopped"
    assert bot.stopped_at is not None
    assert bot.error_message is None
    assert bot.strategy is not None
    assert bot.strategy.stop_calls == 1  # type: ignore[attr-defined]
    assert events[before:] == ["BotStoppedEvent"]
    assert rules.removed == ["strat-bot-2699"]
    assert await _db_status(db) == "created"

    with pytest.raises(BotStateConflict) as again:
        await manager.stop_bot(BOT_ID)
    assert type(again.value) is BotStateConflict
    assert str(again.value) == "중지할 수 없는 상태입니다: bot-2699 (현재: stopped)"
    assert rules.removed == ["strat-bot-2699"]

    assert await manager.resume_bot(BOT_ID) is None
    assert bot.status.value == "running"


async def test_account_suspension_stops_every_bot_when_one_on_stop_fails(
    manager, ctx, events
):
    failing = await _create(manager, ctx, _FailingStop, bot_id="bot-a")
    steady = await _create(manager, ctx, _Steady, bot_id="bot-b")
    await manager.start_bot("bot-a")
    await manager.start_bot("bot-b")
    before = len(events)

    await manager._on_account_suspended(AccountSuspendedEvent(account_id="acc-test"))

    assert failing.status.value == "stopped"
    assert steady.status.value == "stopped"
    assert events[before:] == ["BotStoppedEvent", "BotStoppedEvent"]


# ── 복원과 cold-path ────────────────────────────────────────────


async def _insert(db: Database, bot_id: str, status: str) -> None:
    await db.execute_script(BOT_SCHEMA)
    await db.execute(
        """INSERT INTO bots
           (bot_id, name, strategy_id, account_id, config_json, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (bot_id, bot_id, f"strat-{bot_id}", "acc-test", "{}", status),
    )


async def test_load_from_db_restores_status(eventbus, db):
    rows = ["created", "running", "stopping", "stopped", "error", "legacy", "deleted"]
    for status in rows:
        await _insert(db, f"bot-{status}", status)
    manager = BotManager(eventbus=eventbus, db=db)
    await manager.initialize()

    assert await manager.load_from_db() == 6

    restored = {b.bot_id: b.status.value for b in manager._bots.values()}
    assert restored == {
        "bot-created": "created",
        "bot-running": "running",
        "bot-stopping": "stopping",
        "bot-stopped": "stopped",
        "bot-error": "error",
        "bot-legacy": "created",
    }


@pytest.mark.parametrize("status", ["created", "running", "legacy"])
async def test_cold_path_remove_marks_deleted(db, tmp_path, status):
    await _insert(db, BOT_ID, status)

    result = await cold_path_remove_bot(db, BOT_ID, strategies_dir=tmp_path / "s")

    assert result["previous_status"] == status
    assert result["removed"] is True
    assert await _db_status(db) == "deleted"


async def test_cold_path_remove_rejects_deleted_row(db, tmp_path):
    await _insert(db, BOT_ID, "deleted")

    with pytest.raises(BotNotFoundError):
        await cold_path_remove_bot(db, BOT_ID, strategies_dir=tmp_path / "s")

    assert await _db_status(db) == "deleted"


# ── 전이표와 전이 함수 ────────────────────────────────────────────

BOT_STATUSES = ("created", "running", "stopping", "stopped", "error", "deleted")

BOT_ALLOWED_PAIRS = {
    ("created", "running"),
    ("created", "deleted"),
    ("running", "running"),
    ("running", "stopping"),
    ("running", "stopped"),
    ("running", "error"),
    ("running", "deleted"),
    ("stopping", "running"),
    ("stopping", "stopped"),
    ("stopping", "error"),
    ("stopping", "deleted"),
    ("stopped", "running"),
    ("stopped", "stopped"),
    ("stopped", "error"),
    ("stopped", "deleted"),
    ("error", "running"),
    ("error", "stopping"),
    ("error", "stopped"),
    ("error", "error"),
    ("error", "deleted"),
    ("deleted", "stopped"),
    ("deleted", "error"),
    ("deleted", "deleted"),
}

BOT_ALL_PAIRS = [(c, t) for c in BOT_STATUSES for t in BOT_STATUSES]


def test_bot_transition_table_equals_the_23_literal_pairs():
    assert sorted(str(k) for k in BOT_STATUS_TRANSITIONS) == sorted(BOT_STATUSES)
    assert all(type(v) is set for v in BOT_STATUS_TRANSITIONS.values())
    pairs = {
        (str(current), str(target))
        for current, targets in BOT_STATUS_TRANSITIONS.items()
        for target in targets
    }
    assert pairs == BOT_ALLOWED_PAIRS
    assert len(BOT_ALLOWED_PAIRS) == 23
    assert len(BOT_ALL_PAIRS) == 36


@pytest.mark.parametrize(("current", "target"), BOT_ALL_PAIRS)
def test_bot_transition_status_over_all_36_pairs(eventbus, ctx, current, target):
    bot = _bot(eventbus, ctx, _Steady)
    bot.status = BotStatus(current)
    if (current, target) in BOT_ALLOWED_PAIRS:
        returned = _transition_status(bot, BotStatus(target))
        assert returned == target
        assert type(returned) is BotStatus
        assert bot.status == target
        return
    with pytest.raises(Exception) as exc_info:
        _transition_status(bot, BotStatus(target))
    assert type(exc_info.value) is BotStateConflict
    assert str(exc_info.value) == (
        f"봇 상태를 바꿀 수 없습니다: bot-2699 ({current} → {target})"
    )
    assert exc_info.value.code == "BOT_STATE_CONFLICT"
    assert bot.status == current
