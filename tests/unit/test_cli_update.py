"""check_server_running 유틸 함수 및 --format json 테스트.

이슈 #920: --format json 옵션 지원 검증.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.update import check_server_running
from ante.cli.main import cli


class TestCheckServerRunning:
    """check_server_running 테스트."""

    @patch("ante.cli.commands.update.os.kill")
    @patch("ante.main.read_pid_file", return_value=12345)
    def test_pid_exists_and_process_running(
        self, mock_read_pid: object, mock_kill: object
    ) -> None:
        """PID 파일 존재 + 프로세스 실행 중 -> True."""
        assert check_server_running() is True

    @patch(
        "ante.cli.commands.update.os.kill",
        side_effect=ProcessLookupError,
    )
    @patch("ante.main.read_pid_file", return_value=12345)
    def test_pid_exists_but_stale(
        self, mock_read_pid: object, mock_kill: object
    ) -> None:
        """PID 파일 존재 + 프로세스 미존재 (stale) -> False."""
        assert check_server_running() is False

    @patch("ante.main.read_pid_file", return_value=None)
    def test_no_pid_file(self, mock_read_pid: object) -> None:
        """PID 파일 미존재 -> False."""
        assert check_server_running() is False


# ── --format json 테스트 ──────────────────────────────────────


@pytest.fixture()
def runner() -> CliRunner:
    """인증 우회 CliRunner."""
    r = CliRunner()
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


class TestUpdateFormatJson:
    """--format json 출력 테스트."""

    def test_check_format_json_valid(self, runner: CliRunner) -> None:
        """--format json 출력이 유효한 JSON이다 (TC#1)."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, dict)

    def test_check_format_json_fields(self, runner: CliRunner) -> None:
        """JSON 출력에 필수 필드 존재 (TC#2)."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert "current_version" in data
        assert "latest_version" in data
        assert "update_available" in data

    def test_check_format_json_update_available_true(self, runner: CliRunner) -> None:
        """업데이트 가능 시 update_available=true."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        data = json.loads(result.output)
        assert data["current_version"] == "0.6.1"
        assert data["latest_version"] == "0.7.0"
        assert data["update_available"] is True

    def test_check_format_json_no_update(self, runner: CliRunner) -> None:
        """이미 최신 버전이면 update_available=false."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.7.0"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["update_available"] is False


class TestUpdateFormatText:
    """--format text (기본) 출력 테스트 (TC#3)."""

    def test_check_default_text(self, runner: CliRunner) -> None:
        """기본 출력은 사람이 읽을 수 있는 텍스트 형식이다."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check"])

        assert result.exit_code == 0
        assert "현재 버전: 0.6.1" in result.output
        assert "업데이트 가능" in result.output

    def test_check_explicit_text(self, runner: CliRunner) -> None:
        """--format text 명시 시에도 텍스트 출력."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "text"])

        assert result.exit_code == 0
        assert "현재 버전: 0.6.1" in result.output


class TestUpdateFormatJsonError:
    """JSON 모드 에러 출력 테스트."""

    def test_server_running_json_error(self, runner: CliRunner) -> None:
        """서버 실행 중 에러도 JSON으로 출력된다."""
        with patch("ante.cli.commands.update.check_server_running", return_value=True):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data

    def test_pypi_failure_json_error(self, runner: CliRunner) -> None:
        """PyPI 조회 실패 시 JSON 에러 출력."""
        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value=None),
        ):
            result = runner.invoke(cli, ["update", "--check", "--format", "json"])

        assert result.exit_code == 1
        data = json.loads(result.output)
        assert "error" in data
