"""감사 로그 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ante.web.deps import get_audit_logger
from ante.web.schemas import AuditLogListResponse

router = APIRouter()


@router.get("", response_model=AuditLogListResponse)
async def list_audit_logs(
    audit_logger: Annotated[Any, Depends(get_audit_logger)],
    member_id: str | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """감사 로그 조회."""
    logs = await audit_logger.query(
        member_id=member_id,
        action=action,
        limit=limit,
        offset=offset,
    )
    total = await audit_logger.count(member_id=member_id, action=action)
    return {"logs": logs, "total": total}
