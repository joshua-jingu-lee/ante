"""#3043 데몬 경로(IPC)의 rule update도 저장값이 없으면 정적 seed 위에 갱신한다.

직접 경로(CLI)와 같은 입력에서 같은 저장값을 쓰고, 갱신하지 않은 유형의 seed
규칙이 재로드·재기동 뒤에도 남는다.
"""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.models import TradingMode
from ante.config.config import Config
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.events import NotificationEvent
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer
from ante.rule.base import RuleResult
from tests.unit._readiness_gate_helpers import make_account
from tests.unit.test_rule_config_keys_2583 import (
    KEY1,
    _cli,
    _context,
    _seed_cli,
    _stored_cli,
    _World,
)

SEED_TOML = """
[accounts.acc1]
rules = [
  { type = "daily_loss_limit", enabled = true, max_daily_loss_percent = 0.03 },
  { type = "total_exposure_limit", enabled = true, max_exposure_percent = 0.5 },
]
"""
UPDATED = {"type": "daily_loss_limit", "enabled": True, "max_daily_loss_percent": 0.05}
EXPOSURE = {
    "type": "total_exposure_limit",
    "enabled": True,
    "max_exposure_percent": 0.5,
}
RESPONSE_KEYS = {"account_id", "rule_type", "rule", "dropped_items"}


def _config(tmp_path: Path, text: str = SEED_TOML, name: str = "cfg") -> Config:
    config_dir = tmp_path / name
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "system.toml").write_text(text)
    return Config.load(config_dir=config_dir)


async def _dispatch(world: _World, config: Any, args: dict[str, Any]) -> dict[str, Any]:
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
        config=config,
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc3043", dir="/tmp")
    server = IPCServer(str(Path(socket_dir) / "t.sock"), svc_registry, cmd_registry)
    await server.start()
    try:
        return await server._dispatch(
            {"id": "1", "command": "rule.update", "args": args, "actor": "bob"}
        )
    finally:
        await server.stop()


async def _ipc(
    world: _World, config: Any, params: dict[str, Any], **extra: Any
) -> dict[str, Any]:
    args = {
        "account_id": "acc1",
        "rule_type": "daily_loss_limit",
        "params": params,
        **extra,
    }
    response = await _dispatch(world, config, args)
    assert response["status"] == "ok", response
    return response


def _rule_configs(world: _World) -> list[dict[str, Any]]:
    return sorted(
        (dict(r.config) for r in world.engine()._account_rules),
        key=lambda c: str(c["type"]),
    )


def _exposure_order(world: _World) -> RuleResult:
    return world.engine().evaluate(_context(0.0)).overall_result


@pytest.fixture
async def world(tmp_path: Path):
    database = Database(str(tmp_path / "t.db"))
    await database.connect()
    w = _World(database)
    await w.dyn.initialize()
    yield w
    await database.close()


async def test_daemon_update_keeps_seed_types_after_reload_and_restart(
    world: _World, tmp_path: Path
) -> None:
    config = _config(tmp_path)
    await world.start(config)
    assert _exposure_order(world) == RuleResult.REJECT

    response = await _ipc(world, config, {"max_daily_loss_percent": 0.05})

    assert set(response["result"]) == RESPONSE_KEYS
    assert response["result"]["dropped_items"] == []
    assert json.loads(await world.raw() or "null") == [UPDATED, EXPOSURE]
    assert _rule_configs(world) == [UPDATED, EXPOSURE]
    assert _exposure_order(world) == RuleResult.REJECT

    await world.start(config)
    assert _rule_configs(world) == [UPDATED, EXPOSURE]
    assert _exposure_order(world) == RuleResult.REJECT


async def test_daemon_update_without_enabled_keeps_seed_disabled(
    world: _World, tmp_path: Path
) -> None:
    config = _config(
        tmp_path,
        SEED_TOML.replace("enabled = true, max_daily", "enabled = false, max_daily"),
    )

    response = await _ipc(world, config, {"max_daily_loss_percent": 0.05})

    assert response["result"]["rule"]["enabled"] is False
    assert json.loads(await world.raw() or "null") == [
        {**UPDATED, "enabled": False},
        EXPOSURE,
    ]


async def test_daemon_update_does_not_read_seed_when_stored_value_exists(
    world: _World, tmp_path: Path
) -> None:
    config = _config(tmp_path)
    stored = [{"type": "position_size", "enabled": True, "max_position_percent": 0.2}]
    await world.store_raw("acc1", stored)

    await _ipc(world, config, {"max_daily_loss_percent": 0.05})

    assert json.loads(await world.raw() or "null") == [*stored, UPDATED]


async def test_daemon_update_does_not_store_broker_default_rules(
    world: _World, tmp_path: Path
) -> None:
    world.accounts[0] = make_account(
        "acc1", broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL
    )
    by_id = {a.account_id: a for a in world.accounts}
    world.account_service.get = AsyncMock(side_effect=lambda a: by_id[a])
    config = _config(tmp_path)
    await world.start(config)

    await _ipc(world, config, {"max_daily_loss_percent": 0.05})

    assert json.loads(await world.raw() or "null") == [UPDATED, EXPOSURE]
    types = sorted(str(r.config["type"]) for r in world.engine()._account_rules)
    assert types == ["daily_loss_limit", "total_exposure_limit", "trading_hours"]


async def test_daemon_updates_do_not_mutate_the_long_lived_seed(
    world: _World, tmp_path: Path
) -> None:
    config = _config(tmp_path)
    seed = copy.deepcopy(config.get(KEY1))

    await _ipc(world, config, {"max_daily_loss_percent": 0.05})
    await world.db.execute("DELETE FROM dynamic_config WHERE key=?", (KEY1,))
    await _ipc(world, config, {"max_daily_loss_percent": 0.07})

    assert config.get(KEY1) == seed
    assert json.loads(await world.raw() or "null") == [
        {**UPDATED, "max_daily_loss_percent": 0.07},
        EXPOSURE,
    ]


async def test_daemon_response_shape_is_the_same_with_and_without_seed(
    world: _World, tmp_path: Path
) -> None:
    with_seed = await _ipc(world, _config(tmp_path), {"max_daily_loss_percent": 0.05})
    await world.db.execute("DELETE FROM dynamic_config WHERE key=?", (KEY1,))
    without = await _ipc(
        world, _config(tmp_path, "", "empty"), {"max_daily_loss_percent": 0.05}
    )

    assert set(with_seed) == set(without)
    assert set(with_seed["result"]) == set(without["result"]) == RESPONSE_KEYS
    assert with_seed["result"] == without["result"]


async def test_daemon_seed_drop_notice_names_the_settings_file(
    world: _World, tmp_path: Path
) -> None:
    notes: list[NotificationEvent] = []
    world.bus.subscribe(NotificationEvent, notes.append)
    config = _config(
        tmp_path,
        SEED_TOML.replace("rules = [", "rules = [\n  { enabled = true },"),
    )

    response = await _ipc(world, config, {"max_daily_loss_percent": 0.05})

    assert response["result"]["dropped_items"] == [
        {"stored_index": 0, "rule_type": None}
    ]
    assert json.loads(await world.raw() or "null") == [UPDATED, EXPOSURE]
    assert len(notes) == 1
    assert "seed에서 읽었으면 설정 파일" in notes[0].message


async def _daemon_bytes(
    tmp_path: Path, text: str, ipc_enabled: dict[str, Any]
) -> str | None:
    database = Database(str(tmp_path / "ipc.db"))
    await database.connect()
    try:
        world = _World(database)
        await world.dyn.initialize()
        await _ipc(
            world,
            _config(tmp_path, text, "ipc"),
            {"max_daily_loss_percent": 0.05},
            **ipc_enabled,
        )
        return await world.raw()
    finally:
        await database.close()


@pytest.mark.parametrize("seed_enabled", ["true", "false"])
@pytest.mark.parametrize(
    ("cli_flag", "ipc_enabled"),
    [(None, {}), ("--enabled", {"enabled": True}), ("--disabled", {"enabled": False})],
    ids=["omitted", "enabled", "disabled"],
)
def test_daemon_and_direct_paths_store_the_same_bytes(
    tmp_path: Path,
    seed_enabled: str,
    cli_flag: str | None,
    ipc_enabled: dict[str, Any],
) -> None:
    text = SEED_TOML.replace(
        "enabled = true, max_daily", f"enabled = {seed_enabled}, max_daily"
    )
    cli_dir = tmp_path / "cli"
    db_path = _seed_cli(cli_dir)
    (cli_dir / "system.toml").write_text(text)
    extra = [cli_flag] if cli_flag else []
    result = _cli(cli_dir, "--param", "max_daily_loss_percent=0.05", *extra)
    assert result.exit_code == 0, result.output
    direct = _stored_cli(db_path)

    daemon = asyncio.run(_daemon_bytes(tmp_path, text, ipc_enabled))

    assert direct is not None
    assert daemon == direct
    assert daemon is not None
    assert len(json.loads(daemon)) == 2
