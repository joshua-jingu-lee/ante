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
        assert config.get("runtime.socket_path") == "run/ante.sock"

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
            static={"db": {"path": "my.db"}, "runtime": {"socket_path": "custom.sock"}},
            secrets={},
        )
        assert config.get("db.path") == "my.db"
        assert config.get("runtime.socket_path") == "custom.sock"

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

    def test_empty_env_returns_empty_string(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """환경변수가 빈 문자열이면 그대로 빈 문자열을 반환한다."""
        monkeypatch.setenv("API_KEY", "")
        config = Config(static={}, secrets={"API_KEY": "from_file"})
        # 환경변수가 명시적으로 빈 문자열이면 dotenv로 fallback하지 않는다.
        assert config.secret("API_KEY") == ""

    def test_empty_env_does_not_fallback_to_dotenv(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """명시적 빈 환경변수는 .env fallback을 발생시키지 않는다."""
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        config = Config(static={}, secrets={"TELEGRAM_BOT_TOKEN": "file_value"})
        assert config.secret("TELEGRAM_BOT_TOKEN") == ""


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


# ── path-like 정규화 (Refs #1158) ─────────────────


class TestConfigResolvePath:
    """Config.resolve_path() 테스트.

    Spec: docs/specs/config/03-design-decisions.md `Ante instance/path contract`.
    상대 경로는 `config_dir` 기준, 절대 경로는 그대로, 키 미설정 시 default를 사용한다.
    """

    def test_resolve_path_returns_absolute_passthrough(self, tmp_path: Path) -> None:
        """절대 경로로 설정된 키는 `config_dir`과 무관하게 그대로 반환한다."""
        absolute_db = tmp_path / "elsewhere" / "ante.db"
        toml_file = tmp_path / "system.toml"
        toml_file.write_text(f'[db]\npath = "{absolute_db}"\n')

        config = Config.load(config_dir=tmp_path)

        assert config.resolve_path("db.path", "db/ante.db") == absolute_db

    def test_resolve_path_normalizes_relative_against_config_dir(
        self, tmp_path: Path
    ) -> None:
        """상대 경로는 호출 시점 CWD가 아니라 `config_dir` 기준으로 정규화한다."""
        toml_file = tmp_path / "system.toml"
        toml_file.write_text('[db]\npath = "custom/ante.db"\n')

        config = Config.load(config_dir=tmp_path)

        assert (
            config.resolve_path("db.path", "db/ante.db")
            == tmp_path / "custom" / "ante.db"
        )

    def test_resolve_path_uses_default_when_key_missing(self, tmp_path: Path) -> None:
        """TOML에 키가 없으면 default를 `config_dir` 기준으로 정규화한다."""
        config = Config.load(config_dir=tmp_path)

        # 키가 TOML/DEFAULTS 어디에도 없으면 default가 사용되며,
        # 결과는 config_dir 기준의 절대 경로여야 한다.
        assert (
            config.resolve_path("nonexistent.path", "fallback/ante.db")
            == tmp_path / "fallback" / "ante.db"
        )


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
