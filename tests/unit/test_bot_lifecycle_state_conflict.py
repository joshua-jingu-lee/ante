"""BotManager start_bot/stop_bot state machine 회귀 (#1759).

Refs #1759: ante-oracle A7 ``cli_bot_lifecycle_state_conflict_contract`` 가
재현한 silent-success 결함 잠금. ``BotManager.start_bot`` / ``stop_bot`` 는
``Bot.start`` / ``Bot.stop`` 위에 strict state machine 을 적용해 중복
호출을 ``BotStateConflict`` (code=``BOT_STATE_CONFLICT``) 로 거부한다.
``resume_bot`` (manager.py:699-718) 의 status 체크 + raise 패턴과 동형.

회귀 매트릭스:

- R1: ``start_bot`` 두 번 → 두 번째 ``BotStateConflict`` raise + code.
- R2: ``stop_bot`` 두 번 → 두 번째 ``BotStateConflict`` raise + code.
- R5 (caller silent-ignore 회귀 보존):
  - EventBus 경로 ``_on_bot_stop_request`` 가 비실행 봇에서도 raise 하지
    않는다 (rule engine 의 중복 발행 / cold path 호환).
  - approval ``bot_stop`` executor (``main.py`` lambda 대체) 가 비실행
    봇에서도 raise 하지 않는다 (BotStoppedEvent 재처리 호환).

R3/R4 (CLI/IPC envelope: BOT_STATE_CONFLICT) 는 기존
``tests/unit/test_cli_bot_lifecycle.py`` / ``tests/unit/test_ipc_bot_lifecycle.py``
가 envelope passthrough 를 잠그고 있다 (BotStateConflict 가 BotError
서브클래스이므로 ipc handler 의 ``except BotError`` → ``BotStateConflict``
매핑이 동일하게 동작).
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest

from ante.bot import BotConfig, BotManager
from ante.bot.config import BotStatus
from ante.bot.exceptions import BOT_STATE_CONFLICT_CODE, BotStateConflict
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BotStopEvent
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)


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


class _NoopStrategy(Strategy):
    meta = StrategyMeta(name="noop", version="1.0.0", description="state conflict test")

    async def on_step(self, context):  # type: ignore[override]
        return []


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def ctx() -> StrategyContext:
    return StrategyContext(
        bot_id="bot-1759",
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolio(),
        order_view=_FakeOrders(),
    )


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    try:
        await asyncio.wait_for(database.close(), timeout=5.0)
    except TimeoutError:
        pass


@pytest.fixture
async def manager(eventbus: EventBus, db: Database) -> BotManager:
    m = BotManager(eventbus=eventbus, db=db)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


async def _create_bot(
    manager: BotManager, ctx: StrategyContext, *, bot_id: str = "bot-1759"
):
    config = BotConfig(
        bot_id=bot_id,
        strategy_id=f"strat-{bot_id}",
        account_id="acc-test",
    )
    return await manager.create_bot(config, _NoopStrategy, ctx)


# ── R1: start_bot 두 번 → BotStateConflict ─────────────────────────────


async def test_start_bot_twice_raises_state_conflict(
    manager: BotManager, ctx: StrategyContext
) -> None:
    """이미 실행 중인 봇에 대한 두 번째 start_bot 은 BotStateConflict."""
    bot = await _create_bot(manager, ctx)
    await manager.start_bot(bot.bot_id)
    try:
        assert bot.status == BotStatus.RUNNING

        with pytest.raises(BotStateConflict) as exc:
            await manager.start_bot(bot.bot_id)

        assert exc.value.code == BOT_STATE_CONFLICT_CODE
        # 메시지에 bot_id 및 현재 상태가 노출된다 (운영 추적용).
        assert bot.bot_id in str(exc.value)
        assert BotStatus.RUNNING.value in str(exc.value)
        # 봇 상태는 RUNNING 그대로 — 거부가 부수효과를 남기지 않는다.
        assert bot.status == BotStatus.RUNNING
    finally:
        await manager.stop_bot(bot.bot_id)


# ── R2: stop_bot 두 번 → BotStateConflict ──────────────────────────────


async def test_stop_bot_twice_raises_state_conflict(
    manager: BotManager, ctx: StrategyContext
) -> None:
    """이미 정지된 봇에 대한 두 번째 stop_bot 은 BotStateConflict."""
    bot = await _create_bot(manager, ctx)
    await manager.start_bot(bot.bot_id)
    await manager.stop_bot(bot.bot_id)
    assert bot.status == BotStatus.STOPPED

    with pytest.raises(BotStateConflict) as exc:
        await manager.stop_bot(bot.bot_id)

    assert exc.value.code == BOT_STATE_CONFLICT_CODE
    assert bot.bot_id in str(exc.value)
    assert BotStatus.STOPPED.value in str(exc.value)
    assert bot.status == BotStatus.STOPPED


async def test_stop_bot_on_created_state_raises_state_conflict(
    manager: BotManager, ctx: StrategyContext
) -> None:
    """``CREATED`` 상태(시작된 적 없는 봇) stop_bot 은 BotStateConflict.

    ``Bot.stop()`` 이 ``RUNNING``/``ERROR`` 만 처리하므로 manager 도 동일
    범위로 정합.
    """
    bot = await _create_bot(manager, ctx, bot_id="bot-1759-created")
    assert bot.status == BotStatus.CREATED

    with pytest.raises(BotStateConflict) as exc:
        await manager.stop_bot(bot.bot_id)

    assert exc.value.code == BOT_STATE_CONFLICT_CODE
    assert BotStatus.CREATED.value in str(exc.value)


# ── R5: caller silent-ignore 회귀 보존 ─────────────────────────────────


async def test_on_bot_stop_request_silent_ignores_state_conflict(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    """EventBus ``BotStopEvent`` 핸들러는 비실행 봇에서도 raise 하지 않는다.

    rule engine 이 한도 위반으로 발행한 이벤트가 중복 수신되거나 봇이
    이미 중지되어 있을 수 있다 — 이 cold path 는 idempotent 의미를
    유지한다.
    """
    bot = await _create_bot(manager, ctx, bot_id="bot-1759-evt")
    # 시작된 적 없는 봇 (status=CREATED) — stop_bot 직접 호출은 R2 에서
    # BotStateConflict 가 발생함을 확인했다. 같은 봇에 BotStopEvent 를
    # 발행하면 핸들러가 silent ignore 하여 raise 가 전파되지 않는다.
    assert bot.status == BotStatus.CREATED

    # 핸들러가 BotStateConflict 를 흡수하는지 직접 호출로 검증한다
    # (eventbus.publish 는 핸들러 예외를 로깅만 하고 삼킬 수 있어 회귀
    # 보장이 약하다 — 핸들러 함수를 직접 await 한다).
    event = BotStopEvent(bot_id=bot.bot_id, reason="test-1759-cold-path")
    # raise 가 전파되지 않으면 통과. 어떤 예외든 잡히면 회귀.
    await manager._on_bot_stop_request(event)
    # 상태는 CREATED 그대로 (silent ignore).
    assert bot.status == BotStatus.CREATED


async def test_approval_bot_stop_executor_silent_ignores_state_conflict(
    manager: BotManager, ctx: StrategyContext
) -> None:
    """approval ``bot_stop`` executor (main.py) 는 비실행 봇에서도 raise 하지 않는다.

    ``BotManager.stop_bot`` 이 strict state machine 으로 전환된 이후에도
    approval workflow 의 ``bot_stop`` action 은 idempotent 의미를 보존
    한다 (이미 중지된 봇에 대해 BotStoppedEvent 가 재처리되는 cold path
    회귀 보호). state machine 거부 (``BotStateConflict``) 는 silent
    ignore 하고, 그 외 예외는 전파한다.

    main.py 의 ``_exec_bot_stop_idempotent`` 와 동형 inline 으로
    회귀를 잠근다 (main.py 는 closure 라 직접 import 불가).
    """
    bot = await _create_bot(manager, ctx, bot_id="bot-1759-approval")
    assert bot.status == BotStatus.CREATED  # 시작된 적 없음 → stop_bot 거부 대상

    async def _exec_bot_stop_idempotent(params: dict) -> None:
        try:
            await manager.stop_bot(params["bot_id"])
        except BotStateConflict:
            return

    # raise 가 전파되지 않으면 통과 — silent ignore 회귀 보존.
    await _exec_bot_stop_idempotent({"bot_id": bot.bot_id})
    assert bot.status == BotStatus.CREATED


# ── 정상 흐름 sanity (회귀 보존) ──────────────────────────────────────


async def test_start_then_stop_remains_legal(
    manager: BotManager, ctx: StrategyContext
) -> None:
    """정상 start → stop 흐름은 state machine 도입 후에도 그대로 동작."""
    bot = await _create_bot(manager, ctx, bot_id="bot-1759-happy")
    await manager.start_bot(bot.bot_id)
    assert bot.status == BotStatus.RUNNING
    await manager.stop_bot(bot.bot_id)
    assert bot.status == BotStatus.STOPPED
