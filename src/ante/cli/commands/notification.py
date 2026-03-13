"""ante notification — 알림 관리 커맨드."""

from __future__ import annotations

import asyncio

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def notification() -> None:
    """알림 관리."""


@notification.command("list")
@click.option("--limit", default=50, help="조회 건수 (기본 50)")
@click.option(
    "--level",
    type=click.Choice(["critical", "error", "warning", "info"]),
    default=None,
    help="레벨 필터",
)
@click.option("--failed", is_flag=True, default=False, help="실패 건만 표시")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("notification:read")
def notification_list(
    ctx: click.Context,
    limit: int,
    level: str | None,
    failed: bool,
    db_path: str,
) -> None:
    """알림 발송 이력 조회."""
    fmt = get_formatter(ctx)

    async def _list() -> list[dict]:
        from ante.core.database import Database

        db = Database(db_path)
        await db.connect()
        try:
            query = "SELECT * FROM notification_history WHERE 1=1"
            params: list[object] = []

            if level:
                query += " AND level = ?"
                params.append(level)

            if failed:
                query += " AND success = ?"
                params.append(False)

            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)

            return await db.fetch_all(query, tuple(params))
        finally:
            await db.close()

    try:
        rows = asyncio.run(_list())
        if fmt.is_json:
            fmt.output({"notifications": rows, "count": len(rows)})
        else:
            display_rows = [
                {
                    "id": r["id"],
                    "level": r["level"],
                    "message": (
                        r["message"][:60] + "..."
                        if len(r["message"]) > 60
                        else r["message"]
                    ),
                    "success": "✓" if r["success"] else "✗",
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
            fmt.table(display_rows, ["id", "level", "message", "success", "created_at"])
    except Exception as e:
        fmt.error(str(e), code="NOTIFICATION_ERROR")
        raise SystemExit(1) from e
