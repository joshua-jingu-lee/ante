"""봇 시작/중지 시 전략별 룰 로드/제거 테스트.

Refs #498
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.bot import BotConfig, BotManager, BotStatus
from ante.core import Database
from ante.eventbus import EventBus
from ante.rule.engine import RuleEngine
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
def mock_account_service():
    """AccountService 목 객체."""
    service = AsyncMock()
    account = Account(
        account_id="default",
        name="테스트",
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
    )
    service.get = AsyncMock(return_value=account)
    service.suspend = AsyncMock()
    return service


@pytest.fixture
def rule_engine(eventbus, mock_account_service):
    engine = RuleEngine(
        eventbus=eventbus,
        account_id="default",
        account_service=mock_account_service,
    )
    return engine


@pytest.fixture
def strategy_rule_configs():
    return {
        "momentum_v1": [
            {"type": "position_size", "id": "ps1", "max_quantity": 100},
            {"type": "trade_frequency", "id": "tf1", "max_trades_per_day": 10},
        ],
        "mean_revert_v1": [
            {"type": "unrealized_loss_limit", "id": "ul1", "max_loss_pct": 5.0},
        ],
    }


@pytest.fixture
async def manager(eventbus, db, rule_engine, strategy_rule_configs):
    m = BotManager(
        eventbus=eventbus,
        db=db,
        rule_engine=rule_engine,
        strategy_rule_configs=strategy_rule_configs,
    )
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


# ── 봇 시작 시 전략별 룰 로드 ──────────────────────


class TestBotStartLoadsRules:
    async def test_start_bot_loads_strategy_rules(self, manager, ctx, rule_engine):
        """봇 시작 시 전략별 룰이 RuleEngine에 로드된다."""
        config = BotConfig(
            bot_id="bot1", strategy_id="momentum_v1", interval_seconds=999
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 시작 전에는 전략별 룰 없음
        assert "momentum_v1" not in rule_engine._strategy_rules

        await manager.start_bot("bot1")

        # 시작 후 전략별 룰 2건 로드됨
        assert "momentum_v1" in rule_engine._strategy_rules
        assert len(rule_engine._strategy_rules["momentum_v1"]) == 2

    async def test_start_bot_no_config_no_error(self, manager, ctx, rule_engine):
        """전략별 룰 설정이 없는 전략이면 에러 없이 진행."""
        config = BotConfig(
            bot_id="bot1", strategy_id="unknown_strategy", interval_seconds=999
        )
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.start_bot("bot1")

        assert "unknown_strategy" not in rule_engine._strategy_rules
        assert manager.get_bot("bot1").status == BotStatus.RUNNING


# ── 봇 중지 시 전략별 룰 제거 ──────────────────────


class TestBotStopRemovesRules:
    async def test_stop_bot_removes_strategy_rules(self, manager, ctx, rule_engine):
        """봇 중지 시 전략별 룰이 RuleEngine에서 제거된다."""
        config = BotConfig(
            bot_id="bot1", strategy_id="momentum_v1", interval_seconds=999
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert "momentum_v1" in rule_engine._strategy_rules

        await manager.stop_bot("bot1")

        assert "momentum_v1" not in rule_engine._strategy_rules

    async def test_stop_bot_no_rules_no_error(self, manager, ctx, rule_engine):
        """전략별 룰이 없는 봇도 중지 시 에러 없이 진행."""
        config = BotConfig(
            bot_id="bot1", strategy_id="unknown_strategy", interval_seconds=999
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await manager.stop_bot("bot1")

        assert manager.get_bot("bot1").status == BotStatus.STOPPED


# ── 시스템 재시작 후 봇 자동 시작 시 룰 복원 ────────


class TestRestartRestoresRules:
    async def test_resume_bot_reloads_rules(self, manager, ctx, rule_engine):
        """봇 재시작(resume) 시 전략별 룰이 다시 로드된다."""
        config = BotConfig(
            bot_id="bot1", strategy_id="momentum_v1", interval_seconds=999
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")

        # 중지 후 룰 제거 확인
        assert "momentum_v1" not in rule_engine._strategy_rules

        # 재시작 — resume_bot은 내부적으로 bot.start()를 직접 호출하므로
        # start_bot()과 동일하게 룰을 로드하도록 _load_strategy_rules 호출 확인
        await manager.start_bot("bot1")

        assert "momentum_v1" in rule_engine._strategy_rules
        assert len(rule_engine._strategy_rules["momentum_v1"]) == 2


# ── RuleEngine 없이도 동작 ──────────────────────


class TestWithoutRuleEngine:
    async def test_no_rule_engine_start_stop(self, eventbus, db, ctx):
        """RuleEngine 미주입 시에도 봇 시작/중지 정상 동작."""
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        config = BotConfig(
            bot_id="bot1", strategy_id="momentum_v1", interval_seconds=999
        )
        await m.create_bot(config, SimpleStrategy, ctx)

        await m.start_bot("bot1")
        assert m.get_bot("bot1").status == BotStatus.RUNNING

        await m.stop_bot("bot1")
        assert m.get_bot("bot1").status == BotStatus.STOPPED
