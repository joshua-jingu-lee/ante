"""`ante.cli._data_path.resolve_data_path` helper 단위 테스트 (#1914).

Spec: docs/specs/config/03-design-decisions.md `Ante instance/path contract`
(특히 `data.path` SSOT 행과 "명시적 CLI override는 작업 대상만 바꾸며 인스턴스
경계 불변" 규약).

본 helper 가 보장해야 하는 invariant:

1. override 가 명시되면 반환값은 override 와 1:1 동일 (변형 금지).
2. override 가 ``None`` 또는 ``""`` 이면 ``Config.resolve_path("data.path",
   "data").resolve()`` 의 문자열을 반환.
3. config_dir 이 cwd-상대(예: ``./config``) 여도 반환값은 항상 절대 경로.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ante.cli._data_path import resolve_data_path


@pytest.fixture
def config_dir_with_data(tmp_path: Path) -> Path:
    """`[data] path = "canonical-data"` 가 적힌 `system.toml` 을 가진 config_dir."""
    cfg_dir = tmp_path / "ante-cfg"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text(
        '[data]\npath = "canonical-data"\n',
        encoding="utf-8",
    )
    return cfg_dir


@pytest.fixture
def config_dir_default(tmp_path: Path) -> Path:
    """`data.path` 가 명시되지 않은 빈 config_dir.

    이 경우 helper 는 default fallback ``"data"`` 를 사용해야 한다.
    """
    cfg_dir = tmp_path / "ante-cfg-empty"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text("", encoding="utf-8")
    return cfg_dir


@pytest.fixture
def env_config_dir(monkeypatch: pytest.MonkeyPatch) -> object:
    """`ANTE_CONFIG_DIR` 를 monkeypatch 로 설정하는 callable fixture."""

    def _set(p: Path) -> None:
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(p))

    return _set


# ── override invariant ───────────────────────────────────────────────────────


class TestOverrideInvariant:
    """override 가 명시되면 그 값을 변형 없이 그대로 반환해야 한다."""

    def test_relative_override_preserved(self) -> None:
        # 상대 경로를 그대로 반환해야 한다 (절대화 금지).
        result = resolve_data_path(None, "./custom-data")
        assert result == "./custom-data"

    def test_absolute_override_preserved(self, tmp_path: Path) -> None:
        target = str(tmp_path / "custom" / "data")
        result = resolve_data_path(None, target)
        assert result == target

    def test_override_with_trailing_slash_preserved(self) -> None:
        # `data/` 같은 trailing slash 도 유지되어야 한다.
        result = resolve_data_path(None, "custom-data/")
        assert result == "custom-data/"


# ── config-resolved default ──────────────────────────────────────────────────


class TestConfigResolvedDefault:
    """override 미명시 시 ``Config.resolve_path("data.path", "data")`` 사용."""

    def test_uses_data_path_from_system_toml(
        self,
        config_dir_with_data: Path,
        env_config_dir: object,
    ) -> None:
        env_config_dir(config_dir_with_data)  # type: ignore[operator]
        result = resolve_data_path(None, None)
        expected = (config_dir_with_data / "canonical-data").resolve()
        assert result == str(expected)

    def test_empty_string_override_falls_back_to_config(
        self,
        config_dir_with_data: Path,
        env_config_dir: object,
    ) -> None:
        env_config_dir(config_dir_with_data)  # type: ignore[operator]
        # 빈 문자열은 명시적 override 가 아니라 미지정과 동일하게 처리.
        result = resolve_data_path(None, "")
        expected = (config_dir_with_data / "canonical-data").resolve()
        assert result == str(expected)

    def test_default_fallback_when_data_path_missing(
        self,
        config_dir_default: Path,
        env_config_dir: object,
    ) -> None:
        # `[data] path` 가 system.toml 에 없으면 ``"data"`` fallback.
        env_config_dir(config_dir_default)  # type: ignore[operator]
        result = resolve_data_path(None, None)
        expected = (config_dir_default / "data").resolve()
        assert result == str(expected)


# ── 절대경로 보장 ────────────────────────────────────────────────────────────


class TestAbsoluteResolve:
    """``.resolve()`` 가 항상 적용되어 cwd 와 무관하게 절대 경로를 반환한다."""

    def test_returns_absolute_path(
        self,
        config_dir_with_data: Path,
        env_config_dir: object,
    ) -> None:
        env_config_dir(config_dir_with_data)  # type: ignore[operator]
        result = resolve_data_path(None, None)
        assert Path(result).is_absolute(), (
            f"helper 반환값은 절대 경로여야 한다. got: {result}"
        )

    def test_resolved_path_independent_of_cwd(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """config_dir 이 cwd-상대 ``"."`` 인 케이스에서도 결과는 절대.

        Config(`config_dir=Path(".")`) 처럼 직접 생성된 객체는 `_config_dir`
        이 cwd 상대일 수 있다. helper 는 `.resolve()` 로 정규화해야 한다.
        """
        from ante.config.config import Config

        # 임시 cwd 안에서 동작.
        monkeypatch.chdir(tmp_path)
        (tmp_path / "system.toml").write_text(
            '[data]\npath = "rel-data"\n',
            encoding="utf-8",
        )
        cfg = Config.load(config_dir=Path("."))
        resolved = cfg.resolve_path("data.path", "data").resolve()
        # `.resolve()` 결과는 항상 절대.
        assert resolved.is_absolute()
        assert str(resolved) == str((tmp_path / "rel-data").resolve())
        # cwd 가 바뀌어도 동일 instance 의 resolved 는 같은 절대 경로를 유지해야
        # 한다 (sanity).
        sub = tmp_path / "sub"
        sub.mkdir()
        os.chdir(sub)
        try:
            assert resolved.is_absolute()
        finally:
            os.chdir(tmp_path)
