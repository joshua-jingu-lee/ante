"""감사 로그 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ante.web.deps import get_audit_logger, require_master_caller
from ante.web.schemas import AuditLogListResponse

router = APIRouter()


@router.get(
    "",
    response_model=AuditLogListResponse,
    responses={
        401: {
            "description": "Authentication required",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": "Master permission required",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
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
    caller_id: Annotated[str, Depends(require_master_caller)],
    member_id: str | None = None,
    action: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """감사 로그 조회.

    인증/권한:
        oracle A7 시그니처(#1359)에서 본 라우트는 인증 없이 감사 로그 목록을
        반환하고 있었다. 감사 로그는 운영 행위 추적 정보(member_id, action,
        resource, IP 등)를 담으므로 ``require_master_caller`` (#1352에서 도입)
        를 적용해 master 권한자만 조회 가능하도록 막는다. 인증 누락은 401,
        non-master는 403. ``audit:read`` scope strict 모델은 ``Member.scopes``
        가 자유 문자열이라 별도 정의가 필요하므로 본 PR scope 외 follow-up.

    NOTE: ``limit``은 다른 list endpoint와 일관된 ``le=100``으로 검증한다.
    이전 구현은 ``min(limit, 200)``로 자동 클램프했으나, #1356에서
    pagination contract 일관성을 위해 클램프를 제거하고 Query
    validation으로 대체했다 (101..200 범위 요청은 새로 422). 다른 caller가
    이 범위를 강제하면 별도 endpoint로 분리한다.
    """
    # caller_id는 ``require_master_caller``가 ``request.state.member_id``에
    # 이미 반영하고 ``AuditMiddleware``가 자동 감사 로그 주체로 사용한다.
    # 핸들러 자체에서 audit query 필터로는 사용하지 않는다 (caller가 master
    # 인 한 전체 로그 조회 권한을 가지며, 현재는 master-only이므로 이 정책이
    # 안전하다). 변수 사용 표시를 위한 명시적 reference.
    _ = caller_id
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
