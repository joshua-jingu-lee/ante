"""account.suspend·account.activate의 응답·서비스 호출·감사 기록 특성 테스트 (#2683 ②).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
``suspend``·``activate``를 기록하는 대역이다.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer, IPCServerState

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


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["account.suspend", "account.activate"])
async def test_reserved_default_account_is_rejected(command: str) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": "default"})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": (
                f"(ipc.{command}) 유효한 account_id가 필요합니다: 'default'. "
                "fallback (default, '', None) 또는 형식 위반 값은 사용할 수 없습니다."
            ),
        },
    }
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize("command", ["account.suspend", "account.activate"])
async def test_numeric_account_id(command: str) -> None:
    harness = _Harness()
    response = await harness.send(command, {"account_id": 7})
    assert response == {
        "id": "req-1",
        "status": "error",
        "error": {
            "code": "EXECUTION_ERROR",
            "message": "expected string or bytes-like object, got 'int'",
        },
    }
    harness.assert_no_service_call()
