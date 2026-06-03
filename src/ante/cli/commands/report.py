"""ante report — 리포트 관리 커맨드."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3

import click
from pydantic import ValidationError

from ante.cli._validators import reject_inverted_date_range, validate_iso_date
from ante.cli.db_context import open_cli_db
from ante.cli.formatter import format_option
from ante.cli.main import get_formatter
from ante.cli.middleware import require_auth, require_scope
from ante.report.models import ReportStatus
from ante.report.validation import ReportSubmitRequest

# `ReportStatus` enum이 `--status` 필터의 SSOT다. `report list`는 DB 진입 전
# preflight에서 invalid 값을 차단해야 하며, 이를 위해 함수 내부 import 대신
# 모듈 상단 import을 사용한다. `ante.report.models`는 dataclass + StrEnum
# + math 만 노출하는 light 모듈이라 `tests/unit/test_cli_dependency_isolation.py`
# 가 회귀를 차단한다.

logger = logging.getLogger(__name__)


@click.group()
def report() -> None:
    """리포트 관리."""


@report.command()
@format_option
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

    # ── non-object JSON 거부 ────────────────────────────────────────────
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

    # ── ReportSubmitRequest 검증 ───────────────────────────────────────
    # SSOT: ``src/ante/report/validation.py::ReportSubmitRequest``.
    #
    # CLI 입력은 제출 스키마 invariant를 통과해야 한다:
    # - ``total_trades >= 0``, ``win_rate ∈ [0.0, 100.0]``, metric finite
    # - ``extra='forbid'`` — 미지정 키는 오타로 간주하여 거부
    #
    # CLI 전용 extras 처리:
    # - ``submitted_by``는 모델 외부 필드 (CLI에서 분리 후 StrategyReport에 주입)
    # - ``detail_json``이 dict로 들어오면 직렬화 (모델은 str 요구)
    #
    # ``backtest_run_id`` (#1999): payload 또는 CLI ``--run`` 으로 줄 수 있다.
    # ``ReportSubmitRequest`` 의 명시 필드이므로 ``extra='forbid'`` 검증을
    # 통과하며, 검증 후 ``effective_run_id`` 로 존재검증 + 영속한다 (아래 _submit).
    submitted_by = report_data.pop("submitted_by", "agent")
    raw_detail = report_data.get("detail_json")
    if isinstance(raw_detail, dict):
        report_data["detail_json"] = json.dumps(raw_detail)

    try:
        validated = ReportSubmitRequest.model_validate(report_data)
    except ValidationError as exc:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant — reports.py web sweep
        # 와 동일 sanitizer). sections 미지원 필드는 ValidationError
        # (extra_forbidden) 경로로 들어오므로 ``str(exc)`` 의
        # ``input_value={...}`` (제출한 sections rationale/evidence) 가
        # 터미널/CI 로그에 반사되지 않도록 loc/type/msg 만 출력한다.
        fmt.error(
            str(exc.errors(include_context=False, include_input=False)),
            code="REPORT_VALIDATION_ERROR",
        )
        raise SystemExit(1) from exc

    # effective run_id (#1999): CLI ``--run`` 우선, 없으면 payload
    # ``backtest_run_id``. ``--run`` 과 payload 가 둘 다 비어있지 않으면 ``--run``
    # 이 silent override 한다 (테스트로 고정). 빈 문자열은 "참조 없음".
    effective_run_id = run_id if run_id else validated.backtest_run_id

    async def _submit() -> dict:
        from ante.core.database import Database

        db = Database(resolved_db_path)
        await db.connect()
        try:
            # effective_run_id 가 제공되면 (CLI --run 이든 payload 이든) backtest_runs
            # 에서 존재 검증한다. payload 직접 주입도 검증 경로를 동일하게 거쳐
            # 미존재 run 참조가 영속되는 우회를 차단한다 (#1999).
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
        fmt.success(f"Report submitted: {result['report_id']}", result)
    except Exception as e:
        fmt.error(str(e), code="REPORT_ERROR")
        raise SystemExit(1) from e


@report.command("list")
@click.option(
    "--status",
    help="상태 필터 (draft/submitted/reviewed/adopted/rejected/archived)",
)
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

    # Preflight: invalid `--status`는 `Database` 생성 전에 차단한다.
    # `ReportStatus` enum이 SSOT이며 inline 비교한다.
    # strategy.py 패턴과 동형이다.
    if status is not None and status not in {s.value for s in ReportStatus}:
        fmt.error(
            f"잘못된 status 값: {status!r}. "
            f"허용값: {sorted(s.value for s in ReportStatus)}",
            code="REPORT_INVALID_STATUS",
        )
        raise SystemExit(1)

    async def _list() -> list[dict]:
        # ``report list`` 는 offline read 명령이므로 read-only DB 아티팩트
        # (0444 파일 / 0555 부모 디렉터리 — 실제 read-only mount) 도 열 수 있어야
        # 한다. 기존 ``Database(resolved_db_path)`` (writer + WAL PRAGMA) +
        # ``ReportStore.initialize()`` (CREATE TABLE reports DDL) 는 read-only fs
        # 에서 ``attempt to write a readonly database`` 로 실패했다. backtest
        # history (#1974) / data list (#1984) 동형으로 ``open_cli_db(
        # read_only=True)`` (mode=ro + immutable fallback, WAL/DDL 미발화) 를
        # 사용하고 ``initialize()`` 를 호출하지 않는다.
        #
        # ``ReportStore.list_reports`` 는 캐시 없이 rows 를 직접 SELECT 하므로
        # initialize 의 schema 부트스트랩이 read 에 필요하지 않다(#1984
        # InstrumentService 캐시 워밍과 달리 캐시 워밍도 불요). 단, ``reports``
        # 테이블이 부재한(아직 한 번도 부트스트랩되지 않은) DB 에서는 SELECT 가
        # ``sqlite3.OperationalError: no such table: reports`` 로 실패하므로,
        # 그 메시지에 한해 빈 목록으로 graceful 처리한다. 다른
        # ``OperationalError`` (locked / disk I/O / malformed 등) 는 삼키지 않고
        # 재전파해 호출 경계에서 ``REPORT_ERROR`` 로 변환되도록 한다.
        async with open_cli_db(
            ctx, read_only=True, db_path_override=resolved_db_path
        ) as db:
            store = ReportStore(db=db)
            report_status = ReportStatus(status) if status else None
            try:
                reports = await store.list_reports(status=report_status)
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
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
) -> None:
    """기간별 성과 집계 조회."""
    from dataclasses import asdict

    fmt = get_formatter(ctx)

    # period별 옵션 배타 검증: DB 연결/_run_performance/asyncio.run 이전에
    # 차단한다 (treasury.py:205-211 동형 패턴). PerformanceTracker는
    # daily/monthly 메서드가 분리되어 있어 silent-ignore API가 없으므로
    # (report.py:276-288에서 daily는 start/end만, monthly는 year만 라우팅)
    # CLI 진입 검증이 실행 경로상 완전한 fix다. `--period` 기본값이 daily
    # 이므로 `--period` 생략 + `--year` 조합도 여기서 거부된다.
    if period == "monthly" and (start or end):
        fmt.error(
            "--start/--end 옵션은 --period monthly와 함께 사용할 수 없습니다. "
            "(daily 전용)",
            code="CLI_OPTION_CONFLICT",
        )
        raise SystemExit(1)
    if period == "daily" and year is not None:
        fmt.error(
            "--year 옵션은 --period daily와 함께 사용할 수 없습니다. (monthly 전용)",
            code="CLI_OPTION_CONFLICT",
        )
        raise SystemExit(1)

    # monthly --year 비양수 거부: period-exclusive 블록 직후,
    # _run_performance/asyncio.run 이전에 차단한다. 캘린더 연도는 양수(>0)만
    # 유효하므로 0/음수는 거부한다. daily+year는 위 period-exclusive
    # CLI_OPTION_CONFLICT가 먼저 잡으므로(이 블록은 그 after 배치) 여기 도달
    # 하는 year는 monthly 경로뿐이며 daily+year<=0도 CLI_OPTION_CONFLICT다.
    # 에러코드는 report 도메인의 기존 REPORT_VALIDATION_ERROR를 재사용한다
    # (report submit 검증과 동일 코드). 상한/미래연도 검증은 범위 밖(>0만 검증).
    if period == "monthly" and year is not None and year <= 0:
        fmt.error(
            "monthly --year는 양수 calendar year여야 합니다. (0 이하 거부)",
            code="REPORT_VALIDATION_ERROR",
        )
        raise SystemExit(1)

    # inverted date range(시작일 > 종료일) 거부: period-exclusive 블록 직후,
    # _run_performance/asyncio.run 이전에 차단한다 (backtest.py 동형,
    # INVALID_DATE_RANGE + exit 1). period-exclusive 게이트가 monthly+start/end
    # 는 이미 CLI_OPTION_CONFLICT로 거부했으므로 여기 도달하는 start/end 조합은
    # daily 경로뿐이다. 순서/코드는 보존(이 블록은 after 배치).
    reject_inverted_date_range(
        start,
        end,
        fmt,
        from_label="시작일",
        to_label="종료일",
    )

    async def _run_performance() -> list[dict]:
        # ``open_cli_db`` 헬퍼 lifecycle (cleanup invariant — 예외/cancellation
        # 시에도 ``Database.close()`` 1회 보장).
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
        # ``report view`` 도 offline read 명령이므로 read-only DB 아티팩트를
        # 열 수 있어야 한다. ``report list`` 와 동형으로 ``open_cli_db(
        # read_only=True)`` (mode=ro + immutable fallback, WAL/DDL 미발화) +
        # ``initialize()`` 미호출. ``ReportStore.get`` 도 캐시 없이 단일 row 를
        # SELECT 하므로 schema 부트스트랩이 read 에 필요하지 않다(backtest
        # history #1974 / data list #1984 동형).
        #
        # ``reports`` 테이블이 부재한 DB 에서는 ``get`` 의 SELECT 가
        # ``sqlite3.OperationalError: no such table: reports`` 로 실패하므로 그
        # 메시지에 한해 ``None`` (미발견) 으로 graceful 처리한다 → 호출 경계에서
        # ``REPORT_NOT_FOUND`` envelope 로 종료된다. 다른 ``OperationalError`` 는
        # 재전파해 ``REPORT_ERROR`` 로 변환되도록 한다(삼키지 않음).
        async with open_cli_db(
            ctx, read_only=True, db_path_override=resolved_db_path
        ) as db:
            store = ReportStore(db)
            try:
                r = await store.get(report_id)
            except sqlite3.OperationalError as exc:
                if "no such table" not in str(exc).lower():
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

    # DB 연결/조회 실패 시 traceback 노출 대신 구조화된 에러 envelope 로
    # 변환한다 (``report_list`` L255-260 와 동형). ``_view()`` 내부 try/finally
    # 는 ``db.close()`` 만 보장할 뿐 예외를 삼키지 않으므로, 호출 경계에서
    # ``REPORT_ERROR`` 로 정규화해 ``exit 1`` 로 종료한다. ``REPORT_NOT_FOUND``
    # (result None) 와 정상 출력은 DB 에러와 구분되는 별도 경로이므로
    # ``except`` 밖에 그대로 둔다.
    try:
        result = asyncio.run(_view())
    except Exception as e:
        fmt.error(str(e), code="REPORT_ERROR")
        raise SystemExit(1) from e

    if not result:
        fmt.error(f"리포트를 찾을 수 없습니다: {report_id}", code="REPORT_NOT_FOUND")
        raise SystemExit(1)

    if fmt.is_json:
        fmt.output(result)
    else:
        for key, value in result.items():
            if value is not None and value != "":
                click.echo(f"  {key:20s}: {value}")
