"""감사 로그 미들웨어 — 상태 변경 API 자동 기록 (안전망)."""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)

# 자동 기록 대상 HTTP 메서드
_MUTATING_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


class AuditMiddleware(BaseHTTPMiddleware):
    """모든 상태 변경(POST/PUT/DELETE/PATCH) 성공 응답을 자동 기록한다.

    핸들러의 명시적 audit 호출과 별도로 동작하며,
    action 접두사 ``api:`` 로 구분된다.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        response = await call_next(request)

        if request.method not in _MUTATING_METHODS:
            return response

        if not (200 <= response.status_code < 400):
            return response

        audit_logger = getattr(request.app.state, "audit_logger", None)
        if audit_logger is None:
            return response

        member_id = getattr(request.state, "member_id", "anonymous")
        ip = request.client.host if request.client else ""

        try:
            await audit_logger.log(
                member_id=member_id,
                action=f"api:{request.method.lower()}",
                resource=request.url.path,
                ip=ip,
            )
        except Exception:
            logger.exception(
                "AuditMiddleware 기록 실패: %s %s", request.method, request.url.path
            )

        return response
