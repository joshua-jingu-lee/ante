"""``ante bot signal-key --rotate`` runtime IPC 라우팅 회귀 lock (#2111).

## 배경

``bot signal-key --rotate`` 는 스펙(ipc.md:86)상 runtime IPC
(``bot.signal_key.rotate`` → ``BotManager.rotate_signal_key()``) 로 정의되어
있으나, CLI 가 ``SignalKeyManager.rotate()`` 를 직접 호출(cold-path DB
mutation)해 runtime 경계 / audit / live 상태 정합성을 깼다. #2111 은 rotate 를
IPC 전용으로 라우팅하고 cold-path mutation 을 제거한다.

## 회귀 lock

- L1: 서버 실행 중 ``--rotate`` → ``ipc_send("bot.signal_key.rotate",
  {"bot_id": ...})`` 호출, ``SignalKeyManager`` 직접 미호출 (cold-path
  미사용).
- L2: 서버 정지(``ServerNotRunningError`` → ``IPC_SERVER_NOT_RUNNING``) →
  에러 + exit 1, **직접 DB rotate 미수행** (fallback cold-path 없음).
- L3: IPC timeout 등 기타 IPC 에러도 그대로 surface (별도 catch / cold-path
  fallback 없음).
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.ipc.exceptions import ServerNotRunningError
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
    """인증을 mock 으로 우회한 CliRunner (external_gate test 동형)."""
    r = CliRunner(mix_stderr=False)
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


# ── L1: 서버 실행 중 → IPC 라우팅 + cold-path 미사용 ──────────────────────


class TestRotateRoutesToIpcWhenServerRunning:
    """L1: ``--rotate`` 는 ``ipc_send`` 로 라우팅하고 cold-path 를 쓰지 않는다."""

    def test_rotate_calls_ipc_send_not_signal_key_manager(
        self, runner: CliRunner
    ) -> None:
        mock_send = AsyncMock(
            return_value={
                "bot_id": "bot-1",
                "signal_key": "sk_ipc_rotated",
                "rotated": True,
            }
        )
        # cold-path 가 호출되면 즉시 실패하는 가드들.
        guard_skm_cls = patch(
            "ante.bot.signal_key.SignalKeyManager",
            side_effect=AssertionError(
                "rotate 가 SignalKeyManager cold-path 를 호출함 (#2111 위반)"
            ),
        )
        guard_create_services = patch(
            "ante.cli.commands.bot._create_services",
            side_effect=AssertionError(
                "rotate 가 _create_services cold-path 를 호출함 (#2111 위반)"
            ),
        )

        with (
            patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send),
            guard_skm_cls,
            guard_create_services,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "bot-1", "--rotate"],
            )

        assert result.exit_code == 0, result.stdout + result.stderr
        # IPC 라우팅: command + args 정확성.
        mock_send.assert_awaited_once()
        assert mock_send.await_args.args[0] == "bot.signal_key.rotate"
        assert mock_send.await_args.args[1] == {"bot_id": "bot-1"}
        # 출력 계약 보존 (#2111): 라우팅을 IPC 로 옮겨도 출력은 기존
        # standard envelope (``{status, message, data}``, json/text 공통) 을
        # 유지한다. cli_registry signal-key 계약의 문서화·drift-test 된
        # mixed-branch 결정.
        payload = json.loads(result.stdout)
        assert payload["status"] == "ok"
        assert payload["data"]["signal_key"] == "sk_ipc_rotated"
        assert payload["data"]["rotated"] is True

    def test_rotate_text_mode_success_message(self, runner: CliRunner) -> None:
        """text 모드는 ``fmt.success`` 메시지로 surface (exit 0)."""
        mock_send = AsyncMock(
            return_value={
                "bot_id": "bot-1",
                "signal_key": "sk_ipc_rotated",
                "rotated": True,
            }
        )
        with patch("ante.cli.commands.ipc_helpers.ipc_send", new=mock_send):
            result = runner.invoke(cli, ["bot", "signal-key", "bot-1", "--rotate"])

        assert result.exit_code == 0, result.stdout + result.stderr
        assert "시그널 키 재발급 완료: bot-1" in result.stdout
        assert mock_send.await_args.args[0] == "bot.signal_key.rotate"


# ── L2: 서버 정지 → 에러 + exit 1, cold-path fallback 없음 ────────────────


class TestRotateNoColdPathFallbackWhenServerStopped:
    """L2/L3: 서버 정지/IPC 에러 시 cold-path DB mutation 으로 fallback 하지
    않는다."""

    def test_server_not_running_exits_one_no_db_rotate_json(
        self, runner: CliRunner
    ) -> None:
        """``ServerNotRunningError`` → ``IPC_SERVER_NOT_RUNNING`` + exit 1,
        직접 DB rotate 미수행.

        ``ipc_send`` 의 실제 변환 경로(``IPCClient.send`` 가 raise 한
        ``ServerNotRunningError`` → ``IPC_SERVER_NOT_RUNNING`` ClickException)
        를 타도록 ``IPCClient.send`` 와 socket 경로 resolver 만 mock 하고,
        cold-path 진입은 가드로 막는다.
        """

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ServerNotRunningError("서버 미기동")

        guard_skm_cls = patch(
            "ante.bot.signal_key.SignalKeyManager",
            side_effect=AssertionError(
                "서버 정지 fallback 으로 cold-path rotate 가 호출됨 (#2111 위반)"
            ),
        )
        guard_create_services = patch(
            "ante.cli.commands.bot._create_services",
            side_effect=AssertionError(
                "서버 정지 fallback 으로 _create_services 가 호출됨 (#2111 위반)"
            ),
        )

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/nonexistent-ante-2111.sock",
            ),
            patch("ante.ipc.client.IPCClient.send", new=_raise),
            guard_skm_cls,
            guard_create_services,
        ):
            result = runner.invoke(
                cli,
                ["--format", "json", "bot", "signal-key", "bot-1", "--rotate"],
            )

        assert result.exit_code == 1, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "IPC_SERVER_NOT_RUNNING"

    def test_server_not_running_exits_one_text(self, runner: CliRunner) -> None:
        """text 모드에서도 서버 정지 → exit 1 + stderr ``Error:``."""

        async def _raise(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            raise ServerNotRunningError("서버 미기동")

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/nonexistent-ante-2111.sock",
            ),
            patch("ante.ipc.client.IPCClient.send", new=_raise),
            patch(
                "ante.bot.signal_key.SignalKeyManager",
                side_effect=AssertionError("cold-path 호출됨 (#2111 위반)"),
            ),
        ):
            result = runner.invoke(cli, ["bot", "signal-key", "bot-1", "--rotate"])

        assert result.exit_code == 1, result.stdout + result.stderr
        assert "Error:" in result.stderr
        # IPC_SERVER_NOT_RUNNING code 가 text envelope 에 포함.
        assert "IPC_SERVER_NOT_RUNNING" in result.stderr
