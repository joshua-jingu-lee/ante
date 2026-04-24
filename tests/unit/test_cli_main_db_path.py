"""get_db_path 헬퍼 회귀 테스트 (issue #1125).

`ante init`이 생성한 `<config_dir>/db/ante.db`를 후속 CLI들이 동일하게
바라보도록 보장한다. `--config-dir` / `ANTE_CONFIG_DIR`로 확정된 경로가
우선되어야 하고, 누락 시 `~/.config/ante/db/ante.db`로 폴백한다.
"""

from __future__ import annotations

import os
from pathlib import Path

import click
import pytest

from ante.cli.main import cli, get_db_path


def test_get_db_path_uses_config_dir() -> None:
    """ctx.obj['config_dir']이 있으면 그 하위 db/ante.db를 반환."""
    ctx = click.Context(cli, obj={"config_dir": Path("/tmp/ante-test-cfg")})
    assert get_db_path(ctx) == "/tmp/ante-test-cfg/db/ante.db"


def test_get_db_path_defaults_to_home() -> None:
    """ctx.obj에 config_dir이 없으면 ~/.config/ante/db/ante.db로 폴백."""
    ctx = click.Context(cli, obj={})
    expected = str(Path.home() / ".config" / "ante" / "db" / "ante.db")
    assert get_db_path(ctx) == expected


def test_get_db_path_accepts_string_config_dir() -> None:
    """config_dir이 문자열로 전달되어도 정상 변환."""
    ctx = click.Context(cli, obj={"config_dir": "/tmp/ante-string-cfg"})
    assert get_db_path(ctx) == "/tmp/ante-string-cfg/db/ante.db"


def test_get_db_path_without_ctx_argument() -> None:
    """ctx 인자 없이 호출 시 current_context가 없으면 기본 경로 사용."""
    # 현재 Click 컨텍스트 외부에서 호출 — silent fallback
    result = get_db_path()
    expected = str(Path.home() / ".config" / "ante" / "db" / "ante.db")
    assert result == expected


def test_get_db_path_with_none_obj() -> None:
    """ctx.obj가 None 또는 비-dict여도 안전하게 기본 경로로 폴백."""
    ctx = click.Context(cli)
    # Click Context는 ensure_object 호출 전엔 obj가 None일 수 있다
    expected = str(Path.home() / ".config" / "ante" / "db" / "ante.db")
    assert get_db_path(ctx) == expected


@pytest.mark.parametrize(
    "config_dir_value",
    [
        Path("/var/tmp/ante-a"),
        Path("/var/tmp/ante-b"),
        Path("/home/user/.local/share/ante"),
    ],
)
def test_get_db_path_varied_config_dirs(config_dir_value: Path) -> None:
    """여러 config_dir 값에서 일관적으로 `<config_dir>/db/ante.db` 반환."""
    ctx = click.Context(cli, obj={"config_dir": config_dir_value})
    assert get_db_path(ctx) == str(config_dir_value / "db" / "ante.db")


def test_get_db_path_ignores_env_directly() -> None:
    """get_db_path는 env를 직접 읽지 않는다 (루트 그룹이 ctx에 주입).

    환경변수 해석은 `cli()` 루트 콜백에서 1회만 수행되어 `ctx.obj["config_dir"]`에
    저장되므로, 헬퍼는 ctx만 믿는다. 이 분리로 테스트가 env 오염에 흔들리지 않는다.
    """
    old = os.environ.get("ANTE_CONFIG_DIR")
    os.environ["ANTE_CONFIG_DIR"] = "/tmp/env-should-be-ignored"
    try:
        ctx = click.Context(cli, obj={})
        # ctx.obj에 config_dir이 없으면 env가 설정돼 있어도 홈 기본값을 쓴다
        expected = str(Path.home() / ".config" / "ante" / "db" / "ante.db")
        assert get_db_path(ctx) == expected
    finally:
        if old is None:
            os.environ.pop("ANTE_CONFIG_DIR", None)
        else:
            os.environ["ANTE_CONFIG_DIR"] = old
