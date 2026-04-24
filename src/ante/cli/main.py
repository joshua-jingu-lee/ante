"""CLI 루트 그룹 — ante 커맨드 진입점."""

from __future__ import annotations

import click

from ante.cli.formatter import OutputFormatter
from ante.cli.middleware import authenticate_member

try:
    from importlib.metadata import version as pkg_version

    __version__ = pkg_version("ante")
except Exception:
    __version__ = "dev"


class LeafAwareGroup(click.Group):
    """root group invoke 직전에 leaf 서브커맨드 이름을 ctx.obj에 저장.

    Click 8.x의 `Group.invoke`는 root 콜백이 실행되기 직전
    `ctx.protected_args` / `ctx.args`를 비운다(core.py:1680-1682). 따라서
    root 콜백이 단독으로는 `ante member reset-password` 같은 2단계 이상
    서브커맨드의 leaf를 알 수 없다. 이 서브클래스는 `super().invoke(ctx)`
    호출 전에 subcommand 트리를 따라가며 leaf 이름을 추출해
    `ctx.obj["_leaf_command"]`에 저장한다. middleware._get_invoked_subcommand
    가 이 값을 우선적으로 사용하여 `_AUTH_EXEMPT_COMMANDS` (reset-password,
    regenerate-recovery-key)를 leaf 기준으로 매칭하도록 한다.
    """

    def invoke(self, ctx: click.Context) -> object:
        ctx.ensure_object(dict)
        all_args = [*ctx.protected_args, *ctx.args]
        leaf = self._resolve_leaf_command(ctx, all_args)
        if leaf is not None:
            ctx.obj["_leaf_command"] = leaf
        return super().invoke(ctx)

    def _resolve_leaf_command(self, ctx: click.Context, args: list[str]) -> str | None:
        """subcommand 트리를 따라가 leaf 커맨드명을 반환.

        Options(`-x`, `--flag`)는 skip하고 non-option 토큰만 커맨드 후보로
        본다. resolve_command가 알지 못하는 토큰을 만나면 현재까지의
        last known 이름을 leaf로 간주한다.
        """
        cmd: click.Command = self
        remaining = list(args)
        last: str | None = None
        while remaining and isinstance(cmd, click.MultiCommand):
            name: str | None = None
            for tok in remaining:
                if not tok.startswith("-"):
                    name = tok
                    break
            if name is None:
                return last
            sub = cmd.get_command(ctx, name)
            if sub is None:
                return last
            last = name
            remaining = remaining[remaining.index(name) + 1 :]
            cmd = sub
        return last


@click.group(cls=LeafAwareGroup)
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
    """Ante — AI-Native Trading Engine CLI."""
    ctx.ensure_object(dict)
    ctx.obj["format"] = output_format
    ctx.obj["formatter"] = OutputFormatter(output_format)
    if config_dir:
        from pathlib import Path

        ctx.obj["config_dir"] = Path(config_dir)
    authenticate_member(ctx)


def get_formatter(ctx: click.Context) -> OutputFormatter:
    """컨텍스트에서 OutputFormatter를 가져온다."""
    return ctx.obj["formatter"]


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
cli.add_command(feed)
