"""봇 생성의 --param 옵션이 없어졌음을 확인하는 테스트 (#2684)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
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


@pytest.fixture
def runner():
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestBotCreateParamRemoved:
    def test_create_without_params(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                [
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                ],
            )
            assert result.exit_code == 0

            # params 키가 없어야 함
            sent_args = mock_client.send.call_args[0][1]
            assert "params" not in sent_args

    @staticmethod
    def _invoke_with_param(runner, prefix):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }
        with (
            patch(
                "ante.cli.commands.ipc_helpers.get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands.ipc_helpers.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                [
                    *prefix,
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                    "--param",
                    "lookback=20",
                ],
            )
        return result, mock_client

    def test_param_rejected_as_usage_error_in_json_mode(self, runner):
        result, mock_client = self._invoke_with_param(runner, ["--format", "json"])
        assert result.exit_code == 1, result.output
        payload = json.loads(result.stdout)
        assert payload["code"] == "CLI_USAGE_ERROR", payload
        mock_client.send.assert_not_called()

    def test_param_rejected_as_usage_error_in_text_mode(self, runner):
        result, mock_client = self._invoke_with_param(runner, [])
        assert result.exit_code == 2, result.output
        assert "--param" in result.stderr
        mock_client.send.assert_not_called()
