"""POST /api/members 인증 가드 테스트 (issue #1339).

create_member 라우트는 인증된 master 호출자만 사용할 수 있어야 한다.
- Authorization 헤더 없음 또는 invalid token + 세션 쿠키 없음: 401
- 인증된 master (Bearer 또는 세션 쿠키): 201
- 인증된 non-master: 403 (PermissionError 매핑)
- 401 응답 시 service.register는 호출되지 않아야 한다.

대시보드 사용자는 패스워드 로그인 후 ``ante_session`` 쿠키만 가지고
``POST /api/members``를 호출하므로 세션 쿠키 인증 경로도 함께 검증한다
(#1339 P1 — Codex finding).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.member.errors import PermissionDeniedError  # noqa: E402
from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeMember:
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


class FakeMemberService:
    """테스트용 MemberService stub.

    토큰 → member_id 매핑으로 authenticate를 흉내내고,
    register 호출 횟수를 추적한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}  # token → member_id
        self._token_counter = 0
        self.register_calls: list[dict[str, object]] = []

    def add_member(
        self,
        member_id: str,
        token: str,
        role: str = "default",
        member_type: str = "agent",
    ) -> FakeMember:
        """테스트용 멤버 + 토큰 등록."""
        member = FakeMember(member_id=member_id, role=role, type=member_type)
        self._members[member_id] = member
        self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        """토큰 인증 (TokenAuthMiddleware가 호출)."""
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def get(self, member_id: str) -> FakeMember | None:
        """``RequireAuthMiddleware`` (#1403)가 세션 fallback의 ACTIVE 검증을 위해
        호출한다. stub은 등록된 멤버 dict에서 단순 조회한다.
        """
        return self._members.get(member_id)

    async def update_last_active(self, member_id: str) -> None:
        """TokenAuthMiddleware가 호출하는 throttled update no-op."""
        return None

    async def register(
        self,
        member_id: str,
        member_type: str,
        role: str = "default",
        org: str = "default",
        name: str = "",
        scopes: list[str] | None = None,
        registered_by: str = "",
        **kwargs: object,
    ) -> tuple[FakeMember, str]:
        self.register_calls.append(
            {
                "member_id": member_id,
                "registered_by": registered_by,
            }
        )
        # caller가 master가 아니면 PermissionDeniedError (real service 동작 모방)
        caller = self._members.get(registered_by)
        if caller is None or caller.role != "master":
            raise PermissionDeniedError("'register'은(는) master만 수행할 수 있습니다.")
        if member_id in self._members:
            raise ValueError(f"이미 존재하는 멤버: {member_id}")
        member = FakeMember(
            member_id=member_id,
            type=member_type,
            role=role,
            org=org,
            name=name,
            scopes=scopes or [],
            created_by=registered_by,
        )
        self._members[member_id] = member
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"


class FakeSessionService:
    """테스트용 SessionService stub.

    ``ante_session`` 쿠키 인증 경로(#1339 P1)를 검증하기 위해 session_id →
    member_id 매핑을 저장한다. 실제 SQLite 백엔드 의존성을 피한다.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}  # session_id → member_id
        self.validate_calls: list[str] = []

    def add_session(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    async def validate(self, session_id: str) -> dict | None:
        """session_id 매핑이 있으면 SessionService.validate와 동일한
        dict 형태(``{"member_id": ..., ...}``)를 반환, 없으면 None.
        """
        self.validate_calls.append(session_id)
        member_id = self._sessions.get(session_id)
        if member_id is None:
            return None
        return {"member_id": member_id, "created_at": "2026-05-08 00:00:00"}


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member("master-user", token="master-token", role="master")
    svc.add_member("agent-01", token="agent-token", role="default")
    return svc


@pytest.fixture
def session_service() -> FakeSessionService:
    svc = FakeSessionService()
    # master-user의 유효한 세션 (대시보드 로그인 후 발급된 쿠키 시뮬레이션).
    svc.add_session("master-session-id", member_id="master-user")
    # 일반 agent-01 멤버의 세션 (non-master cookie auth 검증용).
    svc.add_session("agent-session-id", member_id="agent-01")
    return svc


@pytest.fixture
def client(
    member_service: FakeMemberService,
    session_service: FakeSessionService,
) -> TestClient:
    app = create_app(
        member_service=member_service,
        session_service=session_service,
    )
    return TestClient(app)


def _payload() -> dict[str, object]:
    return {
        "member_id": "new-agent",
        "member_type": "agent",
        "role": "default",
        "org": "default",
        "name": "테스트",
    }


class TestCreateMemberAuthGuard:
    """POST /api/members 인증 가드 (issue #1339)."""

    def test_create_member_without_auth_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """Authorization 헤더 없이 호출 → 401, member 생성 안 됨."""
        resp = client.post("/api/members", json=_payload())
        assert resp.status_code == 401
        # member가 새로 추가되지 않아야 한다
        assert "new-agent" not in member_service._members

    def test_create_member_with_invalid_token_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """invalid Bearer token → 401."""
        resp = client.post(
            "/api/members",
            json=_payload(),
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert "new-agent" not in member_service._members

    def test_create_member_with_master_token_returns_201(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """master 토큰 → 201, member 생성 + token 반환."""
        resp = client.post(
            "/api/members",
            json=_payload(),
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["member"]["member_id"] == "new-agent"
        assert data["token"].startswith("ante_ak_")
        assert "new-agent" in member_service._members

    def test_create_member_with_non_master_token_returns_403(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증된 non-master → 403 (PermissionError 매핑)."""
        resp = client.post(
            "/api/members",
            json=_payload(),
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403
        assert "new-agent" not in member_service._members

    def test_create_member_unauthenticated_does_not_call_register(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """401 응답 시 svc.register는 호출되지 않아야 한다."""
        resp = client.post("/api/members", json=_payload())
        assert resp.status_code == 401
        assert member_service.register_calls == []

    def test_create_member_without_auth_returns_401_even_if_body_invalid(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 가드는 body validation보다 우선이어야 한다 (#1339 P2 Codex).

        Authorization 헤더 없음 + body에 필수 필드 누락 → 401 (NOT 422).

        FastAPI가 ``body: MemberCreateRequest`` 파라미터를 라우트 함수 호출 전에
        파싱·검증해 버리면, 인증 가드 진입 전에 422가 먼저 반환되어
        "missing or invalid Authorization header는 401" 계약이 깨진다.
        본 테스트가 이 회귀를 직접 잠근다.
        """
        # 필수 필드 ``member_id``, ``member_type`` 모두 누락된 invalid body.
        invalid_payload: dict[str, object] = {"role": "default"}
        resp = client.post("/api/members", json=invalid_payload)
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert member_service.register_calls == []

    def test_create_member_with_invalid_token_returns_401_even_if_body_invalid(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """Invalid token + invalid body → 401 (NOT 422). #1339 P2 Codex."""
        invalid_payload: dict[str, object] = {}
        resp = client.post(
            "/api/members",
            json=invalid_payload,
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, (
            f"인증 실패가 body validation보다 우선이어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert member_service.register_calls == []

    def test_create_member_authenticated_with_invalid_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + body에 필수 필드 누락 → 422 (정상 검증 경로)."""
        invalid_payload: dict[str, object] = {"role": "default"}  # 필수 필드 누락.
        resp = client.post(
            "/api/members",
            json=invalid_payload,
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert member_service.register_calls == []

    # ── 세션 쿠키 인증 (#1339 P1 — 대시보드 axios 호환) ────────────────

    def test_create_member_with_valid_session_cookie_succeeds(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        session_service: FakeSessionService,
    ) -> None:
        """master 멤버의 ``ante_session`` 쿠키만으로 호출 → 201.

        대시보드는 패스워드 로그인 후 axios에 ``Authorization`` 헤더를 추가
        하지 않고 ``ante_session`` HttpOnly 쿠키만 가진 상태로 POST한다.
        세션 쿠키가 유효한 master를 가리키면 토큰 인증과 동일하게 통과해야
        한다.
        """
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/members", json=_payload())
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["member"]["member_id"] == "new-agent"
        assert data["token"].startswith("ante_ak_")
        assert "new-agent" in member_service._members
        # session_service.validate가 실제로 호출됐는지 확인.
        assert "master-session-id" in session_service.validate_calls
        # registered_by가 세션의 member_id로 설정됐는지 확인.
        assert member_service.register_calls[-1]["registered_by"] == "master-user"

    def test_create_member_with_invalid_session_cookie_returns_401(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        session_service: FakeSessionService,
    ) -> None:
        """등록되지 않은 session_id를 가진 쿠키 → 401, register 미호출."""
        client.cookies.set("ante_session", "unknown-session-id")
        resp = client.post("/api/members", json=_payload())
        assert resp.status_code == 401, resp.text
        assert member_service.register_calls == []
        assert "new-agent" not in member_service._members
        # 세션 검증 시도는 한 번 일어나야 한다(가드가 cookie 분기를 탔는지 확인).
        assert "unknown-session-id" in session_service.validate_calls

    def test_create_member_with_session_cookie_non_master_returns_403(
        self,
        client: TestClient,
        member_service: FakeMemberService,
    ) -> None:
        """일반 멤버의 세션 쿠키 → 403 (PermissionError 매핑).

        세션 쿠키 인증은 통과(401 아님)하지만, ``MemberService.register``가
        master가 아닌 caller를 거부해서 403으로 매핑되어야 한다. 토큰 경로
        의 동등 케이스(``test_create_member_with_non_master_token_returns_403``)
        와 동일한 결과 보장.
        """
        client.cookies.set("ante_session", "agent-session-id")
        resp = client.post("/api/members", json=_payload())
        assert resp.status_code == 403, resp.text
        assert "new-agent" not in member_service._members
        # register는 호출됐어야 한다 (caller 결정 후 진입).
        assert len(member_service.register_calls) == 1
        assert member_service.register_calls[0]["registered_by"] == "agent-01"
