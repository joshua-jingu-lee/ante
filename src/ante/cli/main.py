"""CLI 루트 그룹 — ante 커맨드 진입점."""

from __future__ import annotations

from pathlib import Path

import click

from ante.cli.formatter import OutputFormatter

# ``authenticate_member`` is re-exported so existing tests can monkeypatch
# ``ante.cli.main.authenticate_member`` (see ``__all__`` below for details).
from ante.cli.middleware import (
    AuthenticatedGroup,
    _LeafPathMixin,
    authenticate_member,
)
from ante.config.config import Config, resolve_config_dir

# Re-export for backwards compatibility with tests that patch this symbol on
# ``ante.cli.main`` (#1404: leaf auth wrapping is invoked by ``AuthenticatedGroup``
# in middleware.py, but the public function still lives in middleware and is
# re-exported here so existing patches keep working).
__all__ = ["cli", "LeafAwareGroup", "authenticate_member"]

try:
    from importlib.metadata import version as pkg_version

    __version__ = pkg_version("ante")
except Exception:
    __version__ = "dev"


class LeafAwareGroup(_LeafPathMixin):
    """root group invoke 직전에 전체 서브커맨드 경로를 ctx.obj에 저장.

    Click 8.x의 `Group.invoke`는 root 콜백이 실행되기 직전
    `ctx.protected_args` / `ctx.args`를 비운다(core.py:1680-1682). 따라서
    root 콜백이 단독으로는 `ante member reset-password` 같은 2단계 이상
    서브커맨드의 경로를 알 수 없다. 이 서브클래스는 `super().invoke(ctx)`
    호출 전에 subcommand 트리를 따라가며 전체 경로 tuple을 추출해
    `ctx.obj["_leaf_command_path"]`에 저장한다. middleware._get_invoked_command_path
    가 이 값을 이용해 `_AUTH_EXEMPT_COMMAND_PATHS`를 전체 경로 기준으로
    매칭한다.

    예:
    - `ante init` → ("init",)
    - `ante member list` → ("member", "list")
    - `ante member reset-password` → ("member", "reset-password")
    - `ante feed init` → ("feed", "init")  (leaf 이름이 "init"이지만 면제 아님)

    NOTE: 본 클래스는 default-deny 인증 게이트를 부착하지 않는다. #1404 이후
    root group은 :class:`ante.cli.middleware.AuthenticatedGroup`을 사용한다.
    """


@click.group(
    cls=AuthenticatedGroup,
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="출력 형식 (text 또는 json)",
)
@click.option(
    "--config-dir",
    "config_dir",
    type=click.Path(exists=False),
    default=None,
    envvar="ANTE_CONFIG_DIR",
    help="설정 디렉토리 경로 (기본: ~/.config/ante/ 또는 ./config/)",
)
@click.version_option(version=__version__, prog_name="ante")
@click.pass_context
def cli(ctx: click.Context, output_format: str, config_dir: str | None) -> None:
    """Ante — AI-Native Trading Engine CLI.

    인증은 ``AuthenticatedGroup``이 leaf 명령 callback 호출 직전에
    default-deny 게이트로 강제한다(#1404). root callback에서 직접
    ``authenticate_member(ctx)``를 호출하지 않는다.
    """
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["formatter"] = OutputFormatter(output_format)
    if config_dir:
        from pathlib import Path

        ctx.obj["config_dir"] = Path(config_dir)


def get_formatter(ctx: click.Context) -> OutputFormatter:
    """컨텍스트에서 OutputFormatter를 가져온다."""
    return ctx.obj["formatter"]


def get_config_dir(ctx: click.Context | None = None) -> Path:
    """`--config-dir`/`ANTE_CONFIG_DIR` 기반으로 설정 디렉토리 Path를 반환한다.

    우선순위는 `resolve_config_dir()`를 그대로 따른다:
      1. `ctx.obj["config_dir"]` (루트 그룹이 `--config-dir` 또는
         `ANTE_CONFIG_DIR` 환경변수로부터 확정한 Path) — override로 전달
      2. `ANTE_CONFIG_DIR` 환경변수
      3. `~/.config/ante/` (디렉토리가 실제로 존재할 때)
      4. `./config/` (repo-local 폴백)

    `--config-dir`이 DB 경로뿐 아니라 정적 Config(`system.toml`)와 IPC
    소켓 경로 계산까지 일관되게 적용되도록 하는 단일 진입점이다.

    Args:
        ctx: 선택적 Click 컨텍스트. 전달되지 않으면
            `click.get_current_context(silent=True)`로 현재 컨텍스트를 조회한다.

    Returns:
        설정 디렉토리 Path (절대 또는 상대).
    """
    if ctx is None:
        ctx = click.get_current_context(silent=True)
    obj = getattr(ctx, "obj", None) if ctx is not None else None
    override: Path | None = None
    if isinstance(obj, dict):
        raw = obj.get("config_dir")
        if raw is not None:
            override = raw if isinstance(raw, Path) else Path(raw)
    return resolve_config_dir(override=override)


def get_db_path(ctx: click.Context | None = None) -> str:
    """server runtime과 동일한 resolver로 DB 경로를 반환한다.

    Spec: docs/specs/cli/02-design-decisions.md:62-70 — `system.toml`의
    `db.path`를 우선 읽고, 미설정 시 `<config_dir>/db/ante.db` 기본값으로
    폴백한다. 절대 경로면 그대로, 상대 경로면 `config_dir` 기준으로 정규화
    한다 (`Config.resolve_path`).

    이 함수가 필요한 이유: `ante init`은 `<config_dir>/db/ante.db`를 생성하지만
    후속 CLI들이 과거 `Database("db/ante.db")` 처럼 CWD 기준으로 하드코딩하면
    server runtime과 다른 DB를 바라보는 split-brain이 발생한다. cold-path
    CLI(`account create/delete/set-credentials`)와 server runtime은 모두
    이 헬퍼/`Config.resolve_path`를 통해 동일한 DB 경로를 본다.

    Args:
        ctx: 선택적 Click 컨텍스트. 전달되지 않으면
            `click.get_current_context(silent=True)`로 현재 컨텍스트를 조회한다.

    Returns:
        절대 경로 문자열. 상대 `db.path` 입력은 `config_dir` 기준 절대 경로로
        정규화된다.
    """
    cfg_dir = get_config_dir(ctx)
    cfg = Config.load(config_dir=cfg_dir)
    return str(cfg.resolve_path("db.path", "db/ante.db"))


def get_data_path(ctx: click.Context | None = None) -> str:
    """`--config-dir` 기반 system.toml 에서 ``data.path`` 를 읽어 반환한다.

    런타임(`ante.main._init_feed`/`_init_core`의 마이그레이션 호출)이 사용하는
    `s.config.get("data.path", "data/")` 와 동일한 키·기본값을 사용한다.
    `ante update` 가 마이그레이션 서브프로세스에 같은 데이터 루트를 넘겨야
    v002 Parquet 마이그레이션이 런타임이 보는 동일한 트리에 적용된다
    (Refs #1125 Codex 13차 review Finding 1).

    Args:
        ctx: 선택적 Click 컨텍스트. 전달되지 않으면
            `click.get_current_context(silent=True)`로 현재 컨텍스트를 조회한다.

    Returns:
        `data.path` 설정값(절대/상대) 문자열. 미설정이면 `"data/"`.
    """
    cfg = Config.load(config_dir=get_config_dir(ctx))
    return str(cfg.get("data.path", "data/"))


# 서브커맨드 등록
from ante.cli.commands.account import account  # noqa: E402
from ante.cli.commands.approval import approval  # noqa: E402
from ante.cli.commands.audit import audit  # noqa: E402
from ante.cli.commands.backtest import backtest  # noqa: E402
from ante.cli.commands.bot import bot  # noqa: E402
from ante.cli.commands.broker import broker  # noqa: E402
from ante.cli.commands.config import config  # noqa: E402
from ante.cli.commands.data import data  # noqa: E402
from ante.cli.commands.init import init  # noqa: E402
from ante.cli.commands.instrument import instrument  # noqa: E402
from ante.cli.commands.member import member  # noqa: E402
from ante.cli.commands.notification import notification  # noqa: E402
from ante.cli.commands.report import report  # noqa: E402
from ante.cli.commands.rule import rule  # noqa: E402
from ante.cli.commands.signal import signal  # noqa: E402
from ante.cli.commands.strategy import strategy  # noqa: E402
from ante.cli.commands.system import system  # noqa: E402
from ante.cli.commands.trade import trade  # noqa: E402
from ante.cli.commands.treasury import treasury  # noqa: E402
from ante.cli.commands.update import update  # noqa: E402
from ante.feed.cli import feed  # noqa: E402

cli.add_command(account)  # type: ignore[has-type]
cli.add_command(audit)  # type: ignore[has-type]
cli.add_command(approval)  # type: ignore[has-type]
cli.add_command(init)  # type: ignore[has-type]
cli.add_command(bot)  # type: ignore[has-type]
cli.add_command(broker)  # type: ignore[has-type]
cli.add_command(config)  # type: ignore[has-type]
cli.add_command(strategy)  # type: ignore[has-type]
cli.add_command(data)  # type: ignore[has-type]
cli.add_command(backtest)  # type: ignore[has-type]
cli.add_command(report)  # type: ignore[has-type]
cli.add_command(instrument)  # type: ignore[has-type]
cli.add_command(member)  # type: ignore[has-type]
cli.add_command(notification)
cli.add_command(rule)  # type: ignore[has-type]
cli.add_command(signal)
cli.add_command(system)  # type: ignore[has-type]
cli.add_command(trade)  # type: ignore[has-type]
cli.add_command(treasury)  # type: ignore[has-type]
cli.add_command(update)  # type: ignore[has-type]
cli.add_command(feed)  # type: ignore[has-type]
