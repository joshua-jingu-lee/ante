"""봇 삭제 시 Treasury budget 환수 테스트.

Refs #677
"""

import asyncio

import pytest

from ante.bot import BotConfig, BotManager
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
from ante.treasury.treasury import Treasury

# -- Fake 구현체 --


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


class FakeTreasuryManager:
    """TreasuryManager의 경량 대체."""

    def __init__(self) -> None:
        self._treasuries: dict[str, Treasury] = {}

    def register(self, account_id: str, treasury: Treasury) -> None:
        self._treasuries[account_id] = treasury

    def get(self, account_id: str) -> Treasury:
        if account_id not in self._treasuries:
            raise KeyError(f"Treasury not found: account_id={account_id}")
        return self._treasuries[account_id]

    def list_all(self) -> list[Treasury]:
        return list(self._treasuries.values())


# -- Fixtures --


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
async def treasury(db, eventbus):
    t = Treasury(db=db, eventbus=eventbus, account_id="test")
    await t.initialize()
    await t.set_account_balance(1_000_000)
    return t


@pytest.fixture
async def treasury_manager(treasury):
    mgr = FakeTreasuryManager()
    mgr.register("test", treasury)
    return mgr


@pytest.fixture
async def manager(eventbus, db, treasury_manager):
    m = BotManager(eventbus=eventbus, db=db, treasury_manager=treasury_manager)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


# -- Tests --


class TestDeleteBotBudgetRelease:
    """봇 삭제 시 Treasury budget 환수 검증."""

    async def test_delete_releases_budget(self, manager, ctx, treasury):
        """봇 삭제 시 할당액이 전액 환수되고 budget이 제거된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 예산 할당
        result = await treasury.allocate("bot1", 200_000)
        assert result is True
        assert treasury.get_budget("bot1") is not None
        assert treasury.get_budget("bot1").allocated == 200_000
        assert treasury.unallocated == 800_000

        # 봇 삭제
        await manager.delete_bot("bot1")

        # 검증: budget이 제거되고 미할당으로 환수
        assert treasury.get_budget("bot1") is None
        assert treasury.unallocated == 1_000_000

    async def test_delete_without_budget(self, manager, ctx, treasury):
        """예산 할당 없는 봇 삭제 시에도 정상 동작한다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        # 예산 할당 없이 삭제
        await manager.delete_bot("bot1")

        assert treasury.get_budget("bot1") is None
        assert treasury.unallocated == 1_000_000

    async def test_delete_releases_full_amount_after_partial_spend(
        self, manager, ctx, treasury
    ):
        """일부 사용 후 삭제 시 남은 할당액이 환수된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await treasury.allocate("bot1", 300_000)
        # 내부 spent 시뮬레이션 (available 감소)
        budget = treasury.get_budget("bot1")
        budget.available -= 50_000
        budget.spent += 50_000

        await manager.delete_bot("bot1")

        # allocated 전체(300_000)가 unallocated로 환수
        assert treasury.get_budget("bot1") is None
        assert treasury.unallocated == 1_000_000

    async def test_delete_without_treasury_manager(self, eventbus, db, ctx):
        """treasury_manager 없이 생성된 BotManager에서도 삭제가 정상 동작한다."""
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()

        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await m.create_bot(config, SimpleStrategy, ctx)
        await m.delete_bot("bot1")

        assert m.get_bot("bot1") is None

    async def test_budget_db_record_deleted(self, manager, ctx, treasury, db):
        """삭제 후 DB에서도 budget 레코드가 제거된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await treasury.allocate("bot1", 100_000)

        await manager.delete_bot("bot1")

        row = await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = 'bot1'")
        assert row is None

    async def test_transaction_log_recorded(self, manager, ctx, treasury, db):
        """삭제 시 release 트랜잭션 로그가 기록된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await treasury.allocate("bot1", 150_000)

        await manager.delete_bot("bot1")

        rows = await db.fetch_all(
            "SELECT * FROM treasury_transactions"
            " WHERE bot_id = 'bot1' AND transaction_type = 'release'"
        )
        assert len(rows) == 1
        assert rows[0]["amount"] == 150_000

    async def test_recreate_after_delete_no_accumulation(
        self, manager, ctx, treasury, eventbus, db
    ):
        """삭제 후 동일 bot_id로 재생성 시 이전 할당이 누적되지 않는다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await treasury.allocate("bot1", 200_000)

        await manager.delete_bot("bot1")

        # 동일 bot_id로 재생성
        ctx2 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        await manager.create_bot(config, SimpleStrategy, ctx2)
        await treasury.allocate("bot1", 100_000)

        budget = treasury.get_budget("bot1")
        assert budget.allocated == 100_000  # 이전 200_000이 누적되지 않음
        assert treasury.unallocated == 900_000


class TestDeleteBotBudgetReleaseFallback:
    """봇 삭제 시 인메모리에 budget이 없어도 DB fallback으로 환수되는지 검증.

    Refs #982
    """

    async def test_release_budget_db_fallback_after_memory_clear(
        self, manager, ctx, treasury, db
    ):
        """인메모리 _budgets에서 제거된 후에도 DB fallback으로 환수된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await treasury.allocate("bot1", 200_000)

        # 인메모리 _budgets에서만 제거 (서버 재시작 시뮬레이션)
        treasury._budgets.pop("bot1", None)
        assert treasury.get_budget("bot1") is None  # 인메모리에 없음

        # 봇 삭제 -- DB fallback으로 환수되어야 함
        await manager.delete_bot("bot1")

        assert treasury.unallocated == 1_000_000
        row = await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = 'bot1'")
        assert row is None

    async def test_release_budget_db_fallback_cross_account(self, db, eventbus, ctx):
        """봇 account_id와 예산 account_id가 달라도 fallback 루프로 환수된다.

        Refs #982 -- 핵심 시나리오: 봇의 account_id가 treasury의 account_id와
        다르지만, 예산은 다른 treasury에 할당되어 있는 경우.
        """
        # Treasury 2개 생성: 'default'와 'other'
        treasury_default = Treasury(db=db, eventbus=eventbus, account_id="default")
        await treasury_default.initialize()
        await treasury_default.set_account_balance(1_000_000)

        treasury_other = Treasury(db=db, eventbus=eventbus, account_id="other")
        await treasury_other.initialize()
        await treasury_other.set_account_balance(500_000)

        # FakeTreasuryManager에 두 treasury 등록
        tm = FakeTreasuryManager()
        tm.register("default", treasury_default)
        tm.register("other", treasury_other)

        m = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await m.initialize()

        # 봇의 account_id='other'이지만, 예산은 'default' treasury에 할당
        config = BotConfig(bot_id="bot-cross", strategy_id="s1", account_id="other")
        cross_ctx = StrategyContext(
            bot_id="bot-cross",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        await m.create_bot(config, SimpleStrategy, cross_ctx)
        await treasury_default.allocate("bot-cross", 300_000)
        assert treasury_default.unallocated == 700_000

        # 인메모리에서 제거 (서버 재시작 시뮬레이션)
        treasury_default._budgets.pop("bot-cross", None)

        # 봇 삭제: get('other')는 treasury_other를 반환하고 budget 못 찾음
        # -> fallback으로 모든 treasury 순회 -> treasury_default의 DB fallback이 동작
        await m.delete_bot("bot-cross")

        assert treasury_default.unallocated == 1_000_000
        row = await db.fetch_one("SELECT * FROM bot_budgets WHERE bot_id = 'bot-cross'")
        assert row is None

        # cleanup
        for bot in list(m._bots.values()):
            if bot._task and not bot._task.done():
                bot._task.cancel()
