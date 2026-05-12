"""ante report — 리포트 관리 커맨드."""

from __future__ import annotations

import asyncio
import json

import click
from pydantic import ValidationError

from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.web.schemas import ReportSubmitRequest


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
) -> None:
    """리포트 제출."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    with open(json_path) as f:
        try:
            raw_data = json.load(f)
        except json.JSONDecodeError as exc:
            fmt.error(f"Invalid JSON: {exc}", code="REPORT_VALIDATION_ERROR")
            raise SystemExit(1) from exc

    # ── #1415 codex r1 P3: non-object JSON 거부 ─────────────────────────
    # 파일이 JSON object가 아닌 array/string/number/bool/null이면 아래
    # ``report_data.pop(...)``/``report_data.get(...)`` 호출이 ``TypeError``/
    # ``AttributeError``로 raise되어 의도한 ``REPORT_VALIDATION_ERROR`` 구조화
    # 응답을 우회한다. 명시적으로 dict 검증 후 구조화된 exit 1을 반환한다.
    if not isinstance(raw_data, dict):
        fmt.error(
            f"Report file must be a JSON object, got {type(raw_data).__name__}",
            code="REPORT_VALIDATION_ERROR",
        )
        raise SystemExit(1)

    report_data: dict = dict(raw_data)

    # --run 옵션으로 백테스트 run 참조 추가
    if run_id:
        report_data["backtest_run_id"] = run_id

    # ── #1415: Web API와 동일한 ReportSubmitRequest 검증 ────────────────
    # SSOT: ``src/ante/web/schemas.py::ReportSubmitRequest``.
    #
    # CLI 입력은 Web API와 같은 invariant를 통과해야 한다:
    # - ``total_trades >= 0``, ``win_rate ∈ [0.0, 100.0]``, metric finite
    # - ``extra='forbid'`` — 미지정 키는 오타로 간주하여 거부
    #
    # CLI 전용 extras 처리:
    # - ``submitted_by``는 모델 외부 필드 (CLI에서 분리 후 StrategyReport에 주입)
    # - ``backtest_run_id``는 모델 외부 (run_id 참조용, store 컬럼 아님)
    # - ``detail_json``이 dict로 들어오면 직렬화 (모델은 str 요구)
    submitted_by = report_data.pop("submitted_by", "agent")
    report_data.pop("backtest_run_id", None)  # --run 옵션 결과는 모델 검증 대상 아님
    raw_detail = report_data.get("detail_json")
    if isinstance(raw_detail, dict):
        report_data["detail_json"] = json.dumps(raw_detail)

    try:
        validated = ReportSubmitRequest.model_validate(report_data)
    except ValidationError as exc:
        fmt.error(str(exc), code="REPORT_VALIDATION_ERROR")
        raise SystemExit(1) from exc

    async def _submit() -> dict:
        from ante.core.database import Database

        db = Database(resolved_db_path)
        await db.connect()
        try:
            # run_id가 제공되면 backtest_runs에서 참조 검증
            if run_id:
                from ante.backtest.run_store import BacktestRunStore

                run_store = BacktestRunStore(db)
                await run_store.initialize()
                bt_run = await run_store.get(run_id)
                if not bt_run:
                    msg = f"백테스트 run을 찾을 수 없습니다: {run_id}"
                    raise ValueError(msg)

            store = ReportStore(db)
            await store.initialize()

            # StrategyReport 생성 (validated 필드 기준)
            from datetime import UTC, datetime
            from uuid import uuid4

            from ante.report.models import ReportStatus, StrategyReport

            report_obj = StrategyReport(
                report_id=str(uuid4()),
                strategy_name=validated.strategy_name,
                strategy_version=validated.strategy_version,
                strategy_path=validated.strategy_path,
                status=ReportStatus.SUBMITTED,
                submitted_at=datetime.now(tz=UTC),
                submitted_by=submitted_by,
                backtest_period=validated.backtest_period,
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
                "backtest_run_id": run_id,
            }
        finally:
            await db.close()

    try:
        result = asyncio.run(_submit())
        fmt.success(f"Report submitted: {result['report_id']}", result)
    except Exception as e:
        fmt.error(str(e), code="REPORT_ERROR")
        raise SystemExit(1) from e


@report.command("list")
@click.option("--status", help="상태 필터 (pending/adopted/rejected)")
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_list(ctx: click.Context, status: str | None, db_path: str | None) -> None:
    """리포트 목록 조회."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    async def _list() -> list[dict]:
        from ante.core.database import Database
        from ante.report.models import ReportStatus

        db = Database(resolved_db_path)
        await db.connect()
        store = ReportStore(db=db)
        await store.initialize()
        report_status = ReportStatus(status) if status else None
        reports = await store.list_reports(status=report_status)
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
        from ante.cli.main import get_db_path
        from ante.core.database import Database
        from ante.trade.performance import PerformanceTracker

        db = Database(get_db_path())
        await db.connect()
        try:
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
@click.option("--db-path", default=None, help="DB 경로 (미지정 시 config_dir 기반)")
@click.pass_context
@require_auth
@require_scope("report:read")
def report_view(ctx: click.Context, report_id: str, db_path: str | None) -> None:
    """리포트 상세 조회."""
    from ante.cli.main import get_db_path
    from ante.report import ReportStore

    fmt = get_formatter(ctx)
    resolved_db_path = db_path or get_db_path(ctx)

    async def _view() -> dict | None:
        from ante.core.database import Database

        db = Database(resolved_db_path)
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
