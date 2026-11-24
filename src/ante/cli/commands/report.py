"""ante report — 리포트 관리 커맨드."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import click
from pydantic import ValidationError

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import CommandResult, format_option, table_lines
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.contracts.cli_errors import (
    CliOptionConflictError,
    ReportError,
    ReportInvalidStatusError,
    ReportNotFoundError,
    ReportValidationError,
)
from ante.contracts.error_registry import EXECUTION_ERROR_SPEC
from ante.contracts.helpers import error_spec_for_exception
from ante.core import clock
from ante.core.database import OperationalError, is_missing_table
from ante.report.models import ReportStatus
from ante.report.validation import ReportSubmitRequest

logger = logging.getLogger(__name__)


@click.group()
def report() -> None:
    """리포트 관리."""


@report.command()
@format_option
@click.pass_context
@require_auth
@require_scope("report:read")
def schema(ctx: click.Context) -> CommandResult:
    """리포트 제출 스키마 조회."""
    from ante.report import ReportStore

    store = ReportStore.__new__(ReportStore)
    payload = store.get_schema()
    return CommandResult(data=payload, text=(str(payload),))


@report.command()
@click.argument("json_path", type=click.Path(exists=True))
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.option("--run", "run_id", default=None, help="참조할 백테스트 run_id")
@click.pass_context
@require_auth
@require_scope("report:write")
def submit(
    ctx: click.Context,
    json_path: str,
    db_path: str | None,
    run_id: str | None,
) -> CommandResult:
    """리포트 제출."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    resolved_db_path = db_path or get_db_path(ctx)

    with open(json_path) as f:
        try:
            raw_data = json.load(f)
        except json.JSONDecodeError as exc:
            raise ReportValidationError(f"Invalid JSON: {exc}") from exc

    if not isinstance(raw_data, dict):
        raise ReportValidationError(
            f"Report file must be a JSON object, got {type(raw_data).__name__}"
        )

    report_data: dict[str, Any] = dict(raw_data)

    submitted_by = report_data.pop("submitted_by", "agent")
    raw_detail = report_data.get("detail_json")
    if isinstance(raw_detail, dict):
        report_data["detail_json"] = json.dumps(raw_detail)

    try:
        validated = ReportSubmitRequest.model_validate(report_data)
    except ValidationError as exc:
        raise ReportValidationError(
            str(exc.errors(include_context=False, include_input=False))
        ) from exc

    effective_run_id = run_id if run_id else validated.backtest_run_id

    async def _submit() -> dict[str, Any]:
        from ante.core.database import Database

        db = Database(resolved_db_path)
        await db.connect()
        try:
            if effective_run_id:
                from ante.backtest.run_store import BacktestRunStore

                run_store = BacktestRunStore(db)
                await run_store.initialize()
                bt_run = await run_store.get(effective_run_id)
                if not bt_run:
                    msg = f"백테스트 run을 찾을 수 없습니다: {effective_run_id}"
                    raise ValueError(msg)

            store = ReportStore(db)
            await store.initialize()

            from datetime import UTC
            from uuid import uuid4

            from ante.report.models import ReportStatus, StrategyReport

            report_obj = StrategyReport(
                report_id=str(uuid4()),
                strategy_name=validated.strategy_name,
                strategy_version=validated.strategy_version,
                strategy_path=validated.strategy_path,
                status=ReportStatus.SUBMITTED,
                submitted_at=clock.now(UTC),
                submitted_by=submitted_by,
                backtest_period=validated.backtest_period,
                backtest_run_id=effective_run_id,
                total_return_pct=validated.total_return_pct,
                total_trades=validated.total_trades,
                sharpe_ratio=validated.sharpe_ratio,
                max_drawdown_pct=validated.max_drawdown_pct,
                win_rate=validated.win_rate,
                summary=validated.summary,
                rationale=validated.rationale,
                risks=validated.risks,
                recommendations=validated.recommendations,
                detail_json=validated.detail_json,
            )

            report_id = await store.submit(report_obj)
            return {
                "report_id": report_id,
                "strategy": report_obj.strategy_name,
                "status": report_obj.status.value,
                "backtest_run_id": report_obj.backtest_run_id,
            }
        finally:
            await db.close()

    try:
        result = asyncio.run(_submit())
    except Exception as e:
        if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        raise ReportError(str(e)) from e

    return CommandResult(
        data=result, message=f"Report submitted: {result['report_id']}"
    )


@report.command("list")
@click.option(
    "--status",
    help="상태 필터 (draft/submitted/reviewed/adopted/rejected/archived)",
)
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_list(
    ctx: click.Context, status: str | None, db_path: str | None
) -> CommandResult:
    """리포트 목록 조회."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    resolved_db_path = db_path or get_db_path(ctx)

    if status is not None and status not in {s.value for s in ReportStatus}:
        raise ReportInvalidStatusError(
            f"잘못된 status 값: {status!r}. "
            f"허용값: {sorted(s.value for s in ReportStatus)}"
        )

    async def _list() -> list[dict[str, Any]]:
        async with open_cli_db(
            ctx, read_only=True, db_path_override=resolved_db_path
        ) as db:
            store = ReportStore(db=db)
            report_status = ReportStatus(status) if status else None
            try:
                reports = await store.list_reports(status=report_status)
            except OperationalError as exc:
                if not is_missing_table(exc):
                    raise
                logger.debug(
                    "reports 테이블 부재 — 빈 목록으로 graceful 처리", exc_info=True
                )
                return []
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
    except Exception as e:
        if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        raise ReportError(str(e)) from e

    def _lines() -> tuple[str, ...]:
        try:
            columns = ["report_id", "strategy", "status", "submitted_at"]
            return tuple(table_lines(rows, columns))
        except Exception as e:
            if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
                raise
            raise ReportError(str(e)) from e

    return CommandResult(data=rows, text=_lines)


@report.command("performance")
@click.option(
    "--period",
    type=click.Choice(["daily", "monthly"]),
    default="daily",
    help="집계 기간 (daily 또는 monthly)",
)
@click.option("--bot-id", default=None, help="봇 ID 필터")
@click.option(
    "--start",
    default=None,
    callback=validate_iso_date,
    help="시작일 (YYYY-MM-DD, daily 전용)",
)
@click.option(
    "--end",
    default=None,
    callback=validate_iso_date,
    help="종료일 (YYYY-MM-DD, daily 전용)",
)
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
) -> CommandResult:
    """기간별 성과 집계 조회."""
    from dataclasses import asdict

    fmt = get_formatter(ctx)

    if period == "monthly" and (start or end):
        raise CliOptionConflictError(
            "--start/--end 옵션은 --period monthly와 함께 사용할 수 없습니다. "
            "(daily 전용)"
        )
    if period == "daily" and year is not None:
        raise CliOptionConflictError(
            "--year 옵션은 --period daily와 함께 사용할 수 없습니다. (monthly 전용)"
        )

    if period == "monthly" and year is not None and year <= 0:
        raise ReportValidationError(
            "monthly --year는 양수 calendar year여야 합니다. (0 이하 거부)"
        )

    reject_inverted_date_range(
        start,
        end,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_performance() -> list[dict[str, Any]]:
        from ante.trade.performance import PerformanceTracker

        async with open_cli_db(ctx) as db:
            tracker = PerformanceTracker(db)
            if period == "daily":
                daily_summaries = await tracker.get_daily_summary(
                    bot_id=bot_id,
                    start_date=start,
                    end_date=end,
                )
                return [asdict(s) for s in daily_summaries]
            else:
                monthly_summaries = await tracker.get_monthly_summary(
                    bot_id=bot_id,
                    year=year,
                )
                return [asdict(s) for s in monthly_summaries]

    result = asyncio.run(_run_performance())

    if not result:
        message = "집계 데이터가 없습니다."
        empty: dict[str, Any] = {"message": message, "summaries": []}
        return CommandResult(data=empty, text=(message,))

    if period == "daily":
        columns = ["date", "realized_pnl", "trade_count", "win_rate"]
    else:
        columns = ["year", "month", "realized_pnl", "trade_count", "win_rate"]
    return CommandResult(
        data={"period": period, "summaries": result},
        text=lambda: tuple(table_lines(result, columns)),
    )


@report.command("view")
@click.argument("report_id")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_view(
    ctx: click.Context, report_id: str, db_path: str | None
) -> CommandResult:
    """리포트 상세 조회."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    resolved_db_path = db_path or get_db_path(ctx)

    async def _view() -> dict[str, Any] | None:
        async with open_cli_db(
            ctx, read_only=True, db_path_override=resolved_db_path
        ) as db:
            store = ReportStore(db)
            try:
                r = await store.get(report_id)
            except OperationalError as exc:
                if not is_missing_table(exc):
                    raise
                logger.debug(
                    "reports 테이블 부재 — 미발견(None)으로 graceful 처리",
                    exc_info=True,
                )
                return None
            if not r:
                return None
            return {
                "report_id": r.report_id,
                "strategy": f"{r.strategy_name} v{r.strategy_version}",
                "status": r.status.value,
                "submitted_at": str(r.submitted_at),
                "submitted_by": r.submitted_by,
                "backtest_period": r.backtest_period,
                "backtest_run_id": r.backtest_run_id,
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

    try:
        result = asyncio.run(_view())
    except Exception as e:
        if error_spec_for_exception(e).code != EXECUTION_ERROR_SPEC.code:
            raise
        raise ReportError(str(e)) from e

    if not result:
        raise ReportNotFoundError(f"리포트를 찾을 수 없습니다: {report_id}")

    found = result
    return CommandResult(
        data=found,
        text=lambda: tuple(
            f"  {key:20s}: {value}"
            for key, value in found.items()
            if value is not None and value != ""
        ),
    )
