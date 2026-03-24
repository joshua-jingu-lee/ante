"""리포트 관리 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ante.web.deps import get_audit_logger_optional, get_report_store
from ante.web.schemas import (
    ReportDetailResponse,
    ReportListResponse,
    ReportSchemaResponse,
    ReportSubmitResponse,
)

router = APIRouter()


@router.get("/schema", response_model=ReportSchemaResponse)
async def get_report_schema() -> dict:
    """리포트 제출 스키마 조회."""
    from ante.report import ReportStore

    store = ReportStore.__new__(ReportStore)
    return store.get_schema()


@router.post(
    "",
    status_code=201,
    response_model=ReportSubmitResponse,
    responses={503: {"description": "Report store not available"}},
)
async def submit_report(
    body: dict,
    request: Request,
    report_store: Annotated[Any, Depends(get_report_store)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """리포트 제출."""
    report = await report_store.submit(body)

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "anonymous"),
            action="report.submit",
            resource=f"report:{report.report_id}",
            detail=f"strategy={report.strategy_name}",
            ip=request.client.host if request.client else "",
        )

    return {
        "report_id": report.report_id,
        "strategy": report.strategy_name,
        "status": report.status.value,
    }


@router.get(
    "/{report_id}",
    response_model=ReportDetailResponse,
    responses={
        404: {"description": "Report not found"},
        503: {"description": "Report store not available"},
    },
)
async def report_view(
    report_id: str,
    report_store: Annotated[Any, Depends(get_report_store)],
) -> dict:
    """리포트 단건 조회."""
    import json

    report = await report_store.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")

    try:
        detail = json.loads(report.detail_json)
    except (json.JSONDecodeError, TypeError):
        detail = {}

    return {
        "report_id": report.report_id,
        "strategy_name": report.strategy_name,
        "strategy_version": report.strategy_version,
        "strategy_path": report.strategy_path,
        "status": report.status.value,
        "submitted_at": str(report.submitted_at),
        "submitted_by": report.submitted_by,
        "backtest_period": report.backtest_period,
        "total_return_pct": report.total_return_pct,
        "total_trades": report.total_trades,
        "sharpe_ratio": report.sharpe_ratio,
        "max_drawdown_pct": report.max_drawdown_pct,
        "win_rate": report.win_rate,
        "summary": report.summary,
        "rationale": report.rationale,
        "risks": report.risks,
        "recommendations": report.recommendations,
        "equity_curve": detail.get("equity_curve", []),
        "metrics": detail.get("metrics", {}),
        "initial_balance": detail.get("initial_balance"),
        "final_balance": detail.get("final_balance"),
        "config": detail.get("config"),
        "datasets": detail.get("datasets", []),
        "symbols": detail.get("symbols", []),
        "user_notes": report.user_notes,
        "reviewed_at": str(report.reviewed_at) if report.reviewed_at else None,
    }


@router.get(
    "",
    response_model=ReportListResponse,
    responses={503: {"description": "Report store not available"}},
)
async def list_reports(
    report_store: Annotated[Any, Depends(get_report_store)],
    status: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """리포트 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    reports = await report_store.list_reports(status=status)
    items = [
        {
            "report_id": r.report_id,
            "strategy": r.strategy_name,
            "status": r.status.value,
            "submitted_at": str(r.submitted_at),
        }
        for r in reports
    ]

    result = paginate(items, cursor_field="report_id", limit=limit, cursor=cursor)
    return {"reports": result["items"], "next_cursor": result["next_cursor"]}
