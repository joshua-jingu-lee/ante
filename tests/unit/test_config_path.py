"""Config 경로 탐색 및 ante init 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.config.config import resolve_config_dir
from ante.member.models import Member, MemberRole, MemberType

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
    status="active",
    scopes=[],
)


class TestInitCommand:
    @pytest.fixture
    def runner(self):
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

    def test_init_creates_files(self, runner, tmp_path: Path) -> None:
        """ante init이 설정 파일을 생성한다."""
        target = tmp_path / "new_config"
        result = runner.invoke(cli, ["init", "--dir", str(target)])
        assert result.exit_code == 0
        assert "초기화 완료" in result.output
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()

    def test_init_blocks_existing(self, runner, tmp_path: Path) -> None:
        """이미 설정 파일이 있으면 에러."""
        target = tmp_path / "existing"
        target.mkdir()
        (target / "system.toml").write_text("existing")

        result = runner.invoke(cli, ["init", "--dir", str(target)])
        assert "이미 존재합니다" in result.output

    def test_init_default_dir(self, runner, tmp_path: Path) -> None:
        """--dir 미지정 시 ~/.config/ante/ 사용."""
        with patch.object(Path, "home", return_value=tmp_path):
            result = runner.invoke(cli, ["init"])
        assert result.exit_code == 0
        assert (tmp_path / ".config" / "ante" / "system.toml").exists()
