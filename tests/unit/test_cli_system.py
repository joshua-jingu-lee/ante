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

    def test_stop_stale_pid(self, runner, tmp_path, monkeypatch):
        """프로세스가 없으면 canonical PID 정리 후 에러 (Refs #1157)."""
        # Refs #1157: ``runtime.pid_path`` resolver가 결정한 canonical 위치에
        # 기록된 stale PID를 stop이 정리해야 한다.
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
        canonical = tmp_path / "run" / "ante.pid"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("99999")

        with (
            patch("ante.main.read_pid_file", return_value=99999),
            patch("ante.cli.commands.system._is_process_alive", return_value=False),
        ):
            result = runner.invoke(cli, ["system", "stop"])
            assert result.exit_code == 1
            assert "프로세스가 존재하지 않습니다" in result.output
            assert not canonical.exists()

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
    """Refs #1157: PID helpers는 ``Config`` 인자를 받아 ``runtime_pid_path()``로
    canonical 경로를 산출한다. ``PID_FILE`` 모듈 상수는 제거되었다.
    """

    def test_write_and_read_pid_file(self, tmp_path):
        """PID 파일 기록 및 읽기 (canonical resolver 기준)."""
        from ante.config import Config
        from ante.main import _remove_pid_file, _write_pid_file, read_pid_file

        config = Config.load(config_dir=tmp_path)
        try:
            _write_pid_file(config)
            assert read_pid_file(config) == os.getpid()
            assert (tmp_path / "run" / "ante.pid").exists()
        finally:
            _remove_pid_file(config)

    def test_read_pid_file_missing(self, tmp_path):
        """canonical/legacy 모두 부재 시 None."""
        from ante.config import Config
        from ante.main import read_pid_file

        # legacy 경로(`db/ante.pid`)가 cwd에 없도록 격리된 디렉토리로 chdir.
        # tmp_path 자체는 canonical(`run/ante.pid`)도 가지지 않음.
        with patch("ante.main._LEGACY_PID_FALLBACK", tmp_path / "no-legacy"):
            config = Config.load(config_dir=tmp_path)
            assert read_pid_file(config) is None

    def test_read_pid_file_invalid(self, tmp_path):
        """PID 파일 내용이 숫자가 아니면 None."""
        from ante.config import Config
        from ante.main import read_pid_file

        config = Config.load(config_dir=tmp_path)
        canonical = tmp_path / "run" / "ante.pid"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("not-a-number")
        with patch("ante.main._LEGACY_PID_FALLBACK", tmp_path / "no-legacy"):
            assert read_pid_file(config) is None

    def test_remove_pid_file(self, tmp_path):
        """canonical PID 파일 삭제."""
        from ante.config import Config
        from ante.main import _remove_pid_file

        config = Config.load(config_dir=tmp_path)
        canonical = tmp_path / "run" / "ante.pid"
        canonical.parent.mkdir(parents=True, exist_ok=True)
        canonical.write_text("12345")
        _remove_pid_file(config)
        assert not canonical.exists()

    def test_remove_pid_file_missing(self, tmp_path):
        """PID 파일이 없어도 에러 없이 진행."""
        from ante.config import Config
        from ante.main import _remove_pid_file

        config = Config.load(config_dir=tmp_path)
        _remove_pid_file(config)  # Should not raise


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
