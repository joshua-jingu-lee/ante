"""ante audit — 감사 로그 조회 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def audit() -> None:
    """감사 로그 조회."""


def _run(coro):  # noqa: ANN001, ANN202
    return asyncio.run(coro)


@audit.command("list")
@click.option("--member", "member_id", default=None, help="멤버 ID 필터")
@click.option("--action", default=None, help="액션 필터 (prefix 매칭)")
@click.option("--limit", default=20, type=click.IntRange(1, 200), help="조회 건수")
@click.option("--offset", default=0, type=int, help="오프셋")
@click.pass_context
@require_auth
@require_scope("audit:read")
def audit_list(
    ctx: click.Context,
    member_id: str | None,
    action: str | None,
    limit: int,
    offset: int,
) -> None:
    """감사 로그 목록 조회."""
    fmt = get_formatter(ctx)

    async def _run_list() -> list[dict]:
        from ante.audit import AuditLogger
        from ante.core.database import Database

        db = Database("db/ante.db")
        await db.connect()
        try:
            audit_logger = AuditLogger(db)
            await audit_logger.initialize()
            return await audit_logger.query(
                member_id=member_id,
                action=action,
                limit=limit,
                offset=offset,
            )
        finally:
            await db.close()

    result = _run(_run_list())

    if not result:
        fmt.output({"message": "감사 로그가 없습니다.", "logs": []})
        return

    if fmt.is_json:
        fmt.output({"logs": result})
    else:
        fmt.table(
            result,
            ["id", "member_id", "action", "resource", "created_at"],
        )
