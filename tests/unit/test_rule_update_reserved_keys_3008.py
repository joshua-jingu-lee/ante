"""#3008 ``rule update``의 params는 규칙 항목 key를 덮지 못하고 priority는 정수다.

거부는 저장 전이다: 저장값·``ConfigChangedEvent``·엔진의 규칙이 그대로다.
정당한 파라미터·``enabled``·정수 priority의 갱신은 그대로다(대조군).
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.account.models import Account, TradingMode
from ante.account.readiness import ALL_FLAGS, RuntimeReadinessRegistry, is_flag_exempt
from ante.config.dynamic import DynamicConfigService
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus import EventBus
from ante.eventbus.events import ConfigChangedEvent
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from ante.rule import config_update
from ante.rule.base import RuleContext, RuleResult
from ante.rule.config_update import rule_config_to_item, update_account_rule_config
from ante.rule.manager import RuleEngineManager
from tests.unit._readiness_gate_helpers import make_account

KEY = "accounts.acc1.rules"
RULE_ITEM_KEYS = frozenset({"type", "id", "enabled"})
LIMIT = {"max_daily_loss_percent": 0.01}
EXPOSURE = {"max_exposure_percent": 0.9}
RESERVED_VALUES: dict[str, Any] = {"type": "bogus", "enabled": False, "id": "x1"}
BAD_PRIORITIES = [
    pytest.param("high", id="str"),
    pytest.param(True, id="bool"),
    pytest.param(None, id="none"),
    pytest.param(1.5, id="float"),
]


def _over_limit_buy() -> RuleContext:
    return RuleContext(
        bot_id="bot1",
        account_id="acc1",
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=1.0,
        order_type="limit",
        current_price=50000.0,
        current_position=0.0,
        available_balance=1000000.0,
        bot_allocated_budget=1000000.0,
        account_status="active",
        daily_pnl=-2000.0,
        total_pnl=0.0,
        prev_day_total_asset=100000.0,
    )


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


class _World:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.account = make_account(
            "acc1", broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        self.account_service = MagicMock()
        self.account_service.get = AsyncMock(return_value=self.account)
        self.dyn = DynamicConfigService(db, self.bus)
        self.changes: list[ConfigChangedEvent] = []
        self.manager: RuleEngineManager | None = None

    async def update(
        self, rule_type: str, params: dict[str, Any], enabled: bool | None = None
    ) -> dict[str, Any]:
        return await update_account_rule_config(
            account_service=self.account_service,
            dynamic_config=self.dyn,
            account_id="acc1",
            rule_type=rule_type,
            params=params,
            enabled=enabled,
            changed_by="test",
        )

    async def start(self) -> RuleEngineManager:
        manager = RuleEngineManager(
            eventbus=self.bus,
            account_service=self.account_service,
            runtime_readiness=_registry([self.account]),
        )
        await manager.initialize_all([self.account], dynamic_config=self.dyn)
        self.manager = manager
        return manager

    async def raw(self) -> str:
        row = await self.db.fetch_one(
            "SELECT value FROM dynamic_config WHERE key=?", (KEY,)
        )
        assert row is not None
        return str(row["value"])

    def engine_rules(self) -> list[tuple[Any, Any, Any]]:
        assert self.manager is not None
        return [
            (r.config.get("type"), r.rule_id, r.enabled)
            for r in self.manager.get("acc1")._account_rules
        ]

    def over_limit_result(self) -> RuleResult:
        assert self.manager is not None
        return self.manager.get("acc1").evaluate(_over_limit_buy()).overall_result


@pytest.fixture
async def world(tmp_path: Path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    w = _World(database)
    await w.dyn.initialize()
    await w.update("daily_loss_limit", dict(LIMIT))
    await w.update("total_exposure_limit", dict(EXPOSURE))
    await w.start()
    w.bus.subscribe(ConfigChangedEvent, w.changes.append)
    yield w
    await database.close()


def _bad_params() -> list[Any]:
    cases = [
        pytest.param({key: RESERVED_VALUES[key]}, id=f"reserved-{key}")
        for key in sorted(RULE_ITEM_KEYS)
    ]
    cases.append(
        pytest.param(
            {"type": "bogus", "enabled": False, "id": "x1", **LIMIT}, id="all-three"
        )
    )
    cases += [
        pytest.param({"priority": v, **LIMIT}, id=f"priority-{p.id}")
        for p in BAD_PRIORITIES
        for v in p.values
    ]
    return cases


def test_reserved_keys_are_the_response_split_keys() -> None:
    assert getattr(config_update, "RULE_ITEM_KEYS", None) == RULE_ITEM_KEYS
    item = rule_config_to_item(
        {"type": "t", "id": "i", "enabled": True, "priority": 3, "p": 1}
    )
    assert item["params"] == {"priority": 3, "p": 1}


@pytest.mark.parametrize("enabled", [None, True, False])
@pytest.mark.parametrize("params", _bad_params())
async def test_rejected_before_store(
    world: _World, params: dict[str, Any], enabled: bool | None
) -> None:
    before = await world.raw()
    rules_before = world.engine_rules()
    assert world.over_limit_result() == RuleResult.REJECT

    with pytest.raises(ValueError) as exc_info:
        await world.update("daily_loss_limit", params, enabled=enabled)

    assert await world.raw() == before
    assert world.changes == []
    assert world.engine_rules() == rules_before
    assert world.over_limit_result() == RuleResult.REJECT

    message = str(exc_info.value)
    for key in sorted(params.keys() & RULE_ITEM_KEYS):
        assert repr(key) in message
    if not params.keys() & RULE_ITEM_KEYS:
        assert message == "룰 config 검증 실패: priority must be an integer"
    for value in params.values():
        if isinstance(value, str):
            assert value not in message
        else:
            assert repr(value) not in message

    fresh = await world.start()
    assert fresh.rules_unavailable_accounts() == {}
    assert world.over_limit_result() == RuleResult.REJECT


async def test_reserved_message_names_the_right_paths(world: _World) -> None:
    with pytest.raises(ValueError) as exc_info:
        await world.update("daily_loss_limit", {"enabled": False, "type": "bogus"})

    message = str(exc_info.value)
    assert "'enabled', 'type'" in message
    assert "rule_type" in message
    assert "--disabled" in message
    assert "bogus" not in message


async def test_valid_param_update_is_unchanged(world: _World) -> None:
    result = await world.update("daily_loss_limit", {"max_daily_loss_percent": 0.02})

    assert result["rule"] == {
        "type": "daily_loss_limit",
        "enabled": True,
        "params": {"max_daily_loss_percent": 0.02},
    }
    stored = json.loads(await world.raw())
    assert stored[0] == {
        "type": "daily_loss_limit",
        "enabled": True,
        "max_daily_loss_percent": 0.02,
    }
    assert len(world.changes) == 1
    assert world.over_limit_result() == RuleResult.PASS


@pytest.mark.parametrize("priority", [5, 0, -3])
async def test_integer_priority_is_accepted(world: _World, priority: int) -> None:
    result = await world.update(
        "daily_loss_limit", {"priority": priority, **LIMIT}, enabled=None
    )

    assert result["rule"]["params"] == {"priority": priority, **LIMIT}
    stored = json.loads(await world.raw())
    assert stored[0]["priority"] == priority
    assert len(world.changes) == 1
    assert len(world.engine_rules()) == 2
    fresh = await world.start()
    assert fresh.rules_unavailable_accounts() == {}
    priorities = [r.priority for r in fresh.get("acc1")._account_rules]
    assert priorities == sorted(priorities)
    assert world.over_limit_result() == RuleResult.REJECT


@pytest.mark.parametrize("enabled", [False, True])
async def test_enabled_field_is_unchanged(world: _World, enabled: bool) -> None:
    result = await world.update("daily_loss_limit", dict(LIMIT), enabled=enabled)

    assert result["rule"]["enabled"] is enabled
    assert json.loads(await world.raw())[0]["enabled"] is enabled
    expected = RuleResult.REJECT if enabled else RuleResult.PASS
    assert world.over_limit_result() == expected


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
        db = Database(str(db_path))
        await db.connect()
        try:
            await AccountService(db=db, eventbus=EventBus()).initialize()
            await db.execute(
                "INSERT INTO accounts (account_id, name, exchange, currency, "
                "broker_type, trading_mode, credentials, broker_config, status) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    *("acc1", "A", "KRX", "KRW", "test", "virtual"),
                    *(encrypt_credentials({}), "{}", "active"),
                ),
            )
        finally:
            await db.close()

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
            "SELECT value FROM dynamic_config WHERE key=?", (KEY,)
        ).fetchone()
    finally:
        conn.close()
    return None if row is None else str(row[0])


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(("--param", "type=bogus"), id="type"),
        pytest.param(("--param", "priority=high"), id="priority"),
        pytest.param(("--params-json", '{"enabled": false}'), id="enabled-json"),
        pytest.param(("--param", "enabled=false", "--enabled"), id="enabled-and-flag"),
        pytest.param(("--param", "id=x1"), id="id"),
    ],
)
def test_cli_direct_path_rejects_with_param_validation_exit(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    config_dir = tmp_path / "config"
    db_path = _seed_cli(config_dir)
    ok = _cli(config_dir, "--param", "max_daily_loss_percent=0.01")
    assert ok.exit_code == 0, ok.output
    before = _stored_cli(db_path)

    nan = _cli(config_dir, "--param", "max_daily_loss_percent=nan")
    result = _cli(config_dir, *extra)

    assert result.exit_code == nan.exit_code != 0
    assert json.loads(nan.output)["code"] == "RULE_UPDATE_ERROR"
    payload = json.loads(result.output)
    assert payload["status"] == "error"
    assert payload["code"] == "RULE_UPDATE_ERROR"
    assert "bogus" not in result.output
    assert "high" not in result.output
    assert _stored_cli(db_path) == before


@pytest.mark.parametrize(
    "extra",
    [
        pytest.param(("--param", "max_daily_loss_percent=0.02"), id="param"),
        pytest.param(("--disabled",), id="disabled"),
        pytest.param(("--param", "priority=5"), id="int-priority"),
    ],
)
def test_cli_direct_path_controls_succeed(
    tmp_path: Path, extra: tuple[str, ...]
) -> None:
    config_dir = tmp_path / "config"
    _seed_cli(config_dir)

    result = _cli(config_dir, *extra)

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["data"]["rule"]["type"] == "daily_loss_limit"


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
        eventbus=MagicMock(),
        audit_logger=MagicMock(log=AsyncMock()),
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc3008", dir="/tmp")
    server = IPCServer(str(Path(socket_dir) / "t.sock"), svc_registry, cmd_registry)
    await server.start()
    try:
        return await server._dispatch(
            {"id": "1", "command": "rule.update", "args": args, "actor": "bob"}
        )
    finally:
        await server.stop()


@pytest.mark.parametrize(
    "params",
    [
        pytest.param({"type": "bogus"}, id="type"),
        pytest.param({"priority": "high", **LIMIT}, id="priority"),
    ],
)
async def test_ipc_rejects_with_execution_error(
    world: _World, params: dict[str, Any]
) -> None:
    before = await world.raw()

    response = await _dispatch(
        world,
        {"account_id": "acc1", "rule_type": "daily_loss_limit", "params": params},
    )

    assert response["status"] == "error", response
    assert response["error"]["code"] == "EXECUTION_ERROR"
    assert "bogus" not in json.dumps(response)
    assert "high" not in response["error"]["message"]
    assert await world.raw() == before
    assert world.changes == []


async def test_ipc_control_succeeds(world: _World) -> None:
    response = await _dispatch(
        world,
        {
            "account_id": "acc1",
            "rule_type": "daily_loss_limit",
            "params": {"max_daily_loss_percent": 0.02, "priority": 5},
        },
    )

    assert response["status"] == "ok", response
    assert json.loads(await world.raw())[0]["priority"] == 5
