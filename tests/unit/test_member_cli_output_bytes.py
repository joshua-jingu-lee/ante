"""member 12개 명령 × 성공 분기 × {text, json}의 출력 바이트를 고정한다 (#2773).

비교 대상은 stdout과 stderr를 합친 ``result.output`` 전체다. 서버 가동 여부
(``is_active_runtime``)로 갈리는 명령은 IPC 분기와 직접 실행 분기를 각각
고정한다. 비밀값(토큰·복구 키)은 출력에 정확히 한 번 나타나야 한다.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import ExitStack, asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner, Result

from ante.member.models import Member
from ante.member.service import InvalidRoleScan

_TOKEN_REGISTER = "fresh-token-xyz"
_TOKEN_ROTATE = "new-token-abc"
_RECOVERY_KEY = "fresh-recovery-key-xyz"
_PASSWORD_ENV = "ANTE_TEST_MEMBER_BYTES_PASSWORD"
_CONFIG_DIR = "/nonexistent/ante-fixture"

_MASTER = Member(
    member_id="test-master",
    type="human",
    role="master",
    org="default",
    name="Test Master",
    status="active",
)


def _member(member_id: str, **overrides: Any) -> Member:
    fields: dict[str, Any] = {
        "type": "agent",
        "role": "default",
        "org": "default",
        "name": "Agent 1",
        "created_at": "2026-01-01T00:00:00",
        "created_by": "test-master",
    }
    fields.update(overrides)
    return Member(member_id=member_id, **fields)


def _runtime_cases(name: str, args: list[str]) -> dict[str, tuple[list[str], bool]]:
    return {f"{name}_ipc": (args, True), f"{name}_direct": (args, False)}


_CASES: dict[str, tuple[list[str], bool]] = {
    "list_empty": (["member", "list"], False),
    "list_rows": (["member", "list"], False),
    "info": (["member", "info", "agent-1"], False),
    "list_invalid_roles_empty": (["member", "list-invalid-roles"], False),
    "list_invalid_roles_rows": (
        ["--config-dir", _CONFIG_DIR, "member", "list-invalid-roles"],
        False,
    ),
    **_runtime_cases(
        "register",
        [
            "member",
            "register",
            "--id",
            "agent-2",
            "--type",
            "agent",
            "--name",
            "새 에이전트",
        ],
    ),
    **_runtime_cases("set_emoji", ["member", "set-emoji", "agent-1", "🤖"]),
    **_runtime_cases(
        "update_scopes",
        ["member", "update-scopes", "agent-1", "--scopes", "account:read,member:read"],
    ),
    **_runtime_cases("suspend", ["member", "suspend", "agent-1"]),
    **_runtime_cases("reactivate", ["member", "reactivate", "agent-1"]),
    **_runtime_cases("revoke", ["member", "revoke", "agent-1", "--yes"]),
    **_runtime_cases("rotate_token", ["member", "rotate-token", "agent-1"]),
    **_runtime_cases(
        "reset_password",
        [
            "member",
            "reset-password",
            "--recovery-key",
            "test-recovery-key",
            "--new-password-env",
            _PASSWORD_ENV,
        ],
    ),
    **_runtime_cases(
        "regenerate_recovery_key",
        ["member", "regenerate-recovery-key", "--password-env", _PASSWORD_ENV],
    ),
}

_SECRETS: dict[str, str] = {
    "register_ipc": _TOKEN_REGISTER,
    "register_direct": _TOKEN_REGISTER,
    "rotate_token_ipc": _TOKEN_ROTATE,
    "rotate_token_direct": _TOKEN_ROTATE,
    "regenerate_recovery_key_ipc": _RECOVERY_KEY,
    "regenerate_recovery_key_direct": _RECOVERY_KEY,
}

_IPC_RESULTS: dict[str, dict[str, Any]] = {
    "register": {
        "member_id": "agent-2",
        "type": "agent",
        "role": "default",
        "org": "default",
        "name": "새 에이전트",
        "token": _TOKEN_REGISTER,
    },
    "set_emoji": {"member_id": "agent-1", "emoji": "🤖"},
    "update_scopes": {
        "member_id": "agent-1",
        "scopes": ["account:read", "member:read"],
        "status": "active",
    },
    "suspend": {"member_id": "agent-1", "status": "suspended"},
    "reactivate": {"member_id": "agent-1", "status": "active"},
    "revoke": {"member_id": "agent-1", "status": "revoked"},
    "rotate_token": {"member_id": "agent-1", "token": _TOKEN_ROTATE},
    "reset_password": {},
    "regenerate_recovery_key": {"recovery_key": _RECOVERY_KEY},
}


def _prepare_service(branch: str, svc: AsyncMock) -> None:
    svc.list_members.return_value = [_MASTER]
    svc.reset_password.return_value = None
    svc.regenerate_recovery_key.return_value = _RECOVERY_KEY
    svc.register.return_value = (
        _member("agent-2", name="새 에이전트"),
        _TOKEN_REGISTER,
    )
    svc.update_emoji.return_value = _member("agent-1", emoji="🤖")
    svc.update_scopes.return_value = _member(
        "agent-1", scopes=["account:read", "member:read"]
    )
    svc.suspend.return_value = _member("agent-1", status="suspended")
    svc.reactivate.return_value = _member("agent-1")
    svc.revoke.return_value = _member("agent-1", status="revoked")
    svc.rotate_token.return_value = (_member("agent-1"), _TOKEN_ROTATE)
    svc.get.return_value = _member(
        "agent-1",
        emoji="🦊",
        scopes=["member:read", "bot:read"],
        last_active_at="2026-01-02T00:00:00",
    )
    svc.find_invalid_role_members.return_value = InvalidRoleScan(
        actionable=[], legacy_revoked=[]
    )
    if branch == "list_empty":
        svc.list_members.return_value = []
    elif branch == "list_rows":
        svc.list_members.return_value = [
            _member("agent-1", emoji="🦊", scopes=["member:read", "bot:read"]),
            _member(
                "analyst", type="human", org="research", name="", status="suspended"
            ),
        ]
    elif branch == "list_invalid_roles_rows":
        svc.find_invalid_role_members.return_value = InvalidRoleScan(
            actionable=[
                _member(
                    "legacy-1",
                    role="operator",
                    token_hash="hash-fixture-0001",
                    token_expires_at="2026-06-01T00:00:00",
                )
            ],
            legacy_revoked=[_member("legacy-2", role="admin", status="revoked")],
        )


@pytest.fixture(autouse=True)
def _bypass_auth() -> Iterator[None]:
    with patch(
        "ante.cli.main.authenticate_member",
        side_effect=lambda ctx: ctx.obj.update({"member": _MASTER}),
    ):
        yield


def _invoke_case(
    branch: str, mode: str, *, mix_stderr: bool = True
) -> tuple[Result, AsyncMock]:
    from ante.cli.main import cli

    args, active = _CASES[branch]
    svc = AsyncMock()
    _prepare_service(branch, svc)
    ipc_key = branch.rsplit("_", 1)[0]
    ipc_send = AsyncMock(return_value=_IPC_RESULTS.get(ipc_key, {}))

    @asynccontextmanager
    async def _create_service(ctx: Any = None) -> AsyncIterator[AsyncMock]:
        yield svc

    full_args = ["--format", "json", *args] if mode == "json" else list(args)
    with ExitStack() as stack:
        stack.enter_context(
            patch("ante.cli.commands.member._create_service", new=_create_service)
        )
        stack.enter_context(
            patch("ante.cli.cold_path.is_active_runtime", return_value=active)
        )
        stack.enter_context(
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send)
        )
        result = CliRunner(mix_stderr=mix_stderr).invoke(
            cli,
            full_args,
            env={"ANTE_MEMBER_TOKEN": "", _PASSWORD_ENV: "current-password-456"},
            catch_exceptions=False,
        )
    return result, ipc_send


_MEMBER_OUTPUT_BYTES: dict[tuple[str, str], str] = {
    ("list_empty", "text"): ("등록된 멤버가 없습니다.\n"),
    ("list_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "message": "등록된 멤버가 없습니다.",\n'
        '    "members": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_rows", "text"): (
        "  🦊  agent-1              agent  default  default         active     memb"
        "er:read, bot:read\n"
        "  -  analyst              human  default  research        suspended  -\n"
    ),
    ("list_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "members": [\n'
        "      {\n"
        '        "member_id": "agent-1",\n'
        '        "type": "agent",\n'
        '        "role": "default",\n'
        '        "org": "default",\n'
        '        "name": "Agent 1",\n'
        '        "emoji": "🦊",\n'
        '        "status": "active",\n'
        '        "scopes": [\n'
        '          "member:read",\n'
        '          "bot:read"\n'
        "        ],\n"
        '        "created_at": "2026-01-01T00:00:00"\n'
        "      },\n"
        "      {\n"
        '        "member_id": "analyst",\n'
        '        "type": "human",\n'
        '        "role": "default",\n'
        '        "org": "research",\n'
        '        "name": "",\n'
        '        "emoji": "",\n'
        '        "status": "suspended",\n'
        '        "scopes": [],\n'
        '        "created_at": "2026-01-01T00:00:00"\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("info", "text"): (
        "  Member ID : agent-1\n"
        "  타입      : agent\n"
        "  역할      : default\n"
        "  조직      : default\n"
        "  이름      : Agent 1\n"
        "  이모지    : 🦊\n"
        "  상태      : active\n"
        "  권한      : member:read, bot:read\n"
        "  생성일    : 2026-01-01T00:00:00\n"
        "  생성자    : test-master\n"
    ),
    ("info", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "type": "agent",\n'
        '    "role": "default",\n'
        '    "org": "default",\n'
        '    "name": "Agent 1",\n'
        '    "emoji": "🦊",\n'
        '    "status": "active",\n'
        '    "scopes": [\n'
        '      "member:read",\n'
        '      "bot:read"\n'
        "    ],\n"
        '    "created_at": "2026-01-01T00:00:00",\n'
        '    "created_by": "test-master",\n'
        '    "last_active_at": "2026-01-02T00:00:00"\n'
        "  }\n"
        "}\n"
    ),
    ("list_invalid_roles_empty", "text"): (
        "  recommended_action : review_then_revoke\n"
        "  valid_roles        : master, admin, default\n"
        "  actionable         : 0건\n"
        "  legacy_revoked     : 0건\n"
        "\n"
        "[actionable]\n"
        "  (none)\n"
        "\n"
        "[legacy_revoked]\n"
        "  (none)\n"
    ),
    ("list_invalid_roles_empty", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "recommended_action": "review_then_revoke",\n'
        '    "valid_roles": [\n'
        '      "master",\n'
        '      "admin",\n'
        '      "default"\n'
        "    ],\n"
        '    "actionable_count": 0,\n'
        '    "legacy_revoked_count": 0,\n'
        '    "actionable": [],\n'
        '    "legacy_revoked": []\n'
        "  }\n"
        "}\n"
    ),
    ("list_invalid_roles_rows", "text"): (
        "  recommended_action : review_then_revoke\n"
        "  valid_roles        : master, admin, default\n"
        "  actionable         : 1건\n"
        "  legacy_revoked     : 1건\n"
        "\n"
        "[actionable]\n"
        "  legacy-1             role=operator             status=active     created"
        "_at=2026-01-01T00:00:00  has_token=True\n"
        "\n"
        "[legacy_revoked]\n"
        "  legacy-2             role=admin                status=revoked    created"
        "_at=2026-01-01T00:00:00  has_token=False\n"
    ),
    ("list_invalid_roles_rows", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "recommended_action": "review_then_revoke",\n'
        '    "valid_roles": [\n'
        '      "master",\n'
        '      "admin",\n'
        '      "default"\n'
        "    ],\n"
        '    "actionable_count": 1,\n'
        '    "legacy_revoked_count": 1,\n'
        '    "actionable": [\n'
        "      {\n"
        '        "member_id": "legacy-1",\n'
        '        "role": "operator",\n'
        '        "type": "agent",\n'
        '        "name": "Agent 1",\n'
        '        "status": "active",\n'
        '        "created_at": "2026-01-01T00:00:00",\n'
        '        "has_token": true,\n'
        '        "token_expires_at": "2026-06-01T00:00:00",\n'
        '        "revoke_command": "ante --config-dir /nonexistent/ante-fixture mem'
        'ber revoke --yes -- legacy-1"\n'
        "      }\n"
        "    ],\n"
        '    "legacy_revoked": [\n'
        "      {\n"
        '        "member_id": "legacy-2",\n'
        '        "role": "admin",\n'
        '        "type": "agent",\n'
        '        "name": "Agent 1",\n'
        '        "status": "revoked",\n'
        '        "created_at": "2026-01-01T00:00:00",\n'
        '        "has_token": false,\n'
        '        "token_expires_at": null\n'
        "      }\n"
        "    ]\n"
        "  }\n"
        "}\n"
    ),
    ("register_ipc", "text"): (
        "멤버 등록 완료\n  토큰: fresh-token-xyz\n  이 토큰은 다시 표시되지 않습니다.\n"
    ),
    ("register_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-2",\n'
        '    "type": "agent",\n'
        '    "role": "default",\n'
        '    "org": "default",\n'
        '    "name": "새 에이전트",\n'
        '    "token": "fresh-token-xyz"\n'
        "  }\n"
        "}\n"
    ),
    ("register_direct", "text"): (
        "멤버 등록 완료\n  토큰: fresh-token-xyz\n  이 토큰은 다시 표시되지 않습니다.\n"
    ),
    ("register_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-2",\n'
        '    "type": "agent",\n'
        '    "role": "default",\n'
        '    "org": "default",\n'
        '    "name": "새 에이전트",\n'
        '    "token": "fresh-token-xyz"\n'
        "  }\n"
        "}\n"
    ),
    ("set_emoji_ipc", "text"): ("이모지 설정 완료: agent-1 → 🤖\n"),
    ("set_emoji_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "이모지 설정 완료: agent-1 → 🤖",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "emoji": "🤖"\n'
        "  }\n"
        "}\n"
    ),
    ("set_emoji_direct", "text"): ("이모지 설정 완료: agent-1 → 🤖\n"),
    ("set_emoji_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "이모지 설정 완료: agent-1 → 🤖",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "emoji": "🤖"\n'
        "  }\n"
        "}\n"
    ),
    ("update_scopes_ipc", "text"): ("멤버 권한 변경 완료: agent-1\n"),
    ("update_scopes_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "scopes": [\n'
        '      "account:read",\n'
        '      "member:read"\n'
        "    ],\n"
        '    "status": "active"\n'
        "  }\n"
        "}\n"
    ),
    ("update_scopes_direct", "text"): ("멤버 권한 변경 완료: agent-1\n"),
    ("update_scopes_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "scopes": [\n'
        '      "account:read",\n'
        '      "member:read"\n'
        "    ],\n"
        '    "status": "active"\n'
        "  }\n"
        "}\n"
    ),
    ("suspend_ipc", "text"): ("멤버 정지 완료: agent-1\n"),
    ("suspend_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 정지 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "suspended"\n'
        "  }\n"
        "}\n"
    ),
    ("suspend_direct", "text"): ("멤버 정지 완료: agent-1\n"),
    ("suspend_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 정지 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "suspended"\n'
        "  }\n"
        "}\n"
    ),
    ("reactivate_ipc", "text"): ("멤버 재활성화 완료: agent-1\n"),
    ("reactivate_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 재활성화 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "active"\n'
        "  }\n"
        "}\n"
    ),
    ("reactivate_direct", "text"): ("멤버 재활성화 완료: agent-1\n"),
    ("reactivate_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 재활성화 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "active"\n'
        "  }\n"
        "}\n"
    ),
    ("revoke_ipc", "text"): ("멤버 폐기 완료: agent-1\n"),
    ("revoke_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 폐기 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "revoked"\n'
        "  }\n"
        "}\n"
    ),
    ("revoke_direct", "text"): ("멤버 폐기 완료: agent-1\n"),
    ("revoke_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "멤버 폐기 완료: agent-1",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "status": "revoked"\n'
        "  }\n"
        "}\n"
    ),
    ("rotate_token_ipc", "text"): (
        "  기존 토큰이 즉시 무효화되었습니다.\n"
        "  새 토큰: new-token-abc\n"
        "  이 토큰은 다시 표시되지 않습니다.\n"
    ),
    ("rotate_token_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "token": "new-token-abc"\n'
        "  }\n"
        "}\n"
    ),
    ("rotate_token_direct", "text"): (
        "  기존 토큰이 즉시 무효화되었습니다.\n"
        "  새 토큰: new-token-abc\n"
        "  이 토큰은 다시 표시되지 않습니다.\n"
    ),
    ("rotate_token_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "member_id": "agent-1",\n'
        '    "token": "new-token-abc"\n'
        "  }\n"
        "}\n"
    ),
    ("reset_password_ipc", "text"): ("패스워드가 변경되었습니다.\n"),
    ("reset_password_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "패스워드가 변경되었습니다.",\n'
        '  "data": {}\n'
        "}\n"
    ),
    ("reset_password_direct", "text"): ("패스워드가 변경되었습니다.\n"),
    ("reset_password_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "패스워드가 변경되었습니다.",\n'
        '  "data": {}\n'
        "}\n"
    ),
    ("regenerate_recovery_key_ipc", "text"): (
        "  기존 복구 키가 폐기되었습니다.\n"
        "\n"
        "  새 복구 키: fresh-recovery-key-xyz\n"
        "\n"
        "  안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.\n"
    ),
    ("regenerate_recovery_key_ipc", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "recovery_key": "fresh-recovery-key-xyz"\n'
        "  }\n"
        "}\n"
    ),
    ("regenerate_recovery_key_direct", "text"): (
        "  기존 복구 키가 폐기되었습니다.\n"
        "\n"
        "  새 복구 키: fresh-recovery-key-xyz\n"
        "\n"
        "  안전한 곳에 보관하세요. 이 키는 다시 표시되지 않습니다.\n"
    ),
    ("regenerate_recovery_key_direct", "json"): (
        "{\n"
        '  "status": "ok",\n'
        '  "message": "",\n'
        '  "data": {\n'
        '    "recovery_key": "fresh-recovery-key-xyz"\n'
        "  }\n"
        "}\n"
    ),
}


class TestMemberOutputBytes:
    def test_cases_cover_every_branch_and_mode(self) -> None:
        assert set(_MEMBER_OUTPUT_BYTES) == {
            (branch, mode) for branch in _CASES for mode in ("text", "json")
        }
        assert len(_MEMBER_OUTPUT_BYTES) == 46

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _CASES for m in ("text", "json")]
    )
    def test_output_bytes(self, branch: str, mode: str) -> None:
        result, ipc_send = _invoke_case(branch, mode)
        assert result.exit_code == 0, result.output
        assert result.output == _MEMBER_OUTPUT_BYTES[(branch, mode)]
        assert ipc_send.await_count == (1 if _CASES[branch][1] else 0)

    @pytest.mark.parametrize(
        ("branch", "mode"), [(b, m) for b in _SECRETS for m in ("text", "json")]
    )
    def test_secret_appears_exactly_once(self, branch: str, mode: str) -> None:
        result, _ = _invoke_case(branch, mode, mix_stderr=False)
        assert result.exit_code == 0, result.output
        assert result.stdout.count(_SECRETS[branch]) == 1
        assert _SECRETS[branch] not in result.stderr
