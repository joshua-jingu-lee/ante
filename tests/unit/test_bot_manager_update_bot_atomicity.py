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

    async def test_update_bot_budget_failure_skips_rollback_on_concurrent_update(
        self, eventbus, db, ctx, monkeypatch, caplog
    ) -> None:
        """Refs #1460: concurrent update race 시 rollback 스킵.

        시나리오:
        1. update_bot(A) 가 진입하여 new_config(A) 를 만들고 ``bot.config`` 에
           대입 + DB commit 까지 성공.
        2. ``treasury.update_budget`` await 진입.
        3. 같은 봇에 대해 update_bot(B) 가 끼어들어 ``bot.config`` 를
           third_config(B) 로 교체 (성공 가정).
        4. ``treasury.update_budget`` 이 raise → A 의 rollback 경로 진입.
        5. ``bot.config is new_config(A)`` 가 False (지금은 third_config(B)) →
           rollback 스킵, DB save 도 추가로 호출되지 않음.
        6. 원래 budget 예외만 propagate, ``bot.config`` 는 third_config(B) 유지.
        7. ``_save_bot_config`` 는 A 의 new_config commit 1회만 수행한다 (즉
           ``call_count == 1``) — rollback 의 두 번째 save 가 일어나지 않음을
           보증.
        """

        # _save_bot_config call count 추적: monkeypatch 로 wrapping.
        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )
        bot = manager.get_bot(bot_id)
        assert bot is not None

        # 같은 bot_id 에 대한 다른 update 가 만들어낸 ``third_config`` 시뮬레이션.
        third_config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            account_id="acc-test",
            interval_seconds=240,
            name="concurrent-renamed",
        )

        # _save_bot_config 호출 횟수 추적.
        original_save = manager._save_bot_config
        save_call_count = {"n": 0}

        async def counting_save(config):
            save_call_count["n"] += 1
            return await original_save(config)

        monkeypatch.setattr(manager, "_save_bot_config", counting_save)

        # race 시뮬레이션: treasury.update_budget 안에서 bot.config 를
        # third_config 로 교체한 직후 raise.
        class _BoomError(RuntimeError):
            pass

        class _RaceSimulatingTreasury:
            def __init__(self, bot_ref, replacement: BotConfig) -> None:
                self._bot_ref = bot_ref
                self._replacement = replacement
                self.update_budget_calls: list[tuple[str, float]] = []

            async def update_budget(
                self, called_bot_id: str, target_amount: float
            ) -> None:
                self.update_budget_calls.append((called_bot_id, target_amount))
                # await 중 끼어든 다른 update_bot 이 bot.config 를 교체한 상황을
                # 모사 (실제 코드 경로에선 다른 task 가 했을 일이지만, 단위
                # 테스트에선 side_effect 안에서 직접 변조).
                self._bot_ref.config = self._replacement
                raise _BoomError("boom-after-race")

        race_treasury = _RaceSimulatingTreasury(bot, third_config)
        tm = _RaisingTreasuryManager("acc-test", race_treasury)  # type: ignore[arg-type]
        manager._treasury_manager = tm  # type: ignore[assignment]

        with caplog.at_level(logging.WARNING, logger="ante.bot.manager"):
            with pytest.raises(_BoomError):
                await manager.update_bot(bot_id, interval_seconds=120, budget=100_000.0)

        # update_budget 은 진입했어야 한다.
        assert race_treasury.update_budget_calls == [(bot_id, 100_000.0)]

        # 핵심 보증: _save_bot_config 가 정확히 1회만 호출됨 (new_config commit
        # 만 수행, rollback save 는 스킵). 만약 conditional rollback 이 빠지면
        # call_count == 2 가 되어야 한다.
        assert save_call_count["n"] == 1

        # bot.config 는 third_config(B) 그대로 유지되어야 한다 (덮어쓰지 않음).
        assert bot.config is third_config
        assert bot.config.name == "concurrent-renamed"
        assert bot.config.interval_seconds == 240

        # "rollback skipped" warning 흔적 확인.
        assert any(
            "rollback skipped" in record.message and record.levelno == logging.WARNING
            for record in caplog.records
        )

    async def test_update_bot_concurrent_requests_serialized_by_lock(
        self, eventbus, db, ctx
    ) -> None:
        """Refs #1460 (attempt 3): per-bot asyncio.Lock 로 update_bot 직렬화.

        시나리오:
        1. 같은 봇에 대해 update_bot(A) 와 update_bot(B) 를 ``asyncio.gather``
           로 동시 호출한다.
        2. A 는 budget 처리에서 ``await asyncio.sleep(0.05)`` 후 raise — A 가
           먼저 진입했다면 lock 을 0.05 초 이상 잡고 있는다.
        3. B 는 정상 성공 (treasury.update_budget no-op).
        4. lock 으로 인해 두 요청은 직렬화된다. 어느 쪽이 먼저 들어와도 다른
           쪽의 ``new_config`` 가 동시에 ``bot.config`` 에 노출되어 섞이는 일은
           없다. A 가 raise 한 변경은 rollback 으로 사라지고, B 의 변경만
           최종 상태에 남는다 (또는 B 가 먼저 끝나고 A 가 뒤이어 진입한
           경우엔 A 는 raise 로 변경 없음).
        5. 핵심 보증: 어느 직렬 순서든 ``bot.config.name == "bot-B"`` (B 의
           변경) 이고, A 의 변경 (``interval_seconds == 3000``) 은 절대로 남지
           않는다.
        """

        manager = BotManager(eventbus=eventbus, db=db, treasury_manager=None)
        await manager.initialize()
        bot_id = await _make_stopped_bot(
            manager, ctx, account_id="acc-test", interval_seconds=60
        )
        bot = manager.get_bot(bot_id)
        assert bot is not None

        # A 는 update_budget 안에서 sleep + raise. B 는 같은 treasury 객체를
        # 쓰면 안 되므로(둘 다 raise 되어 버림) 두 요청의 budget 처리 분기를
        # 다르게 만들기 위해 A 만 budget 을 지정한다. B 는 budget=None 으로
        # treasury 경로를 타지 않고 runtime control 변경만 수행한다.
        class _SleepThenRaiseTreasury:
            def __init__(self) -> None:
                self.update_budget_calls: list[tuple[str, float]] = []

            async def update_budget(
                self, called_bot_id: str, target_amount: float
            ) -> None:
                self.update_budget_calls.append((called_bot_id, target_amount))
                # lock 을 충분히 길게 잡고 있도록 대기 후 raise — 동시 호출된
                # B 가 끼어들 시간을 확보한다.
                await asyncio.sleep(0.05)
                raise RuntimeError("A budget boom")

        sleep_treasury = _SleepThenRaiseTreasury()
        tm = _RaisingTreasuryManager("acc-test", sleep_treasury)  # type: ignore[arg-type]
        manager._treasury_manager = tm  # type: ignore[assignment]

        # A: interval=3000 + budget 실패 → rollback 으로 변경 소실.
        # B: name="bot-B" + budget=None → 정상 성공.
        async def call_a():
            try:
                await manager.update_bot(
                    bot_id, interval_seconds=3000, budget=100_000.0
                )
            except RuntimeError:
                # 기대된 raise — 결과를 무시하고 직렬화 결과만 본다.
                return "A-raised"
            return "A-ok"

        async def call_b():
            await manager.update_bot(bot_id, name="bot-B")
            return "B-ok"

        results = await asyncio.gather(call_a(), call_b())

        # A 는 항상 raise, B 는 항상 성공.
        assert results[0] == "A-raised"
        assert results[1] == "B-ok"

        # 직렬화 결과 보증:
        # - A 의 interval_seconds=3000 변경은 어느 직렬 순서에서도 최종
        #   상태에 절대 남지 않는다 (A 가 raise → rollback 으로 소실).
        # - B 의 name="bot-B" 변경은 항상 최종 상태에 남는다.
        # - A 가 먼저 직렬화 → B 가 뒤이어 진입한 경우: A rollback 후
        #   interval_seconds=60, 그 다음 B 가 name="bot-B" 만 변경. 최종
        #   ``bot.config.interval_seconds == 60`` and ``bot.config.name ==
        #   "bot-B"``.
        # - B 가 먼저 직렬화 → A 가 뒤이어 진입한 경우: B 가 name="bot-B"
        #   로 변경. 그 다음 A 가 interval_seconds=3000 로 변경 시도 후 raise
        #   → rollback. rollback 의 old_config 는 이 시점 ``bot.config`` (B
        #   가 만든 config) 이므로 name="bot-B" 가 보존된 채 A 변경만 사라짐.
        #   최종 ``bot.config.interval_seconds == 60`` and ``bot.config.name
        #   == "bot-B"``.
        assert bot.config.interval_seconds == 60
        assert bot.config.name == "bot-B"

        # DB 도 동일하게 직렬화 결과를 반영해야 한다.
        assert await _read_db_interval(db, bot_id) == 60

        # treasury.update_budget 은 정확히 1회 (A 의 호출 1회) 만 일어났다.
        assert sleep_treasury.update_budget_calls == [(bot_id, 100_000.0)]
