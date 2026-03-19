"""결재 API — 목록/상세/승인·거부."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ante.web.deps import get_approval_service, get_report_store_optional
from ante.web.schemas import (
    ApprovalDetailResponse,
    ApprovalListResponse,
    ApprovalUpdateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ApprovalStatusUpdate(BaseModel):
    """승인/거부 요청."""

    status: str  # "approved" | "rejected"
    memo: str = ""


@router.get("", response_model=ApprovalListResponse)
async def list_approvals(
    approval_service: Annotated[Any, Depends(get_approval_service)],
    status: str | None = Query(default=None),
    type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """결재 목록 조회."""
    approvals = await approval_service.list(
        status=status, type=type, limit=limit, offset=offset
    )

    return {
        "approvals": [asdict(a) for a in approvals],
        "total": len(approvals),
    }


@router.get("/{approval_id}", response_model=ApprovalDetailResponse)
async def get_approval(
    approval_id: str,
    approval_service: Annotated[Any, Depends(get_approval_service)],
    report_store: Annotated[Any | None, Depends(get_report_store_optional)],
) -> dict:
    """결재 상세 조회."""
    approval = await approval_service.get(approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="결재 요청을 찾을 수 없습니다")

    result: dict = {"approval": asdict(approval)}

    # 전략 리포트 유형이면 report_detail 포함
    if approval.reference_id and report_store is not None:
        report = await report_store.get(approval.reference_id)
        if report:
            result["report_detail"] = (
                asdict(report) if hasattr(report, "__dataclass_fields__") else report
            )

    return result


@router.patch("/{approval_id}/status", response_model=ApprovalUpdateResponse)
async def update_approval_status(
    approval_id: str,
    body: ApprovalStatusUpdate,
    approval_service: Annotated[Any, Depends(get_approval_service)],
) -> dict:
    """결재 승인/거부 처리."""
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
