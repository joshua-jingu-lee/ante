"""IPCServer ``_dispatch`` preflight wrapper 검증.

Refs #1850 (#1819 부모 epic): dispatch wrapper 가 handler 호출 전에
``CommandSpec.required_services`` 부재 / ``CommandSpec.account_id_policy``
위반을 사전 차단하는지 확인한다.

- ``required_services`` 부재 → ``SERVICE_NOT_CONFIGURED`` envelope (handler
  미호출). ``ServiceRegistry`` 는 dataclass 이며 optional service 는 default
  ``None`` 이라 ``getattr(svc, name, None) is None`` 로 판정한다.
- ``account_id_policy == "required"`` 누락/invalid → ``InvalidAccountIdError``
  (``code="VALIDATION_ERROR"``) raise → 기존 ``server.py`` except 가
  ``VALIDATION_ERROR`` envelope 으로 변환.
- ``account_id_policy == "optional_filter"`` → 값 있으면 검증, 없으면 skip.
- lifecycle gate (``DRAINING`` / ``STOPPED`` / ``SHUTTING_DOWN`` + mutating)
  는 preflight 보다 항상 먼저 — preflight 로 인한 envelope 이 lifecycle
  거부를 덮어쓰지 않는다.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer


def _make_service_registry(**overrides: Any) -> ServiceRegistry:
    """기본 7 service 채운 ServiceRegistry. overrides 로 특정 필드 교체."""
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


@pytest.fixture
def socket_path() -> str:
    """Unix 소켓 경로 길이 제한(104B) 회피 — /tmp 직접 사용."""
    td = tempfile.mkdtemp(prefix="ipc-preflight", dir="/tmp")
    return str(Path(td) / "t.sock")


# ── required_services preflight ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_required_services_present_calls_handler(socket_path: str) -> None:
    """required_services 모두 존재하면 handler 가 호출되고 정상 응답."""
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    cmd_registry.register(
        "test.needs_account",
        handler,
        is_mutating=False,
        required_services=frozenset({"account"}),
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.needs_account", "args": {}, "actor": "t"}
        )
        assert response["status"] == "ok"
        assert response["result"] == {"ok": True}
        assert called is True
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_required_services_missing_returns_service_not_configured(
    socket_path: str,
) -> None:
    """required_services 부재 시 SERVICE_NOT_CONFIGURED envelope, handler 미호출.

    ``audit_logger`` 는 ServiceRegistry default=None 이므로 미주입 시 부재.
    """
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    cmd_registry.register(
        "test.needs_audit",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
    )

    # audit_logger 를 주입하지 않은 ServiceRegistry — default=None.
    svc_registry = _make_service_registry()
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.needs_audit", "args": {}, "actor": "t"}
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
        assert "audit_logger" in response["error"]["message"]
        assert called is False
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_required_services_missing_attribute_returns_service_not_configured(
    socket_path: str,
) -> None:
    """ServiceRegistry 에 정의조차 없는 attribute 도 부재로 판정 — getattr default None.

    실제로는 등록 시 검증되어야 할 spec 문제이지만, dispatch wrapper 가
    defensive 하게 처리하는지 확인.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.needs_nonexistent",
        handler,
        is_mutating=False,
        required_services=frozenset({"nonexistent_service"}),
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.needs_nonexistent",
                "args": {},
                "actor": "t",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
        assert "nonexistent_service" in response["error"]["message"]
    finally:
        await server.stop()


# ── account_id_policy="required" preflight ──────────────────────────────────


@pytest.mark.asyncio
async def test_account_id_required_present_calls_handler(socket_path: str) -> None:
    """account_id_policy=required + valid account_id 시 handler 호출 정상."""
    cmd_registry = CommandRegistry()
    received: dict[str, Any] = {}

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        received.update(args)
        return {"account_id": args["account_id"]}

    cmd_registry.register(
        "test.account_required",
        handler,
        is_mutating=True,
        account_id_policy="required",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_required",
                "args": {"account_id": "live-001"},
                "actor": "t",
            }
        )
        assert response["status"] == "ok"
        assert response["result"]["account_id"] == "live-001"
        assert received["account_id"] == "live-001"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_id_required_missing_returns_validation_error(
    socket_path: str,
) -> None:
    """account_id_policy=required + args 에 account_id 없으면 VALIDATION_ERROR.

    ``require_account_id(None)`` 이 ``InvalidAccountIdError``
    (``code="VALIDATION_ERROR"``) 를 raise 하고, 기존 except 의
    ``getattr(e, "code", ...)`` 가 ``VALIDATION_ERROR`` envelope 으로 변환.
    handler 는 호출되지 않는다.
    """
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    cmd_registry.register(
        "test.account_required",
        handler,
        is_mutating=True,
        account_id_policy="required",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_required",
                "args": {},
                "actor": "t",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert called is False
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_id_required_invalid_returns_validation_error(
    socket_path: str,
) -> None:
    """account_id_policy=required + invalid (예: "default") 도 VALIDATION_ERROR.

    ``"default"`` 는 ``INVALID_RUNTIME_ACCOUNT_IDS`` fallback 예약어이므로
    ``require_account_id`` 가 거부한다.
    """
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    cmd_registry.register(
        "test.account_required",
        handler,
        is_mutating=True,
        account_id_policy="required",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_required",
                "args": {"account_id": "default"},
                "actor": "t",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert called is False
    finally:
        await server.stop()


# ── account_id_policy="optional_filter" preflight ───────────────────────────


@pytest.mark.asyncio
async def test_account_id_optional_filter_present_validates(socket_path: str) -> None:
    """optional_filter + 값 존재 시 검증 통과하면 handler 호출."""
    cmd_registry = CommandRegistry()
    received: dict[str, Any] = {}

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        received.update(args)
        return {"filtered": args.get("account_id")}

    cmd_registry.register(
        "test.account_filter",
        handler,
        is_mutating=False,
        account_id_policy="optional_filter",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_filter",
                "args": {"account_id": "live-001"},
                "actor": "t",
            }
        )
        assert response["status"] == "ok"
        assert response["result"] == {"filtered": "live-001"}
        assert received["account_id"] == "live-001"
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_id_optional_filter_invalid_returns_validation_error(
    socket_path: str,
) -> None:
    """optional_filter + 값이 invalid 면 VALIDATION_ERROR 로 거부."""
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"ok": True}

    cmd_registry.register(
        "test.account_filter",
        handler,
        is_mutating=False,
        account_id_policy="optional_filter",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_filter",
                "args": {"account_id": "default"},
                "actor": "t",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"
        assert called is False
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_id_optional_filter_absent_skips(socket_path: str) -> None:
    """optional_filter + account_id 부재 시 검증 skip — handler 정상 호출."""
    cmd_registry = CommandRegistry()
    called = False

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        nonlocal called
        called = True
        return {"filtered": args.get("account_id")}

    cmd_registry.register(
        "test.account_filter",
        handler,
        is_mutating=False,
        account_id_policy="optional_filter",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_filter",
                "args": {},
                "actor": "t",
            }
        )
        assert response["status"] == "ok"
        assert response["result"] == {"filtered": None}
        assert called is True
    finally:
        await server.stop()


# ── account_id_policy="none" (default) ─────────────────────────────────────


@pytest.mark.asyncio
async def test_account_id_none_skips_validation(socket_path: str) -> None:
    """account_id_policy=none (default) 면 args 의 account_id 값과 무관하게 skip."""
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"acc": args.get("account_id")}

    # default account_id_policy="none"
    cmd_registry.register("test.no_policy", handler, is_mutating=False)

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        # invalid "default" 값을 보내도 wrapper 가 검증 skip
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.no_policy",
                "args": {"account_id": "default"},
                "actor": "t",
            }
        )
        assert response["status"] == "ok"
        assert response["result"] == {"acc": "default"}
    finally:
        await server.stop()


# ── lifecycle gate ordering (preflight 보다 항상 먼저) ─────────────────────


@pytest.mark.asyncio
async def test_lifecycle_gate_before_preflight_draining(socket_path: str) -> None:
    """DRAINING 상태 시 required_services preflight 에 도달 전 SERVICE_UNAVAILABLE.

    lifecycle 거부가 우선이므로 부재한 service 가 있어도 SERVICE_NOT_CONFIGURED
    envelope 이 노출되어서는 안 된다(envelope drift 방지).
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.needs_audit",
        handler,
        is_mutating=False,
        required_services=frozenset({"audit_logger"}),
    )

    # audit_logger 부재 — 평소라면 SERVICE_NOT_CONFIGURED 발화.
    svc_registry = _make_service_registry()
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    await server.stop_accepting()
    server.stop_dispatching()  # DRAINING 전환

    response = await server._dispatch(
        {"id": "1", "command": "test.needs_audit", "args": {}, "actor": "t"}
    )
    # lifecycle gate 가 먼저 — SERVICE_UNAVAILABLE 이 노출되어야 함.
    assert response["status"] == "error"
    assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert "리소스 종료 중" in response["error"]["message"]

    await server.drain_connections(timeout=0.1)
    if Path(socket_path).exists():
        server.unlink_socket()


@pytest.mark.asyncio
async def test_shutdown_mutating_blocked_before_preflight(socket_path: str) -> None:
    """SHUTTING_DOWN + mutating 시 preflight 에 도달 전 SERVICE_UNAVAILABLE.

    account_id_policy=required 라도 lifecycle gate 가 먼저 — VALIDATION_ERROR
    envelope 이 노출되어서는 안 된다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.account_required_mut",
        handler,
        is_mutating=True,
        account_id_policy="required",
    )

    svc_registry = _make_service_registry()
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        await server.stop_accepting()  # SHUTTING_DOWN 전환

        # account_id 누락 — 평소라면 VALIDATION_ERROR 발화.
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.account_required_mut",
                "args": {},
                "actor": "t",
            }
        )
        # lifecycle gate 가 먼저 — SERVICE_UNAVAILABLE 이 노출되어야 함.
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_UNAVAILABLE"
        assert "종료 중" in response["error"]["message"]
    finally:
        await server.drain_connections(timeout=0.1)
        if Path(socket_path).exists():
            server.unlink_socket()


@pytest.mark.asyncio
async def test_shutdown_readonly_passes_through_preflight(socket_path: str) -> None:
    """SHUTTING_DOWN + read-only 면 preflight 까지 진행 — required_services 검증 동작.

    SHUTTING_DOWN 단계에서 read-only 명령은 lifecycle gate 를 통과하므로
    이어지는 required_services preflight 가 정상 동작해야 한다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.readonly_needs_audit",
        handler,
        is_mutating=False,
        required_services=frozenset({"audit_logger"}),
    )

    svc_registry = _make_service_registry()  # audit_logger 미주입
    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        await server.stop_accepting()  # SHUTTING_DOWN 전환

        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.readonly_needs_audit",
                "args": {},
                "actor": "t",
            }
        )
        # read-only 는 lifecycle gate 통과 → preflight 도달 → audit_logger 부재
        # 로 SERVICE_NOT_CONFIGURED.
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
        assert "audit_logger" in response["error"]["message"]
    finally:
        await server.drain_connections(timeout=0.1)
        if Path(socket_path).exists():
            server.unlink_socket()


# ── #2109: broker.reconcile fail-closed audit_logger required ──────────────


@pytest.mark.asyncio
async def test_broker_reconcile_missing_audit_logger_rejected(
    socket_path: str,
) -> None:
    """(e) ``broker.reconcile`` 은 ``audit_logger`` 미주입 시 preflight 거부.

    Refs #2109: ``audit_logger`` 를 ``required_services`` 에 추가해 fail-closed
    로 동작한다 — audit_logger 가 없으면 (unaudited correction 위험) 명령을
    아예 거부한다. ``audit_logger`` 부재 검사는 account_id preflight 보다 먼저
    이뤄지므로(required_services preflight 가 try 블록보다 앞) 유효 account_id
    여부와 무관하게 ``SERVICE_NOT_CONFIGURED`` 다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    # account / reconciler / bot_manager 는 있으나 audit_logger 미주입.
    svc_registry = _make_service_registry()
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "broker.reconcile",
                "args": {"account_id": "acc-a", "fix": True},
                "actor": "cli-user",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
        assert "audit_logger" in response["error"]["message"]
    finally:
        await server.stop()
