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
