"""ante update CLI 명령 단위 테스트."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.update import update


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestUpdateCheckFlag:
    """--check 옵션 테스트."""

    def test_check_shows_update_available(self, runner: CliRunner) -> None:
        """PyPI에 더 높은 버전이 있으면 업데이트 가능 메시지를 출력한다."""
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
        ):
            result = runner.invoke(update, ["--check"])

        assert result.exit_code == 0
        assert "현재 버전: 1.0.0" in result.output
        assert "업데이트 가능: 1.0.0" in result.output
        assert "2.0.0" in result.output

    def test_check_shows_already_latest(self, runner: CliRunner) -> None:
        """이미 최신 버전이면 '이미 최신 버전입니다' 메시지를 출력한다."""
        with (
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="2.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
        ):
            result = runner.invoke(update, ["--check"])

        assert result.exit_code == 0
        assert "이미 최신 버전입니다" in result.output


class TestServerRunningBlock:
    """서버 실행 중 차단 테스트."""

    def test_server_running_blocks_update(self, runner: CliRunner) -> None:
        """서버가 실행 중이면 exit code 1로 종료한다."""
        with patch("ante.cli.commands.update.check_server_running", return_value=True):
            result = runner.invoke(update, ["--check"])

        assert result.exit_code == 1
        assert "서버가 실행 중입니다" in result.output


class TestUpdateChecker:
    """checker 모듈 단위 테스트."""

    def test_is_update_available_true(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("1.0.0", "1.1.0") is True

    def test_is_update_available_false_same(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("1.0.0", "1.0.0") is False

    def test_is_update_available_false_lower(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("2.0.0", "1.0.0") is False

    def test_is_update_available_invalid_version(self) -> None:
        from ante.update.checker import is_update_available

        assert is_update_available("invalid", "also-invalid") is False

    def test_get_current_version_fallback(self) -> None:
        from ante.update.checker import get_current_version

        with patch(
            "ante.update.checker.pkg_version",
            side_effect=Exception("not installed"),
        ):
            assert get_current_version() == "dev"

    def test_get_latest_version_failure(self) -> None:
        from ante.update.checker import get_latest_version

        with patch(
            "ante.update.checker.urllib.request.urlopen",
            side_effect=Exception("network error"),
        ):
            assert get_latest_version() is None
