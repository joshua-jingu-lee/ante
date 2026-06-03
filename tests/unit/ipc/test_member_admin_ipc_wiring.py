"""member admin mutation 8개 runtime IPC wiring 검증 (#2113).

member admin mutation 8개(``member.register`` / ``member.set_emoji`` /
``member.suspend`` / ``member.reactivate`` / ``member.revoke`` /
``member.rotate_token`` / ``member.reset_password`` /
``member.regenerate_recovery_key``)를 ``member.update_scopes`` 동형으로
runtime IPC (IPC-first + 서버 정지 fallback) 로 wiring 했음을 검증한다.

핵심 invariant:

(a) is_active_runtime True → 각 CLI 명령이 ``ipc_send("member.X")`` 위임 +
    handler 가 MemberService 위임 + audit 1회 발화.
(b) is_active_runtime False → CLI cold-path fallback (직접 MemberService).
(c) ServerNotRunning → CLI ClickException surface (secret 비노출).
(d) 출력 shape parity (register/rotate_token fields+token, regen recovery_key).
(e) comprehensive secret 비노출: token / recovery_key / new_password / password
    가 ``_audit_detail`` · audit.log detail · IPC error envelope message ·
    server logger.exception · CLI ClickException surface · 테스트 snapshot
    어디에도 없다.
(f) ``_assert_master(actor)`` 게이트 보존 (suspended_by/...=actor 전달).
(g) reset/regen audit resource=member:{resolved master_id} + audit member_id=
    고정 sentinel 상수 (client actor 가 아님).
(h) member.register audit_action lockstep (``member.register``).
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.core.registry import ServiceRegistry
from ante.ipc.registry import (
    _RECOVERY_AUDIT_MEMBER_ID,
    CommandRegistry,
    register_all_handlers,
)
from ante.ipc.server import IPCServer
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# 테스트가 leak 여부를 검사하는 secret 토큰 sentinels. 어떤 envelope/audit/log
# 에도 등장하면 안 된다.
SECRET_TOKEN = "SECRET-TOKEN-aaaaaaaaaaaaaaaaaaaa"
SECRET_RECOVERY_KEY = "SECRET-RECOVERY-bbbbbbbbbbbbbbbb"
SECRET_NEW_PASSWORD = "SECRET-NEWPW-cccccccccccccccc"
SECRET_PASSWORD = "SECRET-PW-dddddddddddddddddddd"

_ALL_SECRETS = (
    SECRET_TOKEN,
    SECRET_RECOVERY_KEY,
    SECRET_NEW_PASSWORD,
    SECRET_PASSWORD,
)


def _make_member(member_id: str = "alice", **overrides: Any) -> Member:
    base: dict[str, Any] = {
        "member_id": member_id,
        "type": MemberType.HUMAN,
        "role": MemberRole.DEFAULT,
        "org": "default",
        "name": member_id,
        "emoji": "",
        "status": MemberStatus.ACTIVE,
        "scopes": [],
        "token_hash": "hash",
        "password_hash": "pwhash",
        "recovery_key_hash": "rkhash",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "system",
    }
    base.update(overrides)
    return Member(**base)


def _make_audit_logger_mock() -> MagicMock:
    logger = MagicMock()
    logger.log = AsyncMock(return_value=None)
    return logger


def _make_member_service_mock() -> MagicMock:
    svc = MagicMock()
    svc.register = AsyncMock()
    svc.update_emoji = AsyncMock()
    svc.suspend = AsyncMock()
    svc.reactivate = AsyncMock()
    svc.revoke = AsyncMock()
    svc.rotate_token = AsyncMock()
    svc.reset_password = AsyncMock()
    svc.regenerate_recovery_key = AsyncMock()
    svc.list_members = AsyncMock()
    return svc


def _make_service_registry(
    *, member_service: Any, audit_logger: Any
) -> ServiceRegistry:
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        audit_logger=audit_logger,
        member_service=member_service,
    )


@pytest.fixture
def socket_path() -> str:
    td = tempfile.mkdtemp(prefix="ipc-member", dir="/tmp")
    return str(Path(td) / "t.sock")


def _audit_call_strings(audit_logger: MagicMock) -> str:
    """audit_logger.log 호출의 모든 인자를 직렬화한 문자열."""
    parts: list[str] = []
    for call in audit_logger.log.await_args_list:
        parts.append(repr(call.args))
        parts.append(repr(call.kwargs))
    return " ".join(parts)


def _assert_no_secret(blob: str) -> None:
    for secret in _ALL_SECRETS:
        assert secret not in blob, f"secret {secret!r} leaked into: {blob}"


# ── (a)+(f)+(h): authenticated member 명령 6개 IPC handler ─────────────────


@pytest.mark.asyncio
async def test_register_handler_delegates_and_audits(socket_path: str) -> None:
    member_service = _make_member_service_mock()
    member_service.register.return_value = (
        _make_member("bob", type=MemberType.AGENT, role=MemberRole.DEFAULT),
        SECRET_TOKEN,
    )
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )

    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.register",
                "args": {"member_id": "bob", "member_type": "agent"},
                "actor": "master-1",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    # (f) master 게이트 보존: registered_by=actor 로 위임.
    _, kwargs = member_service.register.await_args
    assert kwargs["registered_by"] == "master-1"
    # (d) shape parity: token 은 result 에만.
    assert response["result"]["token"] == SECRET_TOKEN
    assert response["result"]["member_id"] == "bob"
    # (a)+(h): audit 1회, action=member.register, member_id=actor.
    audit_logger.log.assert_awaited_once()
    _, akw = audit_logger.log.await_args
    assert akw["action"] == "member.register"
    assert akw["member_id"] == "master-1"
    assert akw["resource"] == "member:bob"
    # (e) secret 비노출: _audit_detail 은 envelope 에서 strip, audit detail
    # 에도 token 없음.
    assert "_audit_detail" not in response["result"]
    _assert_no_secret(_audit_call_strings(audit_logger))


@pytest.mark.asyncio
async def test_set_emoji_handler_delegates_to_update_emoji(socket_path: str) -> None:
    member_service = _make_member_service_mock()
    member_service.update_emoji.return_value = _make_member("alice", emoji="🦊")
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.set_emoji",
                "args": {"member_id": "alice", "emoji": "🦊"},
                "actor": "master-1",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    # set_emoji 메서드 없음 → update_emoji 위임.
    member_service.update_emoji.assert_awaited_once()
    args, kwargs = member_service.update_emoji.await_args
    assert args[0] == "alice"
    assert kwargs["updated_by"] == "master-1"
    assert response["result"]["emoji"] == "🦊"
    _, akw = audit_logger.log.await_args
    assert akw["action"] == "member.set_emoji"


@pytest.mark.parametrize(
    ("command", "service_attr", "by_kwarg", "action"),
    [
        ("member.suspend", "suspend", "suspended_by", "member.suspend"),
        ("member.reactivate", "reactivate", "reactivated_by", "member.reactivate"),
        ("member.revoke", "revoke", "revoked_by", "member.revoke"),
    ],
)
@pytest.mark.asyncio
async def test_state_change_handlers_pass_actor_as_by(
    socket_path: str,
    command: str,
    service_attr: str,
    by_kwarg: str,
    action: str,
) -> None:
    """(f) suspend/reactivate/revoke 가 ``*_by=actor`` 로 master 게이트 보존."""
    member_service = _make_member_service_mock()
    getattr(member_service, service_attr).return_value = _make_member(
        "alice", status=MemberStatus.SUSPENDED
    )
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": command,
                "args": {"member_id": "alice"},
                "actor": "master-1",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    _, kwargs = getattr(member_service, service_attr).await_args
    assert kwargs[by_kwarg] == "master-1"
    _, akw = audit_logger.log.await_args
    assert akw["action"] == action
    assert akw["member_id"] == "master-1"
    assert akw["resource"] == "member:alice"


@pytest.mark.asyncio
async def test_rotate_token_handler_token_in_result_only(socket_path: str) -> None:
    member_service = _make_member_service_mock()
    member_service.rotate_token.return_value = (_make_member("alice"), SECRET_TOKEN)
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.rotate_token",
                "args": {"member_id": "alice"},
                "actor": "master-1",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    _, kwargs = member_service.rotate_token.await_args
    assert kwargs["rotated_by"] == "master-1"
    # (d) shape parity + (e) token 은 result 에만, audit detail 에 없음.
    assert response["result"]["token"] == SECRET_TOKEN
    _, akw = audit_logger.log.await_args
    assert akw["action"] == "member.rotate_token"
    _assert_no_secret(_audit_call_strings(audit_logger))


# ── (g): auth-exempt reset/regen — sentinel member_id + master-lookup ──────


@pytest.mark.asyncio
async def test_reset_password_handler_master_lookup_and_sentinel(
    socket_path: str,
) -> None:
    member_service = _make_member_service_mock()
    member_service.list_members.return_value = [
        _make_member("agent-x", type=MemberType.AGENT, role=MemberRole.DEFAULT),
        _make_member("master-bob", role=MemberRole.MASTER),
    ]
    member_service.reset_password.return_value = None
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        # client actor 를 의도적으로 스푸핑 시도(임의 값) — audit 에 반영되면 안 됨.
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.reset_password",
                "args": {
                    "recovery_key": SECRET_RECOVERY_KEY,
                    "new_password": SECRET_NEW_PASSWORD,
                },
                "actor": "attacker-spoofed-actor",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    # master-lookup 은 서버 handler 가 수행 → 해석된 master id 로 reset_password.
    args, _ = member_service.reset_password.await_args
    assert args[0] == "master-bob"
    assert args[1] == SECRET_RECOVERY_KEY
    assert args[2] == SECRET_NEW_PASSWORD
    # (g) audit resource=member:{resolved master_id}, member_id=고정 sentinel
    # (client actor 가 아님).
    _, akw = audit_logger.log.await_args
    assert akw["action"] == "member.reset_password"
    assert akw["resource"] == "member:master-bob"
    assert akw["member_id"] == _RECOVERY_AUDIT_MEMBER_ID
    assert akw["member_id"] != "attacker-spoofed-actor"
    # (e) secret 비노출: recovery_key / new_password 가 audit / envelope 에 없음.
    _assert_no_secret(_audit_call_strings(audit_logger))
    _assert_no_secret(repr(response))


@pytest.mark.asyncio
async def test_regenerate_recovery_key_handler_sentinel_and_result_only(
    socket_path: str,
) -> None:
    member_service = _make_member_service_mock()
    member_service.list_members.return_value = [
        _make_member("master-bob", role=MemberRole.MASTER),
    ]
    member_service.regenerate_recovery_key.return_value = SECRET_RECOVERY_KEY
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.regenerate_recovery_key",
                "args": {"password": SECRET_PASSWORD},
                "actor": "attacker-spoofed-actor",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok"
    args, _ = member_service.regenerate_recovery_key.await_args
    assert args[0] == "master-bob"
    assert args[1] == SECRET_PASSWORD
    # (d) 새 recovery key 는 result 에만.
    assert response["result"]["recovery_key"] == SECRET_RECOVERY_KEY
    # (g) sentinel member_id.
    _, akw = audit_logger.log.await_args
    assert akw["action"] == "member.regenerate_recovery_key"
    assert akw["resource"] == "member:master-bob"
    assert akw["member_id"] == _RECOVERY_AUDIT_MEMBER_ID
    # (e) input password 는 audit/envelope 에 없음. 새 recovery key 는 audit
    # detail 에 없음(result 에만).
    _assert_no_secret(_audit_call_strings(audit_logger))


def test_recovery_audit_sentinel_is_reserved_namespace() -> None:
    """#2295: recovery audit sentinel 은 reserved ``system:`` 네임스페이스 값.

    이전 (#2295 이전): ``"recovery"`` — 사용자/agent member_id 와 충돌 가능.
    #2295 가 ``"system:recovery"`` 로 변경해 ``system:kill_switch`` 와 동일한
    reserved ``system:`` 네임스페이스에 두고 충돌을 제거한다 (member register
    가 ``system:`` prefix 등록을 거부 — defense-in-depth).
    """
    assert _RECOVERY_AUDIT_MEMBER_ID == "system:recovery"
    assert _RECOVERY_AUDIT_MEMBER_ID.startswith("system:")


# ── (e) comprehensive secret 비노출: 실패 경로 envelope + server log ────────


@pytest.mark.asyncio
async def test_reset_password_failure_envelope_and_log_no_secret(
    socket_path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """handler 가 raise 해 IPC error envelope + server logger.exception 경로를
    타도 secret 이 어디에도 노출되지 않는다.

    ``reset_password`` 가 invalid recovery credential 로 raise 하는 메시지에
    secret 이 들어가지 않음 + ``_dispatch`` 의 ``logger.exception`` /
    error envelope message 에도 secret 이 없음을 검증한다.
    """
    from ante.member.errors import MemberInvalidRecoveryCredentialError

    member_service = _make_member_service_mock()
    member_service.list_members.return_value = [
        _make_member("master-bob", role=MemberRole.MASTER),
    ]
    member_service.reset_password.side_effect = MemberInvalidRecoveryCredentialError(
        "recovery credential 검증 실패"
    )
    audit_logger = _make_audit_logger_mock()
    svc = _make_service_registry(
        member_service=member_service, audit_logger=audit_logger
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        with caplog.at_level(logging.DEBUG):
            response = await server._dispatch(
                {
                    "id": "1",
                    "command": "member.reset_password",
                    "args": {
                        "recovery_key": SECRET_RECOVERY_KEY,
                        "new_password": SECRET_NEW_PASSWORD,
                    },
                    "actor": "cli",
                }
            )
    finally:
        await server.stop()

    assert response["status"] == "error"
    # 실패 시 audit 미발화 invariant.
    audit_logger.log.assert_not_awaited()
    # IPC error envelope message 에 secret 없음.
    _assert_no_secret(repr(response))
    # server logger.exception 출력에 secret 없음.
    _assert_no_secret(caplog.text)


# ── required_services preflight: audit_logger / member_service ─────────────


@pytest.mark.asyncio
async def test_member_handlers_require_audit_logger(socket_path: str) -> None:
    """audit_logger 부재 시 preflight 가 모든 member admin 명령을 거부한다."""
    member_service = _make_member_service_mock()
    svc = ServiceRegistry(
        account=MagicMock(),
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        member_service=member_service,
        # audit_logger 미주입(None).
    )
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    server = IPCServer(socket_path, svc, cmd_registry)
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "1",
                "command": "member.suspend",
                "args": {"member_id": "alice"},
                "actor": "master-1",
            }
        )
    finally:
        await server.stop()
    assert response["status"] == "error"
    member_service.suspend.assert_not_awaited()
