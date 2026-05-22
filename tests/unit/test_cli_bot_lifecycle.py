"""``ante bot start/stop/status`` CLI leaf 회귀 테스트 (#1713).

Refs #1713/#1712: IPC handler(``bot.start``/``bot.stop``/``bot.status``)를
CLI ingress로 노출한다.
회귀 매트릭스:

- 성공 경로 (start/stop/status: BotInfo or detail envelope 반환).
- 에러 envelope (``BOT_NOT_FOUND`` / ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED``
  / ``BOT_STATE_CONFLICT``): JSON 모드는 {status,code,message} 분리 필드, text
  모드는 ``Error: {code}: {message}`` 톤.
- ``--format`` option 노출 (`format_option` 데코레이터 적용 확인).
- ``ante bot --help`` 에 start/stop/status 표시.
- status text-mode 출력의 optional sections (strategy/budget/positions).
- trade_service=None 환경 (positions 키 부재) 정상 처리.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from click.testing import CliRunner


def _make_member():
    member = MagicMock()
    member.member_id = "test-user"
    from ante.member.models import MemberType

    member.type = MemberType.HUMAN
    return member


def _mock_authenticate(ctx):
    ctx.obj["member"] = _make_member()


def _invoke_cli(args: list[str]):
    """CLI 호출 헬퍼 (인증 우회)."""
    from ante.cli.main import cli

    runner = CliRunner()
    with patch("ante.cli.main.authenticate_member", side_effect=_mock_authenticate):
        result = runner.invoke(
            cli,
            args,
            obj={"member": _make_member()},
            env={"ANTE_MEMBER_TOKEN": ""},
            catch_exceptions=False,
        )
    return result


# ── Click 노출 (help / --format) ──────────────────────────────────────────


class TestBotLifecycleClickRegistration:
    """``ante bot --help`` 에 신규 leaf 가 노출되고 ``--format`` option 이 동작한다."""

    def test_bot_help_lists_start_stop_status(self) -> None:
        """``ante bot --help`` 결과에 start/stop/status가 표시된다."""
        result = _invoke_cli(["bot", "--help"])
        assert result.exit_code == 0
        # Click subcommand 리스트에 3개 명령 노출
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output

    def test_bot_start_has_format_option(self) -> None:
        """``ante bot start --help`` 에 ``--format`` 옵션이 노출된다."""
        result = _invoke_cli(["bot", "start", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output

    def test_bot_stop_has_format_option(self) -> None:
        """``ante bot stop --help`` 에 ``--format`` 옵션이 노출된다."""
        result = _invoke_cli(["bot", "stop", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output

    def test_bot_status_has_format_option(self) -> None:
        """``ante bot status --help`` 에 ``--format`` 옵션이 노출된다."""
        result = _invoke_cli(["bot", "status", "--help"])
        assert result.exit_code == 0
        assert "--format" in result.output


# ── bot start ────────────────────────────────────────────────────────────


class TestBotStart:
    """``ante bot start`` 성공/에러 envelope."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_success(self, mock_ipc_cls, mock_socket) -> None:
        """성공: ``bot.start`` IPC 호출 + ``{bot: info}`` result + exit 0.

        text 모드는 ``봇 시작 완료: {bot_id}`` 메시지만 출력한다 (Codex P2 fix).
        """
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": {"bot_id": "bot-1", "status": "running"}},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "start", "bot-1"])

        assert result.exit_code == 0
        assert "봇 시작 완료: bot-1" in result.output
        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "bot.start"
        assert call_args[0][1] == {"bot_id": "bot-1"}

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_success_json_passthrough(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """JSON 모드: IPC result(``{bot: info}``) envelope 그대로 출력 — ``bot
        status``와 동일 shape, agent 파싱 일관성 보장 (Codex P2 fix)."""
        info = {"bot_id": "bot-1", "status": "running"}
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": info},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "start", "bot-1"])

        assert result.exit_code == 0
        import json as _json

        data = _json.loads(result.output)
        # passthrough: ``{"bot": info}`` 그대로 (success wrapper 부착 금지)
        assert data == {"bot": info}

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_not_found_json_envelope(self, mock_ipc_cls, mock_socket) -> None:
        """missing bot: ``BOT_NOT_FOUND`` envelope (JSON) + exit 1."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "BOT_NOT_FOUND", "message": "Bot not found: bot-x"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "start", "bot-x"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "BOT_NOT_FOUND"
        assert "Bot not found" in data["message"]

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_credentials_missing_envelope(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """app_key 부재: ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` envelope."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {
                "code": "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED",
                "message": "계좌에 인증정보(app_key)가 설정되지 않았습니다",
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "start", "bot-1"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["code"] == "BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED"
        assert "인증정보" in data["message"]

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_state_conflict_envelope(self, mock_ipc_cls, mock_socket) -> None:
        """상태머신 거부: ``BOT_STATE_CONFLICT`` envelope."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {
                "code": "BOT_STATE_CONFLICT",
                "message": "이미 실행 중인 봇입니다",
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "start", "bot-1"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["code"] == "BOT_STATE_CONFLICT"

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_start_error_text_mode_carries_code_prefix(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """text 모드 에러는 ``{code}: {message}`` 톤 + exit 1 (#1673 미러)."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "BOT_NOT_FOUND", "message": "Bot not found: bot-x"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "start", "bot-x"])

        assert result.exit_code == 1
        # text 모드에서는 ``Error: {code}: {message}`` (stderr).
        assert "BOT_NOT_FOUND" in result.output
        assert "Bot not found" in result.output


# ── bot stop ─────────────────────────────────────────────────────────────


class TestBotStop:
    """``ante bot stop`` 성공/에러 envelope."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_stop_success(self, mock_ipc_cls, mock_socket) -> None:
        """성공: ``bot.stop`` IPC 호출 + result + exit 0.

        text 모드는 ``봇 중지 완료: {bot_id}`` 메시지만 출력 (Codex P2 fix)."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": {"bot_id": "bot-1", "status": "stopped"}},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "stop", "bot-1"])

        assert result.exit_code == 0
        assert "봇 중지 완료: bot-1" in result.output
        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "bot.stop"
        assert call_args[0][1] == {"bot_id": "bot-1"}

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_stop_success_json_passthrough(self, mock_ipc_cls, mock_socket) -> None:
        """JSON 모드: IPC result envelope 그대로 출력 (Codex P2 fix)."""
        info = {"bot_id": "bot-1", "status": "stopped"}
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": info},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "stop", "bot-1"])

        assert result.exit_code == 0
        import json as _json

        data = _json.loads(result.output)
        assert data == {"bot": info}

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_stop_not_found_json_envelope(self, mock_ipc_cls, mock_socket) -> None:
        """missing bot: ``BOT_NOT_FOUND`` JSON envelope + exit 1."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "BOT_NOT_FOUND", "message": "Bot not found: bot-x"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "stop", "bot-x"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["code"] == "BOT_NOT_FOUND"

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_stop_state_conflict_envelope(self, mock_ipc_cls, mock_socket) -> None:
        """상태머신 거부: ``BOT_STATE_CONFLICT`` envelope (이미 정지된 봇 등)."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {
                "code": "BOT_STATE_CONFLICT",
                "message": "정지할 수 없는 상태입니다",
            },
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "stop", "bot-1"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["code"] == "BOT_STATE_CONFLICT"


# ── bot status ───────────────────────────────────────────────────────────


class TestBotStatus:
    """``ante bot status`` 성공/에러 envelope 및 출력 계약."""

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_status_success_json_passthrough(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """JSON 모드: IPC result(``{bot: info}``) 를 그대로 출력한다."""
        info = {
            "bot_id": "bot-1",
            "name": "테스트봇",
            "status": "running",
            "account_id": "acc-1",
            "strategy_id": "strat-1",
            "strategy_name": "MA Cross",
            "interval_seconds": 60,
            "started_at": "2026-05-22T00:00:00Z",
            "budget": {"allocated": 1000000, "available": 750000},
            "positions": [
                {"symbol": "005930", "quantity": 10, "avg_entry_price": 75000.0},
            ],
        }
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": info},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "status", "bot-1"])

        assert result.exit_code == 0
        import json as _json

        data = _json.loads(result.output)
        # passthrough: ``{"bot": info}`` 그대로
        assert data == {"bot": info}
        mock_client.send.assert_awaited_once()
        call_args = mock_client.send.call_args
        assert call_args[0][0] == "bot.status"
        assert call_args[0][1] == {"bot_id": "bot-1"}

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_status_success_text_full_sections(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """text 모드: detail + optional strategy/budget/positions section 출력."""
        info = {
            "bot_id": "bot-1",
            "name": "테스트봇",
            "status": "running",
            "account_id": "acc-1",
            "strategy_id": "strat-1",
            "strategy_name": "MA Cross",
            "interval_seconds": 60,
            "started_at": "2026-05-22T00:00:00Z",
            "budget": {"allocated": 1000000, "available": 750000},
            "positions": [
                {"symbol": "005930", "quantity": 10, "avg_entry_price": 75000.0},
            ],
        }
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": info},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "status", "bot-1"])

        assert result.exit_code == 0
        # detail fields
        assert "bot-1" in result.output
        assert "테스트봇" in result.output
        assert "running" in result.output
        assert "strat-1" in result.output
        # optional sections
        assert "MA Cross" in result.output
        assert "Budget" in result.output
        assert "allocated" in result.output
        assert "Positions (1)" in result.output
        assert "005930" in result.output
        # positions avg는 IPC ``avg_entry_price`` 키를 정확히 반영해야 한다
        # (Codex P2 fix — 기존 ``avg_price`` 조회는 항상 None 반환 버그).
        assert "avg=75000" in result.output

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_status_text_omits_missing_optional_sections(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """trade_service=None: positions 키 부재. budget/strategy_name 부재도 정상."""
        info = {
            "bot_id": "bot-1",
            "name": "테스트봇",
            "status": "running",
            "account_id": "acc-1",
            "strategy_id": "strat-1",
            "interval_seconds": 60,
            # strategy_name, budget, positions 모두 부재 (cold-path/optional deps)
        }
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot": info},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["bot", "status", "bot-1"])

        assert result.exit_code == 0
        # detail 필드는 정상 표시
        assert "bot-1" in result.output
        assert "테스트봇" in result.output
        # 부재 section 은 출력되지 않음
        assert "Budget" not in result.output
        assert "Positions" not in result.output
        assert "Strategy Name" not in result.output

    @patch(
        "ante.cli.commands.ipc_helpers.get_socket_path", return_value="/tmp/test.sock"
    )
    @patch("ante.cli.commands.ipc_helpers.IPCClient")
    def test_bot_status_not_found_json_envelope(
        self, mock_ipc_cls, mock_socket
    ) -> None:
        """missing bot: ``BOT_NOT_FOUND`` JSON envelope + exit 1."""
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "error",
            "error": {"code": "BOT_NOT_FOUND", "message": "Bot not found: bot-x"},
        }
        mock_ipc_cls.return_value = mock_client

        result = _invoke_cli(["--format", "json", "bot", "status", "bot-x"])

        assert result.exit_code == 1
        import json as _json

        data = _json.loads(result.output)
        assert data["status"] == "error"
        assert data["code"] == "BOT_NOT_FOUND"
