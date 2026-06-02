"""bots.strategy_id 컬럼 ↔ config_json.strategy_id 일관성 회귀 (#2129 + #2130).

봇 전략 변경 경로(``update_bot(strategy_id=...)`` / ``assign_strategy`` /
``change_strategy``)가 ``bots.strategy_id`` 컬럼과 ``config_json.strategy_id``
를 항상 동일하게 갱신하는지, ``update_bot`` 의 전략 변경이 미등록/exchange
비호환 전략을 거부하는지, lifecycle(rule load/unload·runtime config) 순서가
보존되는지 검증한다.
"""

from __future__ import annotations

import asyncio
import json

import pytest

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
from ante.strategy.exceptions import IncompatibleExchangeError, StrategyNotFoundError
from ante.strategy.registry import StrategyRegistry

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


# 실제 전략 파일 소스. ``StrategyLoader.load`` 가 파일에서 단일 Strategy
# subclass 를 로드해 ``meta.exchange`` 를 읽으므로, registry.register 가
# 가리키는 filepath 에 실제로 작성한다.
_KRX_STRATEGY_SOURCE = """
from ante.strategy import Strategy, StrategyMeta


class KrxStrategy(Strategy):
    meta = StrategyMeta(
        name="krx_compat", version="1.0.0", description="krx", exchange="KRX"
    )

    async def on_step(self, context):
        return []
"""

_NASDAQ_STRATEGY_SOURCE = """
from ante.strategy import Strategy, StrategyMeta


class NasdaqStrategy(Strategy):
    meta = StrategyMeta(
        name="nasdaq_only", version="1.0.0", description="nasdaq", exchange="NASDAQ"
    )

    async def on_step(self, context):
        return []
"""


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
async def manager(eventbus, db):
    """account_service 미주입 manager — assign/change·일관성 코어 검증용."""
    m = BotManager(eventbus=eventbus, db=db)
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
async def manager_with_account(eventbus, db, account_service):
    """account_service 주입 manager — update_bot exchange 검증용."""
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


async def _register_strategy(db, source: str, name: str, version: str, tmp_path):
    """전략 파일을 작성하고 ``StrategyRegistry`` 에 등록한다.

    반환값은 등록된 ``strategy_id`` (``{name}_v{version}``).
    """
    filepath = tmp_path / f"{name}.py"
    filepath.write_text(source, encoding="utf-8")
    registry = StrategyRegistry(db)
    await registry.initialize()
    meta = StrategyMeta(name=name, version=version, description="test")
    record = await registry.register(filepath, meta)
    return record.strategy_id


async def _make_krx_account(account_service, account_id="acc-test"):
    account = Account(
        account_id=account_id,
        name="활성계좌",
        exchange="KRX",
        currency="KRW",
        broker_type="test",
        status=AccountStatus.ACTIVE,
        credentials={"app_key": "test", "app_secret": "test"},
    )
    await account_service.create(account)
    return account


async def _row_strategy_ids(db, bot_id):
    """``bots`` row 의 컬럼 strategy_id 와 config_json.strategy_id 를 반환."""
    row = await db.fetch_one(
        "SELECT strategy_id, config_json FROM bots WHERE bot_id = ?", (bot_id,)
    )
    cfg = json.loads(row["config_json"])
    return row["strategy_id"], cfg["strategy_id"]


# ── (a) update_bot --strategy (등록·호환) → 컬럼+config_json 둘 다 새 ID ──


class TestUpdateBotStrategyConsistency:
    async def test_update_strategy_updates_both_stores(
        self, manager_with_account, account_service, ctx, db, tmp_path
    ):
        """#2129: update_bot --strategy(등록·호환) → 컬럼+config_json 둘 다 새 ID."""
        await _make_krx_account(account_service)
        new_sid = await _register_strategy(
            db, _KRX_STRATEGY_SOURCE, "krx_compat", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot("bot1", strategy_id=new_sid)

        assert bot.config.strategy_id == new_sid
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == new_sid
        assert cfg == new_sid

    async def test_update_unregistered_strategy_raises_before_persist(
        self, manager_with_account, account_service, ctx, db
    ):
        """#2129 (b): update_bot 미등록 strategy → raise(저장/swap 전)."""
        await _make_krx_account(account_service)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(StrategyNotFoundError):
            await manager_with_account.update_bot("bot1", strategy_id="missing_v1.0.0")

        # swap 전 raise: 메모리 config 와 DB 둘 다 옛 ID 유지.
        assert manager_with_account.get_bot("bot1").config.strategy_id == "s1"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s1"
        assert cfg == "s1"

    async def test_update_incompatible_exchange_raises_before_persist(
        self, manager_with_account, account_service, ctx, db, tmp_path
    ):
        """#2129 (c): update_bot exchange 비호환 strategy → raise(저장/swap 전)."""
        await _make_krx_account(account_service)
        # NASDAQ 전략 vs KRX 계좌 → 비호환.
        bad_sid = await _register_strategy(
            db, _NASDAQ_STRATEGY_SOURCE, "nasdaq_only", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(IncompatibleExchangeError):
            await manager_with_account.update_bot("bot1", strategy_id=bad_sid)

        assert manager_with_account.get_bot("bot1").config.strategy_id == "s1"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s1"
        assert cfg == "s1"

    async def test_update_non_strategy_field_skips_validation(
        self, manager_with_account, account_service, ctx, db
    ):
        """strategy_id 미변경(name 만 변경)이면 registry 검증을 트리거하지 않는다.

        ``s1`` 은 registry 에 등록되지 않았지만, strategy_id 가 그대로이면
        검증을 건너뛰므로 name-only update 가 성공해야 한다.
        """
        await _make_krx_account(account_service)
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", name="old", account_id="acc-test"
        )
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot("bot1", name="new")
        assert bot.config.name == "new"
        assert bot.config.strategy_id == "s1"

    async def test_update_same_strategy_id_skips_validation(
        self, manager_with_account, account_service, ctx
    ):
        """strategy_id 를 같은 값으로 명시 전달해도 검증을 건너뛴다(no-op)."""
        await _make_krx_account(account_service)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot("bot1", strategy_id="s1")
        assert bot.config.strategy_id == "s1"

    async def test_update_strategy_without_account_service_skips_exchange(
        self, manager, ctx, db, tmp_path
    ):
        """account_service 미주입이면 존재 검증만 하고 exchange 검증은 skip.

        create_bot 과 동일하게 account 정보가 없으면 호환성 검증을 수행하지
        않는다. registry 존재 검증은 여전히 적용된다.
        """
        new_sid = await _register_strategy(
            db, _KRX_STRATEGY_SOURCE, "krx_compat", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        bot = await manager.update_bot("bot1", strategy_id=new_sid)
        assert bot.config.strategy_id == new_sid
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == new_sid == cfg

    async def test_update_unregistered_strategy_raises_without_account_service(
        self, manager, ctx, db
    ):
        """account_service 없이도 미등록 strategy 는 거부된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(StrategyNotFoundError):
            await manager.update_bot("bot1", strategy_id="missing_v1.0.0")
        assert manager.get_bot("bot1").config.strategy_id == "s1"


# ── (d)(e) assign_strategy / change_strategy 일관성 ──────────────


class TestAssignChangeConsistency:
    async def test_assign_strategy_updates_both_stores(self, manager, ctx, db):
        """#2130 (d): assign_strategy → 컬럼+config_json 일관."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.assign_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s2"
        assert cfg == "s2"

    async def test_change_strategy_updates_both_stores(self, manager, ctx, db):
        """#2130 (e): change_strategy → 컬럼+config_json 일관."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        await manager.change_strategy("bot1", "s2")

        assert manager.get_bot("bot1").config.strategy_id == "s2"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s2"
        assert cfg == "s2"

    async def test_assign_running_bot_updates_both_stores(self, manager, ctx, db):
        """running 봇 assign 후에도 컬럼+config_json 일관 + 재시작."""
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await manager.assign_strategy("bot1", "s2")

        bot = manager.get_bot("bot1")
        assert bot.config.strategy_id == "s2"
        assert bot.status == BotStatus.RUNNING
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s2" == cfg


# ── (f) lifecycle 순서 보존 (stop→unload→persist→load→start) ──────


class _RuleEngineSpy:
    """rule load/unload 호출을 기록하는 최소 spy."""

    def __init__(self, events: list[str]) -> None:
        self._events = events

    def load_strategy_rules_from_config(self, strategy_id, rule_configs):
        self._events.append(f"load_rules:{strategy_id}")

    def remove_strategy_rules(self, strategy_id):
        self._events.append(f"unload_rules:{strategy_id}")


class TestLifecycleOrderPreserved:
    async def test_assign_running_preserves_stop_unload_persist_load_start_order(
        self, eventbus, db, ctx
    ):
        """#2130 (f): running 봇 assign 순서 = stop→unload→persist→load→start.

        rule load/unload 와 persist(``_save_bot_config``) 호출 시퀀스를
        기록해, Codex Plan Review 가 보존을 요구한 lifecycle 순서를 회귀
        보호한다.
        """
        events: list[str] = []
        spy = _RuleEngineSpy(events)
        # rule_configs 가 있어야 _load_strategy_rules 가 실제 호출을 한다.
        m = BotManager(
            eventbus=eventbus,
            db=db,
            rule_engine=spy,  # type: ignore[arg-type]
            strategy_rule_configs={
                "s1": [{"type": "x"}],
                "s2": [{"type": "y"}],
            },
        )
        await m.initialize()
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", interval_seconds=999, account_id="acc-test"
        )
        await m.create_bot(config, SimpleStrategy, ctx)
        await m.start_bot("bot1")
        # start_bot 도 _load_strategy_rules 를 호출하므로 이전 이벤트 비운다.
        events.clear()

        # persist 시점 기록을 위해 _save_bot_config 를 wrapping.
        original_save = m._save_bot_config

        async def spy_save(cfg):
            events.append(f"persist:{cfg.strategy_id}")
            return await original_save(cfg)

        m._save_bot_config = spy_save  # type: ignore[method-assign]

        # bot.stop/start 도 시퀀스에 기록.
        bot = m.get_bot("bot1")
        original_stop = bot.stop
        original_start = bot.start

        async def spy_stop():
            events.append("stop")
            return await original_stop()

        async def spy_start():
            events.append("start")
            return await original_start()

        bot.stop = spy_stop  # type: ignore[method-assign]
        bot.start = spy_start  # type: ignore[method-assign]

        await m.assign_strategy("bot1", "s2")

        # 핵심 순서: stop → old rule unload(s1) → persist(s2) → new rule load(s2)
        # → start.
        assert events == [
            "stop",
            "unload_rules:s1",
            "persist:s2",
            "load_rules:s2",
            "start",
        ]

        # cleanup
        for b in list(m._bots.values()):
            if b._task and not b._task.done():
                b._task.cancel()
        try:
            await asyncio.wait_for(m.stop_all(), timeout=5.0)
        except TimeoutError:
            pass

    async def test_change_strategy_persists_after_runtime_update(
        self, eventbus, db, ctx
    ):
        """change_strategy 는 runtime config 갱신 후 persist 한다 (stopped 봇).

        stopped 봇이므로 rule load/unload 는 발생하지 않지만, runtime
        ``bot.config.strategy_id`` 갱신 → persist 순서를 회귀 보호한다.
        """
        events: list[str] = []
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await m.create_bot(config, SimpleStrategy, ctx)

        bot = m.get_bot("bot1")
        original_save = m._save_bot_config

        async def spy_save(cfg):
            # persist 시점에 runtime config 가 이미 새 strategy_id 여야 한다.
            events.append(f"persist:runtime={bot.config.strategy_id}")
            return await original_save(cfg)

        m._save_bot_config = spy_save  # type: ignore[method-assign]

        await m.change_strategy("bot1", "s2")

        assert events == ["persist:runtime=s2"]

        for b in list(m._bots.values()):
            if b._task and not b._task.done():
                b._task.cancel()
        try:
            await asyncio.wait_for(m.stop_all(), timeout=5.0)
        except TimeoutError:
            pass


# ── (g) load_from_db 후 재로드 일관 ──────────────────────────────


class TestReloadConsistency:
    async def test_assign_then_reload_consistent(self, manager, eventbus, ctx, db):
        """#2130 (g): assign 후 새 매니저로 load_from_db → 컬럼 기반 복원이 일관.

        load_from_db 는 컬럼을 읽어 BotConfig 를 만든다. assign 으로 컬럼과
        config_json 이 모두 새 ID 이므로, 재로드된 config 와 DB 의 두 store 가
        모두 같은 ID 를 가리켜야 한다.
        """
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.assign_strategy("bot1", "s2")

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        reloaded = manager2.get_bot("bot1")
        assert reloaded.config.strategy_id == "s2"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert reloaded.config.strategy_id == col == cfg == "s2"

    async def test_update_strategy_then_reload_consistent(
        self, manager_with_account, account_service, eventbus, ctx, db, tmp_path
    ):
        """#2129 (g): update_bot --strategy 후 재로드 일관."""
        await _make_krx_account(account_service)
        new_sid = await _register_strategy(
            db, _KRX_STRATEGY_SOURCE, "krx_compat", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)
        await manager_with_account.update_bot("bot1", strategy_id=new_sid)

        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        await manager2.load_from_db()

        reloaded = manager2.get_bot("bot1")
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert reloaded.config.strategy_id == col == cfg == new_sid
