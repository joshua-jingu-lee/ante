"""IPCServer ``_dispatch`` preflight wrapper 검증.

Refs #1850 (#1819 부모 epic): dispatch wrapper 가 handler 호출 전에
``CommandSpec.required_services`` 부재 / 요청 모델의 계좌 ID 필드
위반을 사전 차단하는지 확인한다.

- ``required_services`` 부재 → ``SERVICE_NOT_CONFIGURED`` envelope (handler
  미호출). ``ServiceRegistry`` 는 dataclass 이며 optional service 는 default
  ``None`` 이라 ``getattr(svc, name, None) is None`` 로 판정한다.
- 요청 모델의 ``AccountId`` 필드 누락/invalid → 모델 검증이
  ``VALIDATION_ERROR`` envelope 으로 거부(handler 미호출).
- ``AccountId | None`` 필드 → 값 있으면 검증, 없으면 ``None``.
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
from ante.ipc.requests import AccountId, IPCRequest
from ante.ipc.server import IPCServer
from tests.unit.ipc.request_fixtures import NoArgsRequest
from tests.unit.ipc.validation_messages import validation_message


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
        request_model=NoArgsRequest,
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
        request_model=NoArgsRequest,
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
        request_model=NoArgsRequest,
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


# ── 요청 모델의 계좌 ID 필드 (account_id_policy 의 대체, #2683 ⑦) ──────────


class _AccountRequired(IPCRequest):
    account_id: AccountId


class _AccountFilter(IPCRequest):
    account_id: AccountId | None = None


async def _dispatch_one(
    socket_path: str,
    command: str,
    model: type[IPCRequest],
    args: Any,
    *,
    is_mutating: bool,
) -> tuple[dict[str, Any], list[Any]]:
    cmd_registry = CommandRegistry()
    received: list[Any] = []

    async def handler(svc: ServiceRegistry, request: Any, actor: str) -> dict:
        received.append(request)
        return {"account_id": request.account_id}

    cmd_registry.register(
        command, handler, is_mutating=is_mutating, request_model=model
    )
    server = IPCServer(socket_path, _make_service_registry(), cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": command, "args": args, "actor": "t"}
        )
    finally:
        await server.stop()
    return response, received


def _rejected(command: str, kind: str) -> dict[str, Any]:
    return {
        "id": "1",
        "status": "error",
        "error": {
            "code": "VALIDATION_ERROR",
            "message": validation_message(command, ("account_id", kind)),
        },
    }


@pytest.mark.asyncio
async def test_account_id_required_present_calls_handler(socket_path: str) -> None:
    """계좌 ID 필드 + 유효한 account_id 면 handler 가 모델을 받는다."""
    response, received = await _dispatch_one(
        socket_path,
        "test.account_required",
        _AccountRequired,
        {"account_id": "live-001"},
        is_mutating=True,
    )
    assert response == {
        "id": "1",
        "status": "ok",
        "result": {"account_id": "live-001"},
    }
    assert received == [_AccountRequired(account_id="live-001")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "kind"),
    [
        pytest.param({}, "missing", id="missing"),
        pytest.param({"account_id": "default"}, "invalid_account_id", id="reserved"),
    ],
)
async def test_account_id_required_rejected_before_handler(
    socket_path: str, args: dict[str, Any], kind: str
) -> None:
    """계좌 ID 필드가 없거나 잘못되면 handler 전에 VALIDATION_ERROR."""
    response, received = await _dispatch_one(
        socket_path, "test.account_required", _AccountRequired, args, is_mutating=True
    )
    assert response == _rejected("test.account_required", kind)
    assert received == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("args", "account_id"),
    [
        pytest.param({"account_id": "live-001"}, "live-001", id="present"),
        pytest.param({}, None, id="absent"),
    ],
)
async def test_account_id_optional_filter_passes(
    socket_path: str, args: dict[str, Any], account_id: str | None
) -> None:
    """``AccountId | None`` 필드는 값이 있으면 검증하고 없으면 ``None``."""
    response, received = await _dispatch_one(
        socket_path, "test.account_filter", _AccountFilter, args, is_mutating=False
    )
    assert response == {
        "id": "1",
        "status": "ok",
        "result": {"account_id": account_id},
    }
    assert received == [_AccountFilter(account_id=account_id)]


@pytest.mark.asyncio
async def test_account_id_optional_filter_invalid_returns_validation_error(
    socket_path: str,
) -> None:
    """``AccountId | None`` 필드에 잘못된 값이면 VALIDATION_ERROR 로 거부."""
    response, received = await _dispatch_one(
        socket_path,
        "test.account_filter",
        _AccountFilter,
        {"account_id": "default"},
        is_mutating=False,
    )
    assert response == _rejected("test.account_filter", "invalid_account_id")
    assert received == []


# ── 계좌 ID 필드가 없는 요청 모델 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_account_id_without_field_is_rejected_as_unknown_key(
    socket_path: str,
) -> None:
    """모델에 계좌 ID 필드가 없으면 ``account_id``는 모르는 키로 거부된다."""
    response, received = await _dispatch_one(
        socket_path,
        "test.no_account_field",
        NoArgsRequest,
        {"account_id": "default"},
        is_mutating=False,
    )
    assert response == _rejected("test.no_account_field", "extra_forbidden")
    assert received == []


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
        request_model=NoArgsRequest,
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

    계좌 ID 요청 모델이라도 lifecycle gate 가 먼저 — VALIDATION_ERROR
    envelope 이 노출되어서는 안 된다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.account_required_mut",
        handler,
        is_mutating=True,
        request_model=_AccountRequired,
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
        request_model=NoArgsRequest,
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


def _reconcile_services(missing: str | None) -> dict[str, Any]:
    """``broker.reconcile`` 를 끝까지 돌릴 수 있는 가짜 서비스(0봇 계좌)."""
    from unittest.mock import AsyncMock

    broker = MagicMock()
    broker.get_account_positions = AsyncMock(return_value=[])
    account = MagicMock()
    account.get_broker = AsyncMock(return_value=broker)
    reconciler = MagicMock()
    reconciler.detect_account_level = AsyncMock(return_value=[])
    reconciler.reconcile = AsyncMock(return_value=[])
    reconciler.compute_account_diff = AsyncMock(return_value=[])
    bot_manager = MagicMock()
    bot_manager.list_bots = MagicMock(return_value=[])
    audit_logger = MagicMock()
    audit_logger.log = AsyncMock(return_value=None)
    services: dict[str, Any] = {
        "account": account,
        "reconciler": reconciler,
        "bot_manager": bot_manager,
        "audit_logger": audit_logger,
    }
    if missing is not None:
        services[missing] = None
    return services


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "missing", ["account", "reconciler", "bot_manager", "audit_logger"]
)
async def test_broker_reconcile_rejects_each_missing_required_service(
    socket_path: str, missing: str
) -> None:
    """``broker.reconcile`` 은 account·reconciler·bot_manager·audit_logger 중 하나라도
    없으면 handler 에 들어가기 전에 ``SERVICE_NOT_CONFIGURED`` 로 거부한다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    services = _reconcile_services(missing)
    svc_registry = _make_service_registry(**services)

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
        assert response["status"] == "error", response
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED", response
        assert missing in response["error"]["message"]
        if services["account"] is not None:
            services["account"].get_broker.assert_not_awaited()
        if services["bot_manager"] is not None:
            services["bot_manager"].list_bots.assert_not_called()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_broker_reconcile_reaches_handler_when_required_services_present(
    socket_path: str,
) -> None:
    """대조군: 네 서비스가 모두 있으면 같은 가짜로 handler 가 끝까지 돈다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    services = _reconcile_services(None)
    svc_registry = _make_service_registry(**services)

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
        assert response["status"] == "ok", response
        assert response["result"]["bot_count"] == 0
        services["account"].get_broker.assert_awaited_once_with("acc-a")
    finally:
        await server.stop()


def _positions_bot_manager() -> MagicMock:
    bot = MagicMock()
    bot.config.account_id = "acc-a"
    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(return_value=bot)
    return bot_manager


@pytest.mark.asyncio
async def test_bot_positions_without_trade_service_returns_empty_collection(
    socket_path: str,
) -> None:
    """``bot.positions`` 는 trade_service 가 없으면 빈 positions 를 낸다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    bot_manager = _positions_bot_manager()
    svc_registry = _make_service_registry(bot_manager=bot_manager)
    assert svc_registry.trade_service is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "bot.positions", "args": {"bot_id": "bot-1"}}
        )
        assert response["status"] == "ok", response
        assert response["result"] == {"positions": []}
        bot_manager.get_bot.assert_called_once_with("bot-1")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_positions_without_bot_manager_is_service_not_configured(
    socket_path: str,
) -> None:
    """``bot.positions`` 는 bot_manager 가 없으면 SERVICE_NOT_CONFIGURED 다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    svc_registry = _make_service_registry(bot_manager=None)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "bot.positions", "args": {"bot_id": "bot-1"}}
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED", response
        assert "bot_manager" in response["error"]["message"]
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_positions_unknown_bot_is_bot_not_found(socket_path: str) -> None:
    """``bot.positions`` 는 bot_manager 로 봇을 찾고, 없으면 BOT_NOT_FOUND 다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    bot_manager = MagicMock()
    bot_manager.get_bot = MagicMock(return_value=None)
    svc_registry = _make_service_registry(bot_manager=bot_manager)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "bot.positions", "args": {"bot_id": "ghost"}}
        )
        assert response["status"] == "error", response
        assert response["error"]["code"] == "BOT_NOT_FOUND", response
        bot_manager.get_bot.assert_called_once_with("ghost")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_shutdown_mutating_blocked_before_required_services_preflight(
    socket_path: str,
) -> None:
    """SHUTTING_DOWN 의 mutating 명령은 서비스가 빠져도 SERVICE_UNAVAILABLE 이다."""
    cmd_registry = CommandRegistry()
    calls: list[dict] = []

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        calls.append(args)
        return {"ok": True}

    cmd_registry.register(
        "test.mut_needs_audit",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        request_model=_AccountRequired,
    )
    svc_registry = _make_service_registry()
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        running = await server._dispatch(
            {"id": "0", "command": "test.mut_needs_audit", "args": {}, "actor": "t"}
        )
        assert running["error"]["code"] == "SERVICE_NOT_CONFIGURED", running

        await server.stop_accepting()
        response = await server._dispatch(
            {"id": "1", "command": "test.mut_needs_audit", "args": {}, "actor": "t"}
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_UNAVAILABLE", response
        assert "종료 중" in response["error"]["message"]
        assert calls == []
    finally:
        await server.drain_connections(timeout=0.1)
        if Path(socket_path).exists():
            server.unlink_socket()


@pytest.mark.parametrize(
    ("bots", "adjustments", "mismatches"),
    [
        ([], [], [{"symbol": "005930"}, {"symbol": "000660"}]),
        (
            [{"bot_id": "bot-1", "account_id": "acc-a"}],
            [{"symbol": "005930", "delta": 1}],
            [{"symbol": "005930"}],
        ),
    ],
)
@pytest.mark.asyncio
async def test_broker_reconcile_envelope_carries_account_and_legacy_fields(
    socket_path: str,
    bots: list[dict],
    adjustments: list[dict],
    mismatches: list[dict],
) -> None:
    """``broker.reconcile`` 응답은 계좌 단위 필드와 legacy 표시 필드를 함께 담는다."""
    from unittest.mock import AsyncMock

    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    services = _reconcile_services(None)
    services["bot_manager"].list_bots = MagicMock(return_value=bots)
    services["reconciler"].reconcile = AsyncMock(return_value=adjustments)
    services["reconciler"].compute_account_diff = AsyncMock(return_value=mismatches)
    services["reconciler"].detect_account_level = AsyncMock(return_value=mismatches)
    svc_registry = _make_service_registry(**services)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "broker.reconcile",
                "args": {"account_id": "acc-a", "fix": False},
                "actor": "cli-user",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok", response
    assert response["result"] == {
        "account_id": "acc-a",
        "fix": False,
        "bot_count": len(bots),
        "adjustments": adjustments,
        "mismatches": mismatches,
        "total_symbols": len(mismatches),
        "discrepancies": mismatches,
        "match": False,
        "fix_applied": False,
        "corrections": len(adjustments),
    }
