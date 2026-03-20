"""토큰 인증 미들웨어 — API 토큰 인증 + last_active_at 갱신."""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Authorization 헤더 접두어
_BEARER_PREFIX = "Bearer "


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """API 토큰 인증 미들웨어.

    Authorization: Bearer <token> 헤더가 있으면 토큰 인증을 수행한다.
    인증 성공 시:
    - request.state.member_id 설정 (AuditMiddleware에서 사용)
    - request.state.member 설정 (라우트 핸들러에서 사용 가능)
    - MemberService.update_last_active() 호출

    헤더가 없으면 인증을 시도하지 않고 다음 미들웨어로 넘긴다.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        auth_header = request.headers.get("authorization", "")

        if auth_header.startswith(_BEARER_PREFIX):
            token = auth_header[len(_BEARER_PREFIX) :]
            await self._authenticate_token(request, token)

        return await call_next(request)

    async def _authenticate_token(self, request: Request, token: str) -> None:
        """토큰 인증 수행. 실패 시 무시 (라우트에서 별도 처리)."""
        member_service = getattr(request.app.state, "member_service", None)
        if member_service is None:
            return

        try:
            member = await member_service.authenticate(token)
            request.state.member_id = member.member_id
            request.state.member = member
            await member_service.update_last_active(member.member_id)
            logger.debug("토큰 인증 성공: %s", member.member_id)
        except PermissionError:
            # 인증 실패는 라우트 핸들러에서 처리
            logger.debug("토큰 인증 실패: 유효하지 않은 토큰")
