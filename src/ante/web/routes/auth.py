"""인증 API — 세션 기반 로그인/로그아웃/현재 사용자 조회."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response

from ante.web.deps import get_member_service, get_session_service
from ante.web.schemas import LoginRequest, LoginResponse, LogoutResponse, MeResponse

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_NAME = "ante_session"
COOKIE_MAX_AGE = 86400  # 24시간


@router.post(
    "/login",
    response_model=LoginResponse,
    responses={
        401: {"description": "Invalid credentials"},
        503: {"description": "Member or session service not available"},
    },
)
async def login(
    body: LoginRequest,
    request: Request,
    response: Response,
    member_service: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any, Depends(get_session_service)],
) -> LoginResponse:
    """패스워드 로그인 -> 세션 쿠키 발급."""
    try:
        member = await member_service.authenticate_password(
            body.member_id, body.password
        )
    except PermissionError:
        raise HTTPException(
            status_code=401,
            detail="ID 또는 패스워드가 올바르지 않습니다",
        )

    await member_service.update_last_active(member.member_id)

    ip_address = request.client.host if request.client else ""
    user_agent = request.headers.get("user-agent", "")
    session_id = await session_service.create(
        member_id=member.member_id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    response.set_cookie(
        key=COOKIE_NAME,
        value=session_id,
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="strict",
        secure=request.url.scheme == "https",
    )

    return LoginResponse(
        member_id=member.member_id,
        name=member.name,
        type=member.type,
    )


@router.post(
    "/logout",
    response_model=LogoutResponse,
    responses={503: {"description": "Session service not available"}},
)
async def logout(
    response: Response,
    session_service: Annotated[Any, Depends(get_session_service)],
    ante_session: str | None = Cookie(default=None),
) -> dict:
    """로그아웃 — 세션 삭제 + 쿠키 제거."""
    if ante_session:
        await session_service.delete(ante_session)

    response.delete_cookie(key=COOKIE_NAME)
    return {"ok": True}


@router.get(
    "/me",
    response_model=MeResponse,
    responses={
        401: {"description": "Not authenticated or session expired"},
        503: {"description": "Member or session service not available"},
    },
)
async def me(
    member_service: Annotated[Any, Depends(get_member_service)],
    session_service: Annotated[Any, Depends(get_session_service)],
    ante_session: str | None = Cookie(default=None),
) -> MeResponse:
    """현재 로그인 사용자 정보."""
    if not ante_session:
        raise HTTPException(status_code=401, detail="인증이 필요합니다")

    session = await session_service.validate(ante_session)
    if not session:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다")

    member = await member_service.get(session["member_id"])
    if not member:
        raise HTTPException(status_code=401, detail="사용자를 찾을 수 없습니다")

    await member_service.update_last_active(member.member_id)

    return MeResponse(
        member_id=member.member_id,
        name=member.name,
        type=member.type,
        emoji=member.emoji,
        role=member.role,
        login_at=session.get("created_at", ""),
    )
