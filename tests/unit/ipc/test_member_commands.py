"""member 명령 9개의 응답·서비스 호출·감사 기록 특성 테스트 (#2683 ③).

실제 ``register_all_handlers``와 ``IPCServer._dispatch``를 지난다. 서비스는
``member_service`` 메서드를 기록하는 대역이다. 비밀값은 테스트용 고정 문자열이다.
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
from ante.member.models import Member, MemberRole, MemberStatus, MemberType
from tests.unit.ipc.test_request_model_domain import validation_message

ACTOR = "ops-lead"
RECOVERY_KEY = "rk-fixed-1"
NEW_PASSWORD = "np-fixed-2"
PASSWORD = "pw-fixed-3"


def _member(member_id: str = "m-7", **overrides: Any) -> Member:
    base: dict[str, Any] = {
        "member_id": member_id,
        "type": MemberType.AGENT,
        "role": MemberRole.DEFAULT,
        "org": "org-2",
        "name": "이름",
        "emoji": "🦊",
        "status": MemberStatus.ACTIVE,
        "scopes": ["strategy:read"],
        "token_hash": "hash",
        "password_hash": "pwhash",
        "recovery_key_hash": "rkhash",
        "created_at": "2026-01-01T00:00:00Z",
        "created_by": "system",
    }
    base.update(overrides)
    return Member(**base)


class _Harness:
    def __init__(self) -> None:
        member = MagicMock()
        member.update_scopes = AsyncMock(
            return_value=_member(scopes=["strategy:read", "trade:write"])
        )
        member.register = AsyncMock(return_value=(_member(), "tok-new"))
        member.update_emoji = AsyncMock(return_value=_member(emoji="🐻"))
        member.suspend = AsyncMock(return_value=_member(status=MemberStatus.SUSPENDED))
        member.reactivate = AsyncMock(return_value=_member())
        member.revoke = AsyncMock(return_value=_member(status=MemberStatus.REVOKED))
        member.rotate_token = AsyncMock(return_value=(_member(), "tok-rotated"))
        member.list_members = AsyncMock(
            return_value=[
                _member("agent-x"),
                _member("master-bob", type=MemberType.HUMAN, role=MemberRole.MASTER),
            ]
        )
        member.reset_password = AsyncMock(return_value=None)
        member.regenerate_recovery_key = AsyncMock(return_value="rk-new")
        self.member = member
        self.audit_logger = MagicMock()
        self.audit_logger.log = AsyncMock(return_value=None)
        registry = CommandRegistry()
        register_all_handlers(registry)
        services = ServiceRegistry(
            account=MagicMock(),
            bot_manager=MagicMock(),
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=MagicMock(),
            audit_logger=self.audit_logger,
            member_service=member,
        )
        self.server = IPCServer("/tmp/unused.sock", services, registry)
        self.server._state = IPCServerState.RUNNING

    async def send(self, command: str, args: Any) -> dict:
        return await self.server._dispatch(
            {"id": "req-1", "command": command, "args": args, "actor": ACTOR}
        )

    def assert_audited(self, action: str, resource: str, detail: str = "") -> None:
        self.audit_logger.log.assert_awaited_once_with(
            member_id=ACTOR, action=action, resource=resource, detail=detail, ip=""
        )

    def assert_no_service_call(self) -> None:
        for name in (
            "update_scopes",
            "register",
            "update_emoji",
            "suspend",
            "reactivate",
            "revoke",
            "rotate_token",
            "list_members",
            "reset_password",
            "regenerate_recovery_key",
        ):
            getattr(self.member, name).assert_not_awaited()
        self.audit_logger.log.assert_not_awaited()


def _ok(result: dict) -> dict:
    return {"id": "req-1", "status": "ok", "result": result}


@pytest.mark.asyncio
async def test_update_scopes_passes_the_list_and_audits() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.update_scopes",
        {"member_id": "m-7", "scopes": ["strategy:read", "trade:write"]},
    )
    assert response == _ok(
        {
            "member_id": "m-7",
            "scopes": ["strategy:read", "trade:write"],
            "status": "active",
        }
    )
    harness.member.update_scopes.assert_awaited_once_with(
        "m-7", ["strategy:read", "trade:write"], updated_by="ops-lead"
    )
    harness.assert_audited(
        "member.update_scopes",
        "member:m-7",
        "scopes=['strategy:read', 'trade:write']",
    )


@pytest.mark.asyncio
async def test_update_scopes_without_scopes_sends_an_empty_list() -> None:
    harness = _Harness()
    response = await harness.send("member.update_scopes", {"member_id": "m-7"})
    assert response["status"] == "ok", response
    harness.member.update_scopes.assert_awaited_once_with(
        "m-7", [], updated_by="ops-lead"
    )
    harness.assert_audited("member.update_scopes", "member:m-7", "scopes=[]")


@pytest.mark.asyncio
async def test_register_passes_every_field_and_returns_the_token() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.register",
        {
            "member_id": "m-7",
            "member_type": "agent",
            "org": "org-2",
            "name": "이름",
            "scopes": ["strategy:read"],
        },
    )
    assert response == _ok(
        {
            "member_id": "m-7",
            "type": "agent",
            "role": "default",
            "org": "org-2",
            "name": "이름",
            "token": "tok-new",
        }
    )
    harness.member.register.assert_awaited_once_with(
        member_id="m-7",
        member_type="agent",
        org="org-2",
        name="이름",
        scopes=["strategy:read"],
        registered_by="ops-lead",
    )
    harness.assert_audited("member.register", "member:m-7")


@pytest.mark.asyncio
async def test_register_defaults() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.register", {"member_id": "m-7", "member_type": "human"}
    )
    assert response["status"] == "ok", response
    harness.member.register.assert_awaited_once_with(
        member_id="m-7",
        member_type="human",
        org="default",
        name="",
        scopes=[],
        registered_by="ops-lead",
    )


@pytest.mark.asyncio
async def test_set_emoji_passes_the_emoji_and_audits() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.set_emoji", {"member_id": "m-7", "emoji": "🐻"}
    )
    assert response == _ok({"member_id": "m-7", "emoji": "🐻"})
    harness.member.update_emoji.assert_awaited_once_with(
        "m-7", "🐻", updated_by="ops-lead"
    )
    harness.assert_audited("member.set_emoji", "member:m-7")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "method", "by_kwarg", "status"),
    [
        ("member.suspend", "suspend", "suspended_by", "suspended"),
        ("member.reactivate", "reactivate", "reactivated_by", "active"),
        ("member.revoke", "revoke", "revoked_by", "revoked"),
    ],
)
async def test_state_change_passes_the_actor_and_audits(
    command: str, method: str, by_kwarg: str, status: str
) -> None:
    harness = _Harness()
    response = await harness.send(command, {"member_id": "m-7"})
    assert response == _ok({"member_id": "m-7", "status": status})
    getattr(harness.member, method).assert_awaited_once_with(
        "m-7", **{by_kwarg: "ops-lead"}
    )
    harness.assert_audited(command, "member:m-7")


@pytest.mark.asyncio
async def test_rotate_token_returns_the_new_token() -> None:
    harness = _Harness()
    response = await harness.send("member.rotate_token", {"member_id": "m-7"})
    assert response == _ok({"member_id": "m-7", "token": "tok-rotated"})
    harness.member.rotate_token.assert_awaited_once_with("m-7", rotated_by="ops-lead")
    harness.assert_audited("member.rotate_token", "member:m-7")


@pytest.mark.asyncio
async def test_reset_password_passes_plain_strings_to_the_service() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.reset_password",
        {"recovery_key": RECOVERY_KEY, "new_password": NEW_PASSWORD},
    )
    assert response == _ok({})
    harness.member.reset_password.assert_awaited_once_with(
        "master-bob", "rk-fixed-1", "np-fixed-2"
    )
    passed = harness.member.reset_password.await_args.args
    assert [type(value) for value in passed] == [str, str, str]
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="system:recovery",
        action="member.reset_password",
        resource="member:master-bob",
        detail="password reset via recovery key",
        ip="",
    )


@pytest.mark.asyncio
async def test_regenerate_recovery_key_passes_a_plain_string_to_the_service() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.regenerate_recovery_key", {"password": PASSWORD}
    )
    assert response == _ok({"recovery_key": "rk-new"})
    harness.member.regenerate_recovery_key.assert_awaited_once_with(
        "master-bob", "pw-fixed-3"
    )
    passed = harness.member.regenerate_recovery_key.await_args.args
    assert [type(value) for value in passed] == [str, str]
    harness.audit_logger.log.assert_awaited_once_with(
        member_id="system:recovery",
        action="member.regenerate_recovery_key",
        resource="member:master-bob",
        detail="recovery key regenerated",
        ip="",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("member.reset_password", {"recovery_key": "", "new_password": ""}),
        ("member.regenerate_recovery_key", {"password": ""}),
    ],
)
async def test_empty_secrets_reach_the_service(
    command: str, args: dict[str, str]
) -> None:
    harness = _Harness()
    response = await harness.send(command, args)
    assert response["status"] == "ok", response
    method = getattr(harness.member, command.removeprefix("member."))
    assert method.await_args.args[1:] == tuple(args.values())


@pytest.mark.asyncio
async def test_scopes_as_a_string_is_split_into_characters() -> None:
    harness = _Harness()
    response = await harness.send(
        "member.update_scopes", {"member_id": "m-7", "scopes": "a,b"}
    )
    assert response["status"] == "ok", response
    harness.member.update_scopes.assert_awaited_once_with(
        "m-7", ["a", ",", "b"], updated_by="ops-lead"
    )


@pytest.mark.asyncio
async def test_missing_member_id_is_an_execution_error() -> None:
    harness = _Harness()
    response = await harness.send("member.suspend", {})
    assert response["error"]["code"] == "EXECUTION_ERROR", response
    harness.assert_no_service_call()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "args"),
    [
        ("member.reset_password", {"recovery_key": 7, "new_password": "MARKSEC01x"}),
        ("member.regenerate_recovery_key", {"password": "MARKSEC02x", "zz": 1}),
    ],
)
async def test_secret_is_not_in_the_response_or_the_log(
    command: str, args: dict[str, Any], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    harness = _Harness()
    harness.member.reset_password.side_effect = ValueError("bad credential")
    harness.member.regenerate_recovery_key.side_effect = ValueError("bad credential")
    response = await harness.send(command, args)
    assert response["status"] == "error", response
    assert "MARKSEC0" not in json.dumps(response, ensure_ascii=False)
    assert "MARKSEC0" not in caplog.text
    harness.audit_logger.log.assert_not_awaited()


def test_validation_message_helper_shape() -> None:
    assert (
        validation_message("member.suspend", ("member_id", "missing"))
        == "member.suspend 인자 검증 실패: member_id(missing)"
    )
