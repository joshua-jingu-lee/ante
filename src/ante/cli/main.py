"""CLI 루트 그룹 — ante 커맨드 진입점."""

from __future__ import annotations

import click

from ante.cli.formatter import OutputFormatter
from ante.cli.middleware import authenticate_member


@click.group()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="출력 형식 (text 또는 json)",
)
@click.version_option(version="0.1.0", prog_name="ante")
@click.pass_context
def cli(ctx: click.Context, output_format: str) -> None:
    """Ante — AI-Native Trading Engine CLI."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["formatter"] = OutputFormatter(output_format)
    authenticate_member(ctx)


def get_formatter(ctx: click.Context) -> OutputFormatter:
    """컨텍스트에서 OutputFormatter를 가져온다."""
    return ctx.obj["formatter"]


# 서브커맨드 등록
from ante.cli.commands.approval import approval  # noqa: E402
from ante.cli.commands.audit import audit  # noqa: E402
from ante.cli.commands.backtest import backtest  # noqa: E402
from ante.cli.commands.bot import bot  # noqa: E402
from ante.cli.commands.broker import broker  # noqa: E402
from ante.cli.commands.config import config  # noqa: E402
from ante.cli.commands.data import data  # noqa: E402
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

cli.add_command(audit)
cli.add_command(approval)
cli.add_command(bot)
cli.add_command(broker)
cli.add_command(config)
cli.add_command(strategy)
cli.add_command(data)
cli.add_command(backtest)
cli.add_command(report)
cli.add_command(instrument)
cli.add_command(member)
cli.add_command(notification)
cli.add_command(rule)
cli.add_command(signal)
cli.add_command(system)
cli.add_command(trade)
cli.add_command(treasury)
