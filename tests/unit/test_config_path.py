"""Config 경로 탐색 및 ante init 테스트."""

import os
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.config.config import resolve_config_dir
from ante.member.models import Member, MemberRole, MemberStatus, MemberType

# ── resolve_config_dir ──────────────────────────


class TestResolveConfigDir:
    def test_override_takes_priority(self, tmp_path: Path) -> None:
        """명시적 override가 최우선."""
        result = resolve_config_dir(override=tmp_path)
        assert result == tmp_path

    def test_env_var_second_priority(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ANTE_CONFIG_DIR 환경변수가 두 번째 우선순위."""
        env_path = tmp_path / "env_config"
        env_path.mkdir()
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_path))
        result = resolve_config_dir()
        assert result == env_path

    def test_user_config_dir_third(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """~/.config/ante/ 가 세 번째 우선순위."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        user_dir = tmp_path / ".config" / "ante"
        user_dir.mkdir(parents=True)
        with patch.object(Path, "home", return_value=tmp_path):
            result = resolve_config_dir()
        assert result == user_dir

    def test_fallback_to_local(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """다른 경로가 없으면 ./config/ 폴백."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        with patch.object(Path, "home", return_value=Path("/nonexistent")):
            result = resolve_config_dir()
        assert result == Path("config")

    def test_env_var_overrides_user_dir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """환경변수가 ~/.config/ante/ 보다 우선."""
        env_path = tmp_path / "env"
        env_path.mkdir()
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_path))

        user_dir = tmp_path / ".config" / "ante"
        user_dir.mkdir(parents=True)

        result = resolve_config_dir()
        assert result == env_path


# ── Config.load() with resolve ──────────────────


class TestConfigLoadResolve:
    def test_load_none_uses_resolve(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """Config.load()에 인자 없으면 resolve_config_dir() 사용."""
        from ante.config import Config

        monkeypatch.setenv("ANTE_CONFIG_DIR", str(tmp_path))
        toml = tmp_path / "system.toml"
        toml.write_text('[system]\nlog_level = "TRACE"\n')

        config = Config.load()
        assert config.get("system.log_level") == "TRACE"


# ── ante init ───────────────────────────────────

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    emoji="🦊",
    status=MemberStatus.ACTIVE,
    scopes=[],
    token_hash="hash",
    password_hash="hash",
    recovery_key_hash="hash",
    created_at="2026-01-01 00:00:00",
    created_by="system",
    token_expires_at="2026-04-01 00:00:00",
)

_MOCK_TOKEN = "ante_hk_test_token_path"
_MOCK_RECOVERY_KEY = "ANTE-RK-TEST-PATH-XXXX-YYYY"


def _mock_bootstrap(*args, **kwargs):
    return (
        {
            "member_id": "test-master",
            "name": "Test Master",
            "role": MemberRole.MASTER,
            "emoji": "🦊",
        },
        _MOCK_TOKEN,
        _MOCK_RECOVERY_KEY,
    )


def _mock_test_account(*args, **kwargs):
    return {"account_id": "test", "broker_type": "test", "exchange": "TEST"}


def _patch_init():
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch(
            "ante.cli.commands.init._create_test_account",
            new=AsyncMock(side_effect=_mock_test_account),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


class TestInitCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_init_creates_files(self, runner, tmp_path: Path) -> None:
        """ante init이 설정 파일을 생성한다 (비대화형, issue #1125)."""
        target = tmp_path / "new_config"
        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        finally:
            for p in patches:
                p.stop()
        assert result.exit_code == 0, result.output
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()

    def test_init_blocks_existing(self, runner, tmp_path: Path) -> None:
        """이미 3개 산출물이 모두 있고 DB 레코드가 완전하면 에러 (I4 state 1)."""
        target = tmp_path / "existing"
        target.mkdir()
        (target / "system.toml").write_text("existing")
        (target / "secrets.env").write_text("existing")
        (target / "db").mkdir()
        (target / "db" / "ante.db").write_text("")

        # state 1: master + test account 모두 존재하는 상태를 시뮬레이션
        with (
            patch(
                "ante.cli.commands.init._master_exists_in_db",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "ante.cli.commands.init._test_account_state",
                new=AsyncMock(return_value="active"),
            ),
            patch("ante.cli.main.authenticate_member"),
        ):
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        assert "init이 이미 완료된 상태입니다" in result.output

    def test_init_default_dir(self, runner, tmp_path: Path) -> None:
        """--dir 미지정 시 ~/.config/ante/ 사용."""
        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            with patch.object(Path, "home", return_value=tmp_path):
                result = runner.invoke(cli, ["init"])
        finally:
            for p in patches:
                p.stop()
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".config" / "ante" / "system.toml").exists()


# ── Issue #1721: Config.load의 ANTE_DB_ENCRYPTION_KEY export 패스 ───────────


class TestConfigLoadExportsEncryptionKey:
    """``Config.load`` 부수효과 — ``secrets.env`` 의 ``ANTE_DB_ENCRYPTION_KEY``
    를 ``os.environ`` 에 export하는 단일 키 패스 회귀.

    이슈 #1721 행렬 (Config.load 행):

    - valid env + (무관)              → export 비대상.
    - invalid/없음 env + valid file   → file value를 ``os.environ`` 에 set.
    - invalid/없음 env + invalid/없음 file → export 비대상.
    """

    def test_r8_only_encryption_key_is_exported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R8: ANTE_DB_ENCRYPTION_KEY만 export하고 다른 secret은 건드리지 않는다."""
        from cryptography.fernet import Fernet

        from ante.config import Config

        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        monkeypatch.delenv("FOO_OTHER_SECRET", raising=False)
        good = Fernet.generate_key().decode()
        (tmp_path / "secrets.env").write_text(
            f"ANTE_DB_ENCRYPTION_KEY={good}\nFOO_OTHER_SECRET=baz\n"
        )

        Config.load(config_dir=tmp_path)

        assert os.environ.get("ANTE_DB_ENCRYPTION_KEY") == good
        assert os.environ.get("FOO_OTHER_SECRET") is None

    def test_r9_existing_valid_env_is_preserved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R9: 사전 set된 valid env는 보존되며 file value로 override되지 않는다."""
        from cryptography.fernet import Fernet

        from ante.config import Config

        env_key = Fernet.generate_key().decode()
        file_key = Fernet.generate_key().decode()
        assert env_key != file_key
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", env_key)
        (tmp_path / "secrets.env").write_text(f"ANTE_DB_ENCRYPTION_KEY={file_key}\n")

        Config.load(config_dir=tmp_path)

        assert os.environ["ANTE_DB_ENCRYPTION_KEY"] == env_key

    def test_r10_empty_env_overridden_by_valid_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R10: 빈 env (또는 invalid env)는 file의 valid value로 override."""
        from cryptography.fernet import Fernet

        from ante.config import Config

        file_key = Fernet.generate_key().decode()
        (tmp_path / "secrets.env").write_text(f"ANTE_DB_ENCRYPTION_KEY={file_key}\n")

        # 빈 env
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "")
        Config.load(config_dir=tmp_path)
        assert os.environ["ANTE_DB_ENCRYPTION_KEY"] == file_key

        # invalid env (non-empty이지만 Fernet 아님)
        monkeypatch.setenv("ANTE_DB_ENCRYPTION_KEY", "garbage-not-fernet")
        Config.load(config_dir=tmp_path)
        assert os.environ["ANTE_DB_ENCRYPTION_KEY"] == file_key

    def test_r11_invalid_or_empty_file_not_exported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R11: file value가 빈 또는 invalid Fernet이면 export 비대상."""
        from ante.config import Config

        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)

        # 빈 file 값
        (tmp_path / "secrets.env").write_text("ANTE_DB_ENCRYPTION_KEY=\n")
        Config.load(config_dir=tmp_path)
        assert "ANTE_DB_ENCRYPTION_KEY" not in os.environ

        # invalid file 값 — 다른 디렉토리에서 별도 테스트
        target2 = tmp_path / "second"
        target2.mkdir()
        (target2 / "secrets.env").write_text(
            "ANTE_DB_ENCRYPTION_KEY=garbage-not-fernet\n"
        )
        Config.load(config_dir=target2)
        assert "ANTE_DB_ENCRYPTION_KEY" not in os.environ

    def test_r12_missing_secrets_env_is_noop(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R12: secrets.env 파일 자체가 없으면 export 비대상 (no-op)."""
        from ante.config import Config

        monkeypatch.delenv("ANTE_DB_ENCRYPTION_KEY", raising=False)
        # secrets.env 없음
        assert not (tmp_path / "secrets.env").exists()

        Config.load(config_dir=tmp_path)
        assert "ANTE_DB_ENCRYPTION_KEY" not in os.environ
