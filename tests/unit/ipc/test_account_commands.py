"""account.suspend·account.activate의 응답·서비스 호출·감사 기록 특성 테스트 (#2683 ②).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
``suspend``·``activate``를 기록하는 대역이다.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState
from tests.unit.ipc.test_request_model_domain import validation_message

ACTOR = "ops-lead"


class _Harness:
    def __init__(self) -> None:
        self.account = MagicMock()
        self.account.suspend = AsyncMock(return_value=None)
        self.account.activate = AsyncMock(return_value=None)
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=self.account,
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            audit_logger=self.audit_logger,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any) -> dict:
        return await self.server._dispatch(
            {"id": "req-1", "command": command, "args": args, "actor": ACTOR}
        )

    def assert_no_service_call(self) -> None:
        self.account.suspend.assert_not_awaited()
        self.account.activate.assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


@pytest.mark.asyncio
async def test_suspend_passes_the_reason_and_audits() -> None:
    harness = _Harness()
    response = await harness.send(
        "account.suspend", {"account_id": "acct-7", "reason": "점검"}
    )
    assert response == {
        "id": "req-1",
        "status": "ok",
        "result": {"account_id": "acct-7", "status": "suspended"},
    }
    harness.account.suspend.assert_awaited_once_with(
        "acct-7", reason="점검", suspended_by="ops-lead"
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="account.suspend",
        resource="account:acct-7",
        detail="reason=점검",
        ip="",
    )


@pytest.mark.asyncio
async def test_suspend_without_a_reason_uses_the_ipc_default() -> None:
    harness = _Harness()
    response = await harness.send("account.suspend", {"account_id": "acct-7"})
    assert response["status"] == "ok", response
    harness.account.suspend.assert_awaited_once_with(
        "acct-7", reason="IPC suspend", suspended_by="ops-lead"
    )
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="account.suspend",
        resource="account:acct-7",
        detail="reason=IPC suspend",
        ip="",
    )


@pytest.mark.asyncio
async def test_activate_activates_and_audits() -> None:
    harness = _Harness()
    response = await harness.send("account.activate", {"account_id": "acct-7"})
    assert response == {
        "id": "req-1",
        "status": "ok",
        "result": {"account_id": "acct-7", "status": "active"},
    }
    harness.account.activate.assert_awaited_once_with("acct-7", activated_by="ops-lead")
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="ops-lead",
        action="account.activate",
        resource="account:acct-7",
        detail="",
        ip="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["account.suspend", "account.activate"])
async def test_the_bootstrap_test_account_is_accepted(command: str) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": "test"})
    assert response["status"] == "ok", response
    assert response["result"]["account_id"] == "test"


COMMANDS = ["account.suspend", "account.activate"]


def _rejected(command: str, kind: str) -> dict:
    return {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": validation_message(command, ("account_id", kind)),
        },
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("account_id", ["default", "", "ab", "a" * 31, "bad_id!"])
async def test_invalid_account_id_is_rejected_before_the_handler(
    command: str, account_id: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": account_id})
    assert response == _rejected(command, "invalid_account_id")
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize("account_id", ["abc", "a" * 30])
async def test_account_id_at_the_pattern_bounds_is_accepted(
    command: str, account_id: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": account_id})
    assert response["status"] == "ok", response
    assert response["result"]["account_id"] == account_id


@pytest.mark.asyncio
@pytest.mark.parametrize("command", COMMANDS)
@pytest.mark.parametrize(
    ("args", "kind"),
    [
        ({}, "missing"),
        ({"account_id": None}, "string_type"),
        ({"account_id": 7}, "string_type"),
    ],
)
async def test_missing_or_non_string_account_id(
    command: str, args: dict[str, Any], kind: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response == _rejected(command, kind)
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", COMMANDS)
async def test_invalid_account_id_is_not_reflected(
    command: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    marker = "MARKACCT001SECRET!"
    harness = _Harness()
    response = await harness.send(command, {"account_id": marker})
    assert response == _rejected(command, "invalid_account_id")
    assert "MARKACCT001SECRET" not in json.dumps(response, ensure_ascii=False)
    assert "MARKACCT001SECRET" not in caplog.text
    harness.assert_no_service_call()
