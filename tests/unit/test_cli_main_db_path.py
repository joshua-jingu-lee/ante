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

from ante.cli.main import cli, get_data_path, get_db_path


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


# ---------------------------------------------------------------------------
# get_db_path × system.toml `db.path` (Refs #1158)
#
# Spec: docs/specs/cli/02-design-decisions.md:62-70.
# `get_db_path` 는 server runtime과 동일한 resolver(`Config.resolve_path`)
# 를 통해 `db.path` 를 해석해야 한다. 이로써 cold-path CLI(account create
# /delete/set-credentials)가 보는 DB와 server runtime이 보는 DB가 항상
# 일치하여 split-brain이 발생하지 않는다.
# ---------------------------------------------------------------------------


def test_get_db_path_reads_relative_db_path_from_system_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """system.toml 의 [db].path 가 상대 경로면 config_dir 기준으로 정규화."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    cfg_dir = tmp_path / "instance-rel"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text('[db]\npath = "custom/ante.db"\n')

    ctx = click.Context(cli, obj={"config_dir": cfg_dir})
    assert get_db_path(ctx) == str(cfg_dir / "custom" / "ante.db")


def test_get_db_path_reads_absolute_db_path_from_system_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """system.toml 의 [db].path 가 절대 경로면 config_dir과 무관하게 그대로 사용."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    cfg_dir = tmp_path / "instance-abs"
    cfg_dir.mkdir()
    absolute_db = tmp_path / "elsewhere" / "ante.db"
    (cfg_dir / "system.toml").write_text(f'[db]\npath = "{absolute_db}"\n')

    ctx = click.Context(cli, obj={"config_dir": cfg_dir})
    assert get_db_path(ctx) == str(absolute_db)


def test_explicit_db_path_arg_takes_precedence_over_get_db_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--db-path` 옵션을 가진 커맨드는 자체 인자가 우선이며 get_db_path는 폴백.

    spec: docs/specs/cli/02-design-decisions.md:69 (`--db-path` 가진 커맨드
    들은 기본값을 None으로 두고, 값이 없을 때 `get_db_path(ctx)`로 폴백).
    이 테스트는 헬퍼가 system.toml을 읽되, 호출자(서브커맨드 옵션 핸들러)
    가 명시적 값을 제공하면 헬퍼 결과를 무시할 수 있는 단순 폴백임을 명확히
    한다 — 즉 헬퍼가 호출자 인자를 가로채지 않는다.
    """
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    cfg_dir = tmp_path / "fallback-instance"
    cfg_dir.mkdir()
    (cfg_dir / "system.toml").write_text('[db]\npath = "should-not-be-used.db"\n')

    ctx = click.Context(cli, obj={"config_dir": cfg_dir})
    explicit = "/tmp/explicit-override.db"

    # 호출자(`approval`/`backtest` 등)는 명시적 값이 있으면 헬퍼를 건너뛴다.
    resolved = explicit or get_db_path(ctx)
    assert resolved == explicit


def test_server_runtime_and_cli_resolve_same_db_path_under_chdir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CWD를 다른 곳으로 바꾸어도 server runtime과 CLI가 같은 DB 경로를 본다.

    이 테스트는 #1158이 막아야 하는 split-brain 회귀 가드다. cold-path CLI
    (`account create/delete/set-credentials`)와 server runtime이 동일
    `config_dir` 위에서 서로 다른 DB를 보면 안 된다. server runtime은
    `Config.resolve_path("db.path", ...)` 으로, CLI는 `get_db_path(ctx)` 로
    각각 해석하지만 둘은 같은 결과여야 한다.
    """
    from ante.config import Config

    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    cfg_dir = tmp_path / "shared-instance"
    cfg_dir.mkdir()
    # 상대 경로로 기록해야 split-brain 회귀가 의미 있다 — 절대 경로면
    # CWD와 무관하므로 회귀 가드 가치가 없다.
    (cfg_dir / "system.toml").write_text('[db]\npath = "var/ante.db"\n')

    # 호출 시점 CWD를 다른 곳으로 변경 — 과거 구현은 `Path.cwd()` 기준 결합으로
    # 깨졌을 수 있다.
    other_cwd = tmp_path / "elsewhere-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)

    # CLI 경로
    ctx = click.Context(cli, obj={"config_dir": cfg_dir})
    cli_resolved = get_db_path(ctx)

    # server runtime 경로 (ante.main._init_core가 사용하는 표현식)
    server_cfg = Config.load(config_dir=cfg_dir)
    server_resolved = str(server_cfg.resolve_path("db.path", "db/ante.db"))

    assert cli_resolved == server_resolved
    assert cli_resolved == str(cfg_dir / "var" / "ante.db")


# ---------------------------------------------------------------------------
# get_data_path — Codex 13차 review Finding 1
#
# `ante update` 서브프로세스가 v002 Parquet 마이그레이션을 적용할 때
# 런타임이 보는 동일한 데이터 트리를 사용해야 한다. 헬퍼는 system.toml
# 의 ``data.path`` 키(런타임 `s.config.get("data.path", "data/")` 와 동일)
# 를 그대로 노출한다.
# ---------------------------------------------------------------------------


def test_get_data_path_default_when_no_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """system.toml 이 없거나 [data].path 설정이 없으면 `data/` 기본값."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    custom_dir = tmp_path / "no-data-path"
    custom_dir.mkdir()
    ctx = click.Context(cli, obj={"config_dir": custom_dir})
    assert get_data_path(ctx) == "data/"


def test_get_data_path_reads_system_toml(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """system.toml 에 [data].path 가 절대 경로로 설정되면 그 값을 반환."""
    monkeypatch.delenv("ANTE_CONFIG_DIR", raising=False)
    custom_dir = tmp_path / "with-data-path"
    custom_dir.mkdir()
    custom_data = tmp_path / "shared" / "ante-data"
    (custom_dir / "system.toml").write_text(
        f'[db]\npath = "/tmp/ante.db"\n\n[data]\npath = "{custom_data}"\n'
    )

    ctx = click.Context(cli, obj={"config_dir": custom_dir})
    assert get_data_path(ctx) == str(custom_data)


def test_get_data_path_env_var(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """ANTE_CONFIG_DIR 환경변수도 system.toml 위치 결정에 반영된다."""
    env_dir = tmp_path / "env-data-cfg"
    env_dir.mkdir()
    custom_data = tmp_path / "env-data"
    (env_dir / "system.toml").write_text(
        f'[db]\npath = "/tmp/ante.db"\n\n[data]\npath = "{custom_data}"\n'
    )
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_dir))

    ctx = click.Context(cli, obj={})
    assert get_data_path(ctx) == str(custom_data)


def test_get_data_path_override_beats_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`--config-dir` (ctx.obj['config_dir']) 가 ANTE_CONFIG_DIR 보다 우선."""
    env_dir = tmp_path / "env-cfg"
    env_dir.mkdir()
    (env_dir / "system.toml").write_text(
        '[db]\npath = "/tmp/env-ante.db"\n\n[data]\npath = "/should-not-be-used"\n'
    )
    monkeypatch.setenv("ANTE_CONFIG_DIR", str(env_dir))

    override_dir = tmp_path / "override-cfg"
    override_dir.mkdir()
    custom_data = tmp_path / "override-data"
    (override_dir / "system.toml").write_text(
        f'[db]\npath = "/tmp/override-ante.db"\n\n[data]\npath = "{custom_data}"\n'
    )

    ctx = click.Context(cli, obj={"config_dir": override_dir})
    assert get_data_path(ctx) == str(custom_data)
