"""BotManager.update_bot — budget 배정 실패 매핑 검증.

Refs #1335: ``new_budget is not None`` 일 때 TreasuryManager 가 부재하거나
account 에 등록된 Treasury 가 없으면 ``TreasuryNotConfiguredError`` 가
raise 되어야 한다. ``new_budget is None`` 인 단순 update 경로는 기존과
동일하게 무영향이어야 한다.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.bot import BotConfig, BotManager
from ante.bot.config import BotStatus
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
from ante.treasury.exceptions import TreasuryNotConfiguredError
from ante.treasury.treasury import Treasury


class _FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class _FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1_000_000.0, "available": 500_000.0}


class _FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class _SimpleStrategy(Strategy):
    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class _FakeTreasuryManager:
    """경량 TreasuryManager 대체.

    register 되지 않은 account_id 에 대해 ``KeyError`` 를 raise 한다 (실제
    ``TreasuryManager.get`` 의 거동과 동일).
    """

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


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def ctx() -> StrategyContext:
    return StrategyContext(
        bot_id="bot1",
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolioView(),
        order_view=_FakeOrderView(),
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


async def _make_stopped_bot(
    manager: BotManager, ctx: StrategyContext, *, account_id: str
) -> str:
    """create + force CREATED 상태로 bot1 생성."""
    config = BotConfig(bot_id="bot1", strategy_id="s1", account_id=account_id)
    bot = await manager.create_bot(config, _SimpleStrategy, ctx)
    bot.status = BotStatus.CREATED
    return "bot1"


class TestUpdateBotBudgetTreasuryNotConfigured:
    """``new_budget is not None`` 인데 Treasury 가 없으면 명시적 예외."""

    async def test_update_bot_budget_raises_when_treasury_manager_none(
        self, eventbus, db, ctx
    ) -> None:
        """treasury_manager 자체가 주입되지 않은 경우 → TreasuryNotConfiguredError."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        with pytest.raises(TreasuryNotConfiguredError) as exc_info:
            await manager.update_bot(bot_id, budget=100_000.0)

        assert "treasury manager not configured" in str(exc_info.value)

    async def test_update_bot_budget_raises_when_account_treasury_missing(
        self, eventbus, db, ctx
    ) -> None:
        """treasury_manager 는 있지만 해당 account 에 Treasury 미등록 → 명시적 예외."""
        tm = _FakeTreasuryManager()
        # 'other' account 에만 등록 — 봇 account 'acc-test' 에는 미등록.
        treasury = Treasury(db=db, eventbus=eventbus, account_id="other")
        await treasury.initialize()
        await treasury.set_account_balance(1_000_000)
        tm.register("other", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        with pytest.raises(TreasuryNotConfiguredError) as exc_info:
            await manager.update_bot(bot_id, budget=100_000.0)

        assert "acc-test" in str(exc_info.value)


class TestUpdateBotNoBudgetSilentSkip:
    """``new_budget is None`` 경로는 기존 거동(no-op) 유지."""

    async def test_update_bot_no_budget_silent_skip_when_treasury_missing(
        self, eventbus, db, ctx
    ) -> None:
        """budget 이 없으면 treasury_manager 가 없어도 update 정상."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        # name 만 변경. budget 미지정 → TreasuryNotConfiguredError 가 발생하면 안 된다.
        bot = await manager.update_bot(bot_id, name="새 이름")
        assert bot.config.name == "새 이름"

    async def test_update_bot_no_budget_silent_skip_when_account_missing(
        self, eventbus, db, ctx
    ) -> None:
        """budget 미지정이고 account 에 Treasury 미등록이어도 update 정상."""
        tm = _FakeTreasuryManager()  # 비어 있음
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        bot = await manager.update_bot(bot_id, interval_seconds=120)
        assert bot.config.interval_seconds == 120


class TestUpdateBotBudgetSuccess:
    """정상 경로: Treasury 등록되어 있으면 budget 배정 성공."""

    async def test_update_bot_budget_success_with_treasury_registered(
        self, eventbus, db, ctx
    ) -> None:
        tm = _FakeTreasuryManager()
        treasury = Treasury(db=db, eventbus=eventbus, account_id="acc-test")
        await treasury.initialize()
        await treasury.set_account_balance(1_000_000)
        tm.register("acc-test", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        await manager.update_bot(bot_id, budget=200_000.0)

        budget = treasury.get_budget(bot_id)
        assert budget is not None
        assert budget.allocated == pytest.approx(200_000.0)


class TestDeleteBotHard:
    """Refs #1335 P2: ``hard=True`` 는 row 자체를 삭제한다."""

    async def test_delete_bot_default_soft_deletes_row(self, eventbus, db, ctx) -> None:
        """기본 ``hard=False`` 는 기존 soft delete 거동 유지."""
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        await manager.delete_bot(bot_id)

        # row 는 status='deleted' 로 남아 있어야 한다.
        row = await db.fetch_one(
            "SELECT bot_id, status FROM bots WHERE bot_id = ?", (bot_id,)
        )
        assert row is not None
        assert row["status"] == "deleted"

    async def test_delete_bot_hard_removes_row_from_db(self, eventbus, db, ctx) -> None:
        """``hard=True`` 는 ``DELETE FROM bots`` 로 row 자체를 제거한다.

        rollback 경로(POST /api/bots budget 실패) 가 사용하는 분기.
        soft delete 가 남기는 ``status='deleted'`` row 가 같은 bot_id
        재시도를 막는 문제를 해결한다.
        """
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        await manager.delete_bot(bot_id, hard=True)

        # row 가 DB 에서 완전히 사라져야 한다.
        row = await db.fetch_one(
            "SELECT bot_id, status FROM bots WHERE bot_id = ?", (bot_id,)
        )
        assert row is None

        # 인메모리 상태도 정리되어 있어야 한다.
        assert manager.get_bot(bot_id) is None

    async def test_delete_bot_hard_then_recreate_same_bot_id_succeeds(
        self, eventbus, db, ctx
    ) -> None:
        """hard delete 후 같은 ``bot_id`` 로 재생성 시 정상 row 유지.

        soft delete 였다면 재생성 후 row 가 ``status='deleted'`` 로 남아
        ``load_from_db()`` 에서 제외되었을 것. hard delete 가 이 문제를
        해결함을 검증한다.
        """
        manager = BotManager(eventbus=eventbus, db=db)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        await manager.delete_bot(bot_id, hard=True)

        # 같은 bot_id 로 재생성.
        config = BotConfig(bot_id=bot_id, strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, _SimpleStrategy, ctx)

        row = await db.fetch_one(
            "SELECT bot_id, status FROM bots WHERE bot_id = ?", (bot_id,)
        )
        assert row is not None
        # status 는 default ``created`` 로 시작해야 한다 (deleted 잔존 없음).
        assert row["status"] == "created"

        # load_from_db 도 새 봇을 정상 로드해야 한다 (status != 'deleted').
        loaded = await manager.load_from_db()
        assert loaded == 1
        assert manager.get_bot(bot_id) is not None
