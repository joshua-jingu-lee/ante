"""감사 로그 API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from ante.web.schemas import AuditLogListResponse

router = APIRouter()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    request: Request,
    member_id: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """감사 로그 조회."""
    audit_logger = getattr(request.app.state, "audit_logger", None)
    if audit_logger is None:
        raise HTTPException(status_code=503, detail="Audit logger not available")

    logs = await audit_logger.query(
        member_id=member_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    total = await audit_logger.count(member_id=member_id, action=action)
    return {"logs": logs, "total": total}
