"""ante report — 리포트 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.main import get_formatter


@click.group()
def report() -> None:
    """리포트 관리."""


@report.command()
@click.pass_context
def schema(ctx: click.Context) -> None:
    """리포트 제출 스키마 조회."""
    from ante.report import ReportStore

    fmt = get_formatter(ctx)
    store = ReportStore.__new__(ReportStore)
    fmt.output(store.get_schema())


@report.command()
@click.argument("json_path", type=click.Path(exists=True))
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def submit(ctx: click.Context, json_path: str, db_path: str) -> None:
    """리포트 제출."""
    from ante.report import ReportStore

    fmt = get_formatter(ctx)

    with open(json_path) as f:
        report_data = json.load(f)

    async def _submit() -> dict:
        store = ReportStore(db_path=db_path)
        await store.initialize()
        report_obj = await store.submit(report_data)
        return {
            "report_id": report_obj.report_id,
            "strategy": report_obj.strategy_name,
            "status": report_obj.status.value,
        }

    try:
        result = asyncio.run(_submit())
        fmt.success(f"Report submitted: {result['report_id']}", result)
    except Exception as e:
        fmt.error(str(e), code="REPORT_ERROR")
        raise SystemExit(1) from e


@report.command("list")
@click.option("--status", help="상태 필터 (pending/adopted/rejected)")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
def report_list(ctx: click.Context, status: str | None, db_path: str) -> None:
    """리포트 목록 조회."""
    from ante.report import ReportStore

    fmt = get_formatter(ctx)

    async def _list() -> list[dict]:
        store = ReportStore(db_path=db_path)
        await store.initialize()
        reports = await store.list_reports(status=status)
        return [
            {
                "report_id": r.report_id,
                "strategy": r.strategy_name,
                "status": r.status.value,
                "submitted_at": str(r.submitted_at),
            }
            for r in reports
        ]

    try:
        rows = asyncio.run(_list())
        fmt.table(rows, ["report_id", "strategy", "status", "submitted_at"])
    except Exception as e:
        fmt.error(str(e), code="REPORT_ERROR")
        raise SystemExit(1) from e
