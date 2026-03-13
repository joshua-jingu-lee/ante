"""ante report — 리포트 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope


@click.group()
def report() -> None:
    """리포트 관리."""


@report.command()
@click.pass_context
@require_auth
@require_scope("report:read")
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
@require_auth
@require_scope("report:write")
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
@require_auth
@require_scope("report:read")
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


@report.command("performance")
@click.option(
    "--period",
    type=click.Choice(["daily", "monthly"]),
    default="daily",
    help="집계 기간 (daily 또는 monthly)",
)
@click.option("--bot-id", default=None, help="봇 ID 필터")
@click.option("--start", default=None, help="시작일 (YYYY-MM-DD, daily 전용)")
@click.option("--end", default=None, help="종료일 (YYYY-MM-DD, daily 전용)")
@click.option("--year", default=None, type=int, help="연도 필터 (monthly 전용)")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_performance(
    ctx: click.Context,
    period: str,
    bot_id: str | None,
    start: str | None,
    end: str | None,
    year: int | None,
) -> None:
    """기간별 성과 집계 조회."""
    from dataclasses import asdict

    fmt = get_formatter(ctx)

    async def _run_performance() -> list[dict]:
        from ante.core.database import Database
        from ante.trade.performance import PerformanceTracker

        db = Database("db/ante.db")
        await db.connect()
        try:
            tracker = PerformanceTracker(db)
            if period == "daily":
                summaries = await tracker.get_daily_summary(
                    bot_id=bot_id,
                    start_date=start,
                    end_date=end,
                )
            else:
                summaries = await tracker.get_monthly_summary(
                    bot_id=bot_id,
                    year=year,
                )
            return [asdict(s) for s in summaries]
        finally:
            await db.close()

    result = asyncio.run(_run_performance())

    if not result:
        fmt.output({"message": "집계 데이터가 없습니다.", "summaries": []})
        return

    if fmt.is_json:
        fmt.output({"period": period, "summaries": result})
    else:
        if period == "daily":
            fmt.table(result, ["date", "realized_pnl", "trade_count", "win_rate"])
        else:
            fmt.table(
                result, ["year", "month", "realized_pnl", "trade_count", "win_rate"]
            )


@report.command("view")
@click.argument("report_id")
@click.option("--db-path", default="db/ante.db", help="DB 경로")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_view(ctx: click.Context, report_id: str, db_path: str) -> None:
    """리포트 상세 조회."""
    from ante.report import ReportStore

    fmt = get_formatter(ctx)

    async def _view() -> dict | None:
        from ante.core.database import Database

        db = Database(db_path)
        await db.connect()
        try:
            store = ReportStore(db)
            await store.initialize()
            r = await store.get(report_id)
            if not r:
                return None
            return {
                "report_id": r.report_id,
                "strategy": f"{r.strategy_name} v{r.strategy_version}",
                "status": r.status.value,
                "submitted_at": str(r.submitted_at),
                "submitted_by": r.submitted_by,
                "backtest_period": r.backtest_period,
                "total_return_pct": r.total_return_pct,
                "total_trades": r.total_trades,
                "sharpe_ratio": r.sharpe_ratio,
                "max_drawdown_pct": r.max_drawdown_pct,
                "win_rate": r.win_rate,
                "summary": r.summary,
                "rationale": r.rationale,
                "risks": r.risks,
                "recommendations": r.recommendations,
            }
        finally:
            await db.close()

    result = asyncio.run(_view())

    if not result:
        fmt.error(f"리포트를 찾을 수 없습니다: {report_id}")
        return

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            if value is not None and value != "":
                click.echo(f"  {key:20s}: {value}")
