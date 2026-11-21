"""``_dispatch``의 요청 모델 검증 자리와 출구."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.account_id import InvalidAccountIdError
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


def _demo_server() -> tuple[IPCServer, _Recorder, MagicMock]:
    handler = _Recorder()
    registry = CommandRegistry()
    registry.register(
        "demo.run",
        handler,
        is_mutating=True,
        audit_action="demo.run",
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


@pytest.mark.parametrize("policy", ["required", "optional_filter"])
def test_model_with_account_id_policy_is_rejected_at_registration(
    policy: AccountIdPolicy,
) -> None:
    registry = CommandRegistry()
    with pytest.raises(ValueError) as info:
        registry.register(
            "demo.run",
            _Recorder(),
            is_mutating=True,
            account_id_policy=policy,
            request_model=_DemoRequest,
        )
    assert str(info.value) == (
        f"요청 모델이 있는 명령 'demo.run'에는 account_id_policy '{policy}'를 "
        "쓸 수 없습니다."
    )
    assert registry.get("demo.run") is None


def test_model_with_account_id_policy_none_is_registered() -> None:
    registry = CommandRegistry()
    registry.register(
        "demo.run",
        _Recorder(),
        is_mutating=True,
        account_id_policy="none",
        request_model=_DemoRequest,
    )
    spec = registry.get("demo.run")
    assert spec is not None
    assert spec.request_model is _DemoRequest


def test_policy_without_model_is_registered() -> None:
    registry = CommandRegistry()
    registry.register(
        "demo.scoped", _Recorder(), is_mutating=True, account_id_policy="required"
    )
    spec = registry.get("demo.scoped")
    assert spec is not None
    assert spec.account_id_policy == "required"


def test_all_runtime_handlers_are_still_registered() -> None:
    registry = CommandRegistry()
    register_all_handlers(registry)
    assert len(registry.iter_specs()) == 42


def _server_records(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name == "ante.ipc.server"]


@pytest.mark.asyncio
async def test_validation_failure_logs_one_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    server, _handler, _audit = _demo_server()
    response = await server._dispatch(_request("demo.run", {"name": 5}))
    assert response["error"] == {
        "code": "VALIDATION_ERROR",
        "message": "demo.run 인자 검증 실패: name(string_type)",
    }
    records = _server_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].exc_info is None
    assert records[0].getMessage() == (
        "IPC 요청 검증 거부: demo.run 인자 검증 실패: name(string_type)"
    )
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []


@pytest.mark.asyncio
async def test_other_validation_error_code_still_logs_exception(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    handler = _Recorder()
    registry = CommandRegistry()
    registry.register(
        "demo.scoped", handler, is_mutating=False, account_id_policy="required"
    )
    server = IPCServer("/tmp/unused.sock", _services(), registry)
    server._state = IPCServerState.RUNNING
    response = await server._dispatch(_request("demo.scoped", {"account_id": ""}))
    assert response["status"] == "error"
    assert response["error"]["code"] == "VALIDATION_ERROR"
    assert handler.calls == []
    records = _server_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "ERROR"
    assert records[0].exc_info is not None
    assert records[0].exc_info[0] is InvalidAccountIdError
    assert records[0].getMessage() == "IPC 커맨드 실행 오류: demo.scoped"


@pytest.mark.parametrize(
    ("key", "message"),
    [
        pytest.param(
            "a\nb",
            "demo.run 인자 검증 실패: a\\nb(extra_forbidden)",
            id="newline",
        ),
        pytest.param(
            "a\x1b[31mb",
            "demo.run 인자 검증 실패: a\\x1b[31mb(extra_forbidden)",
            id="esc",
        ),
        pytest.param(
            "계좌", "demo.run 인자 검증 실패: 계좌(extra_forbidden)", id="hangul"
        ),
        pytest.param(
            "a\\b",
            "demo.run 인자 검증 실패: a\\b(extra_forbidden)",
            id="backslash",
        ),
    ],
)
@pytest.mark.asyncio
async def test_unknown_key_name_is_escaped_in_response_and_log(
    key: str, message: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    server, handler, _audit = _demo_server()
    response = await server._dispatch(_request("demo.run", {"name": "a", key: 1}))
    assert response == {
        "id": "req-9",
        "status": "error",
        "error": {"code": "VALIDATION_ERROR", "message": message},
    }
    assert handler.calls == []
    records = _server_records(caplog)
    assert [r.getMessage() for r in records] == [f"IPC 요청 검증 거부: {message}"]
    line = logging.Formatter("%(levelname)s %(message)s").format(records[0])
    assert line == f"WARNING IPC 요청 검증 거부: {message}"
    assert "\n" not in line
    assert "\x1b" not in line
