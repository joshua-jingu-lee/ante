"""토큰 인증 미들웨어 — API 토큰 인증 + last_active_at 갱신."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# Authorization 헤더 접두어
_BEARER_PREFIX = "Bearer "

# last_active_at 갱신 최소 간격 (5분)
_UPDATE_INTERVAL = timedelta(minutes=5)

# 인메모리 캐시: member_id → 마지막 갱신 시각
_last_updated: dict[str, datetime] = {}

# epoch 기준값 (캐시 미스 시 사용)
_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """API 토큰 인증 미들웨어.

    Authorization: Bearer <token> 헤더가 있으면 토큰 인증을 수행한다.
    인증 성공 시:
    - request.state.member_id 설정 (AuditMiddleware에서 사용)
    - request.state.member 설정 (라우트 핸들러에서 사용 가능)
    - last_active_at 갱신 (5분 간격 스로틀링)

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
            await self._throttled_update(member_service, member.member_id)
            logger.debug("토큰 인증 성공: %s", member.member_id)
        except PermissionError:
            # 인증 실패는 라우트 핸들러에서 처리
            logger.debug("토큰 인증 실패: 유효하지 않은 토큰")

    @staticmethod
    async def _throttled_update(member_service: Any, member_id: str) -> None:
        """5분 간격으로 last_active_at을 갱신한다."""
        now = datetime.now(UTC)
        last = _last_updated.get(member_id, _EPOCH)
        if now - last < _UPDATE_INTERVAL:
            return
        await member_service.update_last_active(member_id)
        _last_updated[member_id] = now
