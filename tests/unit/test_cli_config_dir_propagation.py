"""--config-dir 전파 회귀 테스트 (issue #1125).

`ante --config-dir <dir>` 옵션이 DB 경로뿐 아니라 정적 Config 로드와
IPC 소켓 경로 계산까지 일관되게 전파되어야 한다. 과거에는 DB만
override되고 `system.toml`/`ante.sock`은 기본 설치를 바라보는 회귀가
있었다.

Refs #1157: socket은 더 이상 ``db.path`` 부모가 아니라
``runtime.socket_path`` resolver(default ``<config_dir>/run/ante.sock``)를
따른다. 본 모듈의 expected 경로도 그에 맞춰 갱신되었다.
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from ante.cli.commands.ipc_helpers import get_socket_path
from ante.cli.main import cli, get_config_dir


class TestGetConfigDir:
    """get_config_dir 헬퍼: DB 외에도 Config/IPC 경로의 단일 진입점."""

    def test_uses_ctx_obj_config_dir(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ctx.obj['config_dir']이 가장 우선."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        ctx = click.Context(cli, obj={"config_dir": Path("/tmp/ante-cfg-x")})
        assert get_config_dir(ctx) == Path("/tmp/ante-cfg-x")

    def test_accepts_string_value(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ctx.obj['config_dir']이 str여도 Path로 정규화."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        ctx = click.Context(cli, obj={"config_dir": "/tmp/ante-cfg-str"})
        assert get_config_dir(ctx) == Path("/tmp/ante-cfg-str")

    def test_falls_back_to_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ctx에 override가 없으면 ANTE_CONFIG_DIR 환경변수 사용."""
        env_dir = tmp_path / "env-cfg"
        env_dir.mkdir()
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_dir))
        ctx = click.Context(cli, obj={})
        assert get_config_dir(ctx) == env_dir

    def test_override_beats_env(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """ctx override는 환경변수보다 우선."""
        monkeypatch.setenv("ANTE_CONFIG_DIR", "/tmp/env-should-be-ignored")
        override = tmp_path / "cli-override"
        ctx = click.Context(cli, obj={"config_dir": override})
        assert get_config_dir(ctx) == override

    def test_without_ctx(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """ctx 인자 없이 current_context가 없으면 resolve_config_dir 폴백."""
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        fake_home = tmp_path / "fake-home"
        (fake_home / ".config" / "ante").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # Click 컨텍스트 외부에서 호출 — silent fallback
        result = get_config_dir()
        assert result == fake_home / ".config" / "ante"


class TestGetSocketPathConfigDirPropagation:
    """get_socket_path가 --config-dir을 정적 Config 로드까지 전파한다."""

    def test_uses_provided_config_dir(self, tmp_path: Path) -> None:
        """get_socket_path(config_dir)가 해당 dir의 Config로 socket 위치 계산."""
        cfg = tmp_path / "custom"
        cfg.mkdir()
        (cfg / "system.toml").write_text(
            f'[db]\npath = "{cfg}/db/ante.db"\n', encoding="utf-8"
        )

        result = get_socket_path(config_dir=cfg)
        assert result == str(cfg / "run" / "ante.sock")

    def test_default_uses_env_fallback(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """config_dir=None이고 Click 컨텍스트가 없으면 ANTE_CONFIG_DIR 폴백."""
        cfg = tmp_path / "env-config"
        cfg.mkdir()
        (cfg / "system.toml").write_text(
            f'[db]\npath = "{cfg}/db/ante.db"\n', encoding="utf-8"
        )
        monkeypatch.setenv("ANTE_CONFIG_DIR", str(cfg))

        # ~/.config/ante 폴백을 막기 위해 home을 빈 곳으로
        fake_home = tmp_path / "fake-home"
        fake_home.mkdir()
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        result = get_socket_path()
        assert result == str(cfg / "run" / "ante.sock")

    def test_picks_up_ctx_when_no_explicit_arg(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """config_dir 인자 없이 호출해도 활성 Click 컨텍스트의
        ctx.obj['config_dir']을 자동으로 반영한다."""
        cfg = tmp_path / "ctx-config"
        cfg.mkdir()
        (cfg / "system.toml").write_text(
            f'[db]\npath = "{cfg}/db/ante.db"\n', encoding="utf-8"
        )
        # 환경변수 우선순위 회피
        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)

        ctx = click.Context(cli, obj={"config_dir": cfg})
        with ctx:
            result = get_socket_path()
        assert result == str(cfg / "run" / "ante.sock")

    def test_explicit_arg_beats_ctx(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """명시적 config_dir 인자가 활성 ctx보다 우선."""
        cfg_explicit = tmp_path / "explicit"
        cfg_explicit.mkdir()
        (cfg_explicit / "system.toml").write_text(
            f'[db]\npath = "{cfg_explicit}/db/ante.db"\n', encoding="utf-8"
        )

        cfg_ctx = tmp_path / "ctx"
        cfg_ctx.mkdir()
        (cfg_ctx / "system.toml").write_text(
            f'[db]\npath = "{cfg_ctx}/db/ante.db"\n', encoding="utf-8"
        )

        monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
        ctx = click.Context(cli, obj={"config_dir": cfg_ctx})
        with ctx:
            result = get_socket_path(config_dir=cfg_explicit)
        assert result == str(cfg_explicit / "run" / "ante.sock")


class TestConfigLoadAcceptsConfigDir:
    """Config.load(config_dir=...) 계약 회귀."""

    def test_loads_from_specified_dir(self, tmp_path: Path) -> None:
        """Config.load(config_dir)가 해당 dir의 system.toml을 읽는다."""
        from ante.config import Config

        cfg = tmp_path / "alt-config"
        cfg.mkdir()
        (cfg / "system.toml").write_text(
            '[system]\nlog_level = "DEBUG"\n[db]\npath = "x/y/z.db"\n',
            encoding="utf-8",
        )

        config = Config.load(config_dir=cfg)
        assert config.get("system.log_level") == "DEBUG"
        assert config.get("db.path") == "x/y/z.db"
