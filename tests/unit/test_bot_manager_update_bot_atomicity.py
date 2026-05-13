"""BotManager.update_bot — budget 실패 시 원자적 롤백 검증.

Refs #1460 (split #1413/D): 같은 요청에서 runtime control / 기타 config 변경과
budget 변경이 함께 들어오고 budget 단계에서 실패가 발생할 때, runtime control
변경이 memory 또는 DB 어느 쪽에도 부분 commit 되지 않아야 한다.

- TreasuryNotConfiguredError (treasury_manager None / account 미등록)
- InsufficientFundsError (미할당 잔액 부족 / 회수 실패)
- ValueError (budget < 0)

모두 동일하게 atomic 롤백 대상이다. 정상 경로 (budget 성공) 는 새 config +
budget 양쪽 모두 commit 되어야 하며, 기존 거동을 깨지 않는다.
"""

from __future__ import annotations

import asyncio
import json

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
from ante.treasury.exceptions import (
    InsufficientFundsError,
    TreasuryNotConfiguredError,
)
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

    register 되지 않은 account_id 에 대해 ``KeyError`` 를 raise 한다.
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
    config = BotConfig(
        bot_id="bot1",
        strategy_id="s1",
        account_id=account_id,
        # 명시적 baseline runtime control 값 — 롤백 검증의 기준.
        max_restart_attempts=3,
        restart_cooldown_seconds=60,
        step_timeout_seconds=30,
        max_signals_per_step=50,
        interval_seconds=60,
    )
    bot = await manager.create_bot(config, _SimpleStrategy, ctx)
    bot.status = BotStatus.CREATED
    return "bot1"


async def _read_config_json(db: Database, bot_id: str) -> dict:
    row = await db.fetch_one("SELECT config_json FROM bots WHERE bot_id = ?", (bot_id,))
    assert row is not None
    return json.loads(row["config_json"])


class TestUpdateBotAtomicityOnBudgetFailure:
    """budget 실패 시 config 변경이 memory + DB 양쪽에서 롤백된다."""

    async def test_atomicity_on_treasury_not_configured_rolls_back_in_memory(
        self, eventbus, db, ctx
    ) -> None:
        """treasury_manager None → TreasuryNotConfiguredError.

        메모리 config 는 old 그대로.
        """
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_max_restart = bot.config.max_restart_attempts
        old_cooldown = bot.config.restart_cooldown_seconds

        with pytest.raises(TreasuryNotConfiguredError):
            await manager.update_bot(
                bot_id,
                max_restart_attempts=7,
                restart_cooldown_seconds=120,
                budget=100_000.0,
            )

        # 메모리 config 가 old_config 로 복원되어 있어야 한다.
        assert bot.config.max_restart_attempts == old_max_restart
        assert bot.config.restart_cooldown_seconds == old_cooldown

    async def test_atomicity_on_treasury_not_configured_rolls_back_in_db(
        self, eventbus, db, ctx
    ) -> None:
        """treasury_manager None → DB config_json 에도 변경이 commit 되지 않는다."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")

        old_json = await _read_config_json(db, bot_id)

        with pytest.raises(TreasuryNotConfiguredError):
            await manager.update_bot(
                bot_id,
                max_restart_attempts=7,
                restart_cooldown_seconds=120,
                budget=100_000.0,
            )

        # DB config_json 이 update 시도 이전과 동일해야 한다.
        new_json = await _read_config_json(db, bot_id)
        assert new_json == old_json

    async def test_atomicity_on_account_missing_rolls_back_memory_and_db(
        self, eventbus, db, ctx
    ) -> None:
        """account 에 Treasury 미등록 → memory + DB 모두 old_config 유지."""
        tm = _FakeTreasuryManager()
        # 'other' account 에만 등록.
        treasury = Treasury(db=db, eventbus=eventbus, account_id="other")
        await treasury.initialize()
        await treasury.set_account_balance(1_000_000)
        tm.register("other", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_max_restart = bot.config.max_restart_attempts
        old_step_timeout = bot.config.step_timeout_seconds
        old_json = await _read_config_json(db, bot_id)

        with pytest.raises(TreasuryNotConfiguredError):
            await manager.update_bot(
                bot_id,
                max_restart_attempts=9,
                step_timeout_seconds=60,
                budget=50_000.0,
            )

        assert bot.config.max_restart_attempts == old_max_restart
        assert bot.config.step_timeout_seconds == old_step_timeout
        new_json = await _read_config_json(db, bot_id)
        assert new_json == old_json

    async def test_atomicity_on_insufficient_funds_rolls_back_memory_and_db(
        self, eventbus, db, ctx
    ) -> None:
        """InsufficientFundsError 도 atomic 롤백 대상."""
        tm = _FakeTreasuryManager()
        treasury = Treasury(db=db, eventbus=eventbus, account_id="acc-test")
        await treasury.initialize()
        # 잔액 10_000 — 100_000 증액 요청은 부족하다.
        await treasury.set_account_balance(10_000)
        tm.register("acc-test", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_signals = bot.config.max_signals_per_step
        old_interval = bot.config.interval_seconds
        old_json = await _read_config_json(db, bot_id)

        with pytest.raises(InsufficientFundsError):
            await manager.update_bot(
                bot_id,
                max_signals_per_step=120,
                interval_seconds=90,
                budget=100_000.0,
            )

        assert bot.config.max_signals_per_step == old_signals
        assert bot.config.interval_seconds == old_interval
        new_json = await _read_config_json(db, bot_id)
        assert new_json == old_json

    async def test_atomicity_on_negative_budget_rolls_back_memory_and_db(
        self, eventbus, db, ctx
    ) -> None:
        """budget < 0 → Treasury.update_budget 이 ValueError. 동일하게 롤백."""
        tm = _FakeTreasuryManager()
        treasury = Treasury(db=db, eventbus=eventbus, account_id="acc-test")
        await treasury.initialize()
        await treasury.set_account_balance(1_000_000)
        tm.register("acc-test", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_max_restart = bot.config.max_restart_attempts
        old_json = await _read_config_json(db, bot_id)

        with pytest.raises(ValueError):
            await manager.update_bot(
                bot_id,
                max_restart_attempts=8,
                budget=-1.0,
            )

        assert bot.config.max_restart_attempts == old_max_restart
        new_json = await _read_config_json(db, bot_id)
        assert new_json == old_json


class TestUpdateBotAtomicityHappyPathRegression:
    """budget 성공 경로는 새 config + budget 모두 정상 반영 — 기존 거동 유지."""

    async def test_update_bot_atomicity_happy_path_commits_config_and_budget(
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
        bot = manager.get_bot(bot_id)
        assert bot is not None

        await manager.update_bot(
            bot_id,
            max_restart_attempts=8,
            restart_cooldown_seconds=120,
            interval_seconds=90,
            budget=200_000.0,
        )

        # 메모리 config 갱신.
        assert bot.config.max_restart_attempts == 8
        assert bot.config.restart_cooldown_seconds == 120
        assert bot.config.interval_seconds == 90

        # DB config_json 갱신 (runtime control 4개는 config_json 에 직접
        # 저장되지 않지만, interval_seconds 는 저장됨).
        row_json = await _read_config_json(db, bot_id)
        assert row_json["interval_seconds"] == 90

        # budget 정상 배정.
        budget = treasury.get_budget(bot_id)
        assert budget is not None
        assert budget.allocated == pytest.approx(200_000.0)

    async def test_update_bot_atomicity_no_budget_change_keeps_existing_behavior(
        self, eventbus, db, ctx
    ) -> None:
        """budget 미지정 (new_budget is None) → 기존 no-op 거동 유지."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(manager, ctx, account_id="acc-test")
        bot = manager.get_bot(bot_id)
        assert bot is not None

        # budget 미지정. treasury_manager None 이어도 raise 되지 않는다.
        await manager.update_bot(bot_id, max_restart_attempts=5)

        assert bot.config.max_restart_attempts == 5
