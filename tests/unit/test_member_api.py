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
        result = self._filtered(member_type=member_type, org=org, status=status)
        return result[offset : offset + limit]

    async def count(
        self,
        member_type: str | None = None,
        org: str | None = None,
        status: str | None = None,
    ) -> int:
        return len(self._filtered(member_type=member_type, org=org, status=status))

    def _filtered(
        self,
        member_type: str | None = None,
        org: str | None = None,
        status: str | None = None,
    ) -> list[FakeMember]:
        result = list(self._members.values())
        if member_type:
            result = [m for m in result if m.type == member_type]
        if org:
            result = [m for m in result if m.org == org]
        if status:
            result = [m for m in result if m.status == status]
        return result

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

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        if member.type != "human":
            raise PermissionError("human 멤버만 비밀번호를 변경할 수 있습니다")
        if member.password_hash and member.password_hash != old_password:
            raise PermissionError("현재 패스워드가 일치하지 않습니다")
        member.password_hash = new_password

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

    def test_total_is_full_count_not_page_size(self, client, member_service):
        """total은 페이지 크기가 아닌 전체 건수를 반환해야 한다."""
        for i in range(5):
            member_service._members[f"agent-{i:02d}"] = FakeMember(
                member_id=f"agent-{i:02d}", type="agent"
            )
        resp = client.get("/api/members?limit=2&offset=0")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["members"]) == 2
        assert data["total"] == 5

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


class TestChangePassword:
    def test_change_password_success(self, client, member_service):
        """비밀번호 변경 성공."""
        member_service._members["user-01"] = FakeMember(
            member_id="user-01", type="human", password_hash="old123"
        )
        resp = client.patch(
            "/api/members/user-01/password",
            json={"old_password": "old123", "new_password": "new456"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_change_password_wrong_old(self, client, member_service):
        """기존 비밀번호 불일치 → 403."""
        member_service._members["user-01"] = FakeMember(
            member_id="user-01", type="human", password_hash="old123"
        )
        resp = client.patch(
            "/api/members/user-01/password",
            json={"old_password": "wrong", "new_password": "new456"},
        )
        assert resp.status_code == 403

    def test_change_password_nonexistent(self, client):
        """존재하지 않는 멤버 → 404."""
        resp = client.patch(
            "/api/members/nonexistent/password",
            json={"old_password": "old", "new_password": "new"},
        )
        assert resp.status_code == 404

    def test_change_password_agent_forbidden(self, client, member_service):
        """agent 멤버 비밀번호 변경 → 403."""
        member_service._members["agent-01"] = FakeMember(
            member_id="agent-01", type="agent"
        )
        resp = client.patch(
            "/api/members/agent-01/password",
            json={"old_password": "old", "new_password": "new"},
        )
        assert resp.status_code == 403


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


class TestCallerIdPropagation:
    """request.state.member_id가 서비스 호출로 전달되는지 검증."""

    def test_register_passes_caller_id(self, member_service):
        """인증된 사용자의 member_id가 registered_by로 전달."""
        captured: dict[str, str] = {}
        original_register = member_service.register

        async def spy_register(**kwargs):
            captured["registered_by"] = kwargs.get("registered_by", "")
            return await original_register(**kwargs)

        member_service.register = spy_register

        app = create_app(member_service=member_service)

        @app.middleware("http")
        async def inject_member_id(request, call_next):
            request.state.member_id = "master-user"
            return await call_next(request)

        client = TestClient(app)
        resp = client.post(
            "/api/members",
            json={"member_id": "new-agent", "member_type": "agent"},
        )
        assert resp.status_code == 201
        assert captured["registered_by"] == "master-user"

    def test_update_scopes_passes_caller_id(self, member_service):
        """인증된 사용자의 member_id가 updated_by로 전달."""
        captured: dict[str, str] = {}
        original_update = member_service.update_scopes

        async def spy_update(member_id, scopes, updated_by=""):
            captured["updated_by"] = updated_by
            return await original_update(member_id, scopes, updated_by=updated_by)

        member_service.update_scopes = spy_update
        member_service._members["agent-01"] = FakeMember(member_id="agent-01")

        app = create_app(member_service=member_service)

        @app.middleware("http")
        async def inject_member_id(request, call_next):
            request.state.member_id = "master-user"
            return await call_next(request)

        client = TestClient(app)
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": ["trade:read"]},
        )
        assert resp.status_code == 200
        assert captured["updated_by"] == "master-user"

    def test_no_auth_passes_empty_string(self, client, member_service):
        """인증 컨텍스트 없을 때 빈 문자열 전달 (내부 호출)."""
        captured: dict[str, str] = {}
        original_register = member_service.register

        async def spy_register(**kwargs):
            captured["registered_by"] = kwargs.get("registered_by", "")
            return await original_register(**kwargs)

        member_service.register = spy_register
        resp = client.post(
            "/api/members",
            json={"member_id": "new-agent", "member_type": "agent"},
        )
        assert resp.status_code == 201
        assert captured["registered_by"] == ""


class TestPermissionDeniedErrorHandling:
    """PermissionDeniedError가 403으로 처리되는지 검증."""

    def test_register_permission_denied(self, client, member_service):
        """PermissionDeniedError → 403."""
        from ante.member.errors import PermissionDeniedError

        async def raise_pde(**kwargs):
            raise PermissionDeniedError("'register'은(는) master만 수행할 수 있습니다.")

        member_service.register = raise_pde
        resp = client.post(
            "/api/members",
            json={"member_id": "new-agent", "member_type": "agent"},
        )
        assert resp.status_code == 403

    def test_update_scopes_permission_denied(self, client, member_service):
        """update_scopes PermissionDeniedError → 403."""
        from ante.member.errors import PermissionDeniedError

        member_service._members["agent-01"] = FakeMember(member_id="agent-01")

        async def raise_pde(member_id, scopes, updated_by=""):
            raise PermissionDeniedError(
                "'update_scopes'은(는) master만 수행할 수 있습니다."
            )

        member_service.update_scopes = raise_pde
        resp = client.put(
            "/api/members/agent-01/scopes",
            json={"scopes": ["trade:read"]},
        )
        assert resp.status_code == 403
