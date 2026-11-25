"""#2583 규칙이 읽지 않는 key와 쓸 수 없는 값은 저장·생성 지점에서 거부된다.

저장 지점은 쓰기를 거부하고, 생성 지점(``_create_rule``)은 ``RuleConfigError``를 낸다.
기동은 그 계좌만 막고 재로드는 이전 목록을 유지한다(#2624 포함).
"""

from __future__ import annotations

import ast
import inspect
import json
import logging
import math
import sqlite3
import tempfile
import textwrap
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.models import Account, TradingMode
from ante.account.readiness import ALL_FLAGS, RuntimeReadinessRegistry, is_flag_exempt
from ante.approval.handlers import build_executors
from ante.approval.models import ApprovalStatus
from ante.approval.service import ApprovalService
from ante.config.dynamic import DynamicConfigService
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus import EventBus
from ante.eventbus.events import (
    ConfigChangedEvent,
    NotificationEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.main import _RULES_UNAVAILABLE_MESSAGES
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.rule import base as rule_base
from ante.rule import engine as rule_engine_module
from ante.rule.base import RuleContext, RuleResult
from ante.rule.config_update import RULE_ITEM_KEYS, update_account_rule_config
from ante.rule.engine import RULE_REGISTRY, RuleEngine
from ante.rule.exceptions import RuleConfigError
from ante.rule.global_rules import DailyLossLimitRule
from ante.rule.manager import RuleEngineManager
from tests.unit._readiness_gate_helpers import make_account

KEY1 = "accounts.acc1.rules"
LIMIT = {"max_daily_loss_percent": 0.01}
MARK = 0.0371
DEAD_KEY_PARAMS = [
    pytest.param("daily_loss_limit", {"max_daily_loss_rate": 0.01}, id="spec-key"),
    pytest.param("daily_loss_limit", {"max_daily_loss_rate": 5}, id="spec-key-range"),
    pytest.param("daily_loss_limit", {"max_loss_pct": 1}, id="max_loss_pct"),
    pytest.param("daily_loss_limit", {"max_loss_pct": 150}, id="max_loss_pct-150"),
    pytest.param("total_exposure_limit", {"max_exposure_rate": 0.8}, id="exposure"),
    pytest.param("daily_loss_limit", {"action": "halt"}, id="action"),
    pytest.param("trading_hours", {"allowed_hours_start": "09:00"}, id="hours-start"),
    pytest.param("trading_hours", {"allowed_hours_end": "15:30"}, id="hours-end"),
]
LIMIT_KEYS = [
    pytest.param("daily_loss_limit", "max_daily_loss_percent", id="daily"),
    pytest.param("total_exposure_limit", "max_exposure_percent", id="exposure"),
    pytest.param("position_size", "max_position_percent", id="position"),
    pytest.param("unrealized_loss_limit", "max_unrealized_loss_percent", id="unreal"),
]
NON_FINITE = [
    pytest.param(math.nan, id="nan"),
    pytest.param(math.inf, id="inf"),
    pytest.param(-math.inf, id="-inf"),
]


def _context(daily_loss: float = 0.5, **overrides: Any) -> RuleContext:
    fields: dict[str, Any] = {
        "bot_id": "bot1",
        "account_id": "acc1",
        "strategy_id": "s1",
        "symbol": "005930",
        "side": "buy",
        "quantity": 1.0,
        "order_type": "limit",
        "current_price": 1000.0,
        "current_position": 90.0,
        "bot_allocated_budget": 100000.0,
        "unrealized_pnl": -50000.0,
        "daily_pnl": -100000.0 * daily_loss,
        "prev_day_total_asset": 100000.0,
        "total_asset": 100000.0,
        "total_exposure": 90000.0,
    }
    fields.update(overrides)
    return RuleContext(**fields)


def _registry(accounts: list[Account]) -> RuntimeReadinessRegistry:
    reg = RuntimeReadinessRegistry()
    for account in accounts:
        for flag in ALL_FLAGS:
            if not is_flag_exempt(
                flag,
                broker_type=account.broker_type,
                trading_mode=account.trading_mode,
            ):
                reg.mark_ready(account.account_id, flag)
    return reg


class _StaticSeed:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


class _Captured:
    def __init__(self, bus: EventBus) -> None:
        self.validated: list[OrderValidatedEvent] = []
        self.rejected: list[OrderRejectedEvent] = []
        self.modify_rejected: list[OrderModifyRejectedEvent] = []
        self.notifications: list[NotificationEvent] = []
        bus.subscribe(OrderValidatedEvent, self.validated.append)
        bus.subscribe(OrderRejectedEvent, self.rejected.append)
        bus.subscribe(OrderModifyRejectedEvent, self.modify_rejected.append)
        bus.subscribe(NotificationEvent, self.notifications.append)


class _World:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.accounts = [
            make_account("acc1", broker_type="test", trading_mode=TradingMode.VIRTUAL),
            make_account("acc2", broker_type="test", trading_mode=TradingMode.VIRTUAL),
        ]
        by_id = {a.account_id: a for a in self.accounts}
        self.account_service = MagicMock()
        self.account_service.get = AsyncMock(side_effect=lambda a: by_id[a])
        self.dyn = DynamicConfigService(db, self.bus)
        self.changes: list[ConfigChangedEvent] = []
        self.manager: RuleEngineManager | None = None

    async def update(
        self, rule_type: str, params: dict[str, Any], account_id: str = "acc1"
    ) -> dict[str, Any]:
        return await update_account_rule_config(
            account_service=self.account_service,
            dynamic_config=self.dyn,
            account_id=account_id,
            rule_type=rule_type,
            params=params,
            changed_by="test",
        )

    async def store_raw(self, account_id: str, value: list[Any]) -> None:
        await self.dyn.set(
            f"accounts.{account_id}.rules", value, category="rule", changed_by="t"
        )

    async def start(self, config: Any = None) -> RuleEngineManager:
        manager = RuleEngineManager(
            eventbus=self.bus,
            account_service=self.account_service,
            runtime_readiness=_registry(self.accounts),
        )
        await manager.initialize_all(
            self.accounts, config=config, dynamic_config=self.dyn
        )
        self.manager = manager
        return manager

    async def raw(self) -> str | None:
        row = await self.db.fetch_one(
            "SELECT value FROM dynamic_config WHERE key=?", (KEY1,)
        )
        return None if row is None else str(row["value"])

    def engine(self, account_id: str = "acc1") -> RuleEngine:
        assert self.manager is not None
        return self.manager.get(account_id)

    def result(self, daily_loss: float) -> RuleResult:
        return self.engine().evaluate(_context(daily_loss)).overall_result


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def world(db: Database):
    w = _World(db)
    await w.dyn.initialize()
    await w.update("daily_loss_limit", dict(LIMIT))
    await w.update("daily_loss_limit", dict(LIMIT), account_id="acc2")
    await w.start()
    w.bus.subscribe(ConfigChangedEvent, w.changes.append)
    return w


def _self_config_keys(cls: type) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(cls)))
    parents = {id(c): p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}
    keys: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Attribute)
            and node.attr == "config"
            and isinstance(node.value, ast.Name)
            and node.value.id == "self"
        ):
            continue
        get = parents.get(id(node))
        call = parents.get(id(get))
        assert isinstance(get, ast.Attribute) and get.attr == "get", repr(get)
        assert isinstance(call, ast.Call) and call.func is get, repr(call)
        first = call.args[0] if call.args else None
        assert isinstance(first, ast.Constant) and isinstance(first.value, str)
        keys.add(first.value)
    return keys


def _config_get_keys(func: Any) -> set[str]:
    tree = ast.parse(textwrap.dedent(inspect.getsource(func)))
    keys: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "config"
        ):
            first = node.args[0]
            assert isinstance(first, ast.Constant) and isinstance(first.value, str)
            keys.add(first.value)
    return keys


def test_each_rule_declares_exactly_the_keys_it_reads() -> None:
    checked = 0
    for rule_class in RULE_REGISTRY.values():
        declared = rule_class.CONFIG_KEYS
        assert declared, rule_class.__name__
        assert _self_config_keys(rule_class) == set(declared), rule_class.__name__
        checked += 1
    assert checked == len(RULE_REGISTRY) == 6


def test_common_keys_are_what_rule_init_and_create_rule_read() -> None:
    read = _config_get_keys(rule_base.Rule.__init__) | _config_get_keys(
        rule_engine_module.RuleEngine._create_rule
    )
    assert read == set(rule_base.COMMON_CONFIG_KEYS)
    assert set(RULE_ITEM_KEYS) <= set(rule_base.COMMON_CONFIG_KEYS)


def test_range_table_has_only_declared_keys() -> None:
    assert set(DailyLossLimitRule._PARAM_LIMITS) <= DailyLossLimitRule.CONFIG_KEYS
    assert "max_loss_pct" not in DailyLossLimitRule._PARAM_LIMITS


def test_declared_keys_match_the_issue_table() -> None:
    assert {t: set(c.CONFIG_KEYS) for t, c in RULE_REGISTRY.items()} == {
        "daily_loss_limit": {"max_daily_loss_percent"},
        "total_exposure_limit": {"max_exposure_percent", "max_exposure_amount"},
        "trading_hours": {"allowed_hours", "timezone"},
        "position_size": {"max_position_percent", "max_position_amount"},
        "unrealized_loss_limit": {"max_unrealized_loss_percent"},
        "trade_frequency": {"max_trades_per_hour"},
    }


# ── 저장 지점 ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("rule_type", "params"), DEAD_KEY_PARAMS)
async def test_store_rejects_keys_the_rule_does_not_read(
    world: _World, rule_type: str, params: dict[str, Any]
) -> None:
    before = await world.raw()
    rules_before = list(world.engine()._account_rules)
    assert world.result(0.02) == RuleResult.REJECT

    with pytest.raises(ValueError) as exc_info:
        await world.update(rule_type, params)

    assert await world.raw() == before
    assert world.changes == []
    assert all(
        a is b for a, b in zip(world.engine()._account_rules, rules_before, strict=True)
    )
    assert world.result(0.02) == RuleResult.REJECT
    message = str(exc_info.value)
    assert message.startswith("룰 config 검증 실패: ")
    (key,) = params
    assert f"{key!r} is not a config key of {rule_type}" in message
    assert repr(params[key]) not in message.replace(f"{key!r}", "")


async def test_store_accepts_the_code_key_and_common_keys(world: _World) -> None:
    await world.update("daily_loss_limit", {"max_daily_loss_percent": 0.05})
    assert world.result(0.02) == RuleResult.PASS

    result = await world.update(
        "daily_loss_limit",
        {**LIMIT, "name": "일일", "description": "설명", "priority": 5},
    )

    assert result["rule"]["params"] == {
        **LIMIT,
        "name": "일일",
        "description": "설명",
        "priority": 5,
    }
    assert world.result(0.02) == RuleResult.REJECT
    assert world.result(0.06) == RuleResult.REJECT
    assert world.engine()._account_rules[0].name == "일일"


async def test_store_error_order_is_priority_unknown_then_range(world: _World) -> None:
    with pytest.raises(ValueError) as exc_info:
        await world.update(
            "daily_loss_limit",
            {"priority": "high", "max_daily_loss_rate": 0.01, "zzz": 1, **LIMIT},
        )
    assert str(exc_info.value) == (
        "룰 config 검증 실패: priority must be an integer; "
        "'max_daily_loss_rate' is not a config key of daily_loss_limit "
        "(rule keys: max_daily_loss_percent); "
        "'zzz' is not a config key of daily_loss_limit "
        "(rule keys: max_daily_loss_percent)"
    )

    with pytest.raises(ValueError) as exc_info:
        await world.update(
            "daily_loss_limit", {"max_daily_loss_percent": 5, "action": "halt"}
        )
    assert str(exc_info.value) == (
        "룰 config 검증 실패: 'action' is not a config key of daily_loss_limit "
        "(rule keys: max_daily_loss_percent); max_daily_loss_percent must be <= 1"
    )


_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status=MemberStatus.ACTIVE,
    scopes=[],
)


def _seed_cli(config_dir: Path) -> Path:
    import asyncio

    from ante.account.crypto import encrypt_credentials
    from ante.account.service import AccountService

    (config_dir / "db").mkdir(parents=True, exist_ok=True)
    db_path = config_dir / "db" / "ante.db"

    async def _seed() -> None:
        database = Database(str(db_path))
        await database.connect()
        try:
            await AccountService(db=database, eventbus=EventBus()).initialize()
            await database.execute(
                "INSERT INTO accounts (account_id, name, exchange, currency, "
                "broker_type, trading_mode, credentials, broker_config, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *("acc1", "A", "KRX", "KRW", "test", "virtual"),
                    *(encrypt_credentials({}), "{}", "active"),
                ),
            )
        finally:
            await database.close()

    asyncio.run(_seed())
    return db_path


def _cli(config_dir: Path, *extra: str):
    from ante.cli.main import cli

    args = ["--config-dir", str(config_dir), "--format", "json", "rule", "update"]
    args += ["daily_loss_limit", "--account", "acc1", *extra]
    with (
        patch(
            "ante.cli.main.authenticate_member",
            side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
        ),
        patch("ante.cli.cold_path.is_active_runtime", return_value=False),
    ):
        return CliRunner().invoke(
            cli, args, env={"ANTE_MEMBER_TOKEN": ""}, catch_exceptions=False
        )


def _stored_cli(db_path: Path) -> str | None:
    conn = sqlite3.connect(str(db_path))
    try:
        row = conn.execute(
            "SELECT value FROM dynamic_config WHERE key=?", (KEY1,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else str(row[0])


@pytest.mark.parametrize(
    "param",
    [f"max_daily_loss_rate={MARK}", "max_loss_pct=1", "action=halt"],
)
def test_cli_direct_path_rejects_like_nan(tmp_path: Path, param: str) -> None:
    config_dir = tmp_path / "config"
    db_path = _seed_cli(config_dir)
    ok = _cli(config_dir, "--param", "max_daily_loss_percent=0.01")
    assert ok.exit_code == 0, ok.output
    before = _stored_cli(db_path)

    nan = _cli(config_dir, "--param", "max_daily_loss_percent=nan")
    result = _cli(config_dir, "--param", param)

    assert result.exit_code == nan.exit_code == 1
    assert json.loads(nan.output)["code"] == "RULE_UPDATE_ERROR"
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "RULE_UPDATE_ERROR"
    assert param.split("=", 1)[0] in payload["message"]
    assert str(MARK) not in result.output
    assert "halt" not in result.output
    assert _stored_cli(db_path) == before


async def _dispatch(world: _World, args: dict[str, Any]) -> dict[str, Any]:
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    svc_registry = ServiceRegistry(
        account=world.account_service,
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=world.dyn,
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=world.bus,
        audit_logger=MagicMock(log=AsyncMock()),
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc2583", dir="/tmp")
    server = IPCServer(str(Path(socket_dir) / "t.sock"), svc_registry, cmd_registry)
    await server.start()
    try:
        return await server._dispatch(
            {"id": "1", "command": "rule.update", "args": args, "actor": "bob"}
        )
    finally:
        await server.stop()


async def _ipc_update(
    world: _World, rule_type: str, params: dict[str, Any]
) -> dict[str, Any]:
    return await _dispatch(
        world, {"account_id": "acc1", "rule_type": rule_type, "params": params}
    )


async def test_ipc_rejects_like_nan(world: _World) -> None:
    before = await world.raw()

    nan = await _ipc_update(world, "daily_loss_limit", {"max_daily_loss_percent": "x"})
    response = await _ipc_update(
        world, "daily_loss_limit", {"max_daily_loss_rate": MARK}
    )

    assert nan["error"]["code"] == "EXECUTION_ERROR"
    assert response["status"] == "error", response
    assert response["error"]["code"] == "EXECUTION_ERROR"
    assert "max_daily_loss_rate" in response["error"]["message"]
    assert str(MARK) not in json.dumps(response)
    assert await world.raw() == before
    assert world.changes == []


# ── 생성 지점 (#2624) ────────────────────────────────────────────────────────


def _engine() -> RuleEngine:
    engine = RuleEngine(eventbus=EventBus(), account_id="acc1")
    engine.set_bot_strategy_resolver(lambda bot_id: "s1")
    return engine


def _evaluate_strategy(engine: RuleEngine) -> RuleResult:
    return engine.evaluate(_context()).overall_result


@pytest.mark.parametrize("value", NON_FINITE)
@pytest.mark.parametrize(("rule_type", "key"), LIMIT_KEYS)
def test_non_finite_limit_is_rejected_at_creation(
    rule_type: str, key: str, value: float
) -> None:
    item = {"type": rule_type, key: value}
    engine = _engine()
    engine.load_rules_from_config([{"type": rule_type, key: 0.05}])
    engine.load_strategy_rules_from_config("s1", [{"type": rule_type, key: 0.05}])
    account_before = list(engine._account_rules)
    strategy_before = list(engine._strategy_rules["s1"])

    with pytest.raises(RuleConfigError, match=f"{key} must be a finite number"):
        engine.load_rules_from_config([item])
    with pytest.raises(RuleConfigError):
        engine.load_strategy_rules_from_config("s1", [item])
    with pytest.raises(RuleConfigError):
        engine.update_rules("bot1", [item])

    assert engine._account_rules == account_before
    assert engine._strategy_rules["s1"] == strategy_before


@pytest.mark.parametrize(("rule_type", "key"), LIMIT_KEYS)
def test_finite_limit_control_rejects_the_big_loss(rule_type: str, key: str) -> None:
    engine = _engine()

    engine.load_rules_from_config([{"type": rule_type, key: 0.05}])

    assert len(engine._account_rules) == 1
    assert _evaluate_strategy(engine) == RuleResult.REJECT


def test_issue_2624_nan_rule_is_not_built() -> None:
    engine = _engine()

    with pytest.raises(RuleConfigError):
        engine.load_rules_from_config(
            [{"type": "daily_loss_limit", "max_daily_loss_percent": math.nan}]
        )

    assert engine._account_rules == []


@pytest.mark.parametrize(
    "item",
    [
        pytest.param({"type": "daily_loss_limit", "max_daily_loss_rate": 0.01}, id="k"),
        pytest.param(
            {"type": "daily_loss_limit", "enabled": False, "max_loss_pct": 1},
            id="disabled",
        ),
        pytest.param({"type": "daily_loss_limit", "id": 5}, id="int-id"),
        pytest.param({"type": "trading_hours", "id": None}, id="null-id"),
    ],
)
def test_unknown_key_and_non_str_id_are_rejected_at_creation(
    item: dict[str, Any],
) -> None:
    with pytest.raises(RuleConfigError):
        _engine().load_rules_from_config([item])


def test_creation_keeps_seed_and_unknown_type_skip() -> None:
    engine = _engine()

    engine.load_rules_from_config(
        [
            {"type": "trading_hours", "enabled": True},
            {"type": "nope", "whatever": 1},
            {"type": "daily_loss_limit", "id": "d1", "name": "n", **LIMIT},
        ]
    )

    assert [r.rule_id for r in engine._account_rules] == ["trading_hours", "d1"]


@pytest.mark.parametrize(
    "rules",
    [
        pytest.param(
            [{"type": "position_size", "max_position_percent": math.nan}], id="nan"
        ),
        pytest.param([{"type": "position_size", "max_quantity": 1}], id="unknown-key"),
    ],
)
async def test_approval_rule_change_fails_execution(db, rules: list[Any]) -> None:
    engine = _engine()
    deps = SimpleNamespace(rule_engine_manager=SimpleNamespace(get=lambda a: engine))
    svc = ApprovalService(db=db, eventbus=EventBus(), executors=build_executors(deps))
    await svc.initialize()
    req = await svc.create(
        type="rule_change",
        requester="agent",
        title="규칙 변경",
        params={"account_id": "acc1", "bot_id": "bot1", "rules": rules},
    )

    await svc.approve(req.id)

    stored = await svc.get(req.id)
    assert stored is not None
    assert stored.status == ApprovalStatus.EXECUTION_FAILED
    assert "s1" not in engine._strategy_rules


# ── 기동 ─────────────────────────────────────────────────────────────────────


def _toml_seed(text: str) -> _StaticSeed:
    parsed = tomllib.loads(text)
    return _StaticSeed({KEY1: parsed["accounts"]["acc1"]["rules"]})


STARTUP_CASES = [
    pytest.param(
        "seed",
        '[accounts.acc1]\nrules = [{ type = "daily_loss_limit", '
        "max_daily_loss_percent = nan }]\n",
        "max_daily_loss_percent must be a finite number",
        id="toml-nan",
    ),
    pytest.param(
        "dynamic",
        [{"type": "daily_loss_limit", "max_daily_loss_rate": MARK}],
        "'max_daily_loss_rate' is not a config key of daily_loss_limit",
        id="unknown-key",
    ),
    pytest.param(
        "dynamic",
        [{"type": "daily_loss_limit", "max_daily_loss_percent": 7.0371}],
        "max_daily_loss_percent must be <= 1",
        id="out-of-range",
    ),
    pytest.param(
        "dynamic",
        [{"type": "daily_loss_limit", "id": 987654}],
        "id must be a string",
        id="int-id",
    ),
    pytest.param(
        "dynamic",
        [
            {"type": "total_exposure_limit"},
            {"type": "daily_loss_limit", "enabled": False, "max_loss_pct": MARK},
        ],
        "'max_loss_pct' is not a config key of daily_loss_limit",
        id="disabled-unknown-key",
    ),
]


async def _startup_world(db: Database, source: str, value: Any) -> _World:
    world = _World(db)
    await world.dyn.initialize()
    await world.update("daily_loss_limit", dict(LIMIT), account_id="acc2")
    if source == "seed":
        await world.start(_toml_seed(value))
    else:
        await world.store_raw("acc1", value)
        await world.start()
    return world


@pytest.mark.parametrize(("source", "value", "key"), STARTUP_CASES)
async def test_startup_blocks_only_that_account(
    db, caplog, source: str, value: Any, key: str
) -> None:
    caplog.set_level(logging.INFO)
    world = await _startup_world(db, source, value)
    assert world.manager is not None
    cap = _Captured(world.bus)

    assert world.manager.rules_unavailable_accounts() == {"acc1": "invalid_item"}
    assert world.engine("acc1")._account_rules == []
    assert world.engine("acc2").rules_unavailable is False
    assert len(world.engine("acc2")._account_rules) == 1
    errors = [
        r
        for r in caplog.records
        if r.levelno == logging.ERROR and r.name == "ante.rule.manager"
    ]
    assert len(errors) == 1
    assert "invalid_item:RuleConfigError" in errors[0].getMessage()
    rule_log = "\n".join(
        caplog.handler.format(r)
        for r in caplog.records
        if r.name.startswith("ante.rule")
    )
    assert key in rule_log
    for marker in (str(MARK), "7.0371", "987654"):
        assert marker not in rule_log

    await world.bus.publish(_order("acc1"))
    await world.bus.publish(_order("acc1", side="sell", reason="liquidation:bot"))
    await world.bus.publish(_modify("acc1"))
    await world.bus.publish(_order("acc2"))

    blocked = [e for e in cap.rejected if "rules_unavailable" in e.reason]
    assert [e.account_id for e in blocked] == ["acc1", "acc1"]
    assert all(e.account_id != "acc1" for e in cap.validated)
    assert [e.account_id for e in cap.modify_rejected] == ["acc1"]


def _order(account_id: str, *, side: str = "buy", reason: str = "") -> Any:
    return OrderRequestEvent(
        account_id=account_id,
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side=side,
        quantity=1.0,
        order_type="limit",
        price=50000.0,
        reason=reason,
    )


def _modify(account_id: str) -> OrderModifyEvent:
    return OrderModifyEvent(
        account_id=account_id,
        bot_id="bot1",
        strategy_id="s1",
        order_id="ord-1",
        symbol="005930",
        side="buy",
        quantity=1.0,
        price=50000.0,
    )


def test_startup_notice_names_the_new_causes_without_keys() -> None:
    message = _RULES_UNAVAILABLE_MESSAGES["invalid_item"]
    assert "규칙이 읽지 않는 키" in message
    assert "범위 밖 값" in message
    assert "문자열이 아닌 id" in message
    assert "ante rule update <rule_type> --account {id}" in message
    assert "max_daily_loss" not in message
    assert (
        "규칙 객체가 아닌 항목·해시할 수 없는 type의 항목·같은 유형의 둘째 이후 "
        "깨진 항목은 어느 유형으로든 rule update를 한 번 하면 저장값에서 버려져 "
        "풀립니다" in message
    )
    assert "rule update로 풀리지 않습니다" not in message


# ── 재로드 ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        pytest.param([{"type": "daily_loss_limit", "max_daily_loss_rate": MARK}]),
        pytest.param([{"type": "daily_loss_limit", "max_daily_loss_percent": 9.5}]),
    ],
)
async def test_reload_keeps_previous_rules_and_notifies(
    world: _World, value: list[Any]
) -> None:
    engine = world.engine()
    before = list(engine._account_rules)
    cap = _Captured(world.bus)

    await world.store_raw("acc1", value)

    assert all(a is b for a, b in zip(engine._account_rules, before, strict=True))
    assert engine.rules_unavailable is False
    assert [n.title for n in cap.notifications] == [
        "계좌 규칙을 다시 읽지 못함 — 이전 규칙 유지"
    ]
    assert "RuleConfigError" in cap.notifications[0].message
    assert str(MARK) not in cap.notifications[0].message
    assert world.result(0.02) == RuleResult.REJECT


# ── 해제 (데몬이 떠 있는 상태, IPC rule.update) ──────────────────────────────


async def test_rule_update_of_that_type_releases_unknown_key_block(db) -> None:
    world = await _startup_world(
        db, "dynamic", [{"type": "daily_loss_limit", "max_daily_loss_rate": MARK}]
    )
    assert world.engine().rules_unavailable_cause == "invalid_item"

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    assert world.engine().rules_unavailable is False
    assert world.result(0.02) == RuleResult.REJECT


async def test_rule_update_of_that_type_releases_non_string_id_block(db) -> None:
    world = await _startup_world(
        db, "dynamic", [{"type": "daily_loss_limit", "id": 987654}]
    )
    assert world.engine().rules_unavailable_cause == "invalid_item"

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    stored = json.loads(await world.raw() or "null")
    assert all("id" not in item for item in stored)
    assert world.engine().rules_unavailable is False
    assert world.result(0.02) == RuleResult.REJECT


async def test_broken_item_of_another_type_keeps_the_block(db) -> None:
    world = await _startup_world(
        db,
        "dynamic",
        [
            {"type": "daily_loss_limit", "max_daily_loss_rate": MARK},
            {"type": "total_exposure_limit", "max_exposure_rate": 0.8},
        ],
    )

    await _ipc_update(world, "daily_loss_limit", dict(LIMIT))
    assert world.engine().rules_unavailable_cause == "invalid_item"

    await _ipc_update(world, "total_exposure_limit", {"max_exposure_percent": 0.8})
    assert world.engine().rules_unavailable is False


STORED = {"type": "daily_loss_limit", "enabled": True, **LIMIT}
DROPPED_LOGGER = "ante.rule.config_update"


def _dropped_notices(cap: _Captured) -> list[NotificationEvent]:
    return [n for n in cap.notifications if n.level == "warning"]


@pytest.mark.parametrize(
    "broken",
    [
        pytest.param({"max_daily_loss_rate": MARK}, id="unknown-key"),
        pytest.param({"max_daily_loss_percent": 9.5}, id="out-of-range"),
        pytest.param({"priority": "1", **LIMIT}, id="str-priority"),
        pytest.param({"id": 987654, **LIMIT}, id="non-str-id"),
        pytest.param({"enabled": False, "max_loss_pct": MARK}, id="disabled"),
    ],
)
async def test_second_broken_item_of_the_same_type_is_dropped(
    db, caplog, broken: dict[str, Any]
) -> None:
    world = await _startup_world(
        db,
        "dynamic",
        [{"type": "daily_loss_limit", **LIMIT}, {"type": "daily_loss_limit", **broken}],
    )
    assert world.engine().rules_unavailable_cause == "invalid_item"
    cap = _Captured(world.bus)
    caplog.set_level(logging.DEBUG, logger=DROPPED_LOGGER)

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    judged = [
        r
        for r in caplog.records
        if r.name == DROPPED_LOGGER and r.levelno == logging.DEBUG
    ]
    assert len(judged) == (0 if "priority" in broken else 1)
    for record in judged:
        assert record.exc_info is not None
        assert "index=1" in record.getMessage()
    drop_log = "\n".join(
        caplog.handler.format(r) for r in caplog.records if r.name == DROPPED_LOGGER
    )
    for marker in (str(MARK), "9.5", "987654"):
        assert marker not in drop_log
    assert json.loads(await world.raw() or "null") == [STORED]
    assert world.engine().rules_unavailable is False
    assert world.result(0.02) == RuleResult.REJECT
    assert len(_dropped_notices(cap)) == 1
    assert str(MARK) not in _dropped_notices(cap)[0].message


async def test_broken_first_then_healthy_second_keeps_the_second(db) -> None:
    healthy = {
        "type": "daily_loss_limit",
        "id": "second",
        "max_daily_loss_percent": 0.5,
    }
    world = await _startup_world(
        db,
        "dynamic",
        [{"type": "daily_loss_limit", "max_daily_loss_rate": MARK}, healthy],
    )
    cap = _Captured(world.bus)

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    assert json.loads(await world.raw() or "null") == [STORED, healthy]
    assert world.engine().rules_unavailable is False
    assert world.result(0.02) == RuleResult.REJECT
    assert _dropped_notices(cap) == []


@pytest.mark.parametrize(
    "kept",
    [
        pytest.param(
            [{"type": "daily_loss_limit", "id": "b", "max_daily_loss_percent": 0.5}],
            id="healthy-duplicate",
        ),
        pytest.param(
            [{"type": "daily_loss_limit", "id": "b", "enabled": False, **LIMIT}],
            id="disabled-healthy-duplicate",
        ),
        pytest.param([{"type": "no_such_rule", "x": 1}], id="unregistered"),
        pytest.param([{"max_daily_loss_rate": MARK}], id="no-type"),
        pytest.param([{"type": 7}], id="non-str-type"),
        pytest.param(
            [{"type": "no_such_rule"}, {"type": "no_such_rule", "priority": "1"}],
            id="unregistered-duplicate-str-priority",
        ),
        pytest.param(
            [{"priority": 1}, {"priority": "1"}], id="no-type-duplicate-str-priority"
        ),
    ],
)
async def test_items_that_do_not_block_are_kept(db, kept: list[Any]) -> None:
    world = await _startup_world(db, "dynamic", [{"type": "daily_loss_limit", **LIMIT}])
    await world.store_raw("acc1", [{"type": "daily_loss_limit", **LIMIT}, *kept])
    assert world.engine().rules_unavailable is False
    cap = _Captured(world.bus)

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    assert json.loads(await world.raw() or "null") == [STORED, *kept]
    assert world.engine().rules_unavailable is False
    assert world.result(0.02) == RuleResult.REJECT
    assert _dropped_notices(cap) == []


@pytest.mark.parametrize(
    "other",
    [
        pytest.param({"max_exposure_rate": 0.8}, id="unknown-key"),
        pytest.param({"max_exposure_percent": 9.5}, id="out-of-range"),
    ],
)
async def test_fixable_item_of_another_type_is_kept(db, other: dict[str, Any]) -> None:
    other_item = {"type": "total_exposure_limit", **other}
    world = await _startup_world(
        db, "dynamic", [{"type": "daily_loss_limit", **LIMIT}, other_item]
    )
    cap = _Captured(world.bus)

    response = await _ipc_update(world, "daily_loss_limit", dict(LIMIT))

    assert response["status"] == "ok", response
    assert json.loads(await world.raw() or "null") == [STORED, other_item]
    assert world.engine().rules_unavailable_cause == "invalid_item"
    assert _dropped_notices(cap) == []


async def test_running_account_drops_and_reloads(db, caplog) -> None:
    world = await _startup_world(db, "dynamic", [{"type": "daily_loss_limit", **LIMIT}])
    engine = world.engine()
    assert engine.rules_unavailable is False
    await world.db.execute(
        "UPDATE dynamic_config SET value=? WHERE key=?",
        (json.dumps([{"type": "daily_loss_limit", **LIMIT}, 5]), KEY1),
    )
    cap = _Captured(world.bus)
    caplog.set_level(logging.INFO)

    response = await _ipc_update(
        world, "daily_loss_limit", {"max_daily_loss_percent": 0.5}
    )

    assert response["status"] == "ok", response
    assert json.loads(await world.raw() or "null") == [
        {"type": "daily_loss_limit", "enabled": True, "max_daily_loss_percent": 0.5}
    ]
    assert engine.rules_unavailable is False
    assert world.result(0.02) == RuleResult.PASS
    assert world.result(0.6) == RuleResult.REJECT
    assert [n.level for n in cap.notifications] == ["warning"]
    assert any(
        r.name == DROPPED_LOGGER and r.levelno == logging.WARNING
        for r in caplog.records
    )
