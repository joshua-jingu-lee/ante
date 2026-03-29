"""멤버 관리 API."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from ante.member.errors import PermissionDeniedError
from ante.web.deps import get_audit_logger_optional, get_member_service
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


class MemberCreateRequest(BaseModel):
    """멤버 등록 요청."""

    member_id: str
    member_type: str  # "human" | "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    scopes: list[str] = []


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
    responses={503: {"description": "Member service not available"}},
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
        400: {"description": "Invalid member data"},
        403: {"description": "Permission denied"},
        503: {"description": "Member service not available"},
    },
)
async def create_member(
    body: MemberCreateRequest,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 등록. 토큰 1회 반환."""
    caller = _caller_id(request)
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
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
    },
)
async def suspend_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 일시 정지."""
    caller = _caller_id(request)
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
    },
)
async def reactivate_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 재활성화."""
    caller = _caller_id(request)
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
    },
)
async def revoke_member(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 영구 폐기."""
    caller = _caller_id(request)
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
    },
)
async def rotate_token(
    member_id: str,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """토큰 재발급."""
    caller = _caller_id(request)
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
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
        403: {"description": "Permission denied"},
        404: {"description": "Member not found"},
        503: {"description": "Member service not available"},
    },
)
async def update_scopes(
    member_id: str,
    body: ScopesUpdateRequest,
    request: Request,
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """권한 범위 변경."""
    caller = _caller_id(request)
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
