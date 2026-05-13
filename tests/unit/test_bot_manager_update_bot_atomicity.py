"""``BotManager.update_bot`` 의 atomic rollback 동작 검증.

Refs #1460: budget 처리 단계에서 실패가 발생하면 runtime control 변경 (memory
+ DB) 이 ``old_config`` 로 rollback 되어야 한다. TreasuryManager 미주입,
account 미등록, ``treasury.update_budget`` 내부 예외, ``asyncio.CancelledError``
(요청 취소) 모두 같은 rollback 경로를 탄다. 또한 rollback 중 DB save 가 다시
실패해도 원래 budget 예외가 보존되고, in-memory 상태는 일관되게 rollback
유지된다.
"""

from __future__ import annotations

import asyncio
import logging

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

# ----------------------------------------------------------------------------
# Fakes / fixtures
# ----------------------------------------------------------------------------


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

    ``register`` 되지 않은 account_id 에 대해 ``KeyError`` 를 raise 한다 (실제
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


class _RaisingTreasury:
    """``update_budget`` 호출 시 명시된 예외를 raise 하는 Treasury 스텁."""

    def __init__(self, exc: BaseException) -> None:
        self._exc = exc
        self.update_budget_calls: list[tuple[str, float]] = []

    async def update_budget(self, bot_id: str, target_amount: float) -> None:
        self.update_budget_calls.append((bot_id, target_amount))
        raise self._exc


class _RaisingTreasuryManager:
    """단일 account 에 대해 ``_RaisingTreasury`` 를 돌려주는 매니저."""

    def __init__(self, account_id: str, treasury: _RaisingTreasury) -> None:
        self._account_id = account_id
        self._treasury = treasury

    def get(self, account_id: str):
        if account_id != self._account_id:
            raise KeyError(f"Treasury not found: account_id={account_id}")
        return self._treasury

    def list_all(self):
        return [self._treasury]


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
    manager: BotManager,
    ctx: StrategyContext,
    *,
    account_id: str,
    interval_seconds: int = 60,
) -> str:
    """create + force STOPPED 상태로 ``bot1`` 생성."""
    config = BotConfig(
        bot_id="bot1",
        strategy_id="s1",
        account_id=account_id,
        interval_seconds=interval_seconds,
    )
    bot = await manager.create_bot(config, _SimpleStrategy, ctx)
    bot.status = BotStatus.STOPPED
    return "bot1"


async def _read_db_interval(db: Database, bot_id: str) -> int:
    """DB ``config_json`` 에서 ``interval_seconds`` 를 읽는다."""
    import json

    row = await db.fetch_one("SELECT config_json FROM bots WHERE bot_id = ?", (bot_id,))
    assert row is not None
    payload = json.loads(row["config_json"])
    return int(payload["interval_seconds"])


# ----------------------------------------------------------------------------
# Tests
# ----------------------------------------------------------------------------


class TestUpdateBotBudgetRollback:
    """Refs #1460: budget 실패 시 runtime control 변경 atomic rollback."""

    async def test_update_bot_budget_failure_rolls_back_runtime_controls_memory(
        self, eventbus, db, ctx
    ) -> None:
        """memory(in-process ``bot.config``) 가 ``old_config`` 로 rollback 된다."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_config = bot.config

        with pytest.raises(TreasuryNotConfiguredError):
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        # memory 상태는 old_config 로 rollback 되어 있어야 한다 (identity 보장).
        assert bot.config is old_config
        assert bot.config.interval_seconds == 60

    async def test_update_bot_budget_failure_rolls_back_runtime_controls_db(
        self, eventbus, db, ctx
    ) -> None:
        """DB ``config_json`` 도 ``old_config`` 로 rollback 된다."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        with pytest.raises(TreasuryNotConfiguredError):
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        # DB 도 60 으로 복구되어 있어야 한다 (rollback save 적용).
        assert await _read_db_interval(db, bot_id) == 60

    async def test_update_bot_budget_failure_treasury_not_configured(
        self, eventbus, db, ctx
    ) -> None:
        """``TreasuryManager`` 자체가 None 인 경우에도 rollback 수행."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        with pytest.raises(TreasuryNotConfiguredError) as exc_info:
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)
        assert "treasury manager not configured" in str(exc_info.value)

        bot = manager.get_bot(bot_id)
        assert bot is not None
        assert bot.config.interval_seconds == 60
        assert await _read_db_interval(db, bot_id) == 60

    async def test_update_bot_budget_failure_treasury_account_missing(
        self, eventbus, db, ctx
    ) -> None:
        """``_treasury_manager.get(...)`` 가 KeyError → rollback + 명시적 예외."""
        tm = _FakeTreasuryManager()
        # 봇 account 'acc-test' 에는 미등록.
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        with pytest.raises(TreasuryNotConfiguredError) as exc_info:
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)
        assert "acc-test" in str(exc_info.value)

        bot = manager.get_bot(bot_id)
        assert bot is not None
        assert bot.config.interval_seconds == 60
        assert await _read_db_interval(db, bot_id) == 60

    async def test_update_bot_budget_failure_inside_update_budget(
        self, eventbus, db, ctx
    ) -> None:
        """``treasury.update_budget`` 내부 raise → rollback + 같은 예외 propagate."""

        class _BoomError(RuntimeError):
            pass

        raising_treasury = _RaisingTreasury(_BoomError("boom"))
        tm = _RaisingTreasuryManager("acc-test", raising_treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        with pytest.raises(_BoomError):
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        # update_budget 은 호출되었어야 한다 (treasury 까지 진입 후 raise).
        assert raising_treasury.update_budget_calls == [(bot_id, 100_000.0)]

        bot = manager.get_bot(bot_id)
        assert bot is not None
        assert bot.config.interval_seconds == 60
        assert await _read_db_interval(db, bot_id) == 60

    async def test_update_bot_budget_failure_cancellation(
        self, eventbus, db, ctx
    ) -> None:
        """``asyncio.CancelledError`` (요청 취소) 도 rollback 범위에 포함된다.

        CancelledError 는 ``BaseException`` 하위지만 ``Exception`` 하위가
        아니므로, ``except (Exception, asyncio.CancelledError)`` 로 명시 포착
        되어야 한다. rollback 후 CancelledError 가 그대로 propagate 한다.
        """
        raising_treasury = _RaisingTreasury(asyncio.CancelledError())
        tm = _RaisingTreasuryManager("acc-test", raising_treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        with pytest.raises(asyncio.CancelledError):
            await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        bot = manager.get_bot(bot_id)
        assert bot is not None
        # memory rollback 확인.
        assert bot.config.interval_seconds == 60
        # DB rollback 확인 (CancelledError 도 rollback save 가 동작해야 함).
        assert await _read_db_interval(db, bot_id) == 60

    async def test_update_bot_budget_failure_rollback_db_save_also_fails(
        self, eventbus, db, ctx, monkeypatch, caplog
    ) -> None:
        """nested rollback failure: 원래 budget 예외 보존 + memory rollback 적용.

        ``_save_bot_config`` 를 monkeypatch 해서 첫 호출(new_config 저장) 은
        성공, 두 번째 호출(rollback save) 에서 raise 한다. 결과:

        - 원래 budget 예외(``TreasuryNotConfiguredError``) 가 propagate.
        - memory(``bot.config``) 는 ``old_config`` 로 rollback 적용.
        - ``logger.exception`` 호출 흔적이 caplog 에 남는다.
        """
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )
        bot = manager.get_bot(bot_id)
        assert bot is not None
        old_config = bot.config

        original_save = manager._save_bot_config
        call_count = {"n": 0}

        async def flaky_save(config):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # 첫 호출: new_config commit — 정상 동작.
                return await original_save(config)
            # 두 번째 호출: rollback save — 의도적으로 raise.
            raise RuntimeError("rollback save boom")

        # monkeypatch 적용 위치: 이 줄 (`manager._save_bot_config = flaky_save`
        # 를 monkeypatch.setattr 로 대체). 이후 호출되는 update_bot 안에서
        # 1) new_config save 성공, 2) budget 처리 단계에서 TreasuryNotConfigured
        # raise → except 블록 진입, 3) memory rollback (bot.config = old_config)
        # 적용, 4) rollback DB save 호출 → RuntimeError raise → logger.exception
        # 만 남기고 원래 budget 예외 propagate.
        monkeypatch.setattr(manager, "_save_bot_config", flaky_save)

        with caplog.at_level(logging.ERROR, logger="ante.bot.manager"):
            with pytest.raises(TreasuryNotConfiguredError):
                await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        # _save_bot_config 가 정확히 두 번 호출되었는지 검증 (new_config + rollback).
        assert call_count["n"] == 2

        # memory rollback 보증 검증 위치: 아래 두 assertion.
        # bot.config 가 old_config 와 identity 일치해야 한다 (단순 대입 rollback).
        assert bot.config is old_config
        assert bot.config.interval_seconds == 60

        # logger.exception 흔적 확인.
        assert any(
            "rollback DB save failed" in record.message
            and record.levelno >= logging.ERROR
            for record in caplog.records
        )

    async def test_update_bot_budget_success_keeps_runtime_changes(
        self, eventbus, db, ctx
    ) -> None:
        """회귀 보호: budget 성공 경로는 runtime control 변경을 그대로 유지한다."""
        tm = _FakeTreasuryManager()
        treasury = Treasury(db=db, eventbus=eventbus, account_id="acc-test")
        await treasury.initialize()
        await treasury.set_account_balance(1_000_000)
        tm.register("acc-test", treasury)

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=tm)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        bot = await manager.update_bot(bot_id, interval_seconds=120, budget=200_000.0)

        # runtime control 변경 유지.
        assert bot.config.interval_seconds == 120
        assert await _read_db_interval(db, bot_id) == 120
        # budget 도 정상 배정.
        budget = treasury.get_budget(bot_id)
        assert budget is not None
        assert budget.allocated == pytest.approx(200_000.0)

    async def test_update_bot_no_budget_keeps_runtime_changes(
        self, eventbus, db, ctx
    ) -> None:
        """회귀 보호: ``budget`` 미지정 경로는 기존과 동일하게 변경 유지."""
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )

        bot = await manager.update_bot(bot_id, interval_seconds=180)

        assert bot.config.interval_seconds == 180
        assert await _read_db_interval(db, bot_id) == 180
