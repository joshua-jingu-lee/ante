"""Bot/Treasury CLI 커맨드 IPC 전환 테스트.

bot create, bot remove, treasury allocate, treasury deallocate 커맨드가
IPCClient를 통해 서버에 전달되는지 검증한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import click
import pytest

from ante.cli.commands._ipc import ipc_send
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError

# ── ipc_send 헬퍼 테스트 ──────────────────────────────


class TestIpcSend:
    """ipc_send 공통 헬퍼 테스트."""

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """정상 응답 시 result를 반환한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "abc",
            "status": "ok",
            "result": {"bot_id": "bot-1"},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock"
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            result = await ipc_send("bot.create", {"name": "test"}, actor="user1")

        assert result == {"bot_id": "bot-1"}
        mock_client.send.assert_awaited_once_with(
            "bot.create", {"name": "test"}, "user1"
        )

    @pytest.mark.asyncio
    async def test_server_not_running(self) -> None:
        """ServerNotRunningError -> ClickException."""
        mock_client = AsyncMock()
        mock_client.send.side_effect = ServerNotRunningError("no server")

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock"
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            with pytest.raises(click.ClickException, match="서버가 실행 중이 아닙니다"):
                await ipc_send("bot.create", {})

    @pytest.mark.asyncio
    async def test_timeout(self) -> None:
        """IPCTimeoutError -> ClickException."""
        mock_client = AsyncMock()
        mock_client.send.side_effect = IPCTimeoutError("timeout")

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock"
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            with pytest.raises(click.ClickException, match="서버 응답 시간 초과"):
                await ipc_send("bot.create", {})

    @pytest.mark.asyncio
    async def test_server_error_response(self) -> None:
        """서버가 error 응답을 보내면 ClickException."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "abc",
            "status": "error",
            "error": {"code": "EXECUTION_ERROR", "message": "봇을 찾을 수 없습니다"},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock"
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            with pytest.raises(click.ClickException, match="EXECUTION_ERROR"):
                await ipc_send("bot.remove", {"bot_id": "x"})


# ── Bot CLI IPC 테스트 ──────────────────────────────


def _make_member():
    """테스트용 Member mock 객체."""
    member = MagicMock()
    member.member_id = "test-user"
    member.type = MagicMock()
    member.type.value = "human"
    # MemberType.HUMAN 비교를 위해
    from ante.member.models import MemberType

    member.type = MemberType.HUMAN
    return member


def _mock_authenticate(ctx):
    """테스트용 인증 우회 — Member를 ctx.obj에 직접 주입."""
    ctx.obj["member"] = _make_member()


def _invoke_cli(args: list[str], input_text: str | None = None):
    """CLI를 실행하고 결과를 반환한다 (인증 우회)."""
    from click.testing import CliRunner

    from ante.cli.main import cli

    runner = CliRunner()
    with patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate):
        result = runner.invoke(
            cli,
            args,
            obj={"member": _make_member()},
            env={"ANTE_MEMBER_TOKEN": ""},
            input=input_text,
            catch_exceptions=False,
        )
    return result


class TestBotCreateIpc:
    """bot create 커맨드가 IPC를 통해 서버에 전달되는지 검증."""

    @patch("ante.cli.commands.bot._create_services")
    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_bot_create_ipc(self, mock_ipc_cls, mock_socket, mock_services) -> None:
        """bot create가 bot.create IPC 커맨드를 전송한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }
        mock_ipc_cls.return_value = mock_client

        # _create_services는 계좌 대화형 선택 시에만 호출됨
        # --account 지정 시 호출되지 않음

        result = _invoke_cli(
            [
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "strat-1",
                "--account",
                "acc-1",
                "--interval",
                "120",
            ]
        )

        assert result.exit_code == 0
        assert "봇 생성 완료" in result.output

        # IPC send 호출 확인
        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "bot.create"
        sent_args = call_args[0][1]
        assert sent_args["name"] == "테스트봇"
        assert sent_args["strategy_id"] == "strat-1"
        assert sent_args["account_id"] == "acc-1"
        assert sent_args["interval_seconds"] == 120

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_bot_create_with_params(self, mock_ipc_cls, mock_socket) -> None:
        """--param 옵션이 IPC args에 포함된다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "strat-1",
                "--account",
                "acc-1",
                "--param",
                "threshold=0.5",
                "--param",
                "window=20",
            ]
        )

        assert result.exit_code == 0
        sent_args = mock_client.send.call_args[0][1]
        assert sent_args["params"] == {"threshold": 0.5, "window": 20}


class TestBotRemoveIpc:
    """bot remove 커맨드가 IPC를 통해 서버에 전달되는지 검증."""

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_bot_remove_ipc(self, mock_ipc_cls, mock_socket) -> None:
        """bot remove가 bot.remove IPC 커맨드를 전송한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc", "removed": True},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "remove", "bot-abc", "--yes"])

        assert result.exit_code == 0
        assert "봇 삭제 완료" in result.output

        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "bot.remove"
        assert call_args[0][1] == {"bot_id": "bot-abc"}

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_bot_remove_server_error(self, mock_ipc_cls, mock_socket) -> None:
        """서버 에러 시 사용자에게 에러 메시지를 출력한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "EXECUTION_ERROR", "message": "Bot not found"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "remove", "bot-xxx", "--yes"])
        assert result.exit_code != 0
        assert "EXECUTION_ERROR" in result.output


# ── Treasury CLI IPC 테스트 ──────────────────────────────


class TestTreasuryAllocateIpc:
    """treasury allocate 커맨드가 IPC를 통해 서버에 전달되는지 검증."""

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_treasury_allocate_ipc(self, mock_ipc_cls, mock_socket) -> None:
        """treasury allocate가 treasury.allocate IPC 커맨드를 전송한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": True,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "allocate",
                "bot-1",
                "100000",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 0
        assert "예산 할당 완료" in result.output

        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "treasury.allocate"
        sent_args = call_args[0][1]
        assert sent_args["account_id"] == "acc-1"
        assert sent_args["bot_id"] == "bot-1"
        assert sent_args["amount"] == 100000.0

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_treasury_allocate_failure(self, mock_ipc_cls, mock_socket) -> None:
        """할당 실패 시(success=False) 에러 메시지를 출력한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": False,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "allocate",
                "bot-1",
                "999999999",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 0
        assert "예산 할당 실패" in result.output


class TestTreasuryDeallocateIpc:
    """treasury deallocate 커맨드가 IPC를 통해 서버에 전달되는지 검증."""

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_treasury_deallocate_ipc(self, mock_ipc_cls, mock_socket) -> None:
        """treasury deallocate가 treasury.deallocate IPC 커맨드를 전송한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": True,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "deallocate",
                "bot-1",
                "50000",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 0
        assert "예산 회수 완료" in result.output

        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "treasury.deallocate"
        sent_args = call_args[0][1]
        assert sent_args["account_id"] == "acc-1"
        assert sent_args["bot_id"] == "bot-1"
        assert sent_args["amount"] == 50000.0

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_treasury_deallocate_failure(self, mock_ipc_cls, mock_socket) -> None:
        """회수 실패 시(success=False) 에러 메시지를 출력한다."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {
                "account_id": "acc-1",
                "bot_id": "bot-1",
                "success": False,
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "deallocate",
                "bot-1",
                "999999999",
                "--account",
                "acc-1",
            ]
        )

        assert result.exit_code == 0
        assert "예산 회수 실패" in result.output


# ── 서버 미실행 테스트 ──────────────────────────────


class TestServerNotRunning:
    """서버 미실행 시 사용자 친화적 메시지 테스트."""

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_bot_create_server_not_running(self, mock_ipc_cls, mock_socket) -> None:
        """서버 미실행 시 사용자 친화적 에러 메시지를 출력한다."""
        mock_client = AsyncMock()
        mock_client.send.side_effect = ServerNotRunningError("no server")
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "bot",
                "create",
                "--name",
                "test",
                "--strategy",
                "s1",
                "--account",
                "acc-1",
            ]
        )
        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output

    @patch("ante.cli.commands._ipc._get_socket_path", return_value="/tmp/test.sock")
    @patch("ante.cli.commands._ipc.IPCClient")
    def test_treasury_allocate_server_not_running(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """서버 미실행 시 사용자 친화적 에러 메시지를 출력한다."""
        mock_client = AsyncMock()
        mock_client.send.side_effect = ServerNotRunningError("no server")
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(
            [
                "treasury",
                "allocate",
                "bot-1",
                "100000",
                "--account",
                "acc-1",
            ]
        )
        assert result.exit_code != 0
        assert "서버가 실행 중이 아닙니다" in result.output
