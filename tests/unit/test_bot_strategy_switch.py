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
from ante.bot.exceptions import BotError, BotNotAcceptingSignals
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
