"""전략 배정·교체가 봇이 실제로 실행하는 전략 코드를 바꾸는지 (#2838).

실제 ``StrategyRegistry`` 에 등록한 전략 파일 둘(A는 ``AAA``, B는 ``BBB`` 를
산다)과 실제 ``BotManager``(스냅샷 포함)로, 전략 id를 바꾸는 세 경로
(``assign_strategy``·``change_strategy``·``update_bot``) 뒤 다음 주기의 주문이
어느 전략의 것인지, 준비·저장이 실패하면 봇이 하나도 바뀌지 않는지 본다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from ante.account.models import Account, AccountStatus
from ante.bot import BotConfig, BotManager, BotStatus
from ante.bot.exceptions import (
    BotError,
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotStateConflict,
)
from ante.bot.signal_key import SignalKeyManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import BotStartedEvent, OrderRequestEvent
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    StrategyContext,
    StrategyMeta,
)
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyLoadError,
    StrategyNotFoundError,
)
from ante.strategy.loader import StrategyLoader
from ante.strategy.registry import StrategyRegistry
from ante.strategy.snapshot import StrategySnapshot

_SOURCE = """
from ante.strategy import Signal, Strategy, StrategyMeta


class {cls}(Strategy):
    meta = StrategyMeta(
        name="{name}",
        version="1.0.0",
        description="switch probe",
        exchange="{exchange}",
        accepts_external_signals={accepts},
    )
    starts = 0
    stops = 0

    def on_start(self):
        type(self).starts += 1

    def on_stop(self):
        type(self).stops += 1

    async def on_step(self, context):
        return [Signal(symbol="{symbol}", side="buy", quantity=1)]
"""

_TWO_CLASSES = """
from ante.strategy import Strategy, StrategyMeta


class First(Strategy):
    meta = StrategyMeta(name="first", version="1.0.0", description="x")

    async def on_step(self, context):
        return []


class Second(Strategy):
    meta = StrategyMeta(name="second", version="1.0.0", description="x")

    async def on_step(self, context):
        return []
"""


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
    await svc.create(
        Account(
            account_id="acc-test",
            name="활성계좌",
            exchange="KRX",
            currency="KRW",
            broker_type="test",
            status=AccountStatus.ACTIVE,
            credentials={"app_key": "test", "app_secret": "test"},
        )
    )
    return svc


@pytest.fixture
async def signal_keys(db):
    keys = SignalKeyManager(db)
    await keys.initialize()
    return keys


@pytest.fixture
def snapshot_root(tmp_path):
    return tmp_path / "strategies"


@pytest.fixture
async def manager(eventbus, db, account_service, signal_keys, snapshot_root):
    m = BotManager(
        eventbus=eventbus,
        db=db,
        account_service=account_service,
        snapshot=StrategySnapshot(snapshot_root),
        signal_key_manager=signal_keys,
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


@pytest.fixture
def orders(eventbus):
    seen: list[OrderRequestEvent] = []
    eventbus.subscribe(OrderRequestEvent, seen.append, priority=1000)
    return seen


async def _register(db, tmp_path, source: str, name: str) -> str:
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    filepath = src_dir / f"{name}.py"
    filepath.write_text(source, encoding="utf-8")
    registry = StrategyRegistry(db)
    await registry.initialize()
    record = await registry.register(
        filepath, StrategyMeta(name=name, version="1.0.0", description="probe")
    )
    return record.strategy_id


def _probe_source(
    cls: str, name: str, symbol: str, *, exchange="KRX", accepts=False
) -> str:
    return _SOURCE.format(
        cls=cls, name=name, symbol=symbol, exchange=exchange, accepts=accepts
    )


@pytest.fixture
async def strategies(db, tmp_path):
    a = await _register(db, tmp_path, _probe_source("ProbeA", "strat_a", "AAA"), "a")
    b = await _register(db, tmp_path, _probe_source("ProbeB", "strat_b", "BBB"), "b")
    return a, b


async def _create(manager, ctx, db, strategy_id: str):
    record = await StrategyRegistry(db).get(strategy_id)
    source = Path(record.filepath)
    config = BotConfig(
        bot_id="bot1",
        strategy_id=strategy_id,
        account_id="acc-test",
        interval_seconds=999,
    )
    return await manager.create_bot(
        config, StrategyLoader.load(source), ctx, source_path=source
    )


async def _next_order(orders: list, count: int) -> OrderRequestEvent:
    async def _wait() -> None:
        while len(orders) <= count:
            await asyncio.sleep(0.01)

    await asyncio.wait_for(_wait(), timeout=5.0)
    return orders[count]


async def _db_strategy_ids(db) -> tuple[str, str]:
    row = await db.fetch_one(
        "SELECT strategy_id, config_json FROM bots WHERE bot_id = 'bot1'"
    )
    return row["strategy_id"], json.loads(row["config_json"])["strategy_id"]


def _snapshot_files(snapshot_root: Path) -> list[str]:
    return sorted(p.name for p in (snapshot_root / ".running" / "bot1").glob("*.py"))


async def _running_on_a(manager, ctx, db, orders, strategy_id: str):
    bot = await _create(manager, ctx, db, strategy_id)
    await manager.start_bot("bot1")
    assert (await _next_order(orders, 0)).symbol == "AAA"
    return bot


class TestSwitchRunsNewStrategy:
    async def test_assign_running_bot_runs_new_strategy(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        old = bot.strategy

        await manager.assign_strategy("bot1", b)

        order = await _next_order(orders, 1)
        assert order.symbol == "BBB"
        assert order.strategy_id == b
        assert bot.status == BotStatus.RUNNING
        assert type(bot.strategy).meta.name == "strat_b"
        assert type(old).stops == 1
        assert type(bot.strategy).starts == 1
        assert await _db_strategy_ids(db) == (b, b)

    async def test_assign_stopped_bot_then_start_runs_new_strategy(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        await manager.assign_strategy("bot1", b)
        await manager.start_bot("bot1")

        assert (await _next_order(orders, 1)).symbol == "BBB"

    async def test_assign_created_bot_then_start_runs_new_strategy(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        await _create(manager, ctx, db, a)

        await manager.assign_strategy("bot1", b)
        await manager.start_bot("bot1")

        assert (await _next_order(orders, 0)).symbol == "BBB"

    @pytest.mark.parametrize("restart", ["start_bot", "resume_bot"])
    async def test_change_strategy_then_restart_runs_new_strategy(
        self, manager, ctx, db, orders, strategies, restart
    ):
        a, b = strategies
        await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        await manager.change_strategy("bot1", b)
        await getattr(manager, restart)("bot1")

        assert (await _next_order(orders, 1)).symbol == "BBB"

    async def test_update_bot_strategy_then_start_runs_new_strategy(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        await manager.update_bot("bot1", strategy_id=b)
        await manager.start_bot("bot1")

        assert (await _next_order(orders, 1)).symbol == "BBB"
        assert await _db_strategy_ids(db) == (b, b)

    async def test_rotate_after_stopped_switch_judges_new_strategy(
        self, manager, ctx, db, orders, tmp_path, strategies
    ):
        accepts = await _register(
            db,
            tmp_path,
            _probe_source("ProbeS", "strat_s", "SSS", accepts=True),
            "s",
        )
        a, b = strategies
        bot = await _create(manager, ctx, db, accepts)
        await manager.start_bot("bot1")
        await _next_order(orders, 0)
        await manager.stop_bot("bot1")
        assert bot.strategy is not None

        await manager.change_strategy("bot1", b)

        with pytest.raises(BotNotAcceptingSignals):
            await manager.rotate_signal_key("bot1")


class TestBotStartRefusesUnboundStrategy:
    async def test_config_only_change_refuses_start(
        self, manager, ctx, db, eventbus, strategies
    ):
        a, b = strategies
        bot = await _create(manager, ctx, db, a)
        started: list[BotStartedEvent] = []
        eventbus.subscribe(BotStartedEvent, started.append)
        bot.config.strategy_id = b

        with pytest.raises(BotError):
            await bot.start()

        assert bot.status == BotStatus.CREATED
        assert bot.strategy is None
        assert started == []

    async def test_rebind_refused_while_running(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        cls_b = StrategyLoader.load(Path((await StrategyRegistry(db).get(b)).filepath))

        with pytest.raises(BotError):
            bot.rebind_strategy(b, cls_b)

        assert type(bot.strategy).meta.name == "strat_a"
        assert bot.status == BotStatus.RUNNING


async def _unregistered(db, tmp_path) -> str:
    return "nope_v1.0.0"


async def _missing_file(db, tmp_path) -> str:
    sid = await _register(db, tmp_path, _probe_source("ProbeM", "m", "MMM"), "m")
    (tmp_path / "src" / "m.py").unlink()
    return sid


async def _syntax_error(db, tmp_path) -> str:
    return await _register(db, tmp_path, "def broken(:\n", "broken")


async def _two_classes(db, tmp_path) -> str:
    return await _register(db, tmp_path, _TWO_CLASSES, "two")


async def _wrong_exchange(db, tmp_path) -> str:
    source = _probe_source("ProbeN", "n", "NNN", exchange="NASDAQ")
    return await _register(db, tmp_path, source, "nasdaq")


_FAILURES = {
    "unregistered": (_unregistered, StrategyNotFoundError),
    "missing_file": (_missing_file, StrategyLoadError),
    "syntax_error": (_syntax_error, StrategyLoadError),
    "two_classes": (_two_classes, StrategyLoadError),
    "wrong_exchange": (_wrong_exchange, IncompatibleExchangeError),
}


class TestFailedPreparationChangesNothing:
    @pytest.mark.parametrize("case", sorted(_FAILURES))
    async def test_assign_running_bot_keeps_old_strategy(
        self, manager, ctx, db, orders, tmp_path, snapshot_root, strategies, case
    ):
        a, b = strategies
        make, error = _FAILURES[case]
        target = await make(db, tmp_path)
        bot = await _running_on_a(manager, ctx, db, orders, a)
        generation = bot._generation
        before = _snapshot_files(snapshot_root)

        with pytest.raises(error):
            await manager.assign_strategy("bot1", target)

        assert bot.status == BotStatus.RUNNING
        assert bot._generation == generation
        assert bot.config.strategy_id == a
        assert await _db_strategy_ids(db) == (a, a)
        assert _snapshot_files(snapshot_root) == before
        await manager.stop_bot("bot1")
        await manager.start_bot("bot1")
        assert (await _next_order(orders, 1)).symbol == "AAA"

    @pytest.mark.parametrize("path", ["change_strategy", "update_bot"])
    async def test_stopped_paths_keep_old_strategy(
        self, manager, ctx, db, orders, tmp_path, strategies, path
    ):
        a, b = strategies
        target = await _wrong_exchange(db, tmp_path)
        await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        with pytest.raises(IncompatibleExchangeError):
            if path == "change_strategy":
                await manager.change_strategy("bot1", target)
            else:
                await manager.update_bot("bot1", strategy_id=target)

        assert manager.get_bot("bot1").config.strategy_id == a
        assert await _db_strategy_ids(db) == (a, a)
        await manager.start_bot("bot1")
        assert (await _next_order(orders, 1)).symbol == "AAA"


class TestFailureAfterStopRollsBack:
    async def test_assign_save_failure_restores_old_strategy_and_stays_stopped(
        self, manager, ctx, db, orders, strategies, monkeypatch
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)

        async def _fail(config):
            raise RuntimeError("db down")

        monkeypatch.setattr(manager, "_save_bot_config", _fail)
        with pytest.raises(RuntimeError, match="db down"):
            await manager.assign_strategy("bot1", b)
        monkeypatch.undo()

        assert bot.status == BotStatus.STOPPED
        assert bot.config.strategy_id == a
        assert await _db_strategy_ids(db) == (a, a)
        await manager.start_bot("bot1")
        assert (await _next_order(orders, 1)).symbol == "AAA"

    async def test_update_bot_budget_failure_restores_old_strategy(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        with pytest.raises(Exception, match="treasury"):
            await manager.update_bot("bot1", strategy_id=b, budget=1000)

        assert bot.config.strategy_id == a
        assert await _db_strategy_ids(db) == (a, a)
        await manager.start_bot("bot1")
        assert (await _next_order(orders, 1)).symbol == "AAA"

    async def test_update_bot_save_failure_restores_old_strategy(
        self, manager, ctx, db, orders, strategies, monkeypatch
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        async def _fail(config):
            raise RuntimeError("db down")

        monkeypatch.setattr(manager, "_save_bot_config", _fail)
        with pytest.raises(RuntimeError, match="db down"):
            await manager.update_bot("bot1", strategy_id=b)
        monkeypatch.undo()

        assert bot.config.strategy_id == a
        assert await _db_strategy_ids(db) == (a, a)
        await manager.start_bot("bot1")
        assert (await _next_order(orders, 1)).symbol == "AAA"


class _RecordingRules:
    def __init__(self) -> None:
        self.removed: list[str] = []
        self.loaded: list[str] = []

    def remove_strategy_rules(self, strategy_id: str) -> None:
        self.removed.append(strategy_id)

    def load_strategy_rules_from_config(self, strategy_id: str, configs) -> None:
        self.loaded.append(strategy_id)


class TestAssignWhenOldOnStopFails:
    """옛 전략의 on_stop 이 실패하면 배정은 중단되고 봇은 정지한다 (#2697)."""

    async def test_assign_stops_bot_removes_old_rules_and_raises(
        self, manager, ctx, db, orders, strategies, tmp_path
    ):
        _, b = strategies
        failing_source = _probe_source("ProbeF", "strat_f", "AAA").replace(
            "        type(self).stops += 1\n",
            "        type(self).stops += 1\n"
            '        raise RuntimeError("on_stop failed")\n',
        )
        f = await _register(db, tmp_path, failing_source, "f")
        rules = _RecordingRules()
        manager._rule_engine = rules
        bot = await _running_on_a(manager, ctx, db, orders, f)
        old = bot.strategy

        with pytest.raises(RuntimeError) as exc:
            await manager.assign_strategy("bot1", b)

        assert type(exc.value) is RuntimeError
        assert str(exc.value) == "on_stop failed"
        assert type(old).stops == 1
        assert bot.status == BotStatus.STOPPED
        _assert_bound(bot, f, "strat_f")
        assert bot.strategy is old
        assert rules.removed == [f]
        assert await _db_strategy_ids(db) == (f, f)


def _assert_bound(bot, strategy_id: str, name: str) -> None:
    assert bot.config.strategy_id == strategy_id
    assert bot._bound_strategy_id == strategy_id
    assert type(bot.strategy).meta.name == name


class TestRollbackRacingStart:
    """되돌리는 사이에 봇이 시작되면 되돌리지 않고 원래 오류를 올린다."""

    async def test_assign_save_failure_while_started(
        self, manager, ctx, db, orders, strategies, monkeypatch
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)

        async def _start_then_fail(config):
            await manager.start_bot("bot1")
            raise RuntimeError("db down")

        monkeypatch.setattr(manager, "_save_bot_config", _start_then_fail)
        with pytest.raises(RuntimeError, match="db down"):
            await manager.assign_strategy("bot1", b)
        monkeypatch.undo()

        assert bot.status == BotStatus.RUNNING
        _assert_bound(bot, b, "strat_b")
        assert await _db_strategy_ids(db) == (a, a)

    async def test_update_save_failure_while_started(
        self, manager, ctx, db, orders, strategies, monkeypatch
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        async def _start_then_fail(config):
            await manager.start_bot("bot1")
            raise RuntimeError("db down")

        monkeypatch.setattr(manager, "_save_bot_config", _start_then_fail)
        with pytest.raises(RuntimeError, match="db down"):
            await manager.update_bot("bot1", strategy_id=b)
        monkeypatch.undo()

        assert bot.status == BotStatus.RUNNING
        _assert_bound(bot, b, "strat_b")
        assert await _db_strategy_ids(db) == (a, a)

    async def test_update_budget_failure_while_started(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")

        class _StartingTreasury:
            def get(self, account_id):
                return self

            async def update_budget(self, bot_id, amount):
                await manager.start_bot(bot_id)
                raise RuntimeError("treasury down")

        manager._treasury_manager = _StartingTreasury()
        with pytest.raises(RuntimeError, match="treasury down"):
            await manager.update_bot("bot1", strategy_id=b, budget=1000)

        assert bot.status == BotStatus.RUNNING
        _assert_bound(bot, b, "strat_b")
        assert await _db_strategy_ids(db) == (b, b)


class TestStoppingRefusesSwitch:
    @pytest.mark.parametrize("path", ["assign_strategy", "change_strategy"])
    async def test_stopping_bot_refuses_switch(
        self, manager, ctx, db, orders, strategies, path
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")
        bot.status = BotStatus.STOPPING

        with pytest.raises(BotStateConflict):
            await getattr(manager, path)("bot1", b)

        assert bot.config.strategy_id == a
        assert bot._bound_strategy_id == a
        assert type(bot.strategy).meta.name == "strat_a"
        assert await _db_strategy_ids(db) == (a, a)


async def _db_row(db):
    return await db.fetch_one("SELECT status FROM bots WHERE bot_id = 'bot1'")


def _started_events(eventbus) -> list[BotStartedEvent]:
    seen: list[BotStartedEvent] = []
    eventbus.subscribe(BotStartedEvent, seen.append)
    return seen


class TestSwitchRacingDelete:
    """교체·배정·수정이 기다리는 사이에 삭제가 끼면 삭제된 봇에 쓰지 않는다 (#2698)."""

    @pytest.mark.parametrize("hard", [False, True])
    async def test_assign_does_not_restart_bot_deleted_during_save(
        self, manager, ctx, db, orders, eventbus, strategies, monkeypatch, hard
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        started = _started_events(eventbus)
        original_save = manager._save_bot_config

        async def _save_then_delete(config):
            await original_save(config)
            await manager.delete_bot("bot1", hard=hard)

        generation = bot._generation
        monkeypatch.setattr(manager, "_save_bot_config", _save_then_delete)
        with pytest.raises(Exception) as exc_info:
            await manager.assign_strategy("bot1", b)

        assert type(exc_info.value) is BotNotFoundError
        assert bot.status == BotStatus.DELETED
        assert started == []
        assert bot._generation == generation
        assert bot._task is None or bot._task.done()
        row = await _db_row(db)
        if hard:
            assert row is None
        else:
            assert row["status"] == "deleted"

    @pytest.mark.parametrize("path", ["assign_strategy", "change_strategy"])
    async def test_switch_does_not_recreate_row_hard_deleted_during_prepare(
        self, manager, ctx, db, orders, strategies, monkeypatch, path
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        if path == "change_strategy":
            await manager.stop_bot("bot1")
        original_prepare = manager._prepare_strategy

        async def _prepare_then_delete(*args, **kwargs):
            cls = await original_prepare(*args, **kwargs)
            await manager.delete_bot("bot1", hard=True)
            return cls

        monkeypatch.setattr(manager, "_prepare_strategy", _prepare_then_delete)
        with pytest.raises(Exception) as exc_info:
            await getattr(manager, path)("bot1", b)

        assert type(exc_info.value) is BotNotFoundError
        assert await _db_row(db) is None
        assert bot._bound_strategy_id == a
        assert bot.status == BotStatus.DELETED

    async def test_update_strategy_does_not_recreate_row_hard_deleted_during_prepare(
        self, manager, ctx, db, orders, strategies, monkeypatch
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        await manager.stop_bot("bot1")
        original_prepare = manager._prepare_strategy

        async def _prepare_then_delete(*args, **kwargs):
            cls = await original_prepare(*args, **kwargs)
            await manager.delete_bot("bot1", hard=True)
            return cls

        monkeypatch.setattr(manager, "_prepare_strategy", _prepare_then_delete)
        with pytest.raises(Exception) as exc_info:
            await manager.update_bot("bot1", strategy_id=b)

        assert type(exc_info.value) is BotNotFoundError
        assert await _db_row(db) is None
        assert bot._bound_strategy_id == a

    async def test_assign_does_not_start_bot_while_delete_is_in_progress(
        self, manager, ctx, db, orders, eventbus, strategies, monkeypatch, signal_keys
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)
        started = _started_events(eventbus)
        entered = asyncio.Event()
        gate = asyncio.Event()
        original_revoke = signal_keys.revoke

        async def _paused_revoke(bot_id):
            entered.set()
            await gate.wait()
            return await original_revoke(bot_id)

        monkeypatch.setattr(signal_keys, "revoke", _paused_revoke)
        original_save = manager._save_bot_config
        deleting: list[asyncio.Task[None]] = []

        async def _save_then_start_delete(config):
            await original_save(config)
            deleting.append(asyncio.create_task(manager.delete_bot("bot1")))
            await entered.wait()

        monkeypatch.setattr(manager, "_save_bot_config", _save_then_start_delete)
        try:
            with pytest.raises(Exception) as exc_info:
                await manager.assign_strategy("bot1", b)
        finally:
            gate.set()
            await asyncio.wait_for(deleting[0], timeout=5.0)

        assert type(exc_info.value) is BotNotFoundError
        assert started == []
        assert bot.status == BotStatus.DELETED
        assert bot._task is None or bot._task.done()
        assert manager.get_bot("bot1") is None

    async def test_bot_recreated_after_delete_accepts_switch_and_update(
        self, manager, ctx, db, orders, strategies
    ):
        a, b = strategies
        await _running_on_a(manager, ctx, db, orders, a)
        await manager.delete_bot("bot1", hard=True)
        recreated = await _create(manager, ctx, db, a)

        await manager.assign_strategy("bot1", b)
        await manager.update_bot("bot1", interval_seconds=60)

        assert recreated.config.strategy_id == b
        assert recreated._bound_strategy_id == b
        assert recreated.config.interval_seconds == 60
        assert await _db_strategy_ids(db) == (b, b)

    async def test_bot_left_by_failed_delete_accepts_switch_update_and_delete(
        self, manager, ctx, db, orders, strategies, monkeypatch, signal_keys
    ):
        a, b = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)

        async def _fail_revoke(bot_id):
            raise RuntimeError("revoke down")

        monkeypatch.setattr(signal_keys, "revoke", _fail_revoke)
        with pytest.raises(RuntimeError, match="revoke down"):
            await manager.delete_bot("bot1")
        monkeypatch.undo()
        assert manager.get_bot("bot1") is bot

        await manager.assign_strategy("bot1", b)
        await manager.update_bot("bot1", interval_seconds=60)
        await manager.delete_bot("bot1")

        assert bot._bound_strategy_id == b
        assert bot.config.interval_seconds == 60
        assert bot.status == BotStatus.DELETED
        assert manager.get_bot("bot1") is None


class TestStartRacingDelete:
    """삭제가 진행되는 사이에 시작·재개가 봇을 다시 띄우지 않는다 (#2883)."""

    @pytest.mark.parametrize("hard", [False, True])
    @pytest.mark.parametrize(
        ("path", "initial"),
        [
            ("start_bot", BotStatus.RUNNING),
            ("start_bot", BotStatus.ERROR),
            ("resume_bot", BotStatus.RUNNING),
            ("resume_bot", BotStatus.ERROR),
        ],
    )
    async def test_start_path_rejects_bot_being_deleted(
        self,
        manager,
        ctx,
        db,
        orders,
        eventbus,
        strategies,
        monkeypatch,
        path,
        initial,
        hard,
    ):
        a, _ = strategies
        if initial == BotStatus.RUNNING:
            bot = await _running_on_a(manager, ctx, db, orders, a)
        else:
            bot = await _create(manager, ctx, db, a)
            bot.status = BotStatus.ERROR
        manager._restart_counts["bot1"] = 2
        started = _started_events(eventbus)
        seen_status: list[BotStatus] = []
        raised: list[BaseException] = []

        counts_after_call: list[int | None] = []

        async def _start_during_delete(target):
            seen_status.append(target.status)
            try:
                await getattr(manager, path)("bot1")
            except Exception as exc:
                raised.append(exc)
            counts_after_call.append(manager._restart_counts.get("bot1"))

        monkeypatch.setattr(manager, "_liquidate_positions", _start_during_delete)
        generation = bot._generation
        await manager.delete_bot("bot1", handle_positions="liquidate", hard=hard)

        expected_seen = (
            BotStatus.STOPPED if initial == BotStatus.RUNNING else BotStatus.ERROR
        )
        assert seen_status == [expected_seen]
        assert [type(e) for e in raised] == [BotNotFoundError]
        assert started == []
        assert bot._generation == generation
        assert bot._task is None or bot._task.done()
        assert bot.status == BotStatus.DELETED
        assert manager.get_bot("bot1") is None
        assert counts_after_call == [2]
        assert manager._restart_counts.get("bot1") is None
        row = await _db_row(db)
        if hard:
            assert row is None
        else:
            assert row["status"] == "deleted"

    @pytest.mark.parametrize("path", ["start_bot", "resume_bot"])
    async def test_bot_left_by_failed_delete_accepts_start(
        self, manager, ctx, db, orders, eventbus, strategies, monkeypatch, path
    ):
        a, _ = strategies
        bot = await _running_on_a(manager, ctx, db, orders, a)

        async def _fail_liquidate(target):
            raise RuntimeError("liquidate down")

        monkeypatch.setattr(manager, "_liquidate_positions", _fail_liquidate)
        with pytest.raises(RuntimeError, match="liquidate down"):
            await manager.delete_bot("bot1", handle_positions="liquidate")
        monkeypatch.undo()
        assert manager.get_bot("bot1") is bot
        assert bot.status == BotStatus.STOPPED
        started = _started_events(eventbus)

        await getattr(manager, path)("bot1")

        assert bot.status == BotStatus.RUNNING
        assert len(started) == 1
