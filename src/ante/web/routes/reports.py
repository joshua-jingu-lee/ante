"""리포트 관리 API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

router = APIRouter()


@router.get("/schema")
async def get_report_schema() -> dict:
    """리포트 제출 스키마 조회."""
    from ante.report import ReportStore

    store = ReportStore.__new__(ReportStore)
    return store.get_schema()


@router.post("", status_code=201)
async def submit_report(request: Request, body: dict) -> dict:
    """리포트 제출."""
    report_store = getattr(request.app.state, "report_store", None)
    if report_store is None:
        raise HTTPException(status_code=503, detail="Report store not available")

    report = await report_store.submit(body)
    return {
        "report_id": report.report_id,
        "strategy": report.strategy_name,
        "status": report.status.value,
    }


@router.get("")
async def list_reports(
    request: Request,
    status: str | None = None,
    limit: int = 20,
) -> dict:
    """리포트 목록 조회."""
    report_store = getattr(request.app.state, "report_store", None)
    if report_store is None:
        raise HTTPException(status_code=503, detail="Report store not available")

    reports = await report_store.list_reports(status=status)
    return {
        "reports": [
            {
                "report_id": r.report_id,
                "strategy": r.strategy_name,
                "status": r.status.value,
                "submitted_at": str(r.submitted_at),
            }
            for r in reports[:limit]
        ]
    }
