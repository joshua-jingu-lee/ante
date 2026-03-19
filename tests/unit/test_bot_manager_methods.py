"""BotManager 전략 배정/변경/재개 메서드 단위 테스트.

Refs #444
"""

import asyncio

import pytest

from ante.bot import BotConfig, BotError, BotManager, BotStatus
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

# ── Fake 구현체 ──────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        return [{"close": 100.0}]

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


# ── assign_strategy ──────────────────────────────


class TestAssignStrategy:
    async def test_assign_to_stopped_bot(self, manager, ctx):
        """중지 상태 봇에 전략 배정."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.assign_strategy("bot1", "s2")

        bot = manager.get_bot("bot1")
        assert bot.config.strategy_id == "s2"

    async def test_assign_to_running_bot_restarts(self, manager, ctx):
        """running 봇에 전략 배정 시 중지 후 재시작."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.assign_strategy("bot1", "s2")

        bot = manager.get_bot("bot1")
        assert bot.config.strategy_id == "s2"
        assert bot.status == BotStatus.RUNNING

    async def test_assign_updates_db(self, manager, ctx, db):
        """전략 배정 시 DB에 strategy_id가 갱신된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.assign_strategy("bot1", "s2")

        row = await db.fetch_one("SELECT strategy_id FROM bots WHERE bot_id = 'bot1'")
        assert row["strategy_id"] == "s2"

    async def test_assign_not_found_raises(self, manager):
        """존재하지 않는 봇이면 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.assign_strategy("nonexistent", "s1")

    async def test_assign_to_created_bot(self, manager, ctx):
        """created 상태 봇에 전략 배정."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1").status == BotStatus.CREATED

        await manager.assign_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"


# ── change_strategy ──────────────────────────────


class TestChangeStrategy:
    async def test_change_stopped_bot(self, manager, ctx):
        """중지 상태 봇의 전략 교체."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"

    async def test_change_running_raises(self, manager, ctx):
        """running 봇 전략 변경 시 예외."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="실행 중인 봇"):
            await manager.change_strategy("bot1", "s2")

    async def test_change_updates_db(self, manager, ctx, db):
        """전략 교체 시 DB에 strategy_id가 갱신된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.change_strategy("bot1", "s2")

        row = await db.fetch_one("SELECT strategy_id FROM bots WHERE bot_id = 'bot1'")
        assert row["strategy_id"] == "s2"

    async def test_change_not_found_raises(self, manager):
        """존재하지 않는 봇이면 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.change_strategy("nonexistent", "s1")

    async def test_change_created_bot(self, manager, ctx):
        """created 상태 봇의 전략 교체 가능."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"

    async def test_change_error_bot(self, manager, ctx):
        """error 상태 봇의 전략 교체 가능."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        # 수동으로 error 상태 설정
        manager.get_bot("bot1").status = BotStatus.ERROR

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"


# ── resume_bot ───────────────────────────────────


class TestResumeBot:
    async def test_resume_stopped_bot(self, manager, ctx):
        """stopped 봇 재시작."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

        await manager.resume_bot("bot1")

        assert manager.get_bot("bot1").status == BotStatus.RUNNING

    async def test_resume_error_bot(self, manager, ctx):
        """error 봇 재시작."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        # 수동으로 error 상태 설정
        bot = manager.get_bot("bot1")
        bot.status = BotStatus.ERROR
        bot.error_message = "some error"

        await manager.resume_bot("bot1")

        assert bot.status == BotStatus.RUNNING
        assert bot.error_message is None

    async def test_resume_resets_error_counter(self, manager, ctx):
        """재개 시 에러 카운터가 리셋된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        bot = manager.get_bot("bot1")
        bot.status = BotStatus.ERROR
        manager._restart_counts["bot1"] = 3

        await manager.resume_bot("bot1")

        assert manager.get_restart_count("bot1") == 0

    async def test_resume_running_raises(self, manager, ctx):
        """running 봇 재개 시 예외."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="이미 실행 중"):
            await manager.resume_bot("bot1")

    async def test_resume_created_raises(self, manager, ctx):
        """created 상태 봇 재개 시 예외."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        assert manager.get_bot("bot1").status == BotStatus.CREATED

        with pytest.raises(BotError, match="재개할 수 없는 상태"):
            await manager.resume_bot("bot1")

    async def test_resume_not_found_raises(self, manager):
        """존재하지 않는 봇 재개 시 예외."""
        with pytest.raises(BotError, match="not found"):
            await manager.resume_bot("nonexistent")
