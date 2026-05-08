"""POST /api/members 인증 가드 테스트 (issue #1339).

create_member 라우트는 인증된 master 호출자만 사용할 수 있어야 한다.
- Authorization 헤더 없음 또는 invalid token: 401
- 인증된 master: 201
- 인증된 non-master: 403 (PermissionError 매핑)
- 401 응답 시 service.register는 호출되지 않아야 한다.
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


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member("master-user", token="master-token", role="master")
    svc.add_member("agent-01", token="agent-token", role="default")
    return svc


@pytest.fixture
def client(member_service: FakeMemberService) -> TestClient:
    app = create_app(member_service=member_service)
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
