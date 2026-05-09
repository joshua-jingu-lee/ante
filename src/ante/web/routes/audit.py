"""감사 로그 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ante.web.deps import get_audit_logger
from ante.web.schemas import AuditLogListResponse

router = APIRouter()


@router.get(
    "",
    response_model=AuditLogListResponse,
    responses={
        503: {
            "description": "Audit logger not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_audit_logs(
    audit_logger: Annotated[Any, Depends(get_audit_logger)],
    member_id: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """감사 로그 조회.

    NOTE: ``limit``은 다른 list endpoint와 일관된 ``le=100``으로 검증한다.
    이전 구현은 ``min(limit, 200)``로 자동 클램프했으나, #1356에서
    pagination contract 일관성을 위해 클램프를 제거하고 Query
    validation으로 대체했다 (101..200 범위 요청은 새로 422). 다른 caller가
    이 범위를 강제하면 별도 endpoint로 분리한다.
    """
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
