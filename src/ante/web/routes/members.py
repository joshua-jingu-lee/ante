"""멤버 관리 API."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError

from ante.member.errors import PermissionDeniedError
from ante.web.deps import (
    get_audit_logger_optional,
    get_member_service,
    get_session_service_optional,
)
from ante.web.schemas import (
    MemberCreateResponse,
    MemberDetailResponse,
    MemberListResponse,
    MemberScopesResponse,
    MemberTokenResponse,
    OkResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _caller_id(request: Request) -> str:
    """인증 미들웨어가 설정한 member_id를 반환. 미설정 시 빈 문자열."""
    return getattr(request.state, "member_id", "")


_AUTH_REQUIRED_DETAIL = (
    "인증이 필요합니다. Authorization: Bearer <token> 헤더 또는 "
    "유효한 ante_session 쿠키가 필요합니다."
)

_AUTH_REQUIRED_RESPONSE_DESCRIPTION = (
    "Authentication required (missing or invalid Authorization header "
    "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
    "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
    "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
)


async def _resolve_caller_or_401(
    request: Request,
    session_service: Any | None,
) -> str:
    """5개 mutation route의 공통 인증 가드 (issue #1351).

    1) ``TokenAuthMiddleware``가 채운 ``request.state.member_id``를 우선 사용.
    2) Bearer 결정에 실패하면 ``ante_session`` 쿠키 fallback. 단,
       ``session_service is None`` 배포 분기에서는 fallback을 건너뛴다(빈
       caller 유지 → 401).
    3) caller가 비어 있으면 ``HTTPException(401)``을 raise한다.
    4) 세션 쿠키 fallback에서 caller가 결정되면 ``request.state.member_id``를
       갱신해 ``AuditMiddleware``의 자동 감사 로그 주체와 일관성을 유지한다.

    ``create_member``의 인증 가드 패턴과 동일한 톤이다(#1339 SSOT).
    """
    caller = _caller_id(request)
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                caller = session.get("member_id", "") or ""
                if caller:
                    request.state.member_id = caller
    if not caller:
        raise HTTPException(status_code=401, detail=_AUTH_REQUIRED_DETAIL)
    return caller


_AUTH_REQUIRED_RESPONSE: dict[str, Any] = {
    "description": _AUTH_REQUIRED_RESPONSE_DESCRIPTION,
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
        },
    },
}


class MemberCreateRequest(BaseModel):
    """멤버 등록 요청."""

    model_config = ConfigDict(extra="forbid")

    member_id: str
    member_type: str  # "human" | "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    scopes: list[str] = []


# POST /api/members OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작하지만(이슈 #1339 P2 — Codex finding), Swagger UI / agent client / SDK는
# 정확한 입력 contract를 발견할 수 있어야 한다.
#
# ``MemberCreateRequest.model_json_schema()`` 직접 노출은 가능하지만 본 dict 상수로
# manual schema를 두는 편이 OpenAPI 표면 안정성과 spec 정합성 측면에서 더 안전하다.
MEMBER_CREATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "MemberCreateRequest",
    "description": (
        "POST /api/members 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1339). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    ),
    "additionalProperties": False,
    "required": ["member_id", "member_type"],
    "properties": {
        "member_id": {
            "type": "string",
            "description": "고유 식별자.",
        },
        "member_type": {
            "type": "string",
            "enum": ["human", "agent"],
            "description": "멤버 타입.",
        },
        "role": {
            "type": "string",
            "default": "default",
            "description": "역할 (default / master).",
        },
        "org": {
            "type": "string",
            "default": "default",
            "description": "소속 조직.",
        },
        "name": {
            "type": "string",
            "default": "",
            "description": "사용자에게 표시되는 이름.",
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": "권한 범위 목록.",
        },
    },
}


class PasswordChangeRequest(BaseModel):
    """비밀번호 변경 요청."""

    old_password: str
    new_password: str


class ScopesUpdateRequest(BaseModel):
    """권한 범위 변경 요청."""

    scopes: list[str]


@router.get(
    "",
    response_model=MemberListResponse,
    responses={
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_members(
    svc: Annotated[Any, Depends(get_member_service)],
    type: str | None = Query(default=None),
    org: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """멤버 목록 조회."""
    try:
        members = await svc.list_members(
            member_type=type, org=org, status=status, limit=limit, offset=offset
        )
        total = await svc.count(member_type=type, org=org, status=status)
    except Exception:
        logger.exception(
            "멤버 목록 조회 실패 (type=%s, org=%s, status=%s, limit=%d, offset=%d)",
            type,
            org,
            status,
            limit,
            offset,
        )
        raise HTTPException(
            status_code=503, detail="멤버 목록을 조회할 수 없습니다"
        ) from None
    return {"members": [asdict(m) for m in members], "total": total}


@router.post(
    "",
    status_code=201,
    response_model=MemberCreateResponse,
    responses={
        400: {
            "description": "Invalid member data",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization header "
                "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
                "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
                "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, Authorization 헤더와 ante_session 쿠키 모두 "
                "유효하지 않으면 body validation은 실행되지 않고 401이 우선 "
                "반환된다(#1339 P2 / P1 cookie auth)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        # ``$ref`` 매핑을 사용해 ``components.schemas.MemberCreateRequest``를
        # 외부 노출한다(이슈 #1339 P1 — Codex finding). inline schema로 두면
        # FastAPI 자동 components 등록 경로를 거치지 않아 frontend codegen이
        # ``MemberCreateRequest`` 타입을 export하지 않는다. 실제 schema 본체는
        # ``_install_openapi_customizer``가 ``MEMBER_CREATE_REQUEST_SCHEMA``로
        # ``components.schemas``에 등록한다(``app.py``).
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MemberCreateRequest"},
                },
            },
        },
    },
)
async def create_member(
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 등록. 토큰 1회 반환.

    인증 가드는 body validation보다 **반드시 먼저** 실행된다(#1339 P2 — Codex
    finding). FastAPI가 ``body: MemberCreateRequest`` 파라미터를 먼저 파싱하면
    Authorization 헤더 미존재 + 필수 필드 누락 케이스에서 401이 아니라 422가
    먼저 응답되어 "missing or invalid Authorization header는 401" 계약이 깨진다.
    이 이유로 본 라우트는 ``request: Request``만 받고 raw body를 직접 파싱한다
    (``update_account`` SSOT 패턴 일치).

    인증 경로는 두 가지를 모두 받는다(#1339 P1 — Codex finding):
    - **Bearer 토큰**: ``TokenAuthMiddleware``가 ``request.state.member_id``를
      세팅한다. 에이전트 클라이언트(`MCP`, CLI 등)와 ``frontend`` axios의
      ``Authorization`` 헤더 호출이 이 경로를 탄다.
    - **세션 쿠키**: 대시보드는 패스워드 로그인 후 ``ante_session`` HttpOnly
      쿠키만 가진 상태로 axios에 ``Authorization`` 헤더를 추가하지 않는다.
      ``session_service.validate``로 세션 → ``member_id``를 복원한다.

    핸들러 단계 순서:
    1. **인증 가드 (최우선)**: token 또는 세션 쿠키 어느 쪽도 caller를 결정
       하지 못하면 401.
    2. raw bytes 읽고 JSON 파싱 — 실패 시 422.
    3. ``MemberCreateRequest.model_validate`` — ValidationError → 422.
    4. ``svc.register`` 호출. ``PermissionError`` → 403, ``ValueError`` → 400.
    """
    # 1. 인증 가드 (body validation보다 우선).
    #    1-a) Bearer 토큰 (TokenAuthMiddleware가 request.state.member_id 세팅).
    caller = _caller_id(request)
    #    1-b) ante_session 쿠키 fallback (#1339 P1 — 대시보드 axios 호환).
    if not caller and session_service is not None:
        ante_session = request.cookies.get("ante_session")
        if ante_session:
            try:
                session = await session_service.validate(ante_session)
            except Exception:
                # session_service 실패는 인증 실패로 간주한다 (logged + 401).
                logger.exception(
                    "세션 검증 실패 (session_id 일부=%s...)", ante_session[:8]
                )
                session = None
            if session:
                caller = session.get("member_id", "") or ""
                if caller:
                    # AuditMiddleware가 자동 감사 로그에 주체를 남길 수 있도록
                    # request.state에도 반영한다 (#1339 P2 — Codex finding).
                    request.state.member_id = caller
    if not caller:
        raise HTTPException(
            status_code=401,
            detail=(
                "인증이 필요합니다. Authorization: Bearer <token> 헤더 또는 "
                "유효한 ante_session 쿠키가 필요합니다."
            ),
        )

    # 2. raw body 읽기 + JSON 파싱.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(
            status_code=422,
            detail="요청 body가 비어 있습니다.",
        )
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422,
            detail="요청 body의 JSON 파싱에 실패했습니다.",
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail="요청 body는 JSON object여야 합니다.",
        )

    # 3. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = MemberCreateRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    # 4. service 호출.
    try:
        member, token = await svc.register(
            member_id=body.member_id,
            member_type=body.member_type,
            role=body.role,
            org=body.org,
            name=body.name,
            scopes=body.scopes,
            registered_by=caller,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.create",
            resource=f"member:{body.member_id}",
            detail=f"type={body.member_type}, role={body.role}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member), "token": token}


@router.get(
    "/{member_id}",
    response_model=MemberDetailResponse,
    responses={
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_member(
    member_id: str,
    svc: Annotated[Any, Depends(get_member_service)],
) -> dict:
    """멤버 상세 조회."""
    try:
        member = await svc.get(member_id)
    except Exception:
        logger.exception("멤버 상세 조회 실패 (member_id=%s)", member_id)
        raise HTTPException(
            status_code=503, detail="멤버 정보를 조회할 수 없습니다"
        ) from None
    if member is None:
        raise HTTPException(status_code=404, detail="멤버를 찾을 수 없습니다")
    return {"member": asdict(member)}


@router.post(
    "/{member_id}/suspend",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def suspend_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 일시 정지. 인증된 master만 호출 가능 (#1351)."""
    caller = await _resolve_caller_or_401(request, session_service)
    try:
        member = await svc.suspend(member_id, suspended_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.suspend",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member)}


@router.post(
    "/{member_id}/reactivate",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def reactivate_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 재활성화. 인증된 master만 호출 가능 (#1351)."""
    caller = await _resolve_caller_or_401(request, session_service)
    try:
        member = await svc.reactivate(member_id, reactivated_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.reactivate",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member)}


@router.post(
    "/{member_id}/revoke",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def revoke_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 영구 폐기. 인증된 master만 호출 가능 (#1351)."""
    caller = await _resolve_caller_or_401(request, session_service)
    try:
        member = await svc.revoke(member_id, revoked_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.revoke",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member)}


@router.post(
    "/{member_id}/rotate-token",
    response_model=MemberTokenResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def rotate_token(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """토큰 재발급. 인증된 master만 호출 가능 (#1351).

    인증 없이 token rotation 응답에 접근하면 token 값 자체가 노출되므로,
    가장 먼저 차단해야 한다.
    """
    caller = await _resolve_caller_or_401(request, session_service)
    try:
        member, token = await svc.rotate_token(member_id, rotated_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.rotate_token",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member), "token": token}


@router.patch(
    "/{member_id}/password",
    response_model=OkResponse,
    responses={
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def change_password(
    member_id: str,
    body: PasswordChangeRequest,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """비밀번호 변경 (human 멤버 전용)."""
    caller = _caller_id(request)
    try:
        await svc.change_password(member_id, body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or member_id,
            action="member.change_password",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"ok": True}


@router.put(
    "/{member_id}/scopes",
    response_model=MemberScopesResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, 인증이 실패하면 body validation은 실행되지 "
                "않고 401이 우선 반환된다(#1351)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def update_scopes(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any | None, Depends(get_session_service_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """권한 범위 변경. 인증된 master만 호출 가능 (#1351).

    ``create_member``와 동일한 raw body 파싱 패턴을 적용해 인증 가드가 body
    validation보다 우선 실행되도록 한다(#1351 — Codex Plan Review). FastAPI가
    ``body: ScopesUpdateRequest``를 먼저 검증하면 unauth + bad-body 시 401이
    아닌 422가 먼저 반환되어 contract가 깨진다.

    핸들러 단계 순서:
    1. 인증 가드 (최우선) — 실패 시 401.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``ScopesUpdateRequest.model_validate`` — ValidationError → 422.
    4. ``svc.update_scopes`` 호출. ``ValueError`` → 404,
       ``PermissionError``/``PermissionDeniedError`` → 403.
    """
    # 1. 인증 가드 (body validation보다 우선).
    caller = await _resolve_caller_or_401(request, session_service)

    # 2. raw body 읽기 + JSON 파싱.
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

    # 3. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = ScopesUpdateRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    # 4. service 호출.
    try:
        member = await svc.update_scopes(member_id, body.scopes, updated_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.update_scopes",
            resource=f"member:{member_id}",
            detail=f"scopes={body.scopes}",
            ip=request.client.host if request.client else "",
        )

    return {"member": asdict(member)}
