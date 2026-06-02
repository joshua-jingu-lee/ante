"""member admin CLI IPC-first 라우팅 + 서버 정지 fallback 검증 (#2113).

``member.update_scopes`` 동형으로, member admin mutation 8개 CLI 명령이

(a) is_active_runtime True → ``ipc_send("member.X", ...)`` 위임,
(b) is_active_runtime False → cold-path (직접 MemberService) fallback,
(c) ServerNotRunning(ClickException) → stable code envelope surface,
(d) 출력 shape parity (register/rotate_token fields+token, regen recovery_key),
(e) secret 비노출: token/recovery_key/new_password/password 가 CLI
    ClickException surface / JSON 출력 (사용자 표시 result 제외) 어디에도
    의도치 않게 새지 않는다,

를 만족함을 lock 한다. CLI 명령은 함수 본문에서 ``ipc_send`` /
``is_active_runtime`` 을 import 하므로 원본 모듈을 patch 한다.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import click
import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

SECRET_TOKEN = "SECRET-TOKEN-eeeeeeeeeeeeeeeeeeee"
SECRET_RECOVERY_KEY = "SECRET-RECOVERY-ffffffffffffffff"


def _master() -> Member:
    return Member(
        member_id="master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="master",
        status=MemberStatus.ACTIVE,
        scopes=[],
    )


def _invoke(args: list[str]):  # noqa: ANN202
    runner = CliRunner()
    member = _master()

    def _mock_auth(ctx) -> None:  # noqa: ANN001
        ctx.obj["member"] = member

    with patch("ante.cli.main.authenticate_member", side_effect=_mock_auth):
        return runner.invoke(
            cli,
            args,
            obj={"member": member},
            env={"ANTE_MEMBER_TOKEN": "any"},
            catch_exceptions=False,
        )


def _server_not_running_exc() -> click.ClickException:
    exc = click.ClickException(
        "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."
    )
    exc.ipc_error_code = "IPC_SERVER_NOT_RUNNING"  # type: ignore[attr-defined]
    exc.ipc_error_message = exc.message  # type: ignore[attr-defined]
    return exc


# (cli_args, ipc_command, ipc_return) — authenticated 6 commands.
_ROUTED = [
    pytest.param(
        ["--format", "json", "member", "suspend", "target"],
        "member.suspend",
        {"member_id": "target", "status": "suspended"},
        id="suspend",
    ),
    pytest.param(
        ["--format", "json", "member", "reactivate", "target"],
        "member.reactivate",
        {"member_id": "target", "status": "active"},
        id="reactivate",
    ),
    pytest.param(
        ["--format", "json", "member", "revoke", "target", "--yes"],
        "member.revoke",
        {"member_id": "target", "status": "revoked"},
        id="revoke",
    ),
    pytest.param(
        ["--format", "json", "member", "set-emoji", "target", "🤖"],
        "member.set_emoji",
        {"member_id": "target", "emoji": "🤖"},
        id="set-emoji",
    ),
]


# ── (a) IPC-first 위임 ─────────────────────────────────────────────────────


class TestIpcFirstRouting:
    @pytest.mark.parametrize("cli_args,ipc_command,ipc_return", _ROUTED)
    def test_active_runtime_delegates_to_ipc(
        self, cli_args: list[str], ipc_command: str, ipc_return: dict
    ) -> None:
        ipc_send = AsyncMock(return_value=ipc_return)
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
        ):
            result = _invoke(cli_args)
        assert result.exit_code == 0, result.output
        ipc_send.assert_awaited_once()
        call = ipc_send.await_args
        assert call.args[0] == ipc_command
        # actor 는 master member_id (get_member_id).
        assert call.kwargs.get("actor") == "master"

    def test_register_ipc_shape_parity_token_in_output(self) -> None:
        """(d) register IPC 경로가 {fields, token} shape 으로 출력한다."""
        ipc_send = AsyncMock(
            return_value={
                "member_id": "new-agent",
                "type": "agent",
                "role": "default",
                "org": "default",
                "name": "new",
                "token": SECRET_TOKEN,
            }
        )
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "member",
                    "register",
                    "--id",
                    "new-agent",
                    "--type",
                    "agent",
                ]
            )
        assert result.exit_code == 0, result.output
        ipc_send.assert_awaited_once()
        assert ipc_send.await_args.args[0] == "member.register"
        payload = json.loads(result.output)
        assert payload["member_id"] == "new-agent"
        # 발급 토큰은 사용자 표시용 result 에만 surface.
        assert payload["token"] == SECRET_TOKEN

    def test_rotate_token_ipc_shape_parity(self) -> None:
        """(d) rotate-token IPC 경로가 {member_id, token} shape 으로 출력."""
        ipc_send = AsyncMock(
            return_value={"member_id": "target", "token": SECRET_TOKEN}
        )
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
        ):
            result = _invoke(["member", "rotate-token", "target"])
        assert result.exit_code == 0, result.output
        assert ipc_send.await_args.args[0] == "member.rotate_token"
        assert SECRET_TOKEN in result.output

    def test_regen_ipc_shape_parity_recovery_key(self) -> None:
        """(d) regenerate-recovery-key IPC 경로가 {recovery_key} 출력 +
        auth-exempt 라 actor 미전달(secret 만 args 에)."""
        ipc_send = AsyncMock(return_value={"recovery_key": SECRET_RECOVERY_KEY})
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
            patch.dict("os.environ", {"ANTE_REGEN_PW": "current-pw-value"}),
        ):
            result = _invoke(
                [
                    "--format",
                    "json",
                    "member",
                    "regenerate-recovery-key",
                    "--password-env",
                    "ANTE_REGEN_PW",
                ]
            )
        assert result.exit_code == 0, result.output
        assert ipc_send.await_args.args[0] == "member.regenerate_recovery_key"
        # auth-exempt: args 에 password(secret) 만, actor override 없음.
        sent_args = ipc_send.await_args.args[1]
        assert sent_args == {"password": "current-pw-value"}
        payload = json.loads(result.output)
        assert payload["recovery_key"] == SECRET_RECOVERY_KEY

    def test_reset_password_ipc_sends_secret_only(self) -> None:
        """(a) reset-password IPC 경로가 secret 만 보내고 master-lookup 은
        서버가 수행(client member_id 미전송)."""
        ipc_send = AsyncMock(return_value={})
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
            patch.dict("os.environ", {"ANTE_NEW_PW": "new-pw-value"}),
        ):
            result = _invoke(
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "rk-value",
                    "--new-password-env",
                    "ANTE_NEW_PW",
                ]
            )
        assert result.exit_code == 0, result.output
        assert ipc_send.await_args.args[0] == "member.reset_password"
        sent_args = ipc_send.await_args.args[1]
        assert set(sent_args.keys()) == {"recovery_key", "new_password"}
        assert "member_id" not in sent_args


# ── (c) ServerNotRunning → ClickException surface (secret 비노출) ───────────

# format_option 을 보유한 명령만 JSON envelope code 검증에 쓴다
# (suspend/reactivate/revoke). set-emoji 는 success-only 출력이라 별도.
_JSON_SURFACE = [p for p in _ROUTED if getattr(p, "id", None) != "set-emoji"]


class TestServerNotRunningSurface:
    @pytest.mark.parametrize("cli_args,ipc_command,ipc_return", _JSON_SURFACE)
    def test_server_not_running_surfaces_stable_code(
        self, cli_args: list[str], ipc_command: str, ipc_return: dict
    ) -> None:
        ipc_send = AsyncMock(side_effect=_server_not_running_exc())
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
        ):
            result = _invoke(cli_args)
        assert result.exit_code == 1
        # JSON envelope 에 stable code surface
        # (formatter.error shape: {status, code, message}).
        payload = json.loads(result.output)
        assert payload["code"] == "IPC_SERVER_NOT_RUNNING"
        # secret 류 토큰이 surface 에 없음(general).
        assert SECRET_TOKEN not in result.output
        assert SECRET_RECOVERY_KEY not in result.output

    def test_reset_password_server_not_running_no_secret_in_surface(self) -> None:
        """(c)+(e) reset-password ServerNotRunning surface 에 secret 없음."""
        ipc_send = AsyncMock(side_effect=_server_not_running_exc())
        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=True),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
            patch.dict("os.environ", {"ANTE_NEW_PW": "SECRET-IN-PW-gggggg"}),
        ):
            result = _invoke(
                [
                    "member",
                    "reset-password",
                    "--recovery-key",
                    "SECRET-IN-RK-hhhhhh",
                    "--new-password-env",
                    "ANTE_NEW_PW",
                ]
            )
        assert result.exit_code == 1
        assert "SECRET-IN-PW-gggggg" not in result.output
        assert "SECRET-IN-RK-hhhhhh" not in result.output


# ── (b) 서버 정지 → cold-path fallback ─────────────────────────────────────


class TestColdPathFallback:
    def test_inactive_runtime_uses_cold_path(self) -> None:
        """(b) is_active_runtime False → ipc_send 미호출 + 직접 MemberService."""
        ipc_send = AsyncMock()
        suspend = AsyncMock(
            return_value=Member(
                member_id="target",
                type=MemberType.AGENT,
                role=MemberRole.DEFAULT,
                org="default",
                name="target",
                status=MemberStatus.SUSPENDED,
                scopes=[],
            )
        )
        service = AsyncMock()
        service.suspend = suspend

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def _fake_factory(ctx=None):  # noqa: ANN001, ANN202
            yield service

        with (
            patch("ante.cli.cold_path.is_active_runtime", return_value=False),
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=ipc_send),
            patch("ante.cli.commands.member._create_service", new=_fake_factory),
        ):
            result = _invoke(["member", "suspend", "target"])
        assert result.exit_code == 0, result.output
        ipc_send.assert_not_awaited()
        suspend.assert_awaited_once()
        # cold-path 도 suspended_by=actor 로 master 게이트 보존.
        assert suspend.await_args.kwargs["suspended_by"] == "master"
