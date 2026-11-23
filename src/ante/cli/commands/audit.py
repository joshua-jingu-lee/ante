"""ante audit — 감사 로그 조회 커맨드."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine
from typing import Any

import click

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def audit() -> None:
    """감사 로그 조회."""


def _run(coro: Coroutine[Any, Any, Any]) -> Any:
    return asyncio.run(coro)


@audit.command("list")
@click.option("--member", "member_id", default=None, help="멤버 ID 필터")
@click.option("--action", default=None, help="액션 필터 (prefix 매칭)")
@click.option(
    "--from-date",
    default=None,
    callback=validate_iso_date,
    help="시작 날짜 (YYYY-MM-DD)",
)
@click.option(
    "--to-date",
    default=None,
    callback=validate_iso_date,
    help="종료 날짜 (YYYY-MM-DD)",
)
@click.option("--limit", default=20, type=click.IntRange(1, 200), help="조회 건수")
@click.option("--offset", default=0, type=click.IntRange(min=0), help="오프셋")
@click.pass_context
@require_auth
@require_scope("audit:read")
def audit_list(
    ctx: click.Context,
    member_id: str | None,
    action: str | None,
    from_date: str | None,
    to_date: str | None,
    limit: int,
    offset: int,
) -> CommandResult:
    """감사 로그 목록 조회."""
    fmt = get_formatter(ctx)

    reject_inverted_date_range(
        from_date,
        to_date,
        fmt,
        from_label="시작 날짜",
        to_label="종료 날짜",
    )

    async def _run_list() -> list[dict[str, Any]]:
        from ante.audit import AuditLogger

        async with open_cli_db(ctx) as db:
            audit_logger = AuditLogger(db)
            await audit_logger.initialize()
            return await audit_logger.query(
                member_id=member_id,
                action=action,
                from_date=from_date,
                to_date=to_date,
                limit=limit,
                offset=offset,
            )

    result = _run(_run_list())

    if not result:
        empty: dict[str, Any] = {"message": "감사 로그가 없습니다.", "logs": []}
        return CommandResult(data=empty, text=(str(empty),))

    columns = ["id", "member_id", "action", "resource", "created_at"]
    return CommandResult(
        data={"logs": result}, text=lambda: tuple(table_lines(result, columns))
    )
