"""CLI system start/stop 커맨드 단위 테스트."""

from __future__ import annotations

import json
import os
import signal
from unittest.mock import MagicMock, patch

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


class TestSystemStart:
    def test_start_already_running(self, runner):
        """이미 실행 중인 프로세스가 있으면 에러."""
        with (
            patch("ante.main.read_pid_file", return_value=os.getpid()),
            patch("ante.cli.commands.system._is_process_alive", return_value=True),
        ):
            result = runner.invoke(cli, ["system", "start"])
            assert result.exit_code == 1
            assert "이미 실행 중" in result.output

    def test_start_already_running_json(self, runner):
        """JSON 모드에서 이미 실행 중인 경우."""
        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch("ante.cli.commands.system._is_process_alive", return_value=True),
        ):
            result = runner.invoke(cli, ["--format", "json", "system", "start"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["code"] == "ALREADY_RUNNING"

    def test_start_stale_pid_proceeds(self, runner):
        """PID 파일이 있지만 프로세스가 없으면 시작 진행."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("ante.main.read_pid_file", return_value=99999),
            patch("ante.cli.commands.system._is_process_alive", return_value=False),
            patch(
                "ante.cli.commands.system.subprocess.run", return_value=mock_proc
            ) as mock_run,
        ):
            result = runner.invoke(cli, ["system", "start"])
            assert result.exit_code == 0
            mock_run.assert_called_once()
            cmd = mock_run.call_args[0][0]
            assert cmd[-2:] == ["-m", "ante.main"]

    def test_start_no_pid_file(self, runner):
        """PID 파일이 없으면 정상 시작."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.system.subprocess.run", return_value=mock_proc
            ) as mock_run,
        ):
            result = runner.invoke(cli, ["system", "start"])
            assert result.exit_code == 0
            mock_run.assert_called_once()

    def test_start_config_dir_passed_via_env(self, runner):
        """--config-dir 옵션이 환경변수로 전달."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch(
                "ante.cli.commands.system.subprocess.run", return_value=mock_proc
            ) as mock_run,
        ):
            result = runner.invoke(
                cli, ["system", "start", "--config-dir", "/tmp/ante-config"]
            )
            assert result.exit_code == 0
            env = mock_run.call_args[1]["env"]
            assert env["ANTE_CONFIG_DIR"] == "/tmp/ante-config"

    def test_start_nonzero_exit_code(self, runner):
        """서브프로세스가 비정상 종료하면 해당 코드 전파."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1

        with (
            patch("ante.main.read_pid_file", return_value=None),
            patch("ante.cli.commands.system.subprocess.run", return_value=mock_proc),
        ):
            result = runner.invoke(cli, ["system", "start"])
            assert result.exit_code == 1


class TestSystemStop:
    def test_stop_no_pid_file(self, runner):
        """PID 파일이 없으면 에러."""
        with patch("ante.main.read_pid_file", return_value=None):
            result = runner.invoke(cli, ["system", "stop"])
            assert result.exit_code == 1
            assert "PID 파일이 없습니다" in result.output

    def test_stop_no_pid_file_json(self, runner):
        """JSON 모드에서 PID 파일이 없는 경우."""
        with patch("ante.main.read_pid_file", return_value=None):
            result = runner.invoke(cli, ["--format", "json", "system", "stop"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["code"] == "PID_NOT_FOUND"

    def test_stop_stale_pid(self, runner, tmp_path):
        """프로세스가 없으면 stale PID 정리 후 에러."""
        pid_file = tmp_path / "ante.pid"
        pid_file.write_text("99999")

        with (
            patch("ante.main.read_pid_file", return_value=99999),
            patch("ante.cli.commands.system._is_process_alive", return_value=False),
            patch("ante.main.PID_FILE", pid_file),
        ):
            result = runner.invoke(cli, ["system", "stop"])
            assert result.exit_code == 1
            assert "프로세스가 존재하지 않습니다" in result.output
            assert not pid_file.exists()

    def test_stop_sends_sigterm(self, runner):
        """정상 프로세스에 SIGTERM 전송."""
        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch("ante.cli.commands.system._is_process_alive", return_value=True),
            patch("ante.cli.commands.system.os.kill") as mock_kill,
        ):
            result = runner.invoke(cli, ["system", "stop"])
            assert result.exit_code == 0
            mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    def test_stop_sends_sigterm_json(self, runner):
        """JSON 모드에서 정상 종료."""
        with (
            patch("ante.main.read_pid_file", return_value=12345),
            patch("ante.cli.commands.system._is_process_alive", return_value=True),
            patch("ante.cli.commands.system.os.kill"),
        ):
            result = runner.invoke(cli, ["--format", "json", "system", "stop"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["status"] == "ok"
            assert data["pid"] == 12345


class TestPidFileManagement:
    def test_write_and_read_pid_file(self, tmp_path):
        """PID 파일 기록 및 읽기."""
        from ante.main import _write_pid_file, read_pid_file

        pid_file = tmp_path / "ante.pid"
        with patch("ante.main.PID_FILE", pid_file):
            _write_pid_file()
            result = read_pid_file()
            assert result == os.getpid()

    def test_read_pid_file_missing(self, tmp_path):
        """PID 파일이 없으면 None."""
        from ante.main import read_pid_file

        with patch("ante.main.PID_FILE", tmp_path / "nonexistent.pid"):
            assert read_pid_file() is None

    def test_read_pid_file_invalid(self, tmp_path):
        """PID 파일 내용이 숫자가 아니면 None."""
        from ante.main import read_pid_file

        pid_file = tmp_path / "ante.pid"
        pid_file.write_text("not-a-number")
        with patch("ante.main.PID_FILE", pid_file):
            assert read_pid_file() is None

    def test_remove_pid_file(self, tmp_path):
        """PID 파일 삭제."""
        from ante.main import _remove_pid_file

        pid_file = tmp_path / "ante.pid"
        pid_file.write_text("12345")
        with patch("ante.main.PID_FILE", pid_file):
            _remove_pid_file()
            assert not pid_file.exists()

    def test_remove_pid_file_missing(self, tmp_path):
        """PID 파일이 없어도 에러 없이 진행."""
        from ante.main import _remove_pid_file

        pid_file = tmp_path / "nonexistent.pid"
        with patch("ante.main.PID_FILE", pid_file):
            _remove_pid_file()  # Should not raise


class TestIsProcessAlive:
    def test_current_process_is_alive(self):
        """현재 프로세스는 살아있음."""
        from ante.cli.commands.system import _is_process_alive

        assert _is_process_alive(os.getpid()) is True

    def test_nonexistent_process(self):
        """존재하지 않는 PID는 False."""
        from ante.cli.commands.system import _is_process_alive

        # PID 99999999는 존재하지 않을 가능성이 높음
        assert _is_process_alive(99999999) is False
