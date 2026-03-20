"""Config 모듈 단위 테스트."""

from pathlib import Path

import pytest

from ante.config import DEFAULTS, Config, ConfigError

# ── Config 로드 ──────────────────────────────────


class TestConfigLoad:
    """Config.load() 테스트."""

    def test_load_with_toml(self, tmp_path: Path) -> None:
        """TOML 파일에서 설정을 로드한다."""
        toml_file = tmp_path / "system.toml"
        toml_file.write_text(
            '[system]\nlog_level = "DEBUG"\n\n[db]\npath = "custom/db.sqlite"\n'
        )
        config = Config.load(config_dir=tmp_path)

        assert config.get("system.log_level") == "DEBUG"
        assert config.get("db.path") == "custom/db.sqlite"

    def test_load_without_toml(self, tmp_path: Path) -> None:
        """TOML 파일 없이 기본값만으로 Config 생성 가능."""
        config = Config.load(config_dir=tmp_path)

        assert config.get("db.path") == "db/ante.db"
        assert config.get("web.port") == 3982

    def test_load_with_dotenv(self, tmp_path: Path) -> None:
        """.env 파일에서 비밀값을 로드한다."""
        env_file = tmp_path / "secrets.env"
        env_file.write_text('MY_SECRET=hello\nQUOTED="world"\n')
        config = Config.load(config_dir=tmp_path)

        assert config.secret("MY_SECRET") == "hello"
        assert config.secret("QUOTED") == "world"


# ── 정적 설정 접근 ────────────────────────────────


class TestConfigGet:
    """Config.get() 테스트."""

    def test_nested_get(self) -> None:
        """점(.) 구분자로 중첩 키에 접근한다."""
        config = Config(
            static={"db": {"path": "my.db"}, "web": {"port": 9090}},
            secrets={},
        )
        assert config.get("db.path") == "my.db"
        assert config.get("web.port") == 9090

    def test_defaults_fallback(self) -> None:
        """TOML에 없는 키는 DEFAULTS에서 가져온다."""
        config = Config(static={}, secrets={})

        for key, expected in DEFAULTS.items():
            assert config.get(key) == expected

    def test_toml_overrides_defaults(self) -> None:
        """TOML 값이 기본값보다 우선한다."""
        config = Config(
            static={"system": {"log_level": "ERROR"}},
            secrets={},
        )
        assert config.get("system.log_level") == "ERROR"

    def test_missing_key_returns_default(self) -> None:
        """존재하지 않는 키는 default 파라미터 값을 반환한다."""
        config = Config(static={}, secrets={})

        assert config.get("nonexistent.key") is None
        assert config.get("nonexistent.key", "fallback") == "fallback"

    def test_deeply_nested(self) -> None:
        """3단계 이상 중첩도 접근 가능하다."""
        config = Config(
            static={"a": {"b": {"c": 42}}},
            secrets={},
        )
        assert config.get("a.b.c") == 42

    def test_partial_path_returns_default(self) -> None:
        """부분 경로에서 리프가 아닌 노드를 만나면 default 반환."""
        config = Config(
            static={"a": {"b": 1}},
            secrets={},
        )
        assert config.get("a.b.c") is None


# ── 비밀값 접근 ──────────────────────────────────


class TestConfigSecret:
    """Config.secret() 테스트."""

    def test_secret_from_dotenv(self) -> None:
        """.env에서 비밀값을 가져온다."""
        config = Config(static={}, secrets={"API_KEY": "abc123"})
        assert config.secret("API_KEY") == "abc123"

    def test_env_var_overrides_dotenv(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """환경변수가 .env 파일보다 우선한다."""
        monkeypatch.setenv("API_KEY", "from_env")
        config = Config(static={}, secrets={"API_KEY": "from_file"})

        assert config.secret("API_KEY") == "from_env"

    def test_missing_secret_raises(self) -> None:
        """비밀값이 없으면 ConfigError를 발생시킨다."""
        config = Config(static={}, secrets={})
        with pytest.raises(ConfigError, match="Secret not found"):
            config.secret("NONEXISTENT")


# ── 유효성 검증 ──────────────────────────────────


class TestConfigValidate:
    """Config.validate() 테스트."""

    def test_validate_passes_with_defaults(self) -> None:
        """기본값만으로도 검증을 통과한다."""
        config = Config(static={}, secrets={})
        config.validate()

    def test_validate_fails_on_wrong_type(self) -> None:
        """잘못된 타입이면 검증에 실패한다."""
        config = Config(
            static={"web": {"port": "not_an_int"}, "db": {"path": 123}},
            secrets={},
        )
        with pytest.raises(ConfigError, match="Invalid type"):
            config.validate()


# ── .env 파서 ────────────────────────────────────


class TestDotenvParser:
    """_load_dotenv 파서 테스트."""

    def test_comments_and_empty_lines(self, tmp_path: Path) -> None:
        """주석과 빈 줄을 무시한다."""
        env_file = tmp_path / "secrets.env"
        env_file.write_text("# comment\n\nKEY=value\n")
        config = Config.load(config_dir=tmp_path)
        assert config.secret("KEY") == "value"

    def test_single_quotes(self, tmp_path: Path) -> None:
        """작은따옴표로 감싼 값을 파싱한다."""
        env_file = tmp_path / "secrets.env"
        env_file.write_text("KEY='single quoted'\n")
        config = Config.load(config_dir=tmp_path)
        assert config.secret("KEY") == "single quoted"

    def test_value_with_equals(self, tmp_path: Path) -> None:
        """값에 등호(=)가 포함된 경우 첫 번째 등호로만 분리한다."""
        env_file = tmp_path / "secrets.env"
        env_file.write_text("KEY=val=ue\n")
        config = Config.load(config_dir=tmp_path)
        assert config.secret("KEY") == "val=ue"
