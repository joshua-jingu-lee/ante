"""세션 기반 인증 API 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402
from ante.web.session import SessionService  # noqa: E402


@dataclass
class FakeMember:
    """Bearer 토큰 인증 테스트용 가짜 멤버."""

    member_id: str
    type: str = "agent"
    role: str = "default"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
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


@pytest.fixture
async def db(tmp_path):
    from ante.core import Database

    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
async def session_service(db):
    svc = SessionService(db=db, ttl_hours=24)
    await svc.initialize()
    return svc


@pytest.fixture
async def member_service(db):
    from ante.eventbus.bus import EventBus
    from ante.member.service import MemberService

    eventbus = EventBus()
    svc = MemberService(db=db, eventbus=eventbus)
    await svc.initialize()

    # 테스트용 master 멤버 등록
    await svc.bootstrap_master(
        member_id="owner",
        password="test1234",
        name="대표",
        emoji="🦁",
    )
    return svc


@pytest.fixture
def app(member_service, session_service):
    return create_app(
        member_service=member_service,
        session_service=session_service,
    )


@pytest.fixture
def client(app):
    return TestClient(app)


# ── 로그인 ──────────────────────────────────────────────


class TestLogin:
    def test_login_success(self, client):
        """올바른 자격증명으로 로그인 성공."""
        resp = client.post(
            "/api/auth/login",
            json={"member_id": "owner", "password": "test1234"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_id"] == "owner"
        assert data["name"] == "대표"
        assert data["type"] == "human"
        assert "ante_session" in resp.cookies

    def test_login_wrong_password(self, client):
        """잘못된 패스워드로 401 반환."""
        resp = client.post(
            "/api/auth/login",
            json={"member_id": "owner", "password": "wrong"},
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["detail"] == "ID 또는 패스워드가 올바르지 않습니다"

    def test_login_nonexistent_user(self, client):
        """존재하지 않는 사용자로 401 반환."""
        resp = client.post(
            "/api/auth/login",
            json={"member_id": "nobody", "password": "test1234"},
        )
        assert resp.status_code == 401

    def test_login_missing_fields(self, client):
        """필수 필드 누락 시 422."""
        resp = client.post("/api/auth/login", json={})
        assert resp.status_code == 422


# ── 로그아웃 ──────────────────────────────────────────────


class TestLogout:
    def test_logout_clears_cookie(self, client):
        """로그아웃 시 쿠키 제거."""
        # 먼저 로그인
        login_resp = client.post(
            "/api/auth/login",
            json={"member_id": "owner", "password": "test1234"},
        )
        assert login_resp.status_code == 200

        # 로그아웃
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}

    def test_logout_without_session(self, client):
        """세션 없이 로그아웃해도 200."""
        resp = client.post("/api/auth/logout")
        assert resp.status_code == 200


# ── /me ──────────────────────────────────────────────


class TestMe:
    def test_me_authenticated(self, client):
        """로그인 후 /me로 사용자 정보 조회."""
        login_resp = client.post(
            "/api/auth/login",
            json={"member_id": "owner", "password": "test1234"},
        )
        assert login_resp.status_code == 200

        resp = client.get("/api/auth/me")
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_id"] == "owner"
        assert data["name"] == "대표"
        assert data["type"] == "human"
        assert data["emoji"] == "🦁"
        assert data["role"] == "master"

    def test_me_unauthenticated(self, client):
        """세션 없이 /me 접근 시 401."""
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401

    def test_me_after_logout(self, client):
        """로그아웃 후 /me 접근 시 401."""
        # 로그인
        client.post(
            "/api/auth/login",
            json={"member_id": "owner", "password": "test1234"},
        )
        # 로그아웃
        client.post("/api/auth/logout")
        # /me 시도
        resp = client.get("/api/auth/me")
        assert resp.status_code == 401


# ── 세션 서비스 ──────────────────────────────────────


class TestSessionService:
    async def test_create_and_validate(self, session_service):
        """세션 생성 후 유효성 확인."""
        session_id = await session_service.create(member_id="owner")
        session = await session_service.validate(session_id)
        assert session is not None
        assert session["member_id"] == "owner"

    async def test_validate_nonexistent(self, session_service):
        """존재하지 않는 세션은 None."""
        result = await session_service.validate("nonexistent")
        assert result is None

    async def test_delete_session(self, session_service):
        """세션 삭제 후 유효성 없음."""
        session_id = await session_service.create(member_id="owner")
        await session_service.delete(session_id)
        result = await session_service.validate(session_id)
        assert result is None

    async def test_expired_session(self, db):
        """만료된 세션은 None 반환."""
        svc = SessionService(db=db, ttl_hours=0)
        await svc.initialize()
        session_id = await svc.create(member_id="owner")
        result = await svc.validate(session_id)
        assert result is None

    async def test_cleanup_expired(self, db):
        """만료 세션 일괄 정리."""
        svc = SessionService(db=db, ttl_hours=0)
        await svc.initialize()
        await svc.create(member_id="user1")
        await svc.create(member_id="user2")
        count = await svc.cleanup_expired()
        assert count >= 2


# ── /me Bearer 토큰 인증 ─────────────────────────────


class TestMeBearerToken:
    """Bearer 토큰으로 /api/auth/me를 호출하는 테스트."""

    @pytest.fixture
    def agent_member(self) -> FakeMember:
        return FakeMember(
            member_id="agent-01",
            type="agent",
            role="default",
            name="테스트 에이전트",
            emoji="🤖",
        )

    @pytest.fixture
    def mock_member_service(self, agent_member: FakeMember):
        from unittest.mock import AsyncMock

        svc = AsyncMock()
        svc.authenticate = AsyncMock(return_value=agent_member)
        svc.update_last_active = AsyncMock()
        return svc

    @pytest.fixture
    def mock_session_service(self):
        from unittest.mock import AsyncMock

        svc = AsyncMock()
        svc.validate = AsyncMock(return_value=None)
        return svc

    @pytest.fixture
    def bearer_client(self, mock_member_service, mock_session_service):
        app = create_app(
            member_service=mock_member_service,
            session_service=mock_session_service,
        )
        return TestClient(app)

    def test_me_with_bearer_token(self, bearer_client, agent_member):
        """Bearer 토큰으로 /me 호출 시 200과 멤버 정보 반환."""
        resp = bearer_client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer ante_ak_test_token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["member_id"] == "agent-01"
        assert data["name"] == "테스트 에이전트"
        assert data["type"] == "agent"
        assert data["emoji"] == "🤖"
        assert data["role"] == "default"

    def test_me_with_invalid_bearer_token(
        self, mock_member_service, mock_session_service
    ):
        """유효하지 않은 Bearer 토큰으로 /me 호출 시 401."""
        from unittest.mock import AsyncMock

        mock_member_service.authenticate = AsyncMock(
            side_effect=PermissionError("인증 실패")
        )
        app = create_app(
            member_service=mock_member_service,
            session_service=mock_session_service,
        )
        client = TestClient(app)

        resp = client.get(
            "/api/auth/me",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert resp.status_code == 401

    def test_me_no_auth_returns_401(self, bearer_client):
        """인증 수단 없이 /me 호출 시 401."""
        resp = bearer_client.get("/api/auth/me")
        assert resp.status_code == 401
