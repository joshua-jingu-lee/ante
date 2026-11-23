"""데몬 재시작 뒤 DB의 봇을 메모리로 복원한다 (#2813).

매니저 A로 봇을 만든 뒤, 같은 DB 위의 새 EventBus·AccountService·BotManager
(데몬 재시작)로 ``initialize`` → ``restore_bots`` 를 돌려 본다. 복원은 로드만
한다 — 봇을 시작하지 않고, 룰·시그널 키·예산·``bots`` 행을 건드리지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.bot import BotConfig, BotManager, BotStatus
from ante.bot.exceptions import BotAlreadyExistsError
from ante.bot.signal_key import SignalKeyManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    ExternalSignalEvent,
    OrderFilledEvent,
    OrderRequestEvent,
)
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    StrategyContext,
    StrategyMeta,
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
        description="restore probe",
        accepts_external_signals=True,
    )

    async def on_step(self, context):
        return [Signal(symbol="AAA", side="buy", quantity=1)]

    async def on_data(self, data):
        return [Signal(symbol="AAA", side="buy", quantity=1)]

    async def on_fill(self, fill):
        return [Signal(symbol="AAA", side="buy", quantity=1)]
"""


class _Data(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        raise AssertionError("복원된 봇이 데이터를 읽었다")

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class _Portfolio(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class _Orders(OrderView):
    def get_open_orders(self, bot_id):
        return []


def _ctx(bot_id: str) -> StrategyContext:
    return StrategyContext(
        bot_id=bot_id,
        data_provider=_Data(),
        portfolio=_Portfolio(),
        order_view=_Orders(),
    )


class _ContextFactory:
    """컨텍스트 팩토리 대역. ``fail_for`` 의 봇이면 ``ValueError``."""

    def __init__(self, fail_for: set[str] | None = None) -> None:
        self.fail_for = fail_for or set()
        self.created: list[str] = []

    def create(self, config: BotConfig) -> StrategyContext:
        if config.bot_id in self.fail_for:
            raise ValueError("context 생성 실패")
        self.created.append(config.bot_id)
        return _ctx(config.bot_id)


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
def snapshot_root(tmp_path) -> Path:
    return tmp_path / "strategies"


def _account(account_id: str, name: str) -> Account:
    return Account(
        account_id=account_id,
        name=name,
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
        credentials={"app_key": "test", "app_secret": "test"},
    )


@pytest.fixture
async def before(db, snapshot_root):
    """재시작 전의 데몬(매니저 A)."""
    eventbus = EventBus()
    accounts = AccountService(db=db, eventbus=eventbus)
    await accounts.initialize()
    for account_id, name in (
        ("acc-test", "활성"),
        ("acc-susp", "정지"),
        ("acc-del", "삭제"),
    ):
        await accounts.create(_account(account_id, name))
    keys = SignalKeyManager(db)
    await keys.initialize()
    manager = BotManager(
        eventbus=eventbus,
        db=db,
        account_service=accounts,
        snapshot=StrategySnapshot(snapshot_root),
        signal_key_manager=keys,
    )
    await manager.initialize()
    return manager


async def _register(db, tmp_path: Path, name: str) -> tuple[str, Path]:
    src_dir = tmp_path / "src"
    src_dir.mkdir(exist_ok=True)
    filepath = src_dir / f"{name}.py"
    filepath.write_text(_SOURCE.format(cls=f"Probe_{name}", name=name), "utf-8")
    registry = StrategyRegistry(db)
    await registry.initialize()
    record = await registry.register(
        filepath, StrategyMeta(name=name, version="1.0.0", description="probe")
    )
    return record.strategy_id, filepath


async def _create(manager: BotManager, bot_id: str, strategy: tuple[str, Path], **kw):
    strategy_id, source = strategy
    config = BotConfig(
        bot_id=bot_id,
        strategy_id=strategy_id,
        account_id=kw.pop("account_id", "acc-test"),
        name=f"이름-{bot_id}",
        **kw,
    )
    return await manager.create_bot(
        config, StrategyLoader.load(source), _ctx(bot_id), source_path=source
    )


class _Restarted:
    def __init__(self, manager, eventbus, rule_engine, treasury, factory, orders):
        self.manager = manager
        self.eventbus = eventbus
        self.rule_engine = rule_engine
        self.treasury = treasury
        self.factory = factory
        self.orders = orders


async def _restart(db, snapshot_root, *, fail_ctx: set[str] | None = None):
    """같은 DB 위에 새 데몬(매니저 B)을 세우고 ``restore_bots`` 까지 돈다."""
    eventbus = EventBus()
    orders: list[OrderRequestEvent] = []
    eventbus.subscribe(OrderRequestEvent, orders.append, priority=1000)
    accounts = AccountService(db=db, eventbus=eventbus)
    await accounts.initialize()
    keys = SignalKeyManager(db)
    await keys.initialize()
    rule_engine = MagicMock()
    treasury = MagicMock()
    factory = _ContextFactory(fail_ctx)
    registry = StrategyRegistry(db)
    await registry.initialize()
    rule_configs = {
        r.strategy_id: [{"type": "max_position", "enabled": True}]
        for r in await registry.list_strategies()
    }
    manager = BotManager(
        eventbus=eventbus,
        db=db,
        context_factory=factory,  # type: ignore[arg-type]
        account_service=accounts,
        snapshot=StrategySnapshot(snapshot_root),
        signal_key_manager=keys,
        rule_engine=rule_engine,
        strategy_rule_configs=rule_configs,
        treasury_manager=treasury,
    )
    await manager.initialize()
    await manager.restore_bots()
    return _Restarted(manager, eventbus, rule_engine, treasury, factory, orders)


async def _bot_rows(db) -> list[dict[str, Any]]:
    rows = await db.fetch_all("SELECT * FROM bots ORDER BY bot_id")
    return [dict(r) for r in rows]


class TestRestore:
    async def test_bot_survives_restart_as_created(self, db, tmp_path, before):
        strategy = await _register(db, tmp_path, "s1")
        await _create(
            before,
            "b1",
            strategy,
            interval_seconds=120,
            auto_restart=False,
            max_restart_attempts=5,
            restart_cooldown_seconds=30,
            step_timeout_seconds=20,
            max_signals_per_step=7,
        )
        await before.start_bot("b1")
        await before.stop_bot("b1")

        after = await _restart(db, tmp_path / "strategies")

        bot = after.manager.get_bot("b1")
        assert bot is not None
        assert bot.status == BotStatus.CREATED
        assert bot._strategy_cls.__name__ == "Probe_s1"
        assert bot.config.name == "이름-b1"
        assert bot.config.account_id == "acc-test"
        assert bot.config.strategy_id == strategy[0]
        assert (
            bot.config.interval_seconds,
            bot.config.auto_restart,
            bot.config.max_restart_attempts,
            bot.config.restart_cooldown_seconds,
            bot.config.step_timeout_seconds,
            bot.config.max_signals_per_step,
        ) == (120, False, 5, 30, 20, 7)
        assert bot.exchange == "KRX" and bot.currency == "KRW"
        snap = tmp_path / "strategies" / ".running" / "b1" / "s1.py"
        assert snap.exists()
        assert after.factory.created == ["b1"]
        assert [i["bot_id"] for i in after.manager.list_bots()] == ["b1"]

    @pytest.mark.parametrize(
        "db_status", ["running", "stopping", "stopped", "error", "legacy-value"]
    )
    async def test_any_db_status_restores_as_created(
        self, db, tmp_path, before, db_status
    ):
        strategy = await _register(db, tmp_path, "s1")
        await _create(before, "b1", strategy)
        await db.execute("UPDATE bots SET status = ? WHERE bot_id = 'b1'", (db_status,))

        after = await _restart(db, tmp_path / "strategies")

        assert after.manager.get_bot("b1").status == BotStatus.CREATED

    async def test_deleted_bot_is_not_restored(self, db, tmp_path, before):
        strategy = await _register(db, tmp_path, "s1")
        await _create(before, "b1", strategy)
        await _create(before, "b2", await _register(db, tmp_path, "s2"))
        await before.delete_bot("b1")

        after = await _restart(db, tmp_path / "strategies")

        assert after.manager.get_bot("b1") is None
        assert after.manager.get_bot("b2") is not None

    async def test_same_id_create_after_restore_is_rejected(self, db, tmp_path, before):
        strategy = await _register(db, tmp_path, "s1")
        await _create(before, "b1", strategy)

        after = await _restart(db, tmp_path / "strategies")

        with pytest.raises(BotAlreadyExistsError):
            await _create(after.manager, "b1", strategy)

    async def test_suspended_account_row_is_restored(self, db, tmp_path, before):
        await _create(before, "b1", await _register(db, tmp_path, "s1"))
        await _create(
            before, "b2", await _register(db, tmp_path, "s2"), account_id="acc-susp"
        )
        await db.execute(
            "UPDATE accounts SET status = 'suspended' WHERE account_id = 'acc-susp'"
        )

        after = await _restart(db, tmp_path / "strategies")

        assert after.manager.get_bot("b2").status == BotStatus.CREATED


class TestRestoreHasNoSideEffects:
    async def test_no_start_rules_keys_budget_or_row_writes(self, db, tmp_path, before):
        strategy = await _register(db, tmp_path, "s1")
        await _create(before, "b1", strategy)
        key_before = await before._signal_key_manager.get_key("b1")
        assert key_before
        rows_before = await _bot_rows(db)

        after = await _restart(db, tmp_path / "strategies")

        bot = after.manager.get_bot("b1")
        assert bot.strategy is None
        assert bot._task is None
        assert after.manager._restart_tasks == {}
        assert after.manager._restart_reset_tasks == {}
        assert after.rule_engine.method_calls == []
        assert after.treasury.method_calls == []
        assert await after.manager._signal_key_manager.get_key("b1") == key_before
        assert await _bot_rows(db) == rows_before

    async def test_events_after_restore_send_no_order(self, db, tmp_path, before):
        await _create(before, "b1", await _register(db, tmp_path, "s1"))

        after = await _restart(db, tmp_path / "strategies")
        await after.eventbus.publish(
            ExternalSignalEvent(
                account_id="acc-test", bot_id="b1", symbol="AAA", action="buy"
            )
        )
        await after.eventbus.publish(
            OrderFilledEvent(
                account_id="acc-test",
                order_id="o1",
                bot_id="b1",
                symbol="AAA",
                side="buy",
                quantity=1.0,
                price=100.0,
            )
        )
        await asyncio.sleep(0.05)

        assert after.orders == []
        assert after.manager.get_bot("b1").status == BotStatus.CREATED


class TestBrokenRowIsSkipped:
    async def test_each_broken_row_is_skipped_and_others_restored(
        self, db, tmp_path, before, caplog
    ):
        await _create(before, "ok", await _register(db, tmp_path, "s_ok"))
        await _create(before, "nostrat", await _register(db, tmp_path, "s_gone"))
        await db.execute("DELETE FROM strategies WHERE name = 's_gone'")
        _, missing_file = await _register(db, tmp_path, "s_nofile")
        await _create(before, "nofile", (_, missing_file))
        missing_file.unlink()
        await _create(before, "badjson", await _register(db, tmp_path, "s_json"))
        await db.execute(
            "UPDATE bots SET config_json = '{oops' WHERE bot_id = 'badjson'"
        )
        await _create(before, "listjson", await _register(db, tmp_path, "s_list"))
        await db.execute("UPDATE bots SET config_json = '[]' WHERE bot_id = 'listjson'")
        await _create(before, "badacc", await _register(db, tmp_path, "s_acc"))
        await db.execute(
            "UPDATE bots SET account_id = 'default' WHERE bot_id = 'badacc'"
        )
        await _create(before, "noacc", await _register(db, tmp_path, "s_noacc"))
        await db.execute("UPDATE bots SET account_id = 'acc-x' WHERE bot_id = 'noacc'")
        await _create(
            before,
            "delacc",
            await _register(db, tmp_path, "s_del"),
            account_id="acc-del",
        )
        await db.execute(
            "UPDATE accounts SET status = 'deleted' WHERE account_id = 'acc-del'"
        )
        await _create(before, "ctxfail", await _register(db, tmp_path, "s_ctx"))
        await _create(before, "badtype", await _register(db, tmp_path, "s_type"))
        await db.execute(
            'UPDATE bots SET config_json = \'{"interval_seconds": "x"}\''
            " WHERE bot_id = 'badtype'"
        )
        broken = ["nostrat", "nofile", "badjson", "listjson", "badacc", "noacc"]
        broken += ["badtype"]
        broken += ["delacc", "ctxfail"]

        with caplog.at_level(logging.WARNING, logger="ante.bot.manager"):
            after = await _restart(db, tmp_path / "strategies", fail_ctx={"ctxfail"})

        assert [i["bot_id"] for i in after.manager.list_bots()] == ["ok"]
        warned = " ".join(r.getMessage() for r in caplog.records)
        for bot_id in broken:
            assert bot_id in warned
            assert not (tmp_path / "strategies" / ".running" / bot_id).exists()
        handlers = after.eventbus.get_handlers(OrderFilledEvent)
        assert len(handlers) == 1

    async def test_unexpected_error_stops_restore(self, db, tmp_path, before):
        await _create(before, "b1", await _register(db, tmp_path, "s1"))

        class _Boom(_ContextFactory):
            def create(self, config: BotConfig) -> StrategyContext:
                raise RuntimeError("boom")

        eventbus = EventBus()
        accounts = AccountService(db=db, eventbus=eventbus)
        await accounts.initialize()
        manager = BotManager(
            eventbus=eventbus,
            db=db,
            context_factory=_Boom(),  # type: ignore[arg-type]
            account_service=accounts,
            snapshot=StrategySnapshot(tmp_path / "strategies"),
        )
        await manager.initialize()

        with pytest.raises(RuntimeError, match="boom"):
            await manager.restore_bots()


async def test_restore_returns_count_and_row_json_is_unchanged(db, tmp_path, before):
    await _create(before, "b1", await _register(db, tmp_path, "s1"))
    row = await db.fetch_one("SELECT config_json FROM bots WHERE bot_id = 'b1'")
    assert json.loads(row["config_json"])["bot_id"] == "b1"

    eventbus = EventBus()
    accounts = AccountService(db=db, eventbus=eventbus)
    await accounts.initialize()
    manager = BotManager(
        eventbus=eventbus,
        db=db,
        context_factory=_ContextFactory(),  # type: ignore[arg-type]
        account_service=accounts,
        snapshot=StrategySnapshot(tmp_path / "strategies"),
    )
    await manager.initialize()

    assert await manager.restore_bots() == 1


async def test_second_restore_does_not_replace_restored_bot(db, tmp_path, before):
    await _create(before, "b1", await _register(db, tmp_path, "s1"))
    after = await _restart(db, tmp_path / "strategies")
    bot = after.manager.get_bot("b1")

    assert await after.manager.restore_bots() == 0

    assert after.manager.get_bot("b1") is bot
    assert len(after.eventbus.get_handlers(OrderFilledEvent)) == 1
