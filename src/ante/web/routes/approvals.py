"""결재 API — 목록/상세/승인·거부."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError

from ante.approval.models import ApprovalStatus
from ante.web.deps import (
    get_approval_service,
    get_audit_logger_optional,
    get_report_store_optional,
    require_approval_admin,
    require_approval_read,
)
from ante.web.schemas import (
    ApprovalDetailResponse,
    ApprovalListResponse,
    ApprovalUpdateResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class ApprovalStatusUpdate(BaseModel):
    """승인/거부 요청.

    ``status`` 는 ``approved`` / ``rejected`` 만 허용되며, Pydantic
    ``Literal`` SSOT 로 enum 을 OpenAPI 에 노출한다 (#1434). schema 단계에서
    invalid 값이 차단되므로 handler 내 invalid status 400 분기는 reachable
    하지 않다 — Pydantic 이 422 로 사전 차단한다.
    """

    status: Literal["approved", "rejected"]
    memo: str = ""


# PATCH /api/approvals/{approval_id}/status OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다 (#1407). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema 로 두면 frontend codegen 이 ``export type
# ApprovalStatusUpdate`` 를 만들지 못해 generated client 의 requestBody 가
# ``never`` 로 노출된다 (#1429). 따라서 라우트 ``openapi_extra`` 는
# ``$ref`` 매핑만 노출하고 본체 schema 는 ``_install_openapi_customizer`` 가
# ``components.schemas`` 에 ``setdefault`` 등록한다 (``StatusUpdateRequest``
# / ``ReportSubmitRequest`` SSOT 패턴 답습).
#
# 본체 schema 는 Pydantic 모델 SSOT (``ApprovalStatusUpdate``) 의
# ``model_json_schema()`` 출력에서 파생한다. ``default=None`` 만 strip 해
# openapi-typescript 가 optional 필드를 ``?`` 마커로 노출하도록 보존한다 —
# ``required`` / ``additionalProperties`` invariants 는 모두 모델 정의 그대로
# 유지된다.
def _build_approval_status_update_request_schema() -> dict[str, Any]:
    schema = ApprovalStatusUpdate.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    return schema


APPROVAL_STATUS_UPDATE_REQUEST_SCHEMA: dict[str, Any] = (
    _build_approval_status_update_request_schema()
)


@router.get(
    "",
    response_model=ApprovalListResponse,
    responses={
        503: {
            "description": "Approval service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_approvals(
    _caller_id: Annotated[str, Depends(require_approval_read)],
    approval_service: Annotated[Any, Depends(get_approval_service)],
    status: ApprovalStatus | None = Query(default=None),
    # NOTE: ``type``은 본 PR scope 외 (frontend ApprovalType과 backend SSOT
    # 옵션 정렬이 필요하므로 follow-up). enum 강제 시 frontend 일부 호출이
    # 깨질 수 있어 ``str | None``을 유지한다 (Refs #1357 follow-up).
    type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """결재 목록 조회."""
    approvals = await approval_service.list_approvals(
        status=status, type=type, search=search, limit=limit, offset=offset
    )
    total = await approval_service.count(status=status, type=type, search=search)

    return {
        "approvals": [asdict(a) for a in approvals],
        "total": total,
    }


@router.get(
    "/{approval_id}",
    response_model=ApprovalDetailResponse,
    responses={
        404: {
            "description": "Approval not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Approval service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_approval(
    approval_id: str,
    _caller_id: Annotated[str, Depends(require_approval_read)],
    approval_service: Annotated[Any, Depends(get_approval_service)],
    report_store: Annotated[Any | None, Depends(get_report_store_optional)],
) -> dict:
    """결재 상세 조회. 인증된 master/human 또는 ``approval:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
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


@router.patch(
    "/{approval_id}/status",
    response_model=ApprovalUpdateResponse,
    responses={
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization "
                "header AND missing or invalid ante_session cookie). 대시보드 "
                "사용자는 로그인 후 ante_session 쿠키만 가지고 호출하며, "
                "에이전트 클라이언트는 Bearer 토큰만 가지고 호출한다. 둘 중 "
                "하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 approval:admin "
                "scope 보유 agent 만 허용)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Approval not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, 인증이 실패하면 body validation 은 실행되지 "
                "않고 401 이 우선 반환된다(#1407)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Approval service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ApprovalStatusUpdate"},
                },
            },
        },
    },
)
async def update_approval_status(
    approval_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_approval_admin)],
    approval_service: Annotated[Any, Depends(get_approval_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """결재 승인/거부 처리. 인증된 master/human 또는 ``approval:admin`` scope
    를 보유한 agent 만 호출 가능 (#1407 — spec ``approval:admin`` 정합).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: ApprovalStatusUpdate`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_approval_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``ApprovalStatusUpdate.model_validate`` — ValidationError → 422.
       ``status`` 는 ``Literal["approved", "rejected"]`` SSOT 이므로 invalid
       값은 schema 단계에서 422 로 차단된다 (#1434).
    4. service 호출 (``approve`` / ``reject``).
    """
    # 1. raw body 읽기 + JSON 파싱 — 인증 통과 후에만 실행된다.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422, detail="요청 body의 JSON 파싱에 실패했습니다."
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422, detail="요청 body는 JSON object여야 합니다."
        )

    # 2. Pydantic 검증.
    try:
        body = ApprovalStatusUpdate.model_validate(payload)
    except ValidationError as e:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant #1629 L1; bots.py:433
        # / accounts.py:1307 선례와 동일 sanitizer).
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_context=False, include_input=False),
        ) from None

    # ``body.status`` 는 ``Literal["approved", "rejected"]`` 로 좁혀지므로
    # Pydantic 이 사전 422 로 invalid 값을 차단한다 (#1434). 따라서
    # invalid status 400 분기는 reachable 하지 않다.
    try:
        if body.status == "approved":
            approval = await approval_service.approve(
                id=approval_id, resolved_by=caller_id
            )
        else:
            approval = await approval_service.reject(
                id=approval_id, resolved_by=caller_id, reject_reason=body.memo
            )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    action = "approval.approve" if body.status == "approved" else "approval.reject"
    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action=action,
            resource=f"approval:{approval_id}",
            detail=body.memo,
            ip=request.client.host if request.client else "",
        )

    return {"approval": asdict(approval)}
