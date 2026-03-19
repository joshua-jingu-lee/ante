"""멤버 관리 API."""

from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from ante.web.schemas import (
    MemberCreateResponse,
    MemberDetailResponse,
    MemberListResponse,
    MemberScopesResponse,
    MemberTokenResponse,
    OkResponse,
)

router = APIRouter()


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


def _get_member_service(request: Request):
    svc = getattr(request.app.state, "member_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Member service not available")
    return svc


@router.get("", response_model=MemberListResponse)
async def list_members(
    request: Request,
    type: str | None = Query(default=None),
    org: str | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """멤버 목록 조회."""
    svc = _get_member_service(request)
    members = await svc.list(
        member_type=type, org=org, status=status, limit=limit, offset=offset
    )
    return {"members": [asdict(m) for m in members], "total": len(members)}


@router.post("", status_code=201, response_model=MemberCreateResponse)
async def create_member(request: Request, body: MemberCreateRequest) -> dict:
    """멤버 등록. 토큰 1회 반환."""
    svc = _get_member_service(request)

    try:
        member, token = await svc.register(
            member_id=body.member_id,
            member_type=body.member_type,
            role=body.role,
            org=body.org,
            name=body.name,
            scopes=body.scopes,
            registered_by="dashboard",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    return {"member": asdict(member), "token": token}


@router.get("/{member_id}", response_model=MemberDetailResponse)
async def get_member(request: Request, member_id: str) -> dict:
    """멤버 상세 조회."""
    svc = _get_member_service(request)
    member = await svc.get(member_id)
    if member is None:
        raise HTTPException(status_code=404, detail="멤버를 찾을 수 없습니다")
    return {"member": asdict(member)}


@router.post("/{member_id}/suspend", response_model=MemberDetailResponse)
async def suspend_member(request: Request, member_id: str) -> dict:
    """멤버 일시 정지."""
    svc = _get_member_service(request)
    try:
        member = await svc.suspend(member_id, suspended_by="dashboard")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"member": asdict(member)}


@router.post("/{member_id}/reactivate", response_model=MemberDetailResponse)
async def reactivate_member(request: Request, member_id: str) -> dict:
    """멤버 재활성화."""
    svc = _get_member_service(request)
    try:
        member = await svc.reactivate(member_id, reactivated_by="dashboard")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"member": asdict(member)}


@router.post("/{member_id}/revoke", response_model=MemberDetailResponse)
async def revoke_member(request: Request, member_id: str) -> dict:
    """멤버 영구 폐기."""
    svc = _get_member_service(request)
    try:
        member = await svc.revoke(member_id, revoked_by="dashboard")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"member": asdict(member)}


@router.post("/{member_id}/rotate-token", response_model=MemberTokenResponse)
async def rotate_token(request: Request, member_id: str) -> dict:
    """토큰 재발급."""
    svc = _get_member_service(request)
    try:
        member, token = await svc.rotate_token(member_id, rotated_by="dashboard")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"member": asdict(member), "token": token}


@router.patch("/{member_id}/password", response_model=OkResponse)
async def change_password(
    request: Request, member_id: str, body: PasswordChangeRequest
) -> dict:
    """비밀번호 변경 (human 멤버 전용)."""
    svc = _get_member_service(request)
    try:
        await svc.change_password(member_id, body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"ok": True}


@router.put("/{member_id}/scopes", response_model=MemberScopesResponse)
async def update_scopes(
    request: Request, member_id: str, body: ScopesUpdateRequest
) -> dict:
    """권한 범위 변경."""
    svc = _get_member_service(request)
    try:
        member = await svc.update_scopes(member_id, body.scopes, updated_by="dashboard")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    return {"member": asdict(member)}
