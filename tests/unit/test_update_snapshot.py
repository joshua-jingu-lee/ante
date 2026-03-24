"""의존성 스냅샷(pip freeze) 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.update.executor import snapshot_dependencies


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ---------------------------------------------------------------------------
# snapshot_dependencies 함수 직접 테스트
# ---------------------------------------------------------------------------


class TestSnapshotDependencies:
    """snapshot_dependencies 함수 단위 테스트."""

    def test_creates_snapshot_file(self, tmp_path: Path) -> None:
        """업데이트 실행 후 pip_freeze_v{version}.txt 파일이 생성된다."""
        freeze_output = "requests==2.31.0\nclick==8.1.7\n"

        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=freeze_output)
            result = snapshot_dependencies("1.0.0", db_dir=tmp_path)

        assert result is not None
        expected = tmp_path / "pip_freeze_v1.0.0.txt"
        assert expected.exists()
        assert result == expected

    def test_snapshot_content_valid(self, tmp_path: Path) -> None:
        """스냅샷 파일에 package==version 형식 라인이 포함된다."""
        freeze_output = "requests==2.31.0\nclick==8.1.7\nante==1.0.0\n"

        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=freeze_output)
            result = snapshot_dependencies("1.0.0", db_dir=tmp_path)

        assert result is not None
        content = result.read_text(encoding="utf-8")
        lines = [line for line in content.strip().split("\n") if line]
        for line in lines:
            assert "==" in line, f"package==version 형식이 아님: {line}"

    def test_pip_freeze_failure_returns_none(self, tmp_path: Path) -> None:
        """pip freeze가 실패하면 None을 반환한다."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="error")
            result = snapshot_dependencies("1.0.0", db_dir=tmp_path)

        assert result is None

    def test_creates_db_dir_if_missing(self, tmp_path: Path) -> None:
        """db 디렉터리가 없으면 자동으로 생성한다."""
        db_dir = tmp_path / "subdir" / "db"
        assert not db_dir.exists()

        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="pkg==1.0\n")
            result = snapshot_dependencies("0.5.0", db_dir=db_dir)

        assert result is not None
        assert db_dir.exists()


# ---------------------------------------------------------------------------
# CLI 통합: 롤백 안내에 스냅샷 경로 포함
# ---------------------------------------------------------------------------


class TestSnapshotInRollbackMessage:
    """롤백 시 안내 메시지에 스냅샷 파일 경로가 포함되는지 테스트."""

    def _make_patches(
        self,
        *,
        migration_ok: bool = False,
        rollback_ok: bool = True,
        snapshot_path: Path | None = Path("db/pip_freeze_v1.0.0.txt"),
    ) -> list:
        return [
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
            patch("ante.update.executor.pip_upgrade", return_value=True),
            patch(
                "ante.update.executor.run_post_update_migrations",
                return_value=migration_ok,
            ),
            patch(
                "ante.update.executor.rollback_update",
                return_value=rollback_ok,
            ),
            patch("pathlib.Path.exists", return_value=True),
            patch("ante.db.backup.backup_db"),
            patch(
                "ante.update.executor.snapshot_dependencies",
                return_value=snapshot_path,
            ),
            patch("ante.cli.commands.update.check_disk_space", return_value=(True, "")),
        ]

    def test_rollback_message_includes_snapshot_path(self, runner: CliRunner) -> None:
        """롤백 성공 시 의존성 복원 안내에 스냅샷 경로가 포함된다."""
        patches = self._make_patches(migration_ok=False, rollback_ok=True)
        with (
            patches[0],
            patches[1],
            patches[2],
            patches[3],
            patches[4],
            patches[5],
            patches[6],
            patches[7],
            patches[8],
            patches[9],
        ):
            result = runner.invoke(cli, ["update", "-y"])

        assert result.exit_code == 1
        assert "pip install -r" in result.output
        assert "pip_freeze_v1.0.0.txt" in result.output

    def test_manual_recovery_includes_snapshot_path(self, runner: CliRunner) -> None:
        """수동 복구 안내에도 스냅샷 경로가 포함된다."""
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
            patches[8],
            patches[9],
        ):
            result = runner.invoke(cli, ["update", "-y"])

        assert result.exit_code == 1
        assert "pip install -r" in result.output
        assert "pip_freeze_v1.0.0.txt" in result.output
