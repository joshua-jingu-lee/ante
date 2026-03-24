"""Bot 생성 시 Account 상태(active/suspended/deleted) 검증 테스트.

Refs #736
"""

from __future__ import annotations

import asyncio

import pytest

from ante.account.errors import AccountDeletedException, AccountSuspendedError
from ante.account.models import Account, AccountStatus
from ante.bot import BotConfig, BotManager, BotStatus
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


class NoMetaStrategy(Strategy):
    """meta 속성이 없는 전략 (exchange 검증 불가, 상태 검증은 여전히 필요)."""

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
async def account_service(db, eventbus):
    from ante.account.service import AccountService

    svc = AccountService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


@pytest.fixture
async def manager(eventbus, db, account_service):
    m = BotManager(eventbus=eventbus, db=db, account_service=account_service)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


# ── 테스트 ───────────────────────────────────────


class TestBotAccountStatusValidation:
    """Bot 생성 시 Account 상태 검증."""

    async def test_active_account_allowed(self, manager, account_service, ctx):
        """ACTIVE 계좌에 봇 생성 허용."""
        account = Account(
            account_id="active-acct",
            name="활성계좌",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            status=AccountStatus.ACTIVE,
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="active-acct")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.status == BotStatus.CREATED

    async def test_suspended_account_rejected(self, manager, account_service, ctx):
        """SUSPENDED 계좌에 봇 생성 시 AccountSuspendedError."""
        account = Account(
            account_id="suspended-acct",
            name="정지계좌",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            status=AccountStatus.ACTIVE,
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        await account_service.suspend(
            "suspended-acct", reason="test", suspended_by="test"
        )

        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="suspended-acct")
        with pytest.raises(AccountSuspendedError, match="정지된 계좌"):
            await manager.create_bot(config, SimpleStrategy, ctx)

    async def test_deleted_account_rejected(self, manager, account_service, ctx):
        """DELETED 계좌에 봇 생성 시 AccountDeletedException."""
        account = Account(
            account_id="deleted-acct",
            name="삭제계좌",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            status=AccountStatus.ACTIVE,
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        await account_service.suspend(
            "deleted-acct", reason="test", suspended_by="test"
        )
        await account_service.delete("deleted-acct", deleted_by="test")

        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="deleted-acct")
        with pytest.raises(AccountDeletedException, match="삭제된 계좌"):
            await manager.create_bot(config, SimpleStrategy, ctx)

    async def test_no_meta_strategy_still_validates_status(
        self, manager, account_service, ctx
    ):
        """meta 속성이 없는 전략이라도 계좌 상태 검증은 수행되어야 한다."""
        account = Account(
            account_id="suspended-acct2",
            name="정지계좌2",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            status=AccountStatus.ACTIVE,
            credentials={"app_key": "test", "app_secret": "test"},
        )
        await account_service.create(account)
        await account_service.suspend(
            "suspended-acct2", reason="test", suspended_by="test"
        )

        config = BotConfig(
            bot_id="bot-no-meta", strategy_id="s1", account_id="suspended-acct2"
        )
        with pytest.raises(AccountSuspendedError, match="정지된 계좌"):
            await manager.create_bot(config, NoMetaStrategy, ctx)
