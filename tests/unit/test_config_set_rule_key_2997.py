"""``config.set``은 계좌 규칙 key(``accounts.<id>.rules``)를 거부한다 (#2997).

거부는 IPC 핸들러에만 있다. 다른 key의 ``config set``과 ``rule update``의 쓰기는
그대로다(대조군).
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.config import DynamicConfigService
from ante.contracts.cli_errors import ConfigUnsupportedKeyError
from ante.core import Database
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, _handle_config_set
from ante.ipc.requests import ConfigSetRequest
from ante.ipc.server import IPCServer
from ante.rule import config_update
from ante.rule.config_update import update_account_rule_config

RULE_KEY = "accounts.acc1.rules"


def _predicate(key: str) -> bool:
    return config_update.is_account_rules_config_key(key)


@pytest.mark.parametrize("account_id", ["acc1", "domestic", "x-y", "test", ""])
def test_predicate_accepts_every_generated_key(account_id: str) -> None:
    key = config_update.account_rules_config_key(account_id)
    assert _predicate(key) is True


@pytest.mark.parametrize(
    "key", ["accounts.acc1.rules", "accounts..rules", "accounts.a.b.rules"]
)
def test_predicate_true(key: str) -> None:
    assert _predicate(key) is True


@pytest.mark.parametrize(
    "key",
    [
        "accounts.rules",
        "accounts.acc1.name",
        "accounts.acc1.rules.x",
        "Accounts.acc1.rules",
        " accounts.acc1.rules",
        "system.log_level",
    ],
)
def test_predicate_false(key: str) -> None:
    assert _predicate(key) is False


def test_account_rules_config_key_output_unchanged() -> None:
    assert config_update.account_rules_config_key("acc1") == "accounts.acc1.rules"


@pytest.mark.parametrize("category", ["user", "rule"])
async def test_handler_rejects_rule_key_without_calling_service(category: str) -> None:
    fake_dynamic = MagicMock()
    fake_dynamic.set = AsyncMock(return_value=None)
    svc = MagicMock()
    svc.dynamic_config = fake_dynamic

    with pytest.raises(ConfigUnsupportedKeyError) as exc_info:
        await _handle_config_set(
            svc,
            ConfigSetRequest(key=RULE_KEY, value="off", category=category),
            "cli-user",
        )

    message = str(exc_info.value)
    assert "rule update" in message
    assert "off" not in message
    assert "acc1" not in message
    fake_dynamic.set.assert_not_awaited()


async def test_dispatch_returns_config_unsupported_key() -> None:
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    fake_dynamic = MagicMock()
    fake_dynamic.set = AsyncMock(return_value=None)
    svc_registry = ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=fake_dynamic,
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc2997", dir="/tmp")
    server = IPCServer(str(Path(socket_dir) / "t.sock"), svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "config.set",
                "args": {"key": RULE_KEY, "value": "off"},
                "actor": "bob",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "error", response
    assert response["error"]["code"] == "CONFIG_UNSUPPORTED_KEY"
    assert "rule update" in response["error"]["message"]
    fake_dynamic.set.assert_not_awaited()


class _FakeEventBus:
    def __init__(self) -> None:
        self.published: list[Any] = []

    async def publish(self, event: Any) -> None:
        self.published.append(event)


@pytest.fixture
async def dynamic(tmp_path: Path) -> Any:
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    service = DynamicConfigService(db=database, eventbus=_FakeEventBus())
    await service.initialize()
    yield service, database
    await database.close()


async def _update_rule(
    service: DynamicConfigService, rule_type: str, params: dict
) -> None:
    await update_account_rule_config(
        account_service=AsyncMock(),
        dynamic_config=service,
        account_id="acc1",
        rule_type=rule_type,
        params=params,
        changed_by="tester",
    )


async def _row(database: Database, key: str) -> dict[str, Any] | None:
    return await database.fetch_one(
        "SELECT value, category FROM dynamic_config WHERE key = ?", (key,)
    )


async def _history_count(database: Database, key: str) -> int:
    row = await database.fetch_one(
        "SELECT COUNT(*) AS n FROM dynamic_config_history WHERE key = ?", (key,)
    )
    assert row is not None
    return int(row["n"])


def _svc(service: DynamicConfigService) -> Any:
    svc = MagicMock()
    svc.dynamic_config = service
    return svc


async def test_rejected_set_leaves_stored_rules_untouched(dynamic: Any) -> None:
    service, database = dynamic
    await _update_rule(service, "daily_loss_limit", {"max_daily_loss_percent": 0.03})
    before = await _row(database, RULE_KEY)
    history_before = await _history_count(database, RULE_KEY)

    for category in ("user", "rule"):
        with pytest.raises(ConfigUnsupportedKeyError):
            await _handle_config_set(
                _svc(service),
                ConfigSetRequest(key=RULE_KEY, value="off", category=category),
                "cli-user",
            )

    after = await _row(database, RULE_KEY)
    assert after == before
    assert after is not None
    assert after["category"] == "rule"
    assert isinstance(json.loads(after["value"]), list)
    assert await _history_count(database, RULE_KEY) == history_before

    await _update_rule(service, "total_exposure_limit", {"max_exposure_percent": 0.2})
    stored = await service.get(RULE_KEY)
    assert [cfg["type"] for cfg in stored] == [
        "daily_loss_limit",
        "total_exposure_limit",
    ]
    assert await _history_count(database, RULE_KEY) == history_before + 1


@pytest.mark.parametrize(
    ("key", "value", "category", "expected_category"),
    [
        ("system.log_level", "DEBUG", "system", "system"),
        ("display.currency_position", "prefix", None, "user"),
    ],
)
async def test_other_keys_still_write(
    dynamic: Any,
    key: str,
    value: str,
    category: str | None,
    expected_category: str,
) -> None:
    service, database = dynamic
    request = (
        ConfigSetRequest(key=key, value=value)
        if category is None
        else ConfigSetRequest(key=key, value=value, category=category)
    )
    result = await _handle_config_set(_svc(service), request, "cli-user")

    assert result == {"key": key, "value": value}
    row = await _row(database, key)
    assert row is not None
    assert json.loads(row["value"]) == value
    assert row["category"] == expected_category
    assert await _history_count(database, key) == 1
