"""결재 API — 목록/상세/승인·거부."""

from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter()


class ApprovalStatusUpdate(BaseModel):
    """승인/거부 요청."""

    status: str  # "approved" | "rejected"
    memo: str = ""


@router.get("")
async def list_approvals(
    request: Request,
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """결재 목록 조회."""
    approval_service = request.app.state.approval_service

    approvals = await approval_service.list(
        status=status, type=type, limit=limit, offset=offset
    )

    return {
        "approvals": [asdict(a) for a in approvals],
        "total": len(approvals),
    }


@router.get("/{approval_id}")
async def get_approval(request: Request, approval_id: str) -> dict:
    """결재 상세 조회."""
    approval_service = request.app.state.approval_service

    approval = await approval_service.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="결재 요청을 찾을 수 없습니다")

    result: dict = {"approval": asdict(approval)}

    # 전략 리포트 유형이면 report_detail 포함
    if approval.reference_id and hasattr(request.app.state, "report_store"):
        report_store = request.app.state.report_store
        report = await report_store.get(approval.reference_id)
        if report:
            result["report_detail"] = (
                asdict(report) if hasattr(report, "__dataclass_fields__") else report
            )

    return result


@router.patch("/{approval_id}/status")
async def update_approval_status(
    request: Request,
    approval_id: str,
    body: ApprovalStatusUpdate,
) -> dict:
    """결재 승인/거부 처리."""
    approval_service = request.app.state.approval_service

    try:
        if body.status == "approved":
            approval = await approval_service.approve(
                id=approval_id, resolved_by="user"
            )
        elif body.status == "rejected":
            approval = await approval_service.reject(
                id=approval_id, resolved_by="user", reject_reason=body.memo
            )
        else:
            raise HTTPException(
                status_code=400,
                detail="status는 'approved' 또는 'rejected'만 허용됩니다",
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"approval": asdict(approval)}
