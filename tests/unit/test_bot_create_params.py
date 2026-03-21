"""봇 생성 시 전략 파라미터 오버라이드 테스트."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.bot import _parse_param
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


class TestParseParam:
    def test_string_value(self):
        key, value = _parse_param("name=hello")
        assert key == "name"
        assert value == "hello"

    def test_numeric_value(self):
        key, value = _parse_param("lookback=20")
        assert key == "lookback"
        assert value == 20

    def test_float_value(self):
        key, value = _parse_param("threshold=0.5")
        assert key == "threshold"
        assert value == 0.5

    def test_boolean_value(self):
        key, value = _parse_param("enabled=true")
        assert key == "enabled"
        assert value is True

    def test_value_with_equals(self):
        key, value = _parse_param("expr=a=b")
        assert key == "expr"
        assert value == "a=b"

    def test_invalid_format(self):
        import click

        with pytest.raises(click.BadParameter):
            _parse_param("invalidformat")


class TestBotCreateWithParams:
    def test_create_with_params(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
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
                    "--param",
                    "lookback=20",
                    "--param",
                    "threshold=0.5",
                ],
            )
            assert result.exit_code == 0
            assert "생성 완료" in result.output

            # IPC로 전달된 args에 params 포함 확인
            sent_args = mock_client.send.call_args[0][1]
            assert sent_args["params"]["lookback"] == 20
            assert sent_args["params"]["threshold"] == 0.5

    def test_create_without_params(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123"},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
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

    def test_create_invalid_param_format(self, runner):
        result = runner.invoke(
            cli,
            [
                "bot",
                "create",
                "--name",
                "테스트봇",
                "--strategy",
                "stg-1",
                "--param",
                "invalidformat",
            ],
        )
        assert "잘못된 파라미터 형식" in result.output

    def test_create_with_json_output(self, runner):
        mock_client = AsyncMock()
        mock_client.send.return_value = {
            "id": "req-1",
            "status": "ok",
            "result": {"bot_id": "bot-abc123", "params": {"window": 30}},
        }

        with (
            patch(
                "ante.cli.commands._ipc._get_socket_path",
                return_value="/tmp/test.sock",
            ),
            patch("ante.cli.commands._ipc.IPCClient", return_value=mock_client),
        ):
            result = runner.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "bot",
                    "create",
                    "--name",
                    "테스트봇",
                    "--strategy",
                    "stg-1",
                    "--account",
                    "test",
                    "--param",
                    "window=30",
                ],
            )
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["params"]["window"] == 30
