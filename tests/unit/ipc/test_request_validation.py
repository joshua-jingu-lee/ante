"""``_dispatch``의 요청 모델 검증 자리와 출구."""

from __future__ import annotations

import json
import logging
from dataclasses import fields
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.account_id import InvalidAccountIdError
from ante.core.registry import ServiceRegistry
from ante.ipc import protocol
from ante.ipc.registry import CommandRegistry, CommandSpec, register_all_handlers
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


class _ScopedRequest(IPCRequest):
    account_id: str


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


def test_registration_has_no_account_id_policy() -> None:
    registry = CommandRegistry()
    legacy: dict[str, Any] = {"account_id_policy": "required"}
    with pytest.raises(TypeError) as info:
        registry.register(
            "demo.run",
            _Recorder(),
            is_mutating=True,
            request_model=_DemoRequest,
            **legacy,
        )
    assert str(info.value) == (
        "CommandRegistry.register() got an unexpected keyword argument "
        "'account_id_policy'"
    )
    assert registry.get("demo.run") is None
    assert "account_id_policy" not in {f.name for f in fields(CommandSpec)}


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

    async def handler(svc: Any, request: Any, actor: str) -> dict[str, Any]:
        raise InvalidAccountIdError("handler rejected")

    registry = CommandRegistry()
    registry.register(
        "demo.scoped", handler, is_mutating=False, request_model=_ScopedRequest
    )
    server = IPCServer("/tmp/unused.sock", _services(), registry)
    server._state = IPCServerState.RUNNING
    response = await server._dispatch(_request("demo.scoped", {"account_id": ""}))
    assert response["status"] == "error"
    assert response["error"]["code"] == "VALIDATION_ERROR"
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


_HEAD = "demo.run 인자 검증 실패: "
_EXTRA = "(extra_forbidden)"
_KEYS = [f"k{i}" for i in range(80_000)]


def _size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))


def _full_message(keys: list[str]) -> str:
    return _HEAD + ", ".join(f"{key}{_EXTRA}" for key in keys)


def _with(message: str, request_id: Any = "req-9") -> dict[str, Any]:
    return {
        "id": request_id,
        "status": "error",
        "error": {"code": "VALIDATION_ERROR", "message": message},
    }


def _loaded(message: str, keys: list[str]) -> list[str]:
    assert message.startswith(_HEAD)
    body = message[len(_HEAD) :]
    if body.startswith("외 "):
        loaded, rest = [], body[2:]
    else:
        fields, _, rest = body.rpartition(" 외 ")
        loaded = fields.split(", ")
    assert loaded == [f"{key}{_EXTRA}" for key in keys[: len(loaded)]]
    assert rest == f"{len(keys) - len(loaded)}건"
    return loaded


async def _validation_response(
    keys: list[str], request_id: Any = "req-9"
) -> dict[str, Any]:
    server, handler, _audit = _demo_server()
    request = _request("demo.run", {"name": "a", **dict.fromkeys(keys, 0)})
    request["id"] = request_id
    response = await server._dispatch(request)
    assert handler.calls == []
    assert response["id"] == request_id
    assert response["status"] == "error"
    assert response["error"]["code"] == "VALIDATION_ERROR"
    await protocol.encode(response)
    return response


@pytest.mark.asyncio
async def test_oversized_validation_message_is_shortened_into_one_frame() -> None:
    await protocol.encode(_request("demo.run", dict.fromkeys(_KEYS, 0)))
    response = await _validation_response(_KEYS)
    loaded = _loaded(response["error"]["message"], _KEYS)
    assert 0 < len(loaded) < len(_KEYS)


@pytest.mark.asyncio
async def test_shortened_message_carries_as_many_fields_as_fit() -> None:
    response = await _validation_response(_KEYS)
    k = len(_loaded(response["error"]["message"], _KEYS)) + 1
    one_more = f"{_full_message(_KEYS[:k])} 외 {len(_KEYS) - k}건"
    assert _size(_with(one_more)) > protocol.MAX_MESSAGE_SIZE


def _boundary_keys(extra: int) -> list[str]:
    keys = [f"k{i}" for i in range(1_000)]
    filler = protocol.MAX_MESSAGE_SIZE - _size(_with(_full_message([*keys, ""])))
    return [*keys, "z" * (filler + extra)]


@pytest.mark.asyncio
async def test_message_of_exactly_one_frame_is_unchanged() -> None:
    keys = _boundary_keys(0)
    response = await _validation_response(keys)
    assert response == _with(_full_message(keys))
    assert _size(response) == protocol.MAX_MESSAGE_SIZE


@pytest.mark.asyncio
async def test_message_one_byte_over_the_frame_is_shortened() -> None:
    keys = _boundary_keys(1)
    response = await _validation_response(keys)
    assert response == _with(f"{_full_message(keys[:-1])} 외 1건")


@pytest.mark.asyncio
async def test_json_escape_cost_counts_against_the_budget() -> None:
    keys = [f'"\\\x00{i}' for i in range(40_000)]
    response = await _validation_response(keys)
    escaped = [f'"\\\\x00{i}' for i in range(40_000)]
    loaded = _loaded(response["error"]["message"], escaped)
    assert 0 < len(loaded) < len(keys)


@pytest.mark.parametrize(
    "request_id",
    [
        pytest.param("x" * 600_000, id="large-string"),
        pytest.param({"n": list(range(100_000))}, id="non-string"),
    ],
)
@pytest.mark.asyncio
async def test_request_id_counts_against_the_budget(request_id: Any) -> None:
    keys = _KEYS[:40_000]
    response = await _validation_response(keys, request_id)
    loaded = _loaded(response["error"]["message"], keys)
    assert 0 < len(loaded) < len(keys)


@pytest.mark.asyncio
async def test_single_field_over_the_budget_is_only_counted() -> None:
    response = await _validation_response(["z" * protocol.MAX_MESSAGE_SIZE])
    assert response == _with("demo.run 인자 검증 실패: 외 1건")


@pytest.mark.asyncio
async def test_shortened_message_logs_one_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    response = await _validation_response(_KEYS)
    records = _server_records(caplog)
    assert len(records) == 1
    assert records[0].levelname == "WARNING"
    assert records[0].exc_info is None
    assert records[0].getMessage() == (
        f"IPC 요청 검증 거부: {response['error']['message']}"
    )
    assert [r for r in caplog.records if r.levelno >= logging.ERROR] == []
