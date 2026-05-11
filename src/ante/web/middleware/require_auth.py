"""default-deny 인증 게이트 미들웨어 (#1403).

D-015 ADR (``docs/decisions/D-015-default-deny-auth-gate.md``)의 5단계 판정
순서를 그대로 구현한다. spec SSOT:

- ``docs/specs/web-api/02-design-decisions.md`` — 인증 게이트 단계 / CORS 설정
- ``docs/specs/web-api/09-public-paths.md`` — PUBLIC_PATHS / PUBLIC_PREFIXES /
  ``gate-exempt-self-auth`` / 비-``/api`` SPA fallback

요청 처리 순서 (LIFO add 시퀀스 결과):
    ``TokenAuth → RequireAuth → Audit → CORS → 라우트``

본 미들웨어의 5단계 판정 (D-015 ADR 표):
    1. ``OPTIONS`` preflight 면제 → 즉시 통과 (CORS 안전망)
    2. PUBLIC 면제 → ``PUBLIC_PATHS`` exact / ``PUBLIC_PREFIXES`` startswith /
       비-``/api`` SPA fallback. 면제 시 세션 fallback도 시도하지 않음
    3. ``gate-exempt-self-auth`` 면제 → PUBLIC과 동일 통과. 라우트가 자체 self-auth
    4. Bearer caller 확인 → ``request.state.member_id`` 가 비어 있지 않으면 통과
    5. 세션 쿠키 fallback + ACTIVE 검증 → ``ante_session`` 쿠키로 caller 결정 후
       ``MemberStatus.ACTIVE`` 검사. ACTIVE 이면 ``request.state.member_id`` 부착
       후 통과. 그 외 (만료/없음/SUSPENDED/REVOKED) → 401
    6. caller 미결정 시 → 401 (Origin 헤더가 있으면 ``Access-Control-Allow-Origin``
       응답 헤더를 함께 포함, 잔여 P2-A)

scope 검사는 본 미들웨어 책임이 아니다. 라우트 dependency / ``@require_scope``
가 담당한다 (D-015 책임 매트릭스).
"""

from __future__ import annotations

import logging
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from ante.web.errors import PROBLEM_JSON, _build_error

logger = logging.getLogger(__name__)

# PUBLIC_PATHS SSOT: ``docs/specs/web-api/09-public-paths.md``.
# 정확 일치 (exact match) 공개 경로. 인증 없이 누구나 접근 가능.
PUBLIC_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/index.html",
        "/api/system/health",
        "/api/auth/login",
        "/api/auth/logout",
        "/openapi.json",
        "/docs",
        "/redoc",
    }
)

# PUBLIC_PREFIXES SSOT: ``docs/specs/web-api/09-public-paths.md``.
# 접두어 일치. trailing slash 경계를 보장해 ``/assets-foo`` 같은 오인 통과를 막는다.
PUBLIC_PREFIXES: tuple[str, ...] = ("/assets/",)

# gate-exempt-self-auth SSOT: ``docs/specs/web-api/09-public-paths.md`` 9-43~9-51.
# 미들웨어 게이트는 면제, 라우트가 자체적으로 세션/Bearer 검증 후 본인 정보만 응답.
GATE_EXEMPT_SELF_AUTH_PATHS: frozenset[str] = frozenset({"/api/auth/me"})

_AUTH_REQUIRED_DETAIL = (
    "인증이 필요합니다. Authorization: Bearer <token> 헤더 또는 "
    "유효한 ante_session 쿠키가 필요합니다."
)


class RequireAuthMiddleware(BaseHTTPMiddleware):
    """default-deny 인증 게이트.

    D-015 ADR 5단계 판정 순서로 보호 라우트 진입 전에 401을 1차 차단한다.
    scope 검사는 라우트 dependency (``@require_scope``) 책임.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Response:
        # 1단계: OPTIONS preflight 면제 (CORS 안전망).
        # spec 02-design-decisions.md "CORS 설정" 절: 등록 순서에 의존하지
        # 않도록 미들웨어 자체가 OPTIONS를 무조건 통과시킨다.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # 2단계 + 3단계: PUBLIC 면제 / gate-exempt-self-auth 면제.
        # 두 카테고리 모두 미들웨어 단계에서 동일하게 401 없이 통과시킨다.
        # 차이는 라우트 단 책임에 있다 (public = caller-agnostic 응답,
        # gate-exempt-self-auth = 라우트가 자체 self-auth).
        if _is_public_path(path) or path in GATE_EXEMPT_SELF_AUTH_PATHS:
            return await call_next(request)

        # 4단계: Bearer caller 확인.
        # TokenAuthMiddleware가 이미 ``request.state.member_id``를 채웠으면 통과.
        # Bearer 경로는 ``member_service.authenticate``가 ACTIVE 검사를 이미
        # 수행하므로 미들웨어 진입 시점에 부착된 caller는 ACTIVE 보장이 있다.
        caller = getattr(request.state, "member_id", "") or ""
        if caller:
            return await call_next(request)

        # 5단계: 세션 쿠키 fallback + ACTIVE 검증.
        # spec 02-design-decisions.md "세션 fallback 시 멤버 상태 검증" 절을 따른다.
        session_caller = await _resolve_session_caller(request)
        if session_caller is not None:
            request.state.member_id = session_caller
            return await call_next(request)

        # 6단계: caller 미결정 → 401.
        return _unauthorized_response(request)


def _is_public_path(path: str) -> bool:
    """spec 09-public-paths.md SSOT 기준으로 공개 경로 여부 판정.

    분기 우선순위:
    1. ``PUBLIC_PATHS`` exact match
    2. ``PUBLIC_PREFIXES`` startswith (trailing slash 경계 보장)
    3. 비-``/api`` SPA fallback (``/login``, ``/dashboard/foo`` 등 client-side route)
    """
    if path in PUBLIC_PATHS:
        return True
    for prefix in PUBLIC_PREFIXES:
        if path.startswith(prefix):
            return True
    # 비-``/api`` SPA fallback (spec 09-public-paths.md "SPA fallback 경로").
    # ``/api`` exact 또는 ``/api/...``만 보호 대상. 그 외 (``/login``,
    # ``/dashboard/...``, ``/strategies/...`` 등 client-side route)는 면제.
    if path != "/api" and not path.startswith("/api/"):
        return True
    return False


async def _resolve_session_caller(request: Request) -> str | None:
    """``ante_session`` 쿠키 fallback. ACTIVE 멤버이면 caller_id 반환, 그 외 None.

    spec 02-design-decisions.md "세션 fallback 시 멤버 상태 검증" 절 (Codex
    review v3 Finding X)을 따른다:

    - ``SessionService.validate``는 세션 만료/서명만 검증하므로 멤버가
      ``SUSPENDED``/``REVOKED``로 전환되어도 세션 row가 남아 있으면 통과한다.
    - 따라서 미들웨어가 ``member_service.get(caller)``를 호출해
      ``MemberStatus.ACTIVE``를 명시 확인한다.
    - 비ACTIVE이면 caller 부착 없이 None 반환 (호출자가 401 응답 생성).
    """
    ante_session = request.cookies.get("ante_session")
    if not ante_session:
        return None

    session_service = getattr(request.app.state, "session_service", None)
    if session_service is None:
        return None

    member_service = getattr(request.app.state, "member_service", None)
    if member_service is None:
        return None

    try:
        session = await session_service.validate(ante_session)
    except Exception:
        logger.exception("세션 검증 실패 (session_id 일부=%s...)", ante_session[:8])
        return None
    if not session:
        return None

    member_id = session.get("member_id", "") or ""
    if not member_id:
        return None

    try:
        member = await member_service.get(member_id)
    except Exception:
        logger.exception("멤버 조회 실패 (member_id=%s)", member_id)
        return None
    if member is None:
        return None

    # MemberStatus.ACTIVE 검사. enum/str 양쪽 안전 처리.
    from ante.member.models import MemberStatus

    status = getattr(member, "status", None)
    status_value = getattr(status, "value", status)
    if status_value != MemberStatus.ACTIVE.value:
        return None

    return member_id


def _unauthorized_response(request: Request) -> JSONResponse:
    """RFC 7807 형식의 401 응답. Origin 헤더가 있으면 CORS Allow-Origin 동봉.

    spec 02-design-decisions.md "CORS 등록 순서와 RequireAuth의 관계" 절을 따른다.
    잔여 P2-A: cross-origin 인증 실패도 브라우저가 응답을 읽을 수 있도록
    ``Access-Control-Allow-Origin`` 헤더를 명시한다. Origin 헤더가 없으면
    헤더를 추가하지 않는다 (Codex 권장).
    """
    error = _build_error(
        status=401,
        detail=_AUTH_REQUIRED_DETAIL,
        instance=request.url.path,
    )
    headers: dict[str, str] = {}
    origin = request.headers.get("origin")
    if origin:
        # spec: 홈서버 환경이므로 ``allow_origins=["*"]``. CORS Allow-Origin은
        # echoed origin이 아닌 ``*``로 통일해 CORSMiddleware 응답 단과 일관성 유지.
        headers["access-control-allow-origin"] = "*"
    return JSONResponse(
        status_code=401,
        content=error.model_dump(),
        media_type=PROBLEM_JSON,
        headers=headers,
    )
