"""FeedConfig 유닛 테스트."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest

from ante.feed.config import API_KEYS, FeedConfig, _mask_value


@pytest.fixture
def data_path(tmp_path: Path) -> Path:
    """임시 데이터 디렉토리."""
    return tmp_path / "data"


@pytest.fixture
def cfg(data_path: Path) -> FeedConfig:
    """FeedConfig 인스턴스."""
    return FeedConfig(data_path)


# ── init ─────────────────────────────────────────────────────────────────────


class TestInit:
    def test_creates_config_toml(self, cfg: FeedConfig) -> None:
        cfg.init()
        assert cfg.config_path.exists()

    def test_creates_checkpoints_dir(self, cfg: FeedConfig) -> None:
        cfg.init()
        assert (cfg.feed_dir / "checkpoints").is_dir()

    def test_creates_reports_dir(self, cfg: FeedConfig) -> None:
        cfg.init()
        assert (cfg.feed_dir / "reports").is_dir()

    def test_returns_created_paths(self, cfg: FeedConfig) -> None:
        created = cfg.init()
        assert len(created) == 3

    def test_idempotent_second_call(self, cfg: FeedConfig) -> None:
        cfg.init()
        created_again = cfg.init()
        # config.toml은 이미 존재하므로 두 번째 호출에서 포함되지 않음
        assert str(cfg.config_path) not in created_again

    def test_config_toml_contains_defaults(self, cfg: FeedConfig) -> None:
        cfg.init()
        content = cfg.config_path.read_text()
        assert "[general]" in content
        assert "[schedule]" in content

    def test_is_initialized_false_before_init(self, cfg: FeedConfig) -> None:
        assert not cfg.is_initialized()

    def test_is_initialized_true_after_init(self, cfg: FeedConfig) -> None:
        cfg.init()
        assert cfg.is_initialized()


# ── set_api_key ───────────────────────────────────────────────────────────────


class TestSetApiKey:
    def test_writes_key_to_env_file(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        assert cfg.env_path.exists()
        content = cfg.env_path.read_text()
        assert "ANTE_DATAGOKR_API_KEY=abc123" in content

    def test_file_permission_is_0600(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        file_mode = stat.S_IMODE(cfg.env_path.stat().st_mode)
        assert file_mode == 0o600

    def test_returns_env_path(self, cfg: FeedConfig) -> None:
        result = cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        assert result == cfg.env_path

    def test_overwrites_existing_key(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "old_value")
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "new_value")
        content = cfg.env_path.read_text()
        assert "new_value" in content
        assert "old_value" not in content

    def test_multiple_keys_coexist(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "key1")
        cfg.set_api_key("ANTE_DART_API_KEY", "key2")
        content = cfg.env_path.read_text()
        assert "ANTE_DATAGOKR_API_KEY=key1" in content
        assert "ANTE_DART_API_KEY=key2" in content


class TestSetApiKeyNewlineRejection:
    """#2051: 개행 포함 value는 .env 키 주입 위험으로 거부한다."""

    def test_newline_value_raises_value_error(self, cfg: FeedConfig) -> None:
        # 개행 뒤에 KEY=VALUE를 끼워 다른 키 주입을 시도하는 페이로드.
        with pytest.raises(ValueError, match="개행"):
            cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "a\nANTE_DART_API_KEY=evil")

    def test_newline_value_does_not_inject_other_key(self, cfg: FeedConfig) -> None:
        # 거부 시 .env 자체가 생성되지 않아야 한다(쓰기 전 검증, 파일 미변경).
        with pytest.raises(ValueError):
            cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "a\nANTE_DART_API_KEY=evil")
        assert not cfg.env_path.exists()
        keys = cfg.load_api_keys()
        assert keys["ANTE_DART_API_KEY"] is None

    def test_newline_value_preserves_existing_env(self, cfg: FeedConfig) -> None:
        # 기존 .env가 있을 때 거부되면 기존 내용이 그대로 유지된다.
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "realkey")
        before = cfg.env_path.read_text()
        with pytest.raises(ValueError):
            cfg.set_api_key("ANTE_DART_API_KEY", "x\nANTE_DATAGOKR_API_KEY=evil")
        assert cfg.env_path.read_text() == before
        keys = cfg.load_api_keys()
        assert keys["ANTE_DATAGOKR_API_KEY"] == "realkey"
        assert keys["ANTE_DART_API_KEY"] is None

    def test_carriage_return_value_rejected(self, cfg: FeedConfig) -> None:
        with pytest.raises(ValueError, match="개행"):
            cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "a\rANTE_DART_API_KEY=evil")
        assert not cfg.env_path.exists()

    def test_normal_value_still_saved(self, cfg: FeedConfig) -> None:
        # 개행 없는 정상 value는 기존대로 저장된다.
        result = cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "realkey")
        assert result == cfg.env_path
        keys = cfg.load_api_keys()
        assert keys["ANTE_DATAGOKR_API_KEY"] == "realkey"


# ── list_api_keys ─────────────────────────────────────────────────────────────


class TestListApiKeys:
    def test_shows_masked_value_from_env_file(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123def456")
        keys = cfg.list_api_keys()
        datagokr = next(k for k in keys if k["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["value"] == "abc***456"

    def test_shows_unset_for_missing_keys(self, cfg: FeedConfig) -> None:
        keys = cfg.list_api_keys()
        for entry in keys:
            assert entry["value"] == "(미설정)"
            assert entry["source"] == ""

    def test_shows_env_source_for_env_file(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123def456")
        keys = cfg.list_api_keys()
        datagokr = next(k for k in keys if k["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["source"] == ".env"

    def test_shows_env_source_for_environment_variable(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTE_DATAGOKR_API_KEY", "abc123def456")
        keys = cfg.list_api_keys()
        datagokr = next(k for k in keys if k["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["source"] == "env"

    def test_all_supported_keys_appear(self, cfg: FeedConfig) -> None:
        keys = cfg.list_api_keys()
        returned_keys = {k["key"] for k in keys}
        assert returned_keys == set(API_KEYS)


# ── load_api_keys ─────────────────────────────────────────────────────────────


class TestLoadApiKeys:
    def test_returns_none_for_missing_keys(self, cfg: FeedConfig) -> None:
        keys = cfg.load_api_keys()
        for key in API_KEYS:
            assert keys[key] is None

    def test_returns_value_from_env_file(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "mykey123")
        keys = cfg.load_api_keys()
        assert keys["ANTE_DATAGOKR_API_KEY"] == "mykey123"

    def test_env_var_takes_priority_over_env_file(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "file_value")
        monkeypatch.setenv("ANTE_DATAGOKR_API_KEY", "env_value")
        keys = cfg.load_api_keys()
        assert keys["ANTE_DATAGOKR_API_KEY"] == "env_value"

    def test_returns_all_api_keys(self, cfg: FeedConfig) -> None:
        keys = cfg.load_api_keys()
        assert set(keys.keys()) == set(API_KEYS)


# ── check_api_keys ────────────────────────────────────────────────────────────


class TestCheckApiKeys:
    def test_unset_key_returns_set_false(self, cfg: FeedConfig) -> None:
        statuses = cfg.check_api_keys()
        for entry in statuses:
            assert entry["set"] is False

    def test_set_key_returns_set_true(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        statuses = cfg.check_api_keys()
        datagokr = next(s for s in statuses if s["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["set"] is True

    def test_env_var_key_returns_set_true(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTE_DART_API_KEY", "dart_key_value")
        statuses = cfg.check_api_keys()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        assert dart["set"] is True

    def test_set_key_source_is_env_file(self, cfg: FeedConfig) -> None:
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        statuses = cfg.check_api_keys()
        datagokr = next(s for s in statuses if s["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["source"] == ".env"

    def test_env_var_source_is_env(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("ANTE_DATAGOKR_API_KEY", "env_val")
        statuses = cfg.check_api_keys()
        datagokr = next(s for s in statuses if s["key"] == "ANTE_DATAGOKR_API_KEY")
        assert datagokr["source"] == "env"

    def test_empty_env_file_value_is_not_set(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # (a) #2104 재현: .env에 빈 DART 키 + 정상 DATAGOKR 키.
        # 환경변수가 .env를 가리지 않도록 명시적으로 제거한다.
        monkeypatch.delenv("ANTE_DART_API_KEY", raising=False)
        monkeypatch.delenv("ANTE_DATAGOKR_API_KEY", raising=False)
        cfg.feed_dir.mkdir(parents=True, exist_ok=True)
        cfg.env_path.write_text("ANTE_DART_API_KEY=\nANTE_DATAGOKR_API_KEY=abc\n")

        statuses = cfg.check_api_keys()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        datagokr = next(s for s in statuses if s["key"] == "ANTE_DATAGOKR_API_KEY")

        assert dart["set"] is False
        assert dart["source"] == ""
        assert datagokr["set"] is True
        assert datagokr["source"] == ".env"

    def test_env_var_takes_priority_with_set_true(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # (b) 환경변수 경로가 set=True/source="env"로 잡힌다.
        monkeypatch.setenv("ANTE_DART_API_KEY", "xyz")
        statuses = cfg.check_api_keys()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        assert dart["set"] is True
        assert dart["source"] == "env"

    def test_missing_key_is_not_set(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # (c) .env 없음 + 키 없음 → set=False/source="".
        for key in API_KEYS:
            monkeypatch.delenv(key, raising=False)
        statuses = cfg.check_api_keys()
        for entry in statuses:
            assert entry["set"] is False
            assert entry["source"] == ""

    def test_whitespace_only_env_file_value_is_not_set(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # (d) 공백뿐인 .env 값은 strip되어 ""로 정규화 → set=False (회귀 lock).
        monkeypatch.delenv("ANTE_DART_API_KEY", raising=False)
        cfg.feed_dir.mkdir(parents=True, exist_ok=True)
        cfg.env_path.write_text("ANTE_DART_API_KEY=   \n")

        statuses = cfg.check_api_keys()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        assert dart["set"] is False
        assert dart["source"] == ""

    def test_set_true_rows_always_have_source(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # (e) set/source 정합 lock: set=True인 row는 source∈{"env",".env"}.
        monkeypatch.setenv("ANTE_DART_API_KEY", "xyz")
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "abc123")
        statuses = cfg.check_api_keys()
        for entry in statuses:
            if entry["set"]:
                assert entry["source"] in {"env", ".env"}
            else:
                assert entry["source"] == ""


# ── check_api_keys_with_validation (#2046) ────────────────────────────────────


class TestCheckApiKeysWithValidation:
    """네트워크 유효성 3-state 경로 (source.validate_credentials mock)."""

    @pytest.mark.asyncio
    async def test_unset_keys_skip_validation(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """미설정 키는 검증을 생략한다 (valid/detail=None, set=False)."""
        for key in API_KEYS:
            monkeypatch.delenv(key, raising=False)
        statuses = await cfg.check_api_keys_with_validation()
        for entry in statuses:
            assert entry["set"] is False
            assert entry["valid"] is None
            assert entry["detail"] is None

    @pytest.mark.asyncio
    async def test_set_key_validates_valid(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """설정된 키가 유효하면 valid=True/detail=None."""
        for key in API_KEYS:
            monkeypatch.delenv(key, raising=False)
        cfg.set_api_key("ANTE_DART_API_KEY", "dart-key-value")

        from ante.feed.sources import dart as dart_mod

        async def _ok(self: object) -> tuple[bool, None]:
            return True, None

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _ok)
        statuses = await cfg.check_api_keys_with_validation()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        assert dart["set"] is True
        assert dart["source"] == ".env"
        assert dart["valid"] is True
        assert dart["detail"] is None

    @pytest.mark.asyncio
    async def test_set_key_validates_invalid(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """인증 실패 키는 valid=False + detail 사유."""
        for key in API_KEYS:
            monkeypatch.delenv(key, raising=False)
        cfg.set_api_key("ANTE_DATAGOKR_API_KEY", "datagokr-key")

        from ante.feed.sources import data_go_kr as dg_mod

        async def _invalid(self: object) -> tuple[bool, str]:
            return False, "인증 실패 (code=30): not registered"

        monkeypatch.setattr(dg_mod.DataGoKrSource, "validate_credentials", _invalid)
        statuses = await cfg.check_api_keys_with_validation()
        dg = next(s for s in statuses if s["key"] == "ANTE_DATAGOKR_API_KEY")
        assert dg["valid"] is False
        assert dg["detail"] is not None
        assert "30" in dg["detail"]

    @pytest.mark.asyncio
    async def test_set_key_validation_unknown(
        self, cfg: FeedConfig, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """검증 불가(네트워크)는 valid=None + detail 사유, 예외 미전파."""
        for key in API_KEYS:
            monkeypatch.delenv(key, raising=False)
        cfg.set_api_key("ANTE_DART_API_KEY", "dart-key-value")

        from ante.feed.sources import dart as dart_mod

        async def _unknown(self: object) -> tuple[None, str]:
            return None, "검증 불가 (네트워크): offline"

        monkeypatch.setattr(dart_mod.DARTSource, "validate_credentials", _unknown)
        statuses = await cfg.check_api_keys_with_validation()
        dart = next(s for s in statuses if s["key"] == "ANTE_DART_API_KEY")
        assert dart["valid"] is None
        assert dart["detail"] is not None
        assert "네트워크" in dart["detail"]


# ── _mask_value ───────────────────────────────────────────────────────────────


class TestMaskValue:
    def test_masks_long_value(self) -> None:
        assert _mask_value("abc123def456") == "abc***456"

    def test_masks_short_value(self) -> None:
        assert _mask_value("abc") == "***"

    def test_masks_exactly_six_chars(self) -> None:
        assert _mask_value("abcdef") == "***"

    def test_masks_seven_chars(self) -> None:
        result = _mask_value("abcdefg")
        assert result == "abc***efg"
