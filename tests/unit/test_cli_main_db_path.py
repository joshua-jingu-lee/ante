"""get_db_path 헬퍼 회귀 테스트 (issue #1125).

`ante init`이 생성한 `<config_dir>/db/ante.db`를 후속 CLI들이 동일하게
바라보도록 보장한다. 헬퍼는 `resolve_config_dir()`의 우선순위를 그대로
따른다:

    override(ctx.obj["config_dir"]) > ANTE_CONFIG_DIR > ~/.config/ante/
        (존재 시) > ./config/
"""

from __future__ import annotations

from pathlib import Path

import click
import pytest

from ante.cli.main import cli, get_db_path


def test_get_db_path_uses_config_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """ctx.obj['config_dir']이 있으면 그 하위 db/ante.db를 반환."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    ctx = click.Context(cli, obj={"config_dir": Path("/tmp/ante-test-cfg")})
    assert get_db_path(ctx) == "/tmp/ante-test-cfg/db/ante.db"


def test_get_db_path_uses_home_when_exists(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """~/.config/ante가 존재하면 홈 경로 폴백을 사용한다."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    fake_home = tmp_path / "fake-home"
    (fake_home / ".config" / "ante").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    ctx = click.Context(cli, obj={})
    expected = str(fake_home / ".config" / "ante" / "db" / "ante.db")
    assert get_db_path(ctx) == expected


def test_get_db_path_uses_repo_local_config_when_home_absent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """~/.config/ante가 없으면 ./config 폴백을 사용한다.

    resolve_config_dir() 계약을 따라 repo-local `./config/`로 떨어져야 하며,
    무조건 홈으로 직행하는 과거 동작은 회귀가 아니다.
    """
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    fake_home = tmp_path / "fake-home"
    fake_home.mkdir()  # ~/.config/ante는 일부러 만들지 않음
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    monkeypatch.chdir(tmp_path)

    ctx = click.Context(cli, obj={})
    result = get_db_path(ctx)
    # Path("config")는 상대 경로. 최종 문자열은 "config/db/ante.db".
    assert result == str(Path("config") / "db" / "ante.db")


def test_get_db_path_env_var_takes_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ANTE_CONFIG_DIR 환경변수가 ~/.config/ante 존재 여부보다 우선한다."""
    fake_home = tmp_path / "fake-home"
    (fake_home / ".config" / "ante").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    custom_dir = tmp_path / "custom-cfg"
    custom_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(custom_dir))

    ctx = click.Context(cli, obj={})
    assert get_db_path(ctx) == str(custom_dir / "db" / "ante.db")


def test_get_db_path_override_takes_absolute_precedence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ctx.obj['config_dir'] (--config-dir)가 환경변수보다 우선한다."""
    monkeypatch.setenv("ANTE_CONFIG_DIR", "/tmp/env-should-be-ignored")
    override = tmp_path / "cli-override"
    ctx = click.Context(cli, obj={"config_dir": override})
    assert get_db_path(ctx) == str(override / "db" / "ante.db")


def test_get_db_path_accepts_string_config_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """config_dir이 문자열로 전달되어도 정상 변환."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    ctx = click.Context(cli, obj={"config_dir": "/tmp/ante-string-cfg"})
    assert get_db_path(ctx) == "/tmp/ante-string-cfg/db/ante.db"


def test_get_db_path_without_ctx_argument(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ctx 인자 없이 호출 시 current_context가 없으면 resolve_config_dir 폴백.

    ~/.config/ante가 존재하는 상태를 세팅하여 홈 경로가 선택되는지 검증.
    """
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    fake_home = tmp_path / "fake-home"
    (fake_home / ".config" / "ante").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    # 현재 Click 컨텍스트 외부에서 호출 — silent fallback
    result = get_db_path()
    expected = str(fake_home / ".config" / "ante" / "db" / "ante.db")
    assert result == expected


def test_get_db_path_with_none_obj(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ctx.obj가 None 또는 비-dict여도 안전하게 기본 경로로 폴백."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    fake_home = tmp_path / "fake-home"
    (fake_home / ".config" / "ante").mkdir(parents=True)
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

    ctx = click.Context(cli)
    # Click Context는 ensure_object 호출 전엔 obj가 None일 수 있다
    expected = str(fake_home / ".config" / "ante" / "db" / "ante.db")
    assert get_db_path(ctx) == expected


@pytest.mark.parametrize(
    "config_dir_value",
    [
        Path("/var/tmp/ante-a"),
        Path("/var/tmp/ante-b"),
        Path("/home/user/.local/share/ante"),
    ],
)
def test_get_db_path_varied_config_dirs(
    config_dir_value: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """여러 config_dir 값에서 일관적으로 `<config_dir>/db/ante.db` 반환."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    ctx = click.Context(cli, obj={"config_dir": config_dir_value})
    assert get_db_path(ctx) == str(config_dir_value / "db" / "ante.db")


def test_get_db_path_env_used_when_ctx_has_no_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """ctx.obj에 config_dir이 없으면 resolve_config_dir이 env를 읽는다.

    루트 `cli()` 콜백을 거치지 않고 서브커맨드가 직접 호출되거나 테스트에서
    ctx를 직접 만들 때에도 `ANTE_CONFIG_DIR` 환경변수가 반영되어야 한다.
    """
    env_dir = tmp_path / "env-cfg"
    env_dir.mkdir()
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_dir))

    ctx = click.Context(cli, obj={})
    assert get_db_path(ctx) == str(env_dir / "db" / "ante.db")
