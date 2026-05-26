"""IPCServer ``_dispatch`` audit_action 자동 발화 wrapper 검증.

Refs #1851 (#1819 부모 epic): dispatch wrapper 가 handler 정상 종료 후
``CommandSpec.audit_action`` metadata 를 기반으로 ``audit_logger.log`` 를
자동 발화하는지, 그리고 reserved key ``_audit_detail`` 이 public envelope
``result`` 로 새 나가지 않는지 확인한다.

invariant:
- ``audit_action`` 부여 + handler 성공 → ``audit_logger.log`` 1회 호출.
- handler 가 예외로 종료 → audit log 호출 없음.
- ``audit_action=None`` (default) → audit log 호출 없음.
- ``_audit_detail`` 은 public envelope ``result`` 에 절대 포함되지 않는다.
- ``audit_logger.log`` 시그니처는 ``member_id, action, resource, detail, ip``
  keyword-only 5 인자 (``AuditLogger.log``, ``src/ante/audit/logger.py:39``).
- handler 가 ``_audit_detail`` 을 누락해도 wrapper 가 default ("") 로 호출.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import CommandRegistry
from ante.ipc.server import IPCServer


def _make_service_registry(
    *, audit_logger: Any = None, **overrides: Any
) -> ServiceRegistry:
    """기본 7 service + optional audit_logger 채운 ServiceRegistry."""
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
    if audit_logger is not None:
        defaults["audit_logger"] = audit_logger
    return ServiceRegistry(**defaults)


def _make_audit_logger_mock() -> MagicMock:
    """``AuditLogger.log`` 시그니처(async) 를 따르는 mock."""
    logger = MagicMock()
    logger.log = AsyncMock(return_value=None)
    return logger


@pytest.fixture
def socket_path() -> str:
    """Unix 소켓 경로 길이 제한(104B) 회피 — /tmp 직접 사용."""
    td = tempfile.mkdtemp(prefix="ipc-audit", dir="/tmp")
    return str(Path(td) / "t.sock")


# ── audit_action 자동 발화 ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_action_fires_on_success(socket_path: str) -> None:
    """audit_action 부여 + handler 성공 → audit_logger.log 1회 호출."""
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "ok": True,
            "_audit_detail": {
                "resource": "bot:my-bot",
                "detail": "fields=['name']",
                "ip": "127.0.0.1",
            },
        }

    cmd_registry.register(
        "test.audit_cmd",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="test.audit_cmd",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.audit_cmd", "args": {}, "actor": "alice"}
        )
        assert response["status"] == "ok"
        # audit_logger.log 가 정확히 1회 호출됨.
        assert audit_logger.log.await_count == 1
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_audit_action_does_not_fire_on_failure(socket_path: str) -> None:
    """handler 가 예외로 종료 → audit_logger.log 호출 안 됨."""
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        raise RuntimeError("boom")

    cmd_registry.register(
        "test.audit_fail",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="test.audit_fail",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.audit_fail", "args": {}, "actor": "alice"}
        )
        assert response["status"] == "error"
        # 실패한 handler 는 audit 안 남김.
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_no_audit_action_does_not_fire(socket_path: str) -> None:
    """audit_action=None (default) → audit_logger.log 호출 안 됨.

    audit_logger 가 주입되어 있어도 spec.audit_action 이 None 이면 wrapper 가
    호출하지 않는다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {"ok": True}

    cmd_registry.register(
        "test.no_audit",
        handler,
        is_mutating=False,
        # audit_action=None (default)
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.no_audit", "args": {}, "actor": "alice"}
        )
        assert response["status"] == "ok"
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


# ── reserved key strip invariant ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_detail_stripped_from_public_envelope(socket_path: str) -> None:
    """``_audit_detail`` 은 public envelope ``result`` 에 절대 포함되지 않는다."""
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "bot": {"id": "x"},
            "_audit_detail": {
                "resource": "bot:x",
                "detail": "secret-internal-detail",
                "ip": "10.0.0.1",
            },
        }

    cmd_registry.register(
        "test.audit_strip",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="test.audit_strip",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.audit_strip", "args": {}, "actor": "alice"}
        )
        assert response["status"] == "ok"
        # public envelope 의 result 에는 _audit_detail 이 없다.
        assert "_audit_detail" not in response["result"]
        # 정상 result 키는 보존.
        assert response["result"] == {"bot": {"id": "x"}}
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_audit_detail_stripped_even_without_audit_action(
    socket_path: str,
) -> None:
    """audit_action=None 이어도 ``_audit_detail`` 은 envelope 에서 strip 된다.

    handler 가 실수로 reserved key 를 반환하더라도 wrapper 가 보호한다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "ok": True,
            "_audit_detail": {"resource": "x"},
        }

    cmd_registry.register(
        "test.strip_only",
        handler,
        is_mutating=False,
        # audit_action=None — audit 호출은 안 일어남.
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {"id": "1", "command": "test.strip_only", "args": {}, "actor": "alice"}
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


# ── audit_logger.log 시그니처 정확성 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_logger_signature_uses_member_id_action_resource_detail_ip(
    socket_path: str,
) -> None:
    """wrapper 는 AuditLogger.log 의 실제 시그니처를 따른다.

    ``AuditLogger.log`` (``src/ante/audit/logger.py:39``) 시그니처:
    ``log(*, member_id, action, resource="", detail="", ip="")``.

    wrapper 는 ``member_id=actor`` (request.actor) + ``action=spec.audit_action``
    + ``resource/detail/ip`` (``_audit_detail`` 에서 추출) 로 호출한다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "ok": True,
            "_audit_detail": {
                "resource": "bot:42",
                "detail": "fields=['name']",
                "ip": "10.0.0.5",
            },
        }

    cmd_registry.register(
        "test.audit_sig",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="bot.update",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        await server._dispatch(
            {"id": "1", "command": "test.audit_sig", "args": {}, "actor": "bob"}
        )
        # keyword-only 5 인자로 호출되었어야 한다.
        audit_logger.log.assert_awaited_once_with(
            member_id="bob",
            action="bot.update",
            resource="bot:42",
            detail="fields=['name']",
            ip="10.0.0.5",
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_handler_missing_audit_detail_uses_defaults(socket_path: str) -> None:
    """handler 가 ``_audit_detail`` 키를 누락하면 wrapper 가 default "" 로 호출.

    ``AuditLogger.log`` 의 ``resource``/``detail``/``ip`` 는 default ``""`` 이며,
    wrapper 는 None 인 경우 ``""`` 로 정규화해 시그니처와 정합을 유지한다.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        # _audit_detail 누락 — wrapper 가 default 로 처리해야 함.
        return {"ok": True}

    cmd_registry.register(
        "test.audit_no_detail",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="test.audit_no_detail",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.audit_no_detail",
                "args": {},
                "actor": "carol",
            }
        )
        assert response["status"] == "ok"
        # default "" 로 호출되었어야 한다.
        audit_logger.log.assert_awaited_once_with(
            member_id="carol",
            action="test.audit_no_detail",
            resource="",
            detail="",
            ip="",
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_audit_detail_partial_fields_filled_with_defaults(
    socket_path: str,
) -> None:
    """``_audit_detail`` 이 일부 필드만 채워도 누락 필드는 default "" 로 호출."""
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "ok": True,
            # resource 만 채우고 detail / ip 누락.
            "_audit_detail": {"resource": "treasury:acc-1"},
        }

    cmd_registry.register(
        "test.audit_partial",
        handler,
        is_mutating=True,
        required_services=frozenset({"audit_logger"}),
        audit_action="treasury.set_balance",
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(audit_logger=audit_logger)

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        await server._dispatch(
            {
                "id": "1",
                "command": "test.audit_partial",
                "args": {},
                "actor": "ops",
            }
        )
        audit_logger.log.assert_awaited_once_with(
            member_id="ops",
            action="treasury.set_balance",
            resource="treasury:acc-1",
            detail="",
            ip="",
        )
    finally:
        await server.stop()


# ── audit_action + audit_logger 부재 (lifecycle ordering 보조) ─────────────


@pytest.mark.asyncio
async def test_audit_action_without_audit_logger_no_crash(socket_path: str) -> None:
    """방어 케이스 — audit_action 부여되었지만 audit_logger 가 None.

    실제로는 ``required_services={"audit_logger"}`` 가 preflight 에서 차단하므로
    이 경로는 ``required_services`` 미선언 또는 defensive defense-in-depth
    영역이다. wrapper 가 ``getattr(svc, "audit_logger", None) is None`` 인 경우
    호출을 skip 하고 정상 응답을 반환해야 한다 — crash 금지.
    """
    cmd_registry = CommandRegistry()

    async def handler(svc: ServiceRegistry, args: dict, actor: str) -> dict:
        return {
            "ok": True,
            "_audit_detail": {"resource": "x"},
        }

    # required_services 에 audit_logger 미포함 — preflight 차단 없음.
    cmd_registry.register(
        "test.audit_defensive",
        handler,
        is_mutating=True,
        audit_action="test.audit_defensive",
    )

    svc_registry = _make_service_registry()  # audit_logger=None (default)
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "test.audit_defensive",
                "args": {},
                "actor": "x",
            }
        )
        # crash 없이 정상 응답 + _audit_detail strip.
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
    finally:
        await server.stop()
