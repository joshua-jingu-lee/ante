"""마이그레이션 실패 시 자동 롤백 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.commands.update import update
from ante.update.executor import rollback_update


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# rollback_update 함수 직접 테스트
# ---------------------------------------------------------------------------


class TestRollbackUpdate:
    """rollback_update 함수 단위 테스트."""

    def test_pip_downgrade_called(self, tmp_path: Path) -> None:
        """pip 다운그레이드 명령이 올바르게 호출된다."""
        backup = tmp_path / "ante.db.bak.v1.0.0"
        backup.write_text("backup-data")

        with (
            patch("ante.update.executor.subprocess.run") as mock_run,
            patch("ante.update.executor.shutil.copy2"),
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = rollback_update("1.0.0", backup)

        assert result is True
        call_args = mock_run.call_args_list[0]
        cmd = call_args[0][0]
        assert "ante==1.0.0" in cmd

    def test_db_restored_from_backup(self, tmp_path: Path) -> None:
        """백업 파일이 있으면 DB가 복원된다."""
        backup = tmp_path / "ante.db.bak.v1.0.0"
        backup.write_text("backup-data")

        with (
            patch("ante.update.executor.subprocess.run") as mock_run,
            patch("ante.update.executor.shutil.copy2") as mock_copy,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = rollback_update("1.0.0", backup)

        assert result is True
        mock_copy.assert_called_once()
        assert str(backup) == mock_copy.call_args[0][0]

    def test_pip_rollback_failure_returns_false(self) -> None:
        """pip 롤백이 실패하면 False를 반환한다."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = rollback_update("1.0.0")

        assert result is False

    def test_missing_backup_file_returns_false(self, tmp_path: Path) -> None:
        """백업 파일이 존재하지 않으면 False를 반환한다."""
        missing_backup = tmp_path / "nonexistent.bak"

        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = rollback_update("1.0.0", missing_backup)

        assert result is False

    def test_no_backup_path_skips_db_restore(self) -> None:
        """backup_path가 None이면 DB 복원을 건너뛴다."""
        with (
            patch("ante.update.executor.subprocess.run") as mock_run,
            patch("ante.update.executor.shutil.copy2") as mock_copy,
        ):
            mock_run.return_value = MagicMock(returncode=0)
            result = rollback_update("1.0.0", None)

        assert result is True
        mock_copy.assert_not_called()


# ---------------------------------------------------------------------------
# CLI 통합: 마이그레이션 실패 시 롤백 호출
# ---------------------------------------------------------------------------


class TestUpdateMigrationFailureRollback:
    """ante update 명령에서 마이그레이션 실패 시 롤백이 호출되는지 테스트."""

    def _make_patches(
        self,
        *,
        migration_ok: bool = False,
        rollback_ok: bool = True,
        db_exists: bool = True,
    ) -> list:
        """공통 패치를 반환한다."""
        return [
            patch("ante.cli.commands.update.check_server_running", return_value=False),
            patch("ante.update.checker.get_current_version", return_value="1.0.0"),
            patch("ante.update.checker.get_latest_version", return_value="2.0.0"),
            patch("ante.update.executor.pip_upgrade", return_value=True),
            patch(
                "ante.update.executor.run_post_update_migrations",
                return_value=migration_ok,
            ),
            patch(
                "ante.update.executor.rollback_update",
                return_value=rollback_ok,
            ),
            patch("pathlib.Path.exists", return_value=db_exists),
            patch("ante.db.backup.backup_db"),
        ]

    def test_migration_failure_triggers_rollback(self, runner: CliRunner) -> None:
        """마이그레이션 실패 시 rollback_update가 호출된다."""
        patches = self._make_patches(migration_ok=False, rollback_ok=True)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5] as mock_rollback,
            patches[6],
            patches[7],
        ):
            result = runner.invoke(update, ["-y"])

        assert result.exit_code == 1
        mock_rollback.assert_called_once()
        assert "롤백 완료" in result.output

    def test_migration_failure_rollback_fails_shows_manual(
        self, runner: CliRunner
    ) -> None:
        """롤백도 실패하면 수동 복구 안내를 출력한다."""
        patches = self._make_patches(migration_ok=False, rollback_ok=False)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
        ):
            result = runner.invoke(update, ["-y"])

        assert result.exit_code == 1
        assert "자동 롤백 실패" in result.output
        assert "pip install ante==1.0.0" in result.output

    def test_migration_success_no_rollback(self, runner: CliRunner) -> None:
        """마이그레이션 성공 시 롤백이 호출되지 않는다."""
        patches = self._make_patches(migration_ok=True)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5] as mock_rollback,
            patches[6],
            patches[7],
        ):
            result = runner.invoke(update, ["-y"])

        assert result.exit_code == 0
        mock_rollback.assert_not_called()
        assert "업데이트 완료" in result.output
