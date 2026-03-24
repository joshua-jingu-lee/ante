"""check_disk_space 함수 단위 테스트. Refs #922."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.update import _MIN_FREE_MB, check_disk_space


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCheckDiskSpace:
    """check_disk_space 유틸 함수 테스트."""

    def test_sufficient_space_with_db(self, tmp_path: Path) -> None:
        """DB 존재 + 충분한 공간 -> 통과."""
        db_file = tmp_path / "ante.db"
        db_file.write_bytes(b"\x00" * 1024 * 1024)  # 1 MB

        required = 1024 * 1024 * 2 + _MIN_FREE_MB * 1024 * 1024
        fake_free = required + 1024  # 여유 있음

        with patch(
            "ante.cli.commands.update.shutil.disk_usage",
            return_value=type("Usage", (), {"free": fake_free})(),
        ):
            ok, msg = check_disk_space(db_file)

        assert ok is True
        assert msg == ""

    def test_insufficient_space_with_db(self, tmp_path: Path) -> None:
        """DB 존재 + 공간 부족 -> 실패 + 안내 메시지."""
        db_file = tmp_path / "ante.db"
        db_file.write_bytes(b"\x00" * 1024 * 1024)  # 1 MB

        fake_free = 1024  # 거의 없음

        with patch(
            "ante.cli.commands.update.shutil.disk_usage",
            return_value=type("Usage", (), {"free": fake_free})(),
        ):
            ok, msg = check_disk_space(db_file)

        assert ok is False
        assert "디스크 공간 부족" in msg

    def test_no_db_file_sufficient_space(self, tmp_path: Path) -> None:
        """DB 미존재 -> 100MB만 확인, 충분하면 통과."""
        db_file = tmp_path / "ante.db"  # 생성 안 함

        fake_free = _MIN_FREE_MB * 1024 * 1024 + 1024

        with patch(
            "ante.cli.commands.update.shutil.disk_usage",
            return_value=type("Usage", (), {"free": fake_free})(),
        ):
            ok, msg = check_disk_space(db_file)

        assert ok is True
        assert msg == ""

    def test_no_db_file_insufficient_space(self, tmp_path: Path) -> None:
        """DB 미존재 + 100MB 미만 -> 실패."""
        db_file = tmp_path / "ante.db"

        fake_free = 1024  # 거의 없음

        with patch(
            "ante.cli.commands.update.shutil.disk_usage",
            return_value=type("Usage", (), {"free": fake_free})(),
        ):
            ok, msg = check_disk_space(db_file)

        assert ok is False
        assert "디스크 공간 부족" in msg


class TestUpdateDiskSpaceIntegration:
    """update CLI 명령에서 디스크 공간 검사 통합 테스트."""

    def test_disk_space_insufficient_blocks_update(self, runner: CliRunner) -> None:
        """디스크 공간 부족 시 exit code 1로 종료한다."""
        from ante.cli.commands.update import update

        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch(
                "ante.update.checker.get_current_version",
                return_value="1.0.0",
            ),
            patch(
                "ante.update.checker.get_latest_version",
                return_value="2.0.0",
            ),
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(
                    False,
                    "디스크 공간 부족",
                ),
            ),
        ):
            result = runner.invoke(update, ["-y"])

        assert result.exit_code == 1
        assert "디스크 공간 부족" in result.output

    def test_disk_space_sufficient_proceeds(self, runner: CliRunner) -> None:
        """디스크 공간 충분 시 업데이트를 계속 진행한다."""
        from ante.cli.commands.update import update

        with (
            patch(
                "ante.cli.commands.update.check_server_running",
                return_value=False,
            ),
            patch(
                "ante.update.checker.get_current_version",
                return_value="1.0.0",
            ),
            patch(
                "ante.update.checker.get_latest_version",
                return_value="2.0.0",
            ),
            patch(
                "ante.cli.commands.update.check_disk_space",
                return_value=(True, ""),
            ),
            patch("ante.db.backup.backup_db"),
            patch("ante.update.executor.pip_upgrade", return_value=True),
            patch(
                "ante.update.executor.run_post_update_migrations",
                return_value=True,
            ),
            patch("pathlib.Path.exists", return_value=False),
        ):
            result = runner.invoke(update, ["-y"])

        assert result.exit_code == 0
        assert "업데이트 완료" in result.output
