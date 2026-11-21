"""``_dispatch``의 요청 모델 검증 자리와 출구."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import AccountIdPolicy, CommandRegistry, register_all_handlers
from ante.ipc.requests import IPCRequest
from ante.ipc.server import IPCServer, IPCServerState


def _services(**overrides: Any) -> ServiceRegistry:
    defaults: dict[str, Any] = {
        "account": MagicMock(),
        "bot_manager": MagicMock(),
        "treasury_manager": MagicMock(),
        "dynamic_config": MagicMock(),
        "approval": MagicMock(),
        "reconciler": MagicMock(),
        "eventbus": MagicMock(),
    }
    defaults.update(overrides)
    return ServiceRegistry(**defaults)


def _audit_logger() -> MagicMock:
    audit = MagicMock()
    audit.log = AsyncMock(return_value=None)
    return audit


def _system_server(state: IPCServerState, **services: Any) -> IPCServer:
    registry = CommandRegistry()
    register_all_handlers(registry)
    server = IPCServer("/tmp/unused.sock", _services(**services), registry)
    server._state = state
    return server


def _request(command: str, args: Any) -> dict:
    return {"id": "req-9", "command": command, "args": args, "actor": "ops-lead"}


@pytest.mark.asyncio
async def test_shutting_down_rejects_before_validation() -> None:
    account = MagicMock()
    account.suspend_all = AsyncMock(return_value=[])
    server = _system_server(
        IPCServerState.SHUTTING_DOWN, account=account, audit_logger=_audit_logger()
    )
    response = await server._dispatch(_request("system.halt", {"reason": 1}))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {
            "code": "SERVICE_UNAVAILABLE",
            "message": "서버가 종료 중입니다. 변경 명령을 받지 않습니다.",
        },
    }
    account.suspend_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_required_service_rejects_before_validation() -> None:
    account = MagicMock()
    account.suspend_all = AsyncMock(return_value=[])
    server = _system_server(IPCServerState.RUNNING, account=account)
    response = await server._dispatch(_request("system.halt", {"reason": 1}))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {
            "code": "SERVICE_NOT_CONFIGURED",
            "message": "의존 서비스가 구성되지 않았습니다: audit_logger",
        },
    }
    account.suspend_all.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_command_rejects_before_validation() -> None:
    server = _system_server(IPCServerState.RUNNING, audit_logger=_audit_logger())
    response = await server._dispatch(_request("system.halts", {"reason": 1}))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {"code": "UNKNOWN_COMMAND", "message": "미등록 커맨드: system.halts"},
    }


class _DemoRequest(IPCRequest):
    name: str
    count: int = 1


class _Recorder:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def __call__(self, svc: Any, request: Any, actor: str) -> dict:
        self.calls.append(request)
        return {"done": True}


def _demo_server(
    *, account_id_policy: AccountIdPolicy = "none"
) -> tuple[IPCServer, _Recorder, MagicMock]:
    handler = _Recorder()
    registry = CommandRegistry()
    registry.register(
        "demo.run",
        handler,
        is_mutating=True,
        audit_action="demo.run",
        account_id_policy=account_id_policy,
        request_model=_DemoRequest,
    )
    audit = _audit_logger()
    server = IPCServer("/tmp/unused.sock", _services(audit_logger=audit), registry)
    server._state = IPCServerState.RUNNING
    return server, handler, audit


@pytest.mark.asyncio
async def test_valid_args_reach_handler_as_model_instance() -> None:
    server, handler, audit = _demo_server()
    response = await server._dispatch(_request("demo.run", {"name": "a", "count": 3}))
    assert response == {"id": "req-9", "status": "ok", "result": {"done": True}}
    assert handler.calls == [_DemoRequest(name="a", count=3)]
    assert type(handler.calls[0]) is _DemoRequest
    assert audit.log.await_count == 1


@pytest.mark.parametrize(
    ("args", "message"),
    [
        pytest.param(
            {"name": 5}, "demo.run 인자 검증 실패: name(string_type)", id="one"
        ),
        pytest.param(
            {"name": 5, "zz": "v"},
            "demo.run 인자 검증 실패: name(string_type), zz(extra_forbidden)",
            id="two-in-pydantic-order",
        ),
        pytest.param({}, "demo.run 인자 검증 실패: name(missing)", id="missing"),
        pytest.param(
            ["name"], "demo.run 인자 검증 실패: args(model_type)", id="not-an-object"
        ),
        pytest.param(None, "demo.run 인자 검증 실패: args(model_type)", id="null"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_args_are_rejected_without_handler_or_audit(
    args: Any, message: str
) -> None:
    server, handler, audit = _demo_server()
    response = await server._dispatch(_request("demo.run", args))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {"code": "VALIDATION_ERROR", "message": message},
    }
    assert handler.calls == []
    assert audit.log.await_count == 0


@pytest.mark.asyncio
async def test_validation_runs_before_account_id_policy() -> None:
    server, handler, _audit = _demo_server(account_id_policy="required")
    response = await server._dispatch(_request("demo.run", {"name": 5}))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": "demo.run 인자 검증 실패: name(string_type)",
        },
    }
    assert handler.calls == []
