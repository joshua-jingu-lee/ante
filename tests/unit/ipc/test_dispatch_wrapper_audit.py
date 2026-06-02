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
from unittest.mock import AsyncMock, MagicMock, patch

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


# ── account.suspend / account.activate wrapper migration (#1852) ──────────


@pytest.mark.asyncio
async def test_account_suspend_audit_action_fires(socket_path: str) -> None:
    """Refs #1852: ``account.suspend`` 가 wrapper 자동 audit 발화한다.

    register_all_handlers 가 ``audit_action="account.suspend"`` 를 부여하므로
    handler 정상 종료 후 wrapper 가 ``audit_logger.log`` 를 1회 호출하고
    ``_audit_detail`` 의 ``resource``/``detail`` 을 전달한다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.suspend = AsyncMock(return_value=None)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "account.suspend",
                "args": {"account_id": "acc-1", "reason": "ops halt"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="account.suspend",
            resource="account:acc-1",
            detail="reason=ops halt",
            ip="",
        )
        fake_account.suspend.assert_awaited_once_with(
            "acc-1", reason="ops halt", suspended_by="alice"
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_activate_audit_action_fires(socket_path: str) -> None:
    """Refs #1852: ``account.activate`` 가 wrapper 자동 audit 발화한다."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.activate = AsyncMock(return_value=None)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "account.activate",
                "args": {"account_id": "acc-1"},
                "actor": "bob",
            }
        )
        assert response["status"] == "ok"
        audit_logger.log.assert_awaited_once_with(
            member_id="bob",
            action="account.activate",
            resource="account:acc-1",
            detail="",
            ip="",
        )
        fake_account.activate.assert_awaited_once_with("acc-1", activated_by="bob")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_suspend_audit_detail_stripped_from_envelope(
    socket_path: str,
) -> None:
    """Refs #1852: ``account.suspend`` public envelope 에 ``_audit_detail``
    이 절대 노출되지 않는다 (reserved key strip invariant)."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.suspend = AsyncMock(return_value=None)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "account.suspend",
                "args": {"account_id": "acc-1", "reason": "ops"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        assert response["result"] == {
            "account_id": "acc-1",
            "status": "suspended",
        }
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_account_suspend_account_id_policy_required_preflight(
    socket_path: str,
) -> None:
    """Refs #1852: ``account.suspend`` 는 ``account_id_policy="required"`` 로
    invalid/missing ``account_id`` 를 ``VALIDATION_ERROR`` envelope 으로
    handler 호출 전에 거부한다.

    ``require_account_id`` 가 wrapper preflight 단계에서 raise 되면 dispatch
    의 generic except 가 ``getattr(e, "code", ...)`` 로 ``VALIDATION_ERROR``
    envelope 을 만들어 반환한다(#1850 동형). ``account.suspend`` 실제 서비스
    호출은 절대 일어나지 않는다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.suspend = AsyncMock(return_value=None)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        # missing account_id
        response = await server._dispatch(
            {
                "id": "1",
                "command": "account.suspend",
                "args": {"reason": "x"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"

        # empty string
        response = await server._dispatch(
            {
                "id": "2",
                "command": "account.suspend",
                "args": {"account_id": ""},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"

        # reserved 'default'
        response = await server._dispatch(
            {
                "id": "3",
                "command": "account.suspend",
                "args": {"account_id": "default"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"

        # pattern violation
        response = await server._dispatch(
            {
                "id": "4",
                "command": "account.suspend",
                "args": {"account_id": "bad_id!"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "VALIDATION_ERROR"

        # service 호출 / audit 발화는 0회 (preflight 차단)
        fake_account.suspend.assert_not_awaited()
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


# ── bot.signal_key.rotate wrapper audit (#2111) ───────────────────────────


@pytest.mark.asyncio
async def test_bot_signal_key_rotate_audit_action_fires(socket_path: str) -> None:
    """Refs #2111: ``bot.signal_key.rotate`` 가 wrapper 자동 audit 발화한다.

    register_all_handlers 가 ``audit_action="bot.signal_key.rotate"`` 를
    부여하므로 handler 정상 종료 후 wrapper 가 ``audit_logger.log`` 를 1회
    호출하고 ``_audit_detail`` 의 ``resource="bot:{bot_id}"`` (audit.md:121)
    를 전달한다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_bot_manager = MagicMock()
    fake_bot_manager.rotate_signal_key = AsyncMock(return_value="sk_new_rotated")

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, bot_manager=fake_bot_manager
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "bot.signal_key.rotate",
                "args": {"bot_id": "bot-7"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        # public envelope 은 rotated/signal_key 를 담고 _audit_detail 은 strip.
        assert response["result"] == {
            "bot_id": "bot-7",
            "signal_key": "sk_new_rotated",
            "rotated": True,
        }
        assert "_audit_detail" not in response["result"]
        # audit.md:121 SSOT: action=bot.signal_key.rotate, resource=bot:{bot_id}.
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="bot.signal_key.rotate",
            resource="bot:bot-7",
            detail="",
            ip="",
        )
        fake_bot_manager.rotate_signal_key.assert_awaited_once_with("bot-7")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_signal_key_rotate_audit_not_fired_on_failure(
    socket_path: str,
) -> None:
    """Refs #2111: ``BotNotFoundError`` 등 거부 경로는 audit 발화 안 함 +
    stable code envelope (실패 시 audit invariant)."""
    from ante.bot.exceptions import BotNotFoundError
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_bot_manager = MagicMock()
    fake_bot_manager.rotate_signal_key = AsyncMock(
        side_effect=BotNotFoundError("bot-missing")
    )

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, bot_manager=fake_bot_manager
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "bot.signal_key.rotate",
                "args": {"bot_id": "bot-missing"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "BOT_NOT_FOUND"
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


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


# ── #2110 audit wiring (system halt/clear-halt, bot create/remove, ───────────
#    approval approve/reject/cancel) ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_system_halt_audit_action_fires(socket_path: str) -> None:
    """Refs #2110 (audit.md:115): ``system.halt`` 가 wrapper 자동 audit 발화.

    resource 는 ``system:kill_switch`` (audit.md SSOT). handler 성공 후
    ``audit_logger.log`` 1회 호출 + ``_audit_detail`` strip.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.suspend_all = AsyncMock(return_value=[])

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "system.halt",
                "args": {"reason": "ops halt"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="system.halt",
            resource="system:kill_switch",
            detail="reason=ops halt",
            ip="",
        )
        fake_account.suspend_all.assert_awaited_once_with(
            reason="ops halt", suspended_by="alice"
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_system_clear_halt_audit_action_fires(socket_path: str) -> None:
    """Refs #2110 (audit.md:116): ``system.clear_halt`` 자동 audit 발화."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.activate_all = AsyncMock(return_value=[])

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "system.clear_halt",
                "args": {},
                "actor": "bob",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="bob",
            action="system.clear_halt",
            resource="system:kill_switch",
            detail="",
            ip="",
        )
        fake_account.activate_all.assert_awaited_once_with(activated_by="bob")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_system_halt_audit_not_fired_on_failure(socket_path: str) -> None:
    """Refs #2110: handler 예외(suspend_all 실패) 시 audit 미발화."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_account = MagicMock()
    fake_account.suspend_all = AsyncMock(side_effect=RuntimeError("boom"))

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, account=fake_account
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "system.halt",
                "args": {"reason": "x"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_create_audit_action_fires_with_result_bot_id(
    socket_path: str,
) -> None:
    """Refs #2110 (audit.md:117): ``bot.create`` 자동 audit 발화.

    resource 는 **생성 결과** ``bot.bot_id`` 를 쓴다 — 요청 args 의 ``bot_id``
    가 비어 있어도(서버가 채움) result 의 bot_id 로 audit 한다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_bot = MagicMock()
    fake_bot.bot_id = "bot-generated-7"
    fake_bot_manager = MagicMock()
    fake_bot_manager.create_bot = AsyncMock(return_value=fake_bot)

    strategy_record = MagicMock()
    strategy_record.filepath = "/tmp/_fake_strategy.py"
    strategy_registry = MagicMock()
    strategy_registry.get = AsyncMock(return_value=strategy_record)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger,
        bot_manager=fake_bot_manager,
        strategy_registry=strategy_registry,
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        with patch("ante.strategy.loader.StrategyLoader.load") as mock_load:
            mock_load.return_value = MagicMock()
            response = await server._dispatch(
                {
                    "id": "1",
                    "command": "bot.create",
                    "args": {
                        "account_id": "acc1",
                        "strategy_id": "s1",
                        "name": "test",
                        # bot_id 비움 — resource 는 result bot_id 로 채워져야 함.
                        "bot_id": "",
                    },
                    "actor": "alice",
                }
            )
        assert response["status"] == "ok"
        assert response["result"] == {"bot_id": "bot-generated-7"}
        assert "_audit_detail" not in response["result"]
        # resource 는 요청 args 의 빈 bot_id 가 아니라 생성 결과 bot_id.
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="bot.create",
            resource="bot:bot-generated-7",
            detail="",
            ip="",
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_remove_audit_action_is_bot_delete(socket_path: str) -> None:
    """Refs #2110 (audit.md:120): ``bot.remove`` command 의 audit action 은
    audit.md SSOT 에 따라 ``bot.delete`` (command 이름과 다름)."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_bot_manager = MagicMock()
    fake_bot_manager.remove_bot = AsyncMock(return_value=None)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, bot_manager=fake_bot_manager
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "bot.remove",
                "args": {"bot_id": "bot-9"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        assert response["result"] == {"bot_id": "bot-9", "removed": True}
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="bot.delete",
            resource="bot:bot-9",
            detail="",
            ip="",
        )
        fake_bot_manager.remove_bot.assert_awaited_once_with("bot-9")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_bot_remove_audit_not_fired_on_failure(socket_path: str) -> None:
    """Refs #2110: ``BotNotFoundError`` 등 거부 경로는 audit 미발화."""
    from ante.bot.exceptions import BotNotFoundError
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_bot_manager = MagicMock()
    fake_bot_manager.remove_bot = AsyncMock(side_effect=BotNotFoundError("bot-missing"))

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, bot_manager=fake_bot_manager
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "bot.remove",
                "args": {"bot_id": "bot-missing"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert response["error"]["code"] == "BOT_NOT_FOUND"
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_approval_approve_audit_action_fires(socket_path: str) -> None:
    """Refs #2110 (audit.md:112): ``approval.approve`` 자동 audit 발화.

    resource 는 ``approval:{id}`` (요청 args 의 id).
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_request = MagicMock()
    fake_request.id = "apr-1"
    fake_request.status = "approved"
    fake_approval = MagicMock()
    fake_approval.approve = AsyncMock(return_value=fake_request)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, approval=fake_approval
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "approval.approve",
                "args": {"id": "apr-1"},
                "actor": "alice",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="alice",
            action="approval.approve",
            resource="approval:apr-1",
            detail="",
            ip="",
        )
        fake_approval.approve.assert_awaited_once_with("apr-1", resolved_by="alice")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_approval_reject_audit_action_fires(socket_path: str) -> None:
    """Refs #2110 (audit.md:113): ``approval.reject`` 자동 audit 발화."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_request = MagicMock()
    fake_request.id = "apr-2"
    fake_request.status = "rejected"
    fake_approval = MagicMock()
    fake_approval.reject = AsyncMock(return_value=fake_request)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, approval=fake_approval
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "approval.reject",
                "args": {"id": "apr-2", "reason": "no good"},
                "actor": "bob",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="bob",
            action="approval.reject",
            resource="approval:apr-2",
            detail="reason=no good",
            ip="",
        )
        fake_approval.reject.assert_awaited_once_with(
            "apr-2", resolved_by="bob", reject_reason="no good"
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_approval_cancel_audit_action_fires(socket_path: str) -> None:
    """Refs #2110 (audit.md:114): ``approval.cancel`` 자동 audit 발화."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_request = MagicMock()
    fake_request.id = "apr-3"
    fake_request.status = "cancelled"
    fake_approval = MagicMock()
    fake_approval.cancel = AsyncMock(return_value=fake_request)

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, approval=fake_approval
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "approval.cancel",
                "args": {"id": "apr-3"},
                "actor": "carol",
            }
        )
        assert response["status"] == "ok"
        assert "_audit_detail" not in response["result"]
        audit_logger.log.assert_awaited_once_with(
            member_id="carol",
            action="approval.cancel",
            resource="approval:apr-3",
            detail="",
            ip="",
        )
        fake_approval.cancel.assert_awaited_once_with("apr-3", requester="carol")
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_approval_approve_audit_not_fired_on_failure(socket_path: str) -> None:
    """Refs #2110: approve handler 예외 시 audit 미발화."""
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    fake_approval = MagicMock()
    fake_approval.approve = AsyncMock(side_effect=RuntimeError("boom"))

    audit_logger = _make_audit_logger_mock()
    svc_registry = _make_service_registry(
        audit_logger=audit_logger, approval=fake_approval
    )

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "approval.approve",
                "args": {"id": "apr-x"},
                "actor": "alice",
            }
        )
        assert response["status"] == "error"
        assert audit_logger.log.await_count == 0
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_2110_commands_preflight_reject_without_audit_logger(
    socket_path: str,
) -> None:
    """Refs #2110: audit_logger 미주입 시 7개 명령 모두 preflight 거부.

    account.suspend 선례 동형 — required_services 에 audit_logger 가 추가됐으므로
    legacy/미주입 환경에서는 handler 도달 전 ``SERVICE_NOT_CONFIGURED`` 로
    차단되고 audit/상태변경이 일어나지 않는다.
    """
    from ante.ipc.registry import register_all_handlers

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)

    svc_registry = _make_service_registry()  # audit_logger=None (default)
    assert svc_registry.audit_logger is None

    server = IPCServer(socket_path, svc_registry, cmd_registry)
    await server.start()
    try:
        for command, args in [
            ("system.halt", {}),
            ("system.clear_halt", {}),
            ("bot.create", {"account_id": "acc1", "strategy_id": "s1"}),
            ("bot.remove", {"bot_id": "b1"}),
            ("approval.approve", {"id": "apr-1"}),
            ("approval.reject", {"id": "apr-1"}),
            ("approval.cancel", {"id": "apr-1"}),
        ]:
            spec = cmd_registry.get(command)
            assert spec is not None
            assert "audit_logger" in spec.required_services, command
            response = await server._dispatch(
                {"id": "1", "command": command, "args": args, "actor": "x"}
            )
            assert response["status"] == "error", command
            assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED", command
    finally:
        await server.stop()
