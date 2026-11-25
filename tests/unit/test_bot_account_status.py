"""Bot 생성 시 Account 상태(active/suspended/deleted) 검증 테스트.

Refs #736
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from ante.account.errors import AccountDeletedException, AccountSuspendedError
from ante.account.models import Account, AccountStatus
from ante.bot import BotConfig, BotManager, BotStatus
from ante.bot import manager as bot_manager_module
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BotErrorEvent, BotStartedEvent, NotificationEvent
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


class TestSuspendedAccountNoAutoRestart:
    """정지된 계좌의 봇은 자동 재시작되지 않는다 (#2600)."""

    @staticmethod
    async def _error_bot(manager, account_service, bot_id: str, account_id: str):
        await account_service.create(
            Account(
                account_id=account_id,
                name=account_id,
                exchange="KRX",
                currency="KRW",
                broker_type="test",
                status=AccountStatus.ACTIVE,
                credentials={"app_key": "test", "app_secret": "test"},
            )
        )
        config = BotConfig(
            bot_id=bot_id,
            strategy_id="s1",
            restart_cooldown_seconds=10,
            max_restart_attempts=3,
            account_id=account_id,
        )
        ctx = MagicMock()
        ctx.get_positions.return_value = []
        ctx.get_balance.return_value = 0.0
        ctx._drain_actions.return_value = []
        bot = await manager.create_bot(config, SimpleStrategy, ctx=ctx)
        bot.status = BotStatus.ERROR
        return bot

    @staticmethod
    def _gate_cooldown(monkeypatch) -> tuple[asyncio.Event, asyncio.Semaphore]:
        wake = asyncio.Event()
        entered = asyncio.Semaphore(0)

        async def _wait_for_wake(seconds):  # noqa: ARG001
            entered.release()
            await wake.wait()

        monkeypatch.setattr(bot_manager_module, "_cooldown_sleep", _wait_for_wake)
        return wake, entered

    @staticmethod
    def _started(eventbus) -> list[BotStartedEvent]:
        seen: list[BotStartedEvent] = []
        eventbus.subscribe(BotStartedEvent, seen.append)
        return seen

    @staticmethod
    def _notifications(eventbus) -> list[NotificationEvent]:
        seen: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, seen.append)
        return seen

    @staticmethod
    async def _error(eventbus, bot_id: str, account_id: str) -> None:
        await eventbus.publish(
            BotErrorEvent(bot_id=bot_id, error_message="test", account_id=account_id)
        )

    async def test_suspend_cancels_scheduled_restart(
        self, manager, account_service, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager, account_service, "b1", "acc-a")
        wake, entered = self._gate_cooldown(monkeypatch)
        started = self._started(eventbus)
        await self._error(eventbus, "b1", "acc-a")
        task = manager._restart_tasks["b1"]
        await entered.acquire()

        await account_service.suspend("acc-a", reason="test", suspended_by="test")
        await asyncio.wait([task], timeout=5.0)

        assert task.cancelled()
        assert "b1" not in manager._restart_tasks

        await account_service.activate("acc-a", activated_by="test")
        wake.set()
        await asyncio.sleep(0.05)

        assert started == []
        assert bot.status == BotStatus.ERROR

    async def test_error_after_suspend_does_not_restart(
        self, manager, account_service, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager, account_service, "b1", "acc-a")
        wake, _ = self._gate_cooldown(monkeypatch)
        wake.set()
        started = self._started(eventbus)

        await account_service.suspend("acc-a", reason="test", suspended_by="test")
        notifications = self._notifications(eventbus)
        await self._error(eventbus, "b1", "acc-a")
        task = manager._restart_tasks["b1"]
        await asyncio.wait([task], timeout=5.0)

        assert task.done() and not task.cancelled()
        assert task.exception() is None
        assert started == []
        assert bot.status == BotStatus.ERROR
        assert [n for n in notifications if n.title == "봇 자동 재시작 중단"] == []

    async def test_account_lookup_failure_does_not_restart(
        self, manager, account_service, eventbus, monkeypatch
    ):
        bot = await self._error_bot(manager, account_service, "b1", "acc-a")
        wake, entered = self._gate_cooldown(monkeypatch)
        started = self._started(eventbus)
        notifications = self._notifications(eventbus)
        await self._error(eventbus, "b1", "acc-a")
        task = manager._restart_tasks["b1"]
        await entered.acquire()

        async def _fail_get(account_id):  # noqa: ARG001
            raise RuntimeError("lookup failed")

        monkeypatch.setattr(account_service, "get", _fail_get)
        wake.set()
        await asyncio.wait([task], timeout=5.0)

        assert task.done() and not task.cancelled()
        assert task.exception() is None
        assert started == []
        assert bot.status == BotStatus.ERROR
        given_up = [n for n in notifications if n.title == "봇 자동 재시작 중단"]
        assert len(given_up) == 1
        assert given_up[0].level == "error"
        assert given_up[0].category == "bot"
        assert "b1" in given_up[0].message
        assert "acc-a" in given_up[0].message
        assert "lookup failed" not in given_up[0].message
        assert "RuntimeError" not in given_up[0].message

    async def test_active_account_restarts_and_other_account_kept(
        self, manager, account_service, eventbus, monkeypatch
    ):
        bot_a = await self._error_bot(manager, account_service, "b1", "acc-a")
        bot_b = await self._error_bot(manager, account_service, "b2", "acc-b")
        wake, entered = self._gate_cooldown(monkeypatch)
        started = self._started(eventbus)
        await self._error(eventbus, "b1", "acc-a")
        await self._error(eventbus, "b2", "acc-b")
        task_b = manager._restart_tasks["b2"]
        await entered.acquire()
        await entered.acquire()

        await account_service.suspend("acc-a", reason="test", suspended_by="test")
        assert manager._restart_tasks.get("b2") is task_b
        assert not task_b.done()

        wake.set()
        await asyncio.wait([task_b], timeout=5.0)

        assert [e.bot_id for e in started] == ["b2"]
        assert bot_b.status == BotStatus.RUNNING
        assert bot_a.status == BotStatus.ERROR
