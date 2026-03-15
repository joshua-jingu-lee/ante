"""인증 API — 세션 기반 로그인/로그아웃/현재 사용자 조회."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Cookie, HTTPException, Request, Response

from ante.web.schemas import LoginRequest, LoginResponse, MeResponse

logger = logging.getLogger(__name__)

router = APIRouter()

COOKIE_NAME = "ante_session"
COOKIE_MAX_AGE = 86400  # 24시간


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response
) -> LoginResponse:
    """패스워드 로그인 → 세션 쿠키 발급."""
    member_service = request.app.state.member_service
    session_service = request.app.state.session_service

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


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    ante_session: str | None = Cookie(default=None),
) -> dict:
    """로그아웃 — 세션 삭제 + 쿠키 제거."""
    if ante_session:
        session_service = request.app.state.session_service
        await session_service.delete(ante_session)

    response.delete_cookie(key=COOKIE_NAME)
    return {"ok": True}


@router.get("/me")
async def me(
    request: Request,
    ante_session: str | None = Cookie(default=None),
) -> MeResponse:
    """현재 로그인 사용자 정보."""
    if not ante_session:
        raise HTTPException(status_code=401, detail="인증이 필요합니다")

    session_service = request.app.state.session_service
    session = await session_service.validate(ante_session)
    if not session:
        raise HTTPException(status_code=401, detail="세션이 만료되었습니다")

    member_service = request.app.state.member_service
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
    )
