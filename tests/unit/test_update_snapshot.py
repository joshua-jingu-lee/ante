"""의존성 스냅샷(pip freeze) 단위 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.update.executor import (
    run_post_update_migrations,
    snapshot_dependencies,
)


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

    def test_snapshot_uses_provided_db_dir(self, tmp_path: Path) -> None:
        """Codex 10차 review Finding 2 — 호출자가 넘긴 db_dir 을 그대로 쓴다.

        `ante update` 는 `get_db_path(ctx)` 결과의 부모 디렉터리를
        `db_dir` 로 전달한다. 이 값이 custom config_dir 기반이라면
        CWD 기준 `./db` 가 아닌 해당 경로에 스냅샷이 저장돼야 한다.
        """
        custom_dir = tmp_path / "app" / "db"
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="ante==1.0.0\n")
            result = snapshot_dependencies("1.0.0", db_dir=custom_dir)

        assert result is not None
        assert result.parent == custom_dir
        assert result.name == "pip_freeze_v1.0.0.txt"
        assert custom_dir.exists()


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


class TestRunPostUpdateMigrationsDbPath:
    """Codex 10차 review Finding 2 — run_post_update_migrations 가
    전달된 db_path 를 서브프로세스 환경변수로 내려보내야 한다.

    과거 구현은 인자 없이 `python -m ante.db.migrations` 를 실행해
    서브프로세스가 `db/ante.db` CWD 폴백을 사용했다. 이제는 상위
    CLI 가 계산한 실제 DB 경로를 ANTE_DB_PATH 로 내려줘야 한다.
    """

    def test_db_path_passed_as_env_var(self) -> None:
        """db_path 인자가 ANTE_DB_PATH 환경변수로 서브프로세스에 전달된다."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = run_post_update_migrations("/custom/path/ante.db")

        assert ok is True
        call_kwargs = mock_run.call_args.kwargs
        assert "env" in call_kwargs, "서브프로세스 env 키워드가 전달돼야 함"
        assert call_kwargs["env"]["ANTE_DB_PATH"] == "/custom/path/ante.db"

    def test_no_db_path_does_not_set_env(self) -> None:
        """db_path 가 None 이면 ANTE_DB_PATH 는 설정하지 않는다 (하위 호환)."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = run_post_update_migrations(None)

        assert ok is True
        call_kwargs = mock_run.call_args.kwargs
        env = call_kwargs.get("env", {})
        # 원래 환경에 ANTE_DB_PATH 가 있었다면 상속 허용.
        # 단순히 executor 가 새로 주입하지 않았다는 점만 검증하기 위해
        # 현 프로세스 env 에 키가 없었으면 서브프로세스 env 에도 없어야 한다.
        import os as _os

        if "ANTE_DB_PATH" not in _os.environ:
            assert "ANTE_DB_PATH" not in env
