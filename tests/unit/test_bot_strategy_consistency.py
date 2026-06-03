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
from ante.bot import BotConfig, BotImmutableFieldError, BotManager, BotStatus
from ante.bot.exceptions import BOT_IMMUTABLE_FIELD_CODE
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


async def _make_nasdaq_account(account_service, account_id="acc-nasdaq"):
    account = Account(
        account_id=account_id,
        name="나스닥계좌",
        exchange="NASDAQ",
        currency="USD",
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


async def _row_account_ids(db, bot_id):
    """``bots`` row 의 컬럼 account_id 와 config_json.account_id 를 반환 (#2274)."""
    row = await db.fetch_one(
        "SELECT account_id, config_json FROM bots WHERE bot_id = ?", (bot_id,)
    )
    cfg = json.loads(row["config_json"])
    return row["account_id"], cfg["account_id"]


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


# ── account_id + strategy_id 동시 변경 → effective(새) 계좌로 검증 (브랜치 리뷰) ──


class TestUpdateBotAccountIdImmutableVsStrategy:
    """#2282: ``account_id`` 는 ``update_bot`` 의 불변 필드다. 가드는 strategy
    검증/BotConfig 재생성보다 **먼저** 평가되므로, account_id 변경을 동반한
    요청은 strategy 호환성 검증에 도달하기 전에 ``BotImmutableFieldError`` 로
    거부된다.

    #2129 가 도입했던 "account_id+strategy_id 동시 변경 시 effective(새) 계좌로
    strategy 검증" 시나리오는 account_id 가 불변이 되면서 더 이상 발생할 수
    없다(account_id 변경 자체가 먼저 거부). 따라서 strategy 검증은 항상
    ``old_config.account_id`` 로 수행된다. 본 클래스는 (1) account_id 동반
    변경이 strategy 검증 이전에 거부되는지, (2) account_id 를 바꾸지 않는
    strategy 변경은 무회귀로 동작하는지 검증한다.
    """

    async def test_simultaneous_account_and_strategy_change_rejected_before_validation(
        self, manager_with_account, account_service, ctx, db, tmp_path
    ):
        """(a) account_id + strategy_id 동시 변경 → strategy 검증 이전에 거부.

        새 전략(NASDAQ)이 옛 계좌(KRX)와는 비호환이지만, account_id 불변 가드가
        strategy 검증보다 먼저 평가되므로 ``IncompatibleExchangeError`` 가 아니라
        ``BotImmutableFieldError`` 로 거부된다. 옛·새 store 모두 미변경이어야 한다.
        """
        await _make_krx_account(account_service)
        await _make_nasdaq_account(account_service)
        nasdaq_sid = await _register_strategy(
            db, _NASDAQ_STRATEGY_SOURCE, "nasdaq_only", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(BotImmutableFieldError) as exc_info:
            await manager_with_account.update_bot(
                "bot1", account_id="acc-nasdaq", strategy_id=nasdaq_sid
            )
        assert exc_info.value.code == BOT_IMMUTABLE_FIELD_CODE

        # 거부 후 memory config·DB(컬럼·config_json) 모두 옛 값 유지.
        bot = manager_with_account.get_bot("bot1")
        assert bot.config.strategy_id == "s1"
        assert bot.config.account_id == "acc-test"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == "s1" == cfg
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

    async def test_strategy_change_same_account_still_validated_and_persisted(
        self, manager_with_account, account_service, ctx, db, tmp_path
    ):
        """(b) account_id 미변경 strategy 변경 → effective(=옛) 계좌로 검증·persist.

        account_id 를 바꾸지 않으므로 불변 가드를 통과하고, strategy 호환성
        검증(옛 계좌=KRX)이 정상 수행되어 KRX 호환 전략으로 교체된다. account_id
        는 무회귀로 옛 값을 유지한다.
        """
        await _make_krx_account(account_service)
        krx_sid = await _register_strategy(
            db, _KRX_STRATEGY_SOURCE, "krx_compat", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot("bot1", strategy_id=krx_sid)

        assert bot.config.strategy_id == krx_sid
        assert bot.config.account_id == "acc-test"
        col, cfg = await _row_strategy_ids(db, "bot1")
        assert col == krx_sid == cfg
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

    async def test_account_id_noop_same_value_passes(
        self, manager_with_account, account_service, ctx, db
    ):
        """(c) account_id 를 같은 값으로 포함 → no-op 통과(거부 아님).

        updates 에 ``account_id`` 가 현재와 동일하게 포함되어도 변경이 아니므로
        불변 가드를 통과한다. ``s1`` 은 미등록이지만 strategy_id 가 그대로라
        검증이 트리거되지 않아 raise 없이 성공한다.
        """
        await _make_krx_account(account_service)
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", name="old", account_id="acc-test"
        )
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot(
            "bot1", account_id="acc-test", name="new"
        )

        assert bot.config.account_id == "acc-test"
        assert bot.config.name == "new"
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

    async def test_account_only_change_to_different_value_rejected(
        self, manager_with_account, account_service, ctx, db
    ):
        """(d) account_id 만 다른 값으로 변경 → ``BotImmutableFieldError`` 거부.

        strategy_id 가 그대로라 strategy 검증은 트리거되지 않지만, account_id
        불변 가드가 다른 값으로의 변경을 거부한다. memory·DB 모두 미변경.
        """
        await _make_krx_account(account_service)
        await _make_krx_account(account_service, account_id="acc-test2")
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(BotImmutableFieldError) as exc_info:
            await manager_with_account.update_bot("bot1", account_id="acc-test2")
        assert exc_info.value.code == BOT_IMMUTABLE_FIELD_CODE

        bot = manager_with_account.get_bot("bot1")
        assert bot.config.account_id == "acc-test"
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg


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


# ── #2274: bots.account_id 컬럼 ↔ config_json.account_id 일관성 회귀 ──────────


class TestUpdateBotAccountConsistency:
    """#2282 (#2274 후속): ``account_id`` 는 ``update_bot`` 의 불변 필드다.
    다른 값으로의 변경은 ``BotImmutableFieldError`` 로 거부된다.

    #2274 가 ``_save_bot_config`` 의 ``ON CONFLICT DO UPDATE SET`` 에
    ``account_id = excluded.account_id`` 를 추가해 컬럼 drift 를 고쳤고, 그
    결과 ``update_bot`` 으로 account_id 를 바꾸면 재시작 시 실제로 복원되며
    treasury 예산·broker credential·포지션이 재배치되지 않는 불일치가 표면화됐다
    (#2282). 정책 결정: ``account_id`` 를 불변 필드로 제약(Account.update 선례
    미러). 단, ``_save_bot_config`` 의 ``account_id = excluded`` UPSERT 자체는
    create/load·내부 persistence(change_strategy 등) 경로의 컬럼↔config_json
    일관성을 위해 그대로 유지된다 — 제약은 ``update_bot`` ingress 에서만 적용.
    """

    async def test_update_account_id_to_different_value_rejected(
        self, manager_with_account, account_service, ctx, db
    ):
        """(a) update_bot(account_id=other) → ``BotImmutableFieldError`` 거부.

        strategy_id 는 그대로(미등록 ``s1``)라 전략 검증을 트리거하지 않지만,
        account_id 불변 가드가 다른 값으로의 변경을 거부한다. 컬럼·config_json
        모두 옛 값으로 미변경이어야 한다.
        """
        await _make_krx_account(account_service)
        await _make_krx_account(account_service, account_id="acc-new")
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        # 생성 직후 컬럼·config_json 모두 옛 값.
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

        with pytest.raises(BotImmutableFieldError) as exc_info:
            await manager_with_account.update_bot("bot1", account_id="acc-new")
        assert exc_info.value.code == BOT_IMMUTABLE_FIELD_CODE

        # 거부 후 memory·컬럼·config_json 모두 옛 값 미변경.
        bot = manager_with_account.get_bot("bot1")
        assert bot.config.account_id == "acc-test"
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

    async def test_save_bot_config_upsert_preserves_account_id_on_internal_persist(
        self, manager_with_account, account_service, eventbus, ctx, db
    ):
        """(b) #2274 무회귀: ``_save_bot_config`` UPSERT(account_id=excluded) 가
        내부 persistence 경로(change_strategy)에서 account_id 컬럼↔config_json
        일관성을 유지하고, 재시작(load_from_db) 시 그대로 복원된다.

        account_id 변경은 ``update_bot`` 에서 거부되지만, ``account_id =
        excluded.account_id`` UPSERT 자체는 create/내부 persistence 경로에서
        유지되어야 한다(#2282 stop condition). change_strategy 는 account_id 를
        바꾸지 않은 채 ``_save_bot_config`` 를 다시 호출하므로, UPSERT 가
        account_id 컬럼을 같은 값으로 일관되게 보존하는지 검증한다.
        """
        await _make_krx_account(account_service)
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        # 내부 persistence 경로(account_id 미변경)로 _save_bot_config 재호출.
        await manager_with_account.change_strategy("bot1", "s2")

        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

        # 재시작 시뮬레이션: 새 매니저로 DB 에서 재로드 → account_id 복원.
        manager2 = BotManager(eventbus=eventbus, db=db)
        await manager2.initialize()
        count = await manager2.load_from_db()
        assert count == 1

        reloaded = manager2.get_bot("bot1")
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert reloaded.config.account_id == acc_col == acc_cfg == "acc-test"

    async def test_simultaneous_strategy_and_account_change_rejected(
        self, manager_with_account, account_service, ctx, db, tmp_path
    ):
        """(c) strategy_id + account_id 동시 변경 → account_id 불변 가드가 먼저 거부.

        account_id 불변 가드가 strategy 검증보다 먼저 평가되므로, 새 전략의
        호환성과 무관하게 ``BotImmutableFieldError`` 로 거부된다. strategy_id·
        account_id 컬럼·config_json 모두 옛 값으로 미변경이어야 한다.
        """
        await _make_krx_account(account_service)
        await _make_nasdaq_account(account_service)
        nasdaq_sid = await _register_strategy(
            db, _NASDAQ_STRATEGY_SOURCE, "nasdaq_only", "1.0.0", tmp_path
        )
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="acc-test")
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(BotImmutableFieldError) as exc_info:
            await manager_with_account.update_bot(
                "bot1", account_id="acc-nasdaq", strategy_id=nasdaq_sid
            )
        assert exc_info.value.code == BOT_IMMUTABLE_FIELD_CODE

        bot = manager_with_account.get_bot("bot1")
        assert bot.config.strategy_id == "s1"
        assert bot.config.account_id == "acc-test"
        sid_col, sid_cfg = await _row_strategy_ids(db, "bot1")
        assert sid_col == "s1" == sid_cfg
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg

    async def test_update_without_account_change_is_noop_on_account_column(
        self, manager_with_account, account_service, ctx, db
    ):
        """(e) account_id 미변경 update(name 만 변경) → account_id 컬럼 무영향."""
        await _make_krx_account(account_service)
        config = BotConfig(
            bot_id="bot1", strategy_id="s1", name="old", account_id="acc-test"
        )
        await manager_with_account.create_bot(config, SimpleStrategy, ctx)

        bot = await manager_with_account.update_bot("bot1", name="new")

        assert bot.config.name == "new"
        assert bot.config.account_id == "acc-test"
        acc_col, acc_cfg = await _row_account_ids(db, "bot1")
        assert acc_col == "acc-test" == acc_cfg
