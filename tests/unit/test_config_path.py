"""Config 경로 탐색 및 ante init 테스트."""

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

_INIT_INPUT = "\n".join(
    [
        "test-master",  # Member ID
        "Test Master",  # 이름
        "pass1234",  # 패스워드
        "pass1234",  # 패스워드 확인
        "n",  # KIS 스킵
        "n",  # 텔레그램 스킵
        "n",  # data.go.kr 스킵
        "n",  # DART 스킵
    ]
)


def _mock_bootstrap(*args, **kwargs):
    return (
        {"member_id": "test-master", "role": MemberRole.MASTER, "emoji": "🦊"},
        _MOCK_TOKEN,
        _MOCK_RECOVERY_KEY,
    )


def _patch_init():
    return [
        patch(
            "ante.cli.commands.init._bootstrap_master",
            new=AsyncMock(side_effect=_mock_bootstrap),
        ),
        patch("ante.cli.main.authenticate_member"),
    ]


class TestInitCommand:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_init_creates_files(self, runner, tmp_path: Path) -> None:
        """ante init이 설정 파일을 생성한다."""
        target = tmp_path / "new_config"
        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            result = runner.invoke(
                cli, ["init", "--dir", str(target)], input=_INIT_INPUT
            )
        finally:
            for p in patches:
                p.stop()
        assert result.exit_code == 0, result.output
        assert "초기 설정 완료" in result.output
        assert (target / "system.toml").exists()
        assert (target / "secrets.env").exists()

    def test_init_blocks_existing(self, runner, tmp_path: Path) -> None:
        """이미 설정 파일이 있으면 에러."""
        target = tmp_path / "existing"
        target.mkdir()
        (target / "system.toml").write_text("existing")

        with patch("ante.cli.main.authenticate_member"):
            result = runner.invoke(cli, ["init", "--dir", str(target)])
        assert "이미 존재합니다" in result.output

    def test_init_default_dir(self, runner, tmp_path: Path) -> None:
        """--dir 미지정 시 ~/.config/ante/ 사용."""
        patches = _patch_init()
        for p in patches:
            p.start()
        try:
            with patch.object(Path, "home", return_value=tmp_path):
                result = runner.invoke(cli, ["init"], input=_INIT_INPUT)
        finally:
            for p in patches:
                p.stop()
        assert result.exit_code == 0, result.output
        assert (tmp_path / ".config" / "ante" / "system.toml").exists()
