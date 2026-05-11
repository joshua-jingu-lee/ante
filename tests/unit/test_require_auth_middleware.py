"""RequireAuthMiddleware 단위 테스트 (#1403).

D-015 ADR (``docs/decisions/D-015-default-deny-auth-gate.md``) 5단계 판정 순서를
회귀 검증한다. spec SSOT:

- ``docs/specs/web-api/02-design-decisions.md`` — 인증 게이트 단계 + CORS 설정
- ``docs/specs/web-api/09-public-paths.md`` — PUBLIC_PATHS / PUBLIC_PREFIXES /
  ``gate-exempt-self-auth`` / 비-``/api`` SPA fallback

본 테스트는 미들웨어 단의 1차 차단만 검증한다. 라우트 dependency 단의 scope
검증 (``require_scope``)은 ``test_runtime_mutation_auth.py`` 등 별도 매트릭스가
회귀 보호한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.member.models import MemberStatus  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from ante.web.middleware import token_auth as _ta_mod  # noqa: E402


@dataclass
class FakeMember:
    member_id: str
    type: str = "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = MemberStatus.ACTIVE.value
    scopes: list[str] = field(default_factory=list)
    token_hash: str = ""
    password_hash: str = ""
    recovery_key_hash: str = ""
    created_at: str = ""
    created_by: str = ""
    last_active_at: str = ""
    suspended_at: str = ""
    revoked_at: str = ""
    token_expires_at: str = ""


class FakeSessionService:
    """ante_session 쿠키 fallback 시뮬레이션."""

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self._expired: set[str] = set()

    def add(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    def expire(self, session_id: str) -> None:
        self._expired.add(session_id)

    async def validate(self, session_id: str) -> dict | None:
        if session_id in self._expired:
            return None
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-01-01T00:00:00Z"}


class FakeMemberService:
    """Bearer 인증 + 세션 fallback 멤버 조회 모두 지원."""

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add(
        self,
        member_id: str,
        token: str = "",
        status: str = MemberStatus.ACTIVE.value,
        role: str = "default",
        member_type: str = "agent",
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            status=status,
            role=role,
            type=member_type,
        )
        self._members[member_id] = member
        if token:
            self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        member = self._members[member_id]
        # TokenAuthMiddleware SSOT 답습: ACTIVE 아닌 멤버는 인증 거부.
        if member.status != MemberStatus.ACTIVE.value:
            raise PermissionError("inactive member")
        return member

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)

    async def update_last_active(self, member_id: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_throttle_cache() -> None:
    """TokenAuthMiddleware 캐시 초기화."""
    _ta_mod._last_updated.clear()


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add("master-01", token="ante_ak_master", role="master", member_type="human")
    svc.add("active-agent", token="ante_ak_active")
    svc.add("suspended-agent", status=MemberStatus.SUSPENDED.value)
    svc.add("revoked-agent", status=MemberStatus.REVOKED.value)
    return svc


@pytest.fixture
def session_service() -> FakeSessionService:
    svc = FakeSessionService()
    svc.add("session-active", "master-01")
    svc.add("session-suspended", "suspended-agent")
    svc.add("session-revoked", "revoked-agent")
    svc.add("session-expired", "master-01")
    svc.expire("session-expired")
    svc.add("session-orphan", "nonexistent-member")
    return svc


@pytest.fixture
def app(
    member_service: FakeMemberService,
    session_service: FakeSessionService,
) -> Any:
    audit_logger = AsyncMock()
    audit_logger.log = AsyncMock()
    return create_app(
        member_service=member_service,
        session_service=session_service,
        audit_logger=audit_logger,
    )


@pytest.fixture
def client(app: Any) -> TestClient:
    return TestClient(app)


# ── 1단계: OPTIONS preflight 면제 ─────────────────────────────────────────


class TestOptionsPreflight:
    def test_options_preflight_passes_without_auth(self, client: TestClient) -> None:
        """OPTIONS 요청은 인증 없이도 통과 (CORS 안전망)."""
        resp = client.options(
            "/api/bots",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        # CORSMiddleware가 200 + Allow-Origin 응답을 생성한다.
        assert resp.status_code == 200
        assert "access-control-allow-origin" in resp.headers


# ── 2단계: PUBLIC_PATHS / PUBLIC_PREFIXES 면제 ────────────────────────────


class TestPublicPaths:
    def test_public_path_exact_match_health(self, client: TestClient) -> None:
        """``/api/system/health`` PUBLIC exact match → 인증 없이 200."""
        resp = client.get("/api/system/health")
        assert resp.status_code == 200

    def test_public_path_with_query_string(self, client: TestClient) -> None:
        """PUBLIC 경로 + query string도 PUBLIC으로 인식.

        Codex 권장 추가 회귀 케이스 (6 보강).
        """
        resp = client.get("/api/system/health?from=monitor")
        assert resp.status_code == 200

    def test_public_path_openapi_json(self, client: TestClient) -> None:
        """``/openapi.json`` PUBLIC → 인증 없이 200."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200

    def test_public_prefix_assets_passes(self, client: TestClient) -> None:
        """``/assets/*`` PUBLIC prefix → 인증 없이 200 또는 404 (자산 미존재).

        본 미들웨어 책임은 401 차단이 아닌 통과 보장이므로, 자산 자체가
        없어도 401이 아닌 다른 응답(404)이 나와야 한다.
        """
        resp = client.get("/assets/index.js")
        assert resp.status_code != 401

    def test_public_prefix_boundary_does_not_leak(self, client: TestClient) -> None:
        """``/assets-foo`` 같이 ``/assets/`` 경계를 넘지 않는 경로는 PUBLIC 아님.

        Codex 권장 (5 보강): trailing slash 경계로 오인 통과 방지.
        단, 비-``/api`` 경로는 SPA fallback 분기로 면제된다. 본 테스트는
        ``/api/assets-foo``로 경계 검증을 수행한다.
        """
        resp = client.get("/api/assets-foo")
        # 보호된 ``/api`` 경로이면서 PUBLIC_PREFIXES boundary 외이므로 401.
        assert resp.status_code == 401

    def test_spa_fallback_login_passes(self, client: TestClient) -> None:
        """비-``/api`` SPA fallback ``/login`` → 인증 없이 미들웨어 통과.

        실제 응답은 404 (frontend 빌드 미존재) 또는 SPA index.html (빌드 존재)일
        수 있으나 401이 아니어야 한다.
        """
        resp = client.get("/login")
        assert resp.status_code != 401

    def test_spa_fallback_dashboard_deep_link(self, client: TestClient) -> None:
        """비-``/api`` SPA deep link ``/dashboard/foo`` → 401 아님."""
        resp = client.get("/dashboard/foo")
        assert resp.status_code != 401


# ── 3단계: gate-exempt-self-auth ──────────────────────────────────────────


class TestGateExemptSelfAuth:
    def test_auth_me_passes_middleware_route_returns_401(
        self, client: TestClient
    ) -> None:
        """``/api/auth/me``는 미들웨어 면제, 라우트가 self-auth로 401 반환.

        spec 09-public-paths.md ``gate-exempt-self-auth`` 카테고리:
        미들웨어가 차단하지 않고 라우트 자체가 세션/Bearer 검증해 401 또는
        본인 정보 응답.
        """
        resp = client.get("/api/auth/me")
        # 미들웨어가 차단했다면 default-deny detail이 나오겠지만, 라우트가
        # 직접 처리하므로 자체 detail("인증이 필요합니다")이 응답된다.
        assert resp.status_code == 401


# ── 4단계: Bearer caller 확인 ─────────────────────────────────────────────


class TestBearerCaller:
    def test_bearer_token_passes_gate(self, client: TestClient) -> None:
        """Bearer 토큰 부착 시 미들웨어 통과 (라우트에서 200/4xx 결정)."""
        # ``/api/system/halt``는 mutation route이지만 master 권한이 필요.
        # 본 테스트는 미들웨어 통과만 검증하므로 401이 아니면 OK.
        resp = client.get(
            "/api/system/health",
            headers={"Authorization": "Bearer ante_ak_master"},
        )
        # PUBLIC 경로지만 Bearer가 와도 200 보장.
        assert resp.status_code == 200

    def test_bearer_protected_route_passes_gate(self, client: TestClient) -> None:
        """Bearer master 토큰으로 보호 라우트도 미들웨어 통과."""
        # ``/api/bots`` 는 GET이며 미들웨어 통과 후 라우트 의존성을 거친다.
        # bot_manager가 없어도 미들웨어는 통과하고 503 이 응답된다 (401 아님).
        resp = client.get(
            "/api/bots",
            headers={"Authorization": "Bearer ante_ak_master"},
        )
        assert resp.status_code != 401


# ── 5단계: 세션 fallback + ACTIVE 검증 ────────────────────────────────────


class TestSessionFallback:
    def test_active_session_passes_gate(self, client: TestClient) -> None:
        """ACTIVE 멤버의 ante_session 쿠키 → 미들웨어 통과."""
        client.cookies.set("ante_session", "session-active")
        resp = client.get("/api/bots")
        assert resp.status_code != 401

    def test_suspended_session_rejected(self, client: TestClient) -> None:
        """SUSPENDED 멤버의 세션 → 401 (Bearer/세션 비대칭 해소)."""
        client.cookies.set("ante_session", "session-suspended")
        resp = client.get("/api/bots")
        assert resp.status_code == 401

    def test_revoked_session_rejected(self, client: TestClient) -> None:
        """REVOKED 멤버의 세션 → 401."""
        client.cookies.set("ante_session", "session-revoked")
        resp = client.get("/api/bots")
        assert resp.status_code == 401

    def test_expired_session_rejected(self, client: TestClient) -> None:
        """만료된 세션 → 401."""
        client.cookies.set("ante_session", "session-expired")
        resp = client.get("/api/bots")
        assert resp.status_code == 401

    def test_orphan_session_rejected(self, client: TestClient) -> None:
        """세션은 valid하지만 멤버가 삭제된 경우 → 401."""
        client.cookies.set("ante_session", "session-orphan")
        resp = client.get("/api/bots")
        assert resp.status_code == 401


# ── 6단계: caller 미결정 → 401 + CORS 헤더 (잔여 P2-A) ──────────────────────


class TestUnauthorized:
    def test_no_auth_returns_401_problem_json(self, client: TestClient) -> None:
        """헤더/쿠키 둘 다 없으면 401 + RFC 7807 형식."""
        resp = client.get("/api/bots")
        assert resp.status_code == 401
        assert resp.headers.get("content-type", "").startswith(
            "application/problem+json"
        )
        body = resp.json()
        assert body["status"] == 401
        assert body["type"] == "/errors/unauthorized"
        assert body["instance"] == "/api/bots"

    def test_no_auth_with_origin_includes_cors_header(self, client: TestClient) -> None:
        """잔여 P2-A: cross-origin 인증 실패 시 Allow-Origin 헤더 포함.

        spec 02-design-decisions.md "CORS 설정" 절: 브라우저가 응답을 읽을 수
        있도록 401 응답에도 CORS 헤더를 동봉한다.
        """
        resp = client.get(
            "/api/bots",
            headers={"Origin": "http://localhost:3000"},
        )
        assert resp.status_code == 401
        assert "access-control-allow-origin" in resp.headers

    def test_no_auth_without_origin_omits_cors_header(self, client: TestClient) -> None:
        """Codex 권장 (2 보강): no-Origin 401 응답은 Allow-Origin 헤더 없음."""
        resp = client.get("/api/bots")
        assert resp.status_code == 401
        assert "access-control-allow-origin" not in resp.headers

    def test_invalid_bearer_token_returns_401(self, client: TestClient) -> None:
        """무효한 Bearer 토큰 → TokenAuth가 caller 미부착 → 미들웨어 401."""
        resp = client.get(
            "/api/bots",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp.status_code == 401

    def test_invalid_session_cookie_returns_401(self, client: TestClient) -> None:
        """무효한 세션 쿠키 → 미들웨어 401."""
        client.cookies.set("ante_session", "nonexistent-session")
        resp = client.get("/api/bots")
        assert resp.status_code == 401


# ── 보조: 미들웨어가 PUBLIC/gate-exempt 분기에서 세션 fallback을 시도하지 않음 ──


class TestPublicPathSkipsSessionFallback:
    def test_suspended_session_can_reach_login(self, client: TestClient) -> None:
        """SUSPENDED 세션이라도 PUBLIC ``/api/auth/login``에는 도달 가능.

        spec 02-design-decisions.md "공개 경로 판정은 세션 fallback / ACTIVE
        검사보다 먼저 수행한다" (Codex v4 Finding 1): 비ACTIVE 멤버도 재로그인
        / 쿠키 정리 경로에 접근할 수 있어야 한다.
        """
        client.cookies.set("ante_session", "session-suspended")
        # POST /api/auth/login은 body가 필요하지만 422가 나오더라도 401은
        # 아니어야 한다.
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code != 401

    def test_suspended_session_can_reach_health(self, client: TestClient) -> None:
        """SUSPENDED 세션이라도 PUBLIC ``/api/system/health`` 200."""
        client.cookies.set("ante_session", "session-suspended")
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
