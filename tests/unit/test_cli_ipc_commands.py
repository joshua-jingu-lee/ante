"""CLI IPC 전환 테스트 — system halt/activate, account suspend/activate.

#696: CLI 커맨드를 직접 서비스 생성 방식에서 IPCClient 방식으로 전환.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


# ── system halt IPC ────────────────────────────────


class TestSystemHaltIPC:
    def test_halt_sends_ipc_command(self, runner: CliRunner) -> None:
        """system halt가 IPC로 system.halt 커맨드를 전송."""
        mock_response = {
            "status": "ok",
            "data": {"suspended_count": 3},
        }

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["system", "halt", "--reason", "긴급 정지"])

        assert result.exit_code == 0, result.output
        assert "HALTED" in result.output
        assert "3" in result.output
        mock_client.send.assert_called_once_with(
            "system.halt", {"reason": "긴급 정지"}, "test-master"
        )

    def test_halt_default_reason(self, runner: CliRunner) -> None:
        """system halt 사유 미지정 시 빈 문자열."""
        mock_response = {"status": "ok", "data": {"suspended_count": 0}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["system", "halt"])

        assert result.exit_code == 0
        mock_client.send.assert_called_once_with(
            "system.halt", {"reason": ""}, "test-master"
        )


# ── system activate IPC ────────────────────────────


class TestSystemActivateIPC:
    def test_activate_sends_ipc_command(self, runner: CliRunner) -> None:
        """system activate가 IPC로 system.activate 커맨드를 전송."""
        mock_response = {
            "status": "ok",
            "data": {"activated_count": 2},
        }

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["system", "activate"])

        assert result.exit_code == 0, result.output
        assert "ACTIVE" in result.output
        assert "2" in result.output
        mock_client.send.assert_called_once_with(
            "system.activate", {"reason": ""}, "test-master"
        )


# ── account suspend IPC ────────────────────────────


class TestAccountSuspendIPC:
    def test_suspend_sends_ipc_command(self, runner: CliRunner) -> None:
        """account suspend가 IPC로 account.suspend 커맨드를 전송."""
        mock_response = {"status": "ok", "data": {}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["account", "suspend", "domestic"])

        assert result.exit_code == 0, result.output
        assert "정지 완료" in result.output
        mock_client.send.assert_called_once_with(
            "account.suspend",
            {"account_id": "domestic", "reason": "CLI 수동 정지"},
            "test-master",
        )

    def test_suspend_with_reason(self, runner: CliRunner) -> None:
        """account suspend --reason 옵션."""
        mock_response = {"status": "ok", "data": {}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(
                    cli, ["account", "suspend", "domestic", "--reason", "테스트"]
                )

        assert result.exit_code == 0
        mock_client.send.assert_called_once_with(
            "account.suspend",
            {"account_id": "domestic", "reason": "테스트"},
            "test-master",
        )


# ── account activate IPC ────────────────────────────


class TestAccountActivateIPC:
    def test_activate_sends_ipc_command(self, runner: CliRunner) -> None:
        """account activate가 IPC로 account.activate 커맨드를 전송."""
        mock_response = {"status": "ok", "data": {}}

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["account", "activate", "domestic"])

        assert result.exit_code == 0, result.output
        assert "활성화 완료" in result.output
        mock_client.send.assert_called_once_with(
            "account.activate",
            {"account_id": "domestic"},
            "test-master",
        )


# ── 서버 미기동 에러 ────────────────────────────────


class TestServerNotRunning:
    def test_system_halt_server_not_running(self, runner: CliRunner) -> None:
        """서버 미기동 시 사용자 친화적 메시지."""
        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.side_effect = ServerNotRunningError("소켓 없음")
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["system", "halt"])

        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    def test_account_suspend_server_not_running(self, runner: CliRunner) -> None:
        """account suspend 시 서버 미기동 에러."""
        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.side_effect = ServerNotRunningError("소켓 없음")
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["account", "suspend", "domestic"])

        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    def test_ipc_timeout(self, runner: CliRunner) -> None:
        """IPC 타임아웃 시 사용자 친화적 메시지."""
        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.side_effect = IPCTimeoutError("타임아웃")
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["system", "halt"])

        assert result.exit_code != 0
        assert "응답 시간 초과" in result.output


# ── IPC 응답 에러 처리 ────────────────────────────────


class TestIPCErrorResponse:
    def test_error_response(self, runner: CliRunner) -> None:
        """서버 응답 status=error 시 에러 메시지 출력."""
        mock_response = {
            "status": "error",
            "error": {
                "code": "ACCOUNT_NOT_FOUND",
                "message": "계좌를 찾을 수 없습니다",
            },
        }

        with patch(
            "ante.cli.commands.ipc_helpers.IPCClient", autospec=True
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.send.return_value = mock_response
            mock_cls.return_value = mock_client

            with patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ):
                result = runner.invoke(cli, ["account", "suspend", "nonexistent"])

        assert result.exit_code != 0
        assert "ACCOUNT_NOT_FOUND" in result.output
        assert "계좌를 찾을 수 없습니다" in result.output


# ── get_socket_path ────────────────────────────────


class TestGetSocketPath:
    def test_default_socket_path(self) -> None:
        """기본 db.path로부터 소켓 경로 생성."""
        from ante.cli.commands.ipc_helpers import get_socket_path

        with patch("ante.config.Config") as mock_config_cls:
            mock_config = mock_config_cls.load.return_value
            mock_config.get.return_value = "db/ante.db"

            path = get_socket_path()

        assert path == "db/ante.sock"

    def test_custom_db_path(self) -> None:
        """커스텀 db.path로부터 소켓 경로 생성."""
        from ante.cli.commands.ipc_helpers import get_socket_path

        with patch("ante.config.Config") as mock_config_cls:
            mock_config = mock_config_cls.load.return_value
            mock_config.get.return_value = "/data/ante/main.db"

            path = get_socket_path()

        assert path == "/data/ante/ante.sock"
