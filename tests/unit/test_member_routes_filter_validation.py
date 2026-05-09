"""GET /api/members?type=&status= 쿼리 파라미터 검증 테스트 (#1358).

SSOT:
- ``src/ante/member/models.py::MemberType`` (StrEnum: human/agent).
- ``src/ante/member/models.py::MemberStatus`` (StrEnum:
  active/suspended/revoked).
- ``src/ante/web/routes/members.py::list_members``.

검증 대상 (본 PR scope):
- 알려진 ``MemberType`` 값(human/agent)과 ``MemberStatus``
  값(active/suspended/revoked)은 200.
- 미정의 type 값은 422.
- 미정의 status 값은 422.
- ``type``+``status`` 둘 다 invalid면 422.
- 둘 다 생략은 200 (전체 목록).
"""

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
    """list_members / count만 사용하는 최소 stub."""

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}

    async def list_members(
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
            result = [m for m in result if m.type == str(member_type)]
        if org:
            result = [m for m in result if m.org == org]
        if status:
            result = [m for m in result if m.status == str(status)]
        return result


@pytest.fixture
def member_service():
    svc = FakeMemberService()
    # 다양한 타입/상태 시드.
    svc._members["agent-active"] = FakeMember(
        member_id="agent-active", type="agent", status="active"
    )
    svc._members["agent-suspended"] = FakeMember(
        member_id="agent-suspended", type="agent", status="suspended"
    )
    svc._members["human-active"] = FakeMember(
        member_id="human-active", type="human", status="active"
    )
    svc._members["human-revoked"] = FakeMember(
        member_id="human-revoked", type="human", status="revoked"
    )
    return svc


@pytest.fixture
def client(member_service):
    app = create_app(member_service=member_service)
    return TestClient(app)


class TestListMembersTypeFilter:
    """GET /api/members?type= 쿼리 파라미터 검증 (#1358)."""

    def test_type_human_returns_200(self, client):
        res = client.get("/api/members?type=human")
        assert res.status_code == 200, res.text
        ids = {m["member_id"] for m in res.json()["members"]}
        assert ids == {"human-active", "human-revoked"}

    def test_type_agent_returns_200(self, client):
        res = client.get("/api/members?type=agent")
        assert res.status_code == 200, res.text
        ids = {m["member_id"] for m in res.json()["members"]}
        assert ids == {"agent-active", "agent-suspended"}

    def test_type_unknown_value_returns_422(self, client):
        """알 수 없는 type은 422 (200 빈 목록 아님)."""
        res = client.get("/api/members?type=oracle_invalid")
        assert res.status_code == 422, res.text


class TestListMembersStatusFilter:
    """GET /api/members?status= 쿼리 파라미터 검증 (#1358)."""

    def test_status_active_returns_200(self, client):
        res = client.get("/api/members?status=active")
        assert res.status_code == 200, res.text
        ids = {m["member_id"] for m in res.json()["members"]}
        assert ids == {"agent-active", "human-active"}

    def test_status_suspended_returns_200(self, client):
        res = client.get("/api/members?status=suspended")
        assert res.status_code == 200, res.text
        ids = {m["member_id"] for m in res.json()["members"]}
        assert ids == {"agent-suspended"}

    def test_status_revoked_returns_200(self, client):
        res = client.get("/api/members?status=revoked")
        assert res.status_code == 200, res.text
        ids = {m["member_id"] for m in res.json()["members"]}
        assert ids == {"human-revoked"}

    def test_status_unknown_value_returns_422(self, client):
        res = client.get("/api/members?status=oracle_invalid")
        assert res.status_code == 422, res.text


class TestListMembersBothInvalid:
    def test_both_invalid_returns_422(self, client):
        """type+status 모두 invalid면 422."""
        res = client.get("/api/members?type=oracle_invalid&status=oracle_invalid")
        assert res.status_code == 422, res.text


class TestListMembersFiltersOmitted:
    def test_filters_omitted_returns_all(self, client):
        """type/status 미제공은 전체 목록 200."""
        res = client.get("/api/members")
        assert res.status_code == 200, res.text
        assert res.json()["total"] == 4
