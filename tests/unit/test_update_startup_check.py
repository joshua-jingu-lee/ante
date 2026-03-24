"""서버 시작 시 버전 확인 단위 테스트. Refs #923."""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from ante.update.checker import _check_and_log, check_update_on_startup


class TestCheckAndLog:
    """_check_and_log 동기 함수 테스트."""

    def test_new_version_available_logs_info(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """TC-1: 새 버전이 있으면 INFO 로그에 '새 버전 사용 가능' 메시지를 출력한다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
            caplog.at_level(logging.INFO, logger="ante.update.checker"),
        ):
            _check_and_log()

        assert "새 버전 사용 가능" in caplog.text
        assert "v0.7.0" in caplog.text
        assert "v0.6.1" in caplog.text
        assert "ante update" in caplog.text

    def test_already_latest_no_log(self, caplog: pytest.LogCaptureFixture) -> None:
        """TC-2: 이미 최신 버전이면 버전 관련 로그가 없다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="1.0.0"),
            caplog.at_level(logging.INFO, logger="ante.update.checker"),
        ):
            _check_and_log()

        assert "새 버전 사용 가능" not in caplog.text

    def test_network_error_ignored(self, caplog: pytest.LogCaptureFixture) -> None:
        """TC-3: 네트워크 오류 시 예외 없이 WARNING 로그만 남긴다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch(
                "ante.update.checker.get_latest_version",
                return_value=None,
            ),
            caplog.at_level(logging.INFO, logger="ante.update.checker"),
        ):
            _check_and_log()  # 예외 발생 없음

        assert "새 버전 사용 가능" not in caplog.text

    def test_dev_version_skips_check(self, caplog: pytest.LogCaptureFixture) -> None:
        """dev 버전이면 PyPI 조회를 건너뛴다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="dev"),
            patch("ante.update.checker.get_latest_version") as mock_latest,
            caplog.at_level(logging.INFO, logger="ante.update.checker"),
        ):
            _check_and_log()

        mock_latest.assert_not_called()

    def test_no_pip_install_called(self) -> None:
        """TC-4: 자동 업데이트(pip install)가 호출되지 않는다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
            patch("subprocess.run") as mock_run,
            patch("subprocess.call") as mock_call,
            patch("subprocess.Popen") as mock_popen,
        ):
            _check_and_log()

        mock_run.assert_not_called()
        mock_call.assert_not_called()
        mock_popen.assert_not_called()


class TestCheckUpdateOnStartup:
    """check_update_on_startup 비동기 함수 테스트."""

    @pytest.mark.asyncio()
    async def test_runs_without_blocking(self) -> None:
        """비동기로 실행되며 서버 시작을 방해하지 않는다."""
        with (
            patch("ante.update.checker.get_current_version", return_value="0.6.1"),
            patch("ante.update.checker.get_latest_version", return_value="0.7.0"),
        ):
            await check_update_on_startup()  # 예외 없이 완료

    @pytest.mark.asyncio()
    async def test_exception_suppressed(self) -> None:
        """_check_and_log에서 예외가 발생해도 전파되지 않는다."""
        with patch(
            "ante.update.checker._check_and_log",
            side_effect=RuntimeError("unexpected"),
        ):
            await check_update_on_startup()  # 예외 없이 완료
