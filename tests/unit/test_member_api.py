"""멤버 관리 API 테스트."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

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
    """테스트용 MemberService stub."""

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._token_counter = 0

    async def list(
        self,
        member_type: str | None = None,
        org: str | None = None,
        status: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[FakeMember]:
        result = list(self._members.values())
        if member_type:
            result = [m for m in result if m.type == member_type]
        if org:
            result = [m for m in result if m.org == org]
        if status:
            result = [m for m in result if m.status == status]
        return result[offset : offset + limit]

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

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)

    async def suspend(self, member_id: str, suspended_by: str = "") -> FakeMember:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        if member.role == "master":
            raise PermissionError("Master는 정지할 수 없습니다")
        member.status = "suspended"
        return member

    async def reactivate(self, member_id: str, reactivated_by: str = "") -> FakeMember:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.status = "active"
        return member

    async def revoke(self, member_id: str, revoked_by: str = "") -> FakeMember:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        if member.role == "master":
            raise PermissionError("Master는 폐기할 수 없습니다")
        member.status = "revoked"
        return member

    async def rotate_token(
        self, member_id: str, rotated_by: str = ""
    ) -> tuple[FakeMember, str]:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> FakeMember:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.scopes = scopes
        return member


@pytest.fixture
def member_service():
    return FakeMemberService()


@pytest.fixture
def client(member_service):
    app = create_app(member_service=member_service)
    return TestClient(app)


class TestListMembers:
    def test_empty_list(self, client):
        """멤버 없을 때 빈 목록."""
        resp = client.get("/api/members")
        assert resp.status_code == 200
        assert resp.json()["members"] == []

    def test_list_with_data(self, client, member_service):
        """멤버 목록 반환."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", type="agent", name="테스트 에이전트"
        )
        resp = client.get("/api/members")
        assert resp.status_code == 200
        assert len(resp.json()["members"]) == 1

    def test_filter_by_type(self, client, member_service):
        """타입 필터."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", type="agent"
        )
        member_service._members["user-01"] = FakeMember(
            member_id="user-01", type="human"
        )
        resp = client.get("/api/members?type=agent")
        assert resp.status_code == 200
        assert len(resp.json()["members"]) == 1
        assert resp.json()["members"][0]["member_id"] == "agent-01"


class TestCreateMember:
    def test_register_success(self, client):
        """멤버 등록 + 토큰 반환."""
        resp = client.post(
            "/api/members",
            json={
                "member_id": "agent-01",
                "member_type": "agent",
                "name": "테스트 에이전트",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["member"]["member_id"] == "agent-01"
        assert "token" in data
        assert data["token"].startswith("ante_ak_")

    def test_register_duplicate(self, client, member_service):
        """중복 등록 → 400."""
        member_service._members["agent-01"] = FakeMember(member_id="agent-01")
        resp = client.post(
            "/api/members",
            json={"member_id": "agent-01", "member_type": "agent"},
        )
        assert resp.status_code == 400


class TestGetMember:
    def test_get_existing(self, client, member_service):
        """멤버 상세 조회."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", name="에이전트"
        )
        resp = client.get("/api/members/agent-01")
        assert resp.status_code == 200
        assert resp.json()["member"]["member_id"] == "agent-01"

    def test_get_nonexistent(self, client):
        """존재하지 않는 멤버 → 404."""
        resp = client.get("/api/members/nonexistent")
        assert resp.status_code == 404


class TestMemberLifecycle:
    def test_suspend_reactivate(self, client, member_service):
        """정지 → 재활성화 lifecycle."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", status="active"
        )

        resp = client.post("/api/members/agent-01/suspend")
        assert resp.status_code == 200
        assert resp.json()["member"]["status"] == "suspended"

        resp = client.post("/api/members/agent-01/reactivate")
        assert resp.status_code == 200
        assert resp.json()["member"]["status"] == "active"

    def test_revoke(self, client, member_service):
        """영구 폐기."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", status="active"
        )
        resp = client.post("/api/members/agent-01/revoke")
        assert resp.status_code == 200
        assert resp.json()["member"]["status"] == "revoked"

    def test_master_revoke_forbidden(self, client, member_service):
        """master 본인 revoke → 403."""
        member_service._members["master"] = FakeMember(
            member_id="master", role="master"
        )
        resp = client.post("/api/members/master/revoke")
        assert resp.status_code == 403


class TestTokenManagement:
    def test_rotate_token(self, client, member_service):
        """토큰 재발급."""
        member_service._members["agent-01"] = FakeMember(member_id="agent-01")
        resp = client.post("/api/members/agent-01/rotate-token")
        assert resp.status_code == 200
        assert "token" in resp.json()

    def test_rotate_nonexistent(self, client):
        """존재하지 않는 멤버 → 404."""
        resp = client.post("/api/members/nonexistent/rotate-token")
        assert resp.status_code == 404


class TestScopesUpdate:
    def test_update_scopes(self, client, member_service):
        """권한 범위 변경."""
        member_service._members["agent-01"] = FakeMember(member_id="agent-01")
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": ["trade:read", "trade:write"]},
        )
        assert resp.status_code == 200
        assert resp.json()["member"]["scopes"] == ["trade:read", "trade:write"]
