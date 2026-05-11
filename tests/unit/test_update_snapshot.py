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
    """CLI runner with default-deny 인증을 우회하는 헬퍼.

    #1404: ``AuthenticatedGroup``이 leaf command callback에 default-deny
    인증 가드를 자동 부착한다. 본 모듈의 테스트들은 ``ante update`` 자체의
    동작을 검증하므로 인증을 mock으로 우회한다 — ``ante.cli.main.authenticate_member``
    를 patch하여 ``ctx.obj["member"]``에 master stub을 채운다.
    """
    r = CliRunner()
    original_invoke = r.invoke

    from ante.member.models import Member, MemberRole, MemberType

    _master = Member(
        member_id="update-test-master",
        type=MemberType.HUMAN,
        role=MemberRole.MASTER,
        org="default",
        name="Update Test Master",
        status="active",
        scopes=[],
    )

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.ensure_object(dict)
                ctx.obj["member"] = _master

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


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
            # `pathlib.Path.exists`가 항상 True 를 돌려주는 테스트 시나리오에서는
            # `Config.load()` 가 존재하지도 않는 system.toml 을 열려다 IOError 가
            # 난다. update 흐름에서 호출되는 get_data_path / get_db_path 를 직접
            # mocking 해 Config.load() 경로를 우회한다 (#1158: get_db_path 도
            # Config.resolve_path 를 거치므로 같은 mock 가드가 필요하다).
            patch(
                "ante.cli.main.get_data_path",
                return_value="data/",
            ),
            patch(
                "ante.cli.main.get_db_path",
                return_value="db/ante.db",
            ),
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
            patches[10],
            patches[11],
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
            patches[10],
            patches[11],
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


class TestRunPostUpdateMigrationsDataPath:
    """Codex 13차 review Finding 1 — run_post_update_migrations 가 전달된
    data_path 를 서브프로세스 환경변수로 내려보내야 한다.

    과거 구현은 db_path 만 ANTE_DB_PATH 로 전달해, 서브프로세스가
    `data/` CWD 폴백으로 v002 Parquet 마이그레이션을 적용했다. custom
    config_dir / 사용자 지정 data root 환경에서는 런타임이 보는 데이터
    트리와 어긋나 마이그레이션이 빈 디렉토리를 보고 성공 처리되는
    문제가 있었다. 이제는 상위 CLI 가 계산한 실제 데이터 루트를
    ANTE_DATA_PATH 로 내려줘야 한다.
    """

    def test_data_path_passed_as_env_var(self) -> None:
        """data_path 인자가 ANTE_DATA_PATH 환경변수로 서브프로세스에 전달된다."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = run_post_update_migrations(
                "/custom/path/ante.db",
                data_path="/custom/path/data",
            )

        assert ok is True
        call_kwargs = mock_run.call_args.kwargs
        assert "env" in call_kwargs, "서브프로세스 env 키워드가 전달돼야 함"
        assert call_kwargs["env"]["ANTE_DB_PATH"] == "/custom/path/ante.db"
        assert call_kwargs["env"]["ANTE_DATA_PATH"] == "/custom/path/data"

    def test_data_path_keyword_only(self) -> None:
        """data_path 는 키워드 전용 인자 — 위치 인자로는 전달할 수 없다.

        호출자가 db_path 자리에 data_path 를 잘못 끼워 넣는 사고를 막기 위함.
        """
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            with pytest.raises(TypeError):
                run_post_update_migrations(  # type: ignore[misc]
                    "/custom/path/ante.db", "/custom/path/data"
                )

    def test_no_data_path_does_not_set_env(self) -> None:
        """data_path 가 None 이면 ANTE_DATA_PATH 는 설정하지 않는다 (하위 호환)."""
        with patch("ante.update.executor.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            ok = run_post_update_migrations("/custom/path/ante.db")

        assert ok is True
        call_kwargs = mock_run.call_args.kwargs
        env = call_kwargs.get("env", {})
        import os as _os

        if "ANTE_DATA_PATH" not in _os.environ:
            assert "ANTE_DATA_PATH" not in env


class TestUpdateCliPropagatesDataPath:
    """`ante update` CLI 통합: --config-dir 의 data.path 가 마이그레이션 호출에
    그대로 전달되는지 확인 (Codex 13차 review Finding 1)."""

    def test_cli_passes_data_path_from_system_toml(
        self,
        runner: CliRunner,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """system.toml 의 [data].path 가 run_post_update_migrations 의
        data_path 키워드 인자로 전달된다."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)

        config_dir = tmp_path / "cfg"
        config_dir.mkdir()
        custom_data = tmp_path / "shared" / "ante-data"
        (config_dir / "system.toml").write_text(
            f'[db]\npath = "{config_dir / "db" / "ante.db"}"\n\n'
            f'[data]\npath = "{custom_data}"\n'
        )

        captured: dict[str, object] = {}

        def _capture(*args: object, **kwargs: object) -> bool:
            captured["args"] = args
            captured["kwargs"] = kwargs
            return True

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
                "ante.update.executor.snapshot_dependencies",
                return_value=None,
            ),
            patch(
                "ante.update.executor.run_post_update_migrations",
                side_effect=_capture,
            ),
        ):
            result = runner.invoke(
                cli,
                ["--config-dir", str(config_dir), "update", "-y"],
            )

        assert result.exit_code == 0, result.output
        kwargs = captured.get("kwargs") or {}
        assert isinstance(kwargs, dict)
        assert kwargs.get("data_path") == str(custom_data), (
            "update CLI 는 system.toml 의 data.path 를 그대로 전달해야 합니다."
        )
