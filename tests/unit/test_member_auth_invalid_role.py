"""auth read-path 의 ``MemberRole`` enum 강제 회귀 (issue #1466 — split #1417/B).

검증 대상:

- ``MemberService.authenticate(token)`` — 토큰 인증. legacy invalid-role
  member 의 token 이 인증을 통과하지 못한다.
- ``MemberService.authenticate_password(member_id, password)`` — 패스워드
  인증. legacy invalid-role member 의 정상 password 도 인증을 통과하지
  못한다.
- HTTP ``/api/auth/me`` — Bearer token 경로 (TokenAuthMiddleware) +
  session cookie 경로 (gate-exempt-self-auth 라우트 self-auth) 모두 401.
- HTTP 보호된 라우트 (``/api/bots``) — session cookie fallback 단의
  ``RequireAuthMiddleware._resolve_session_caller`` 가 invalid-role 을 거부.
- HTTP 보호된 라우트 — Bearer token 경로 (TokenAuthMiddleware →
  ``MemberService.authenticate``) 가 invalid-role 을 거부.
- 정상 role (``master`` / ``admin`` / ``default``) 인증 경로 회귀 (통과).
- ``_VALID_MEMBER_ROLES`` 캐시가 ``MemberRole`` enum SSOT 와 동치 (drift
  방지 회귀).
- list/get tolerance: ``GET /api/members`` 가 invalid-role row 를 그대로
  노출 (cleanup 가능, #1468 비목표).

본 모듈은 ``test_member.py`` 의 서비스 fixture 패턴과
``test_require_auth_middleware.py`` 의 Fake 패턴을 재사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.core.database import Database  # noqa: E402
from ante.eventbus import EventBus  # noqa: E402
from ante.eventbus.events import MemberAuthFailedEvent  # noqa: E402
from ante.member.auth_service import _VALID_MEMBER_ROLES  # noqa: E402
from ante.member.models import MemberRole, MemberStatus, MemberType  # noqa: E402
from ante.member.service import MemberService  # noqa: E402
from ante.web.app import create_app  # noqa: E402
from ante.web.middleware import token_auth as _ta_mod  # noqa: E402

# ── Service-layer fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def service(db, eventbus) -> MemberService:
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


async def _seed_invalid_role_agent(
    db: Database, service: MemberService
) -> tuple[str, str]:
    """legacy invalid-role agent row 를 DB 에 심는다.

    ``register`` 는 ``_assert_role_enum`` 으로 invalid role 을 차단하므로
    (#1465) 정상 register 한 뒤 DB 직접 UPDATE 로 ``role`` 을
    ``oracle_invalid_role`` 로 변조한다. 이는 #1465 이전에 만들어진 row 를
    재현한다.

    Returns:
        (member_id, token) 튜플.
    """
    member, token = await service.register("agent-bad", MemberType.AGENT)
    await db.execute(
        "UPDATE members SET role = ? WHERE member_id = ?",
        ("oracle_invalid_role", member.member_id),
    )
    return member.member_id, token


async def _seed_invalid_role_human(
    db: Database, service: MemberService, password: str = "pass123"
) -> tuple[str, str]:
    """legacy invalid-role human row 를 DB 에 심는다 (password 인증 회귀용).

    ``bootstrap_master`` 로 password 가 있는 human 을 만든 뒤 role 을 변조한다.
    """
    _, master_token, _ = await service.bootstrap_master("human-bad", password)
    await db.execute(
        "UPDATE members SET role = ? WHERE member_id = ?",
        ("oracle_invalid_role", "human-bad"),
    )
    return "human-bad", master_token


# ── Service: token auth ────────────────────────────────────────────


class TestAuthenticateInvalidRoleToken:
    """``MemberService.authenticate`` 가 legacy invalid-role token 을 거부."""

    async def test_invalid_role_token_raises_permission_error(
        self, service: MemberService, db: Database
    ) -> None:
        _member_id, token = await _seed_invalid_role_agent(db, service)
        with pytest.raises(PermissionError, match="invalid role"):
            await service.authenticate(token)

    async def test_invalid_role_token_publishes_auth_failed_event(
        self, service: MemberService, db: Database, eventbus: EventBus
    ) -> None:
        """invalid-role 거부 시 ``MemberAuthFailedEvent`` 가 발행되어 운영자
        cleanup 신호가 된다."""
        events: list[MemberAuthFailedEvent] = []
        eventbus.subscribe(MemberAuthFailedEvent, lambda e: events.append(e))

        member_id, token = await _seed_invalid_role_agent(db, service)
        with pytest.raises(PermissionError):
            await service.authenticate(token)

        invalid_role_events = [
            e for e in events if "unknown role" in e.reason and e.member_id == member_id
        ]
        assert len(invalid_role_events) == 1, (
            f"invalid-role 거부 시 정확히 1건의 MemberAuthFailedEvent 가 "
            f"발행되어야 한다 — 현재 events: {events!r}"
        )
        assert "oracle_invalid_role" in invalid_role_events[0].reason

    async def test_valid_role_token_passes_regression(
        self, service: MemberService
    ) -> None:
        """``MemberRole.DEFAULT`` 토큰은 정상 통과 (회귀)."""
        _, token = await service.register("agent-ok", MemberType.AGENT)
        member = await service.authenticate(token)
        assert member.member_id == "agent-ok"
        assert member.role == "default"

    async def test_master_role_token_passes_regression(
        self, service: MemberService
    ) -> None:
        """``MemberRole.MASTER`` 토큰은 정상 통과 (회귀)."""
        _, token, _ = await service.bootstrap_master("owner", "pass123")
        member = await service.authenticate(token)
        assert member.role == "master"

    async def test_admin_role_token_passes_regression(
        self, service: MemberService
    ) -> None:
        """``MemberRole.ADMIN`` 토큰은 정상 통과 (회귀)."""
        await service.bootstrap_master("owner", "pass123")
        _, token = await service.register(
            "admin-01",
            MemberType.HUMAN,
            role=MemberRole.ADMIN,
            registered_by="owner",
        )
        member = await service.authenticate(token)
        assert member.role == "admin"


# ── Service: password auth ─────────────────────────────────────────


class TestAuthenticatePasswordInvalidRole:
    """``MemberService.authenticate_password`` 가 invalid-role 을 거부."""

    async def test_invalid_role_password_raises_permission_error(
        self, service: MemberService, db: Database
    ) -> None:
        member_id, _token = await _seed_invalid_role_human(db, service, "pass123")
        with pytest.raises(PermissionError, match="invalid role"):
            await service.authenticate_password(member_id, "pass123")

    async def test_invalid_role_password_publishes_auth_failed_event(
        self, service: MemberService, db: Database, eventbus: EventBus
    ) -> None:
        events: list[MemberAuthFailedEvent] = []
        eventbus.subscribe(MemberAuthFailedEvent, lambda e: events.append(e))

        member_id, _ = await _seed_invalid_role_human(db, service, "pass123")
        with pytest.raises(PermissionError):
            await service.authenticate_password(member_id, "pass123")

        invalid_role_events = [
            e for e in events if "unknown role" in e.reason and e.member_id == member_id
        ]
        assert len(invalid_role_events) == 1, (
            f"invalid-role 거부 시 정확히 1건의 MemberAuthFailedEvent 가 "
            f"발행되어야 한다 — 현재 events: {events!r}"
        )

    async def test_valid_master_password_passes_regression(
        self, service: MemberService
    ) -> None:
        """master 의 정상 password 는 회귀 없이 통과."""
        await service.bootstrap_master("owner", "pass123")
        member = await service.authenticate_password("owner", "pass123")
        assert member.member_id == "owner"
        assert member.role == "master"


# ── Cache equivalence (drift 회귀) ─────────────────────────────────


class TestValidMemberRolesCacheEquivalence:
    """``_VALID_MEMBER_ROLES`` 모듈 캐시가 ``MemberRole`` SSOT 와 일치한다.

    이 회귀가 깨지면 enum 에 새 멤버를 추가했을 때 auth read-path 가
    silently 거부할 수 있다. SSOT drift 의 자동 알람.
    """

    def test_cache_matches_member_role_enum(self) -> None:
        assert _VALID_MEMBER_ROLES == {r.value for r in MemberRole}

    def test_cache_contains_known_roles(self) -> None:
        assert "master" in _VALID_MEMBER_ROLES
        assert "admin" in _VALID_MEMBER_ROLES
        assert "default" in _VALID_MEMBER_ROLES

    def test_cache_excludes_unknown_roles(self) -> None:
        assert "oracle_invalid_role" not in _VALID_MEMBER_ROLES
        assert "owner" not in _VALID_MEMBER_ROLES  # frontend display-only
        assert "" not in _VALID_MEMBER_ROLES


# ── HTTP: Fakes for /api/auth/me + RequireAuth fallback ────────────


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
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}

    def add(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    async def validate(self, session_id: str) -> dict | None:
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-01-01T00:00:00Z"}


class FakeMemberServiceHTTP:
    """Bearer 인증 + 세션 fallback 멤버 조회를 모두 지원하는 Fake.

    실제 ``MemberService.authenticate`` 의 invariant 를 답습한다:
    - 토큰 미존재 → ``PermissionError``
    - 비ACTIVE 멤버 → ``PermissionError``
    - **role 이 ``MemberRole`` SSOT 외이면 ``PermissionError``** (#1466)
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        status: str = MemberStatus.ACTIVE.value,
        member_type: str = "agent",
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            type=member_type,
            role=role,
            status=status,
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
        if member.status != MemberStatus.ACTIVE.value:
            raise PermissionError("inactive member")
        # #1466: AuthService._assert_member_role_known 동치.
        valid = {r.value for r in MemberRole}
        if member.role not in valid:
            raise PermissionError(f"auth principal invalid role: {member.role!r}")
        return member

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)

    async def update_last_active(self, member_id: str) -> None:
        return None


@pytest.fixture(autouse=True)
def _clear_throttle_cache() -> None:
    """TokenAuthMiddleware throttle 캐시 초기화."""
    _ta_mod._last_updated.clear()


@pytest.fixture
def http_member_service() -> FakeMemberServiceHTTP:
    svc = FakeMemberServiceHTTP()
    # 정상 role
    svc.add(
        "master-01",
        token="ante_hk_master",
        role="master",
        member_type="human",
    )
    svc.add("agent-default", token="ante_ak_default", role="default")
    # legacy invalid role (#1466 재현)
    svc.add(
        "agent-invalid",
        token="ante_ak_invalid",
        role="oracle_invalid_role",
    )
    svc.add(
        "human-invalid",
        token="ante_hk_invalid",
        role="oracle_invalid_role",
        member_type="human",
    )
    return svc


@pytest.fixture
def http_session_service() -> FakeSessionService:
    svc = FakeSessionService()
    svc.add("session-master", "master-01")
    svc.add("session-invalid-role", "agent-invalid")
    svc.add("session-invalid-human", "human-invalid")
    return svc


@pytest.fixture
def http_client(
    http_member_service: FakeMemberServiceHTTP,
    http_session_service: FakeSessionService,
) -> TestClient:
    audit_logger = AsyncMock()
    audit_logger.log = AsyncMock()
    app = create_app(
        member_service=http_member_service,
        session_service=http_session_service,
        audit_logger=audit_logger,
    )
    return TestClient(app)


# ── HTTP: /api/auth/me ─────────────────────────────────────────────


class TestAuthMeInvalidRole:
    """``GET /api/auth/me`` 가 invalid-role principal 을 거부."""

    def test_bearer_token_for_invalid_role_agent_returns_401(
        self, http_client: TestClient
    ) -> None:
        """Bearer token 경로: TokenAuthMiddleware 가 ``authenticate`` 실패로
        ``request.state.member`` 를 부착하지 않으므로 self-auth 라우트가 401.
        """
        resp = http_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer ante_ak_invalid"},
        )
        assert resp.status_code == 401, resp.text

    def test_session_cookie_for_invalid_role_returns_401(
        self, http_client: TestClient
    ) -> None:
        """세션 쿠키 경로: 라우트가 직접 멤버 조회 후 role 게이트로 401."""
        http_client.cookies.set("ante_session", "session-invalid-role")
        resp = http_client.get("/api/auth/me")
        assert resp.status_code == 401, resp.text

    def test_bearer_token_for_valid_role_returns_200(
        self, http_client: TestClient
    ) -> None:
        """정상 role bearer 는 200 + 본인 정보 응답 (회귀)."""
        resp = http_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer ante_hk_master"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["member_id"] == "master-01"
        assert body["role"] == "master"

    def test_session_cookie_for_valid_role_returns_200(
        self, http_client: TestClient
    ) -> None:
        """정상 role 세션 쿠키는 200 (회귀)."""
        http_client.cookies.set("ante_session", "session-master")
        resp = http_client.get("/api/auth/me")
        assert resp.status_code == 200, resp.text
        assert resp.json()["role"] == "master"


# ── HTTP: protected route gate ─────────────────────────────────────


class TestProtectedRouteInvalidRoleGate:
    """보호된 라우트 (``/api/bots``) 의 인증 게이트가 invalid-role 차단."""

    def test_bearer_token_invalid_role_returns_401(
        self, http_client: TestClient
    ) -> None:
        """TokenAuthMiddleware ``authenticate`` 가 PermissionError → caller
        미부착 → RequireAuth 401.
        """
        resp = http_client.get(
            "/api/bots",
            headers={"Authorization": "Bearer ante_ak_invalid"},
        )
        assert resp.status_code == 401, resp.text

    def test_session_cookie_invalid_role_returns_401(
        self, http_client: TestClient
    ) -> None:
        """세션 fallback 단의 role 게이트가 invalid-role 거부 → 401."""
        http_client.cookies.set("ante_session", "session-invalid-role")
        resp = http_client.get("/api/bots")
        assert resp.status_code == 401, resp.text

    def test_session_cookie_invalid_role_human_returns_401(
        self, http_client: TestClient
    ) -> None:
        """human + invalid-role 세션도 동일하게 거부."""
        http_client.cookies.set("ante_session", "session-invalid-human")
        resp = http_client.get("/api/bots")
        assert resp.status_code == 401, resp.text

    def test_bearer_token_valid_role_not_401(self, http_client: TestClient) -> None:
        """정상 role bearer 는 인증 게이트 통과 (401 아님)."""
        resp = http_client.get(
            "/api/bots",
            headers={"Authorization": "Bearer ante_hk_master"},
        )
        assert resp.status_code != 401, resp.text

    def test_session_cookie_valid_role_not_401(self, http_client: TestClient) -> None:
        """정상 role 세션은 인증 게이트 통과 (401 아님)."""
        http_client.cookies.set("ante_session", "session-master")
        resp = http_client.get("/api/bots")
        assert resp.status_code != 401, resp.text


# ── HTTP: list/get tolerance (#1468 비목표 보존) ───────────────────


class TestMemberListGetToleranceForInvalidRole:
    """``GET /api/members`` 는 invalid-role row 를 그대로 노출 (cleanup 가능).

    #1468 가 cleanup 책임을 가지므로 본 PR 은 read 표면을 깨면 안 된다.
    """

    def test_list_members_exposes_invalid_role_rows(
        self, http_client: TestClient, http_member_service: FakeMemberServiceHTTP
    ) -> None:
        # FakeMemberServiceHTTP.list_members 가 없으므로 추가 구현
        async def list_members(**kwargs: Any) -> list[FakeMember]:
            return list(http_member_service._members.values())

        async def count(**kwargs: Any) -> int:
            return len(http_member_service._members)

        http_member_service.list_members = list_members  # type: ignore[attr-defined]
        http_member_service.count = count  # type: ignore[attr-defined]

        resp = http_client.get(
            "/api/members",
            headers={"Authorization": "Bearer ante_hk_master"},
        )
        assert resp.status_code == 200, resp.text
        items = resp.json().get("members") or resp.json().get("items") or []
        roles = {item["role"] for item in items}
        assert "oracle_invalid_role" in roles, (
            "GET /api/members 가 invalid-role row 를 그대로 노출해야 한다 "
            "(cleanup 책임은 #1468)"
        )
