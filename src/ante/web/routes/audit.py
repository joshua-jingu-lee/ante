"""감사 로그 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ante.web.deps import get_audit_logger
from ante.web.schemas import AuditLogListResponse

router = APIRouter()


@router.get(
    "",
    response_model=AuditLogListResponse,
    responses={503: {"description": "Audit logger not available"}},
)
async def list_audit_logs(
    audit_logger: Annotated[Any, Depends(get_audit_logger)],
    member_id: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """감사 로그 조회."""
    limit = min(limit, 200)
    logs = await audit_logger.query(
        member_id=member_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )
    total = await audit_logger.count(
        member_id=member_id,
        action=action,
        from_date=from_date,
        to_date=to_date,
    )
    return {"logs": logs, "total": total}
