"""BotManager.create_bot service boundary 재검증 테스트 (#1459, split #1413/B).

배경
----
``BotConfig.__post_init__`` 가 이미 runtime control 4개 필드를 검증하지만,
외부 caller 가 정상 ``BotConfig`` 를 만든 뒤 attribute mutation
(또는 ``dataclasses.replace``) 으로 invariant 를 우회한 객체를
``BotManager.create_bot`` 에 전달할 수 있다.

defense-in-depth 로 service boundary 에서도 동일 invariant 를 재검증한다.

SSOT
----
- ``docs/dashboard/user-stories/bots.md`` B-5 line 197-200
- ``docs/specs/web-api/05-resource-endpoints.md`` ``PUT /api/bots/{bot_id}``

Pass condition
--------------
- 정상 ``BotConfig`` → ``create_bot`` 성공.
- 4개 runtime control 필드 각각 invalid mutation → ``ValueError``.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.bot import BotConfig, BotManager
from ante.bot.config import (
    MAX_MAX_RESTART_ATTEMPTS,
    MAX_MAX_SIGNALS_PER_STEP,
    MAX_RESTART_COOLDOWN_SECONDS,
    MAX_STEP_TIMEOUT_SECONDS,
    MIN_MAX_RESTART_ATTEMPTS,
    MIN_MAX_SIGNALS_PER_STEP,
    MIN_RESTART_COOLDOWN_SECONDS,
    MIN_STEP_TIMEOUT_SECONDS,
)
from ante.core import Database
from ante.eventbus import EventBus
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

# ── Fake 구현체 (기존 test_bot_manager_methods 와 동일 패턴) ─────────


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


class SimpleStrategy(Strategy):
    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


# ── Fixtures ─────────────────────────────────────


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def ctx():
    return StrategyContext(
        bot_id="bot1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolioView(),
        order_view=FakeOrderView(),
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
async def manager(eventbus, db):
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


# ── service boundary invariant ──────────────────────────────


class TestCreateBotServiceBoundaryValid:
    """정상 ``BotConfig`` → ``create_bot`` 성공 (회귀 0)."""

    async def test_default_config_create_bot_success(self, manager, ctx):
        """spec default (3, 60, 30, 50) 값으로 정상 생성 성공."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.bot_id == "bot1"
        assert bot.config.max_restart_attempts == 3
        assert bot.config.restart_cooldown_seconds == 60
        assert bot.config.step_timeout_seconds == 30
        assert bot.config.max_signals_per_step == 50

    async def test_min_boundary_config_create_bot_success(self, manager, ctx):
        """spec min 경계 값으로 정상 생성 성공."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="acc-test",
            max_restart_attempts=MIN_MAX_RESTART_ATTEMPTS,
            restart_cooldown_seconds=MIN_RESTART_COOLDOWN_SECONDS,
            step_timeout_seconds=MIN_STEP_TIMEOUT_SECONDS,
            max_signals_per_step=MIN_MAX_SIGNALS_PER_STEP,
        )
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.config.max_restart_attempts == MIN_MAX_RESTART_ATTEMPTS

    async def test_max_boundary_config_create_bot_success(self, manager, ctx):
        """spec max 경계 값으로 정상 생성 성공."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="acc-test",
            max_restart_attempts=MAX_MAX_RESTART_ATTEMPTS,
            restart_cooldown_seconds=MAX_RESTART_COOLDOWN_SECONDS,
            step_timeout_seconds=MAX_STEP_TIMEOUT_SECONDS,
            max_signals_per_step=MAX_MAX_SIGNALS_PER_STEP,
        )
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.config.max_restart_attempts == MAX_MAX_RESTART_ATTEMPTS


class TestCreateBotServiceBoundaryMutationInvalid:
    """mutation 으로 invariant 우회한 ``BotConfig`` → ``ValueError``.

    각 runtime control 필드별로 mutation 시나리오를 검증한다 (#1459 Scope).
    """

    async def test_max_restart_attempts_mutation_below_min_rejected(self, manager, ctx):
        """``max_restart_attempts`` mutation (< min) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        # post_init 통과 후 attribute mutation 으로 invariant 우회.
        config.max_restart_attempts = MIN_MAX_RESTART_ATTEMPTS - 1
        with pytest.raises(ValueError, match="max_restart_attempts"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        # 봇이 등록되지 않았는지 invariant 확인.
        assert manager.get_bot("bot1") is None

    async def test_max_restart_attempts_mutation_above_max_rejected(self, manager, ctx):
        """``max_restart_attempts`` mutation (> max) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.max_restart_attempts = MAX_MAX_RESTART_ATTEMPTS + 1
        with pytest.raises(ValueError, match="max_restart_attempts"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_restart_cooldown_seconds_mutation_below_min_rejected(
        self, manager, ctx
    ):
        """``restart_cooldown_seconds`` mutation (< min) → ``ValueError``.

        이슈 #1459 Reproduction 본문에 명시된 시나리오:
        ``BotConfig(restart_cooldown_seconds=10, ...)`` 생성 후
        ``config.restart_cooldown_seconds = 0`` mutation.
        """
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="acc-test",
            restart_cooldown_seconds=10,
        )
        config.restart_cooldown_seconds = 0
        with pytest.raises(ValueError, match="restart_cooldown_seconds"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_restart_cooldown_seconds_mutation_above_max_rejected(
        self, manager, ctx
    ):
        """``restart_cooldown_seconds`` mutation (> max) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.restart_cooldown_seconds = MAX_RESTART_COOLDOWN_SECONDS + 1
        with pytest.raises(ValueError, match="restart_cooldown_seconds"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_step_timeout_seconds_mutation_below_min_rejected(self, manager, ctx):
        """``step_timeout_seconds`` mutation (< min) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.step_timeout_seconds = MIN_STEP_TIMEOUT_SECONDS - 1
        with pytest.raises(ValueError, match="step_timeout_seconds"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_step_timeout_seconds_mutation_above_max_rejected(self, manager, ctx):
        """``step_timeout_seconds`` mutation (> max) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.step_timeout_seconds = MAX_STEP_TIMEOUT_SECONDS + 1
        with pytest.raises(ValueError, match="step_timeout_seconds"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_max_signals_per_step_mutation_below_min_rejected(self, manager, ctx):
        """``max_signals_per_step`` mutation (< min) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.max_signals_per_step = MIN_MAX_SIGNALS_PER_STEP - 1
        with pytest.raises(ValueError, match="max_signals_per_step"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None

    async def test_max_signals_per_step_mutation_above_max_rejected(self, manager, ctx):
        """``max_signals_per_step`` mutation (> max) → ``ValueError``."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        config.max_signals_per_step = MAX_MAX_SIGNALS_PER_STEP + 1
        with pytest.raises(ValueError, match="max_signals_per_step"):
            await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1") is None
