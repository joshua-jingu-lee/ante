"""CLI 루트 그룹 — ante 커맨드 진입점."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import click

from ante.cli.formatter import OutputFormatter
from ante.cli.middleware import (
    AuthenticatedGroup,
    _LeafPathMixin,
    authenticate_member,
)
from ante.config.config import Config, resolve_config_dir

__all__ = ["cli", "LeafAwareGroup", "authenticate_member"]

try:
    from importlib.metadata import version as pkg_version

    __version__ = pkg_version("ante")
except Exception:
    __version__ = "dev"


class LeafAwareGroup(_LeafPathMixin):
    """root group invoke 직전에 전체 서브커맨드 경로를 ctx.obj에 저장.

    NOTE: 본 클래스는 default-deny 인증 게이트를 부착하지 않는다.
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
    default-deny 게이트로 강제한다. root callback에서 직접
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
    return cast("OutputFormatter", ctx.obj["formatter"])


def get_config_dir(ctx: click.Context | None = None) -> Path:
    """`--config-dir`/`ANTE_CONFIG_DIR` 기반으로 설정 디렉토리 Path를 반환한다.

    `--config-dir`이 DB 경로뿐 아니라 정적 Config(`system.toml`)와 IPC
    소켓 경로 계산까지 일관되게 적용되도록 하는 단일 진입점이다.

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
    """server runtime과 동일한 resolver로 DB 경로를 반환한다."""
    cfg_dir = get_config_dir(ctx)
    cfg = Config.load(config_dir=cfg_dir)
    return str(cfg.resolve_path("db.path", "db/ante.db"))


def get_data_path(ctx: click.Context | None = None) -> str:
    """`--config-dir` 기반 system.toml 에서 ``data.path`` 를 읽어 반환한다.

    `ante update` 가 마이그레이션 서브프로세스에 같은 데이터 루트를 넘겨야
    v002 Parquet 마이그레이션이 런타임이 보는 동일한 트리에 적용된다.

    Returns:
        `data.path` 설정값(절대/상대) 문자열. 미설정이면 `"data/"`.
    """
    cfg = Config.load(config_dir=get_config_dir(ctx))
    return str(cfg.get("data.path", "data/"))


from ante.cli.commands.account import account  # noqa: E402
from ante.cli.commands.approval import approval  # noqa: E402
from ante.cli.commands.audit import audit  # noqa: E402
from ante.cli.commands.backtest import backtest  # noqa: E402
from ante.cli.commands.bot import bot  # noqa: E402
from ante.cli.commands.broker import broker  # noqa: E402
from ante.cli.commands.config import config  # noqa: E402
from ante.cli.commands.data import data  # noqa: E402
from ante.cli.commands.feed import feed  # noqa: E402
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
