"""check_server_running 유틸 함수 테스트."""

from __future__ import annotations

from unittest.mock import patch

from ante.cli.commands.update import check_server_running


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
