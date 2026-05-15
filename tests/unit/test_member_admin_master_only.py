"""member admin mutation 표면 가드 master-only 회귀 테스트 (#1543).

#1542 spec 결정 (`docs/specs/web-api/11-route-scope-table.md`) 에 따라 member
admin mutation 7 web routes / 6 CLI commands 는 표면 가드에서 master-only 로
정렬되어야 한다. 이 invariant 는 다음 매트릭스로 검증한다:

- master Bearer (HUMAN+master) → 200/201 (정상 mutation 결과)
- ``member:admin`` scope 보유 agent → 403 + service 미호출
- non-master human (예: admin role) → 403 + service 미호출
- non-master agent without scope → 403 + service 미호출
- unauthenticated → 401 + service 미호출
- unauthenticated + invalid body → 401 (auth before validation)
- unauthenticated + invalid JSON → 401 (auth before parsing)

#1511 oracle drift 의 핵심 시그니처: 이전에는 ``member:admin`` agent 가
표면 가드를 통과해 ``MemberService._assert_master`` 가 런타임에서 거부했다.
본 패치 이후엔 표면 가드에서 즉시 차단되어 service 호출이 일어나지 않는다.

Case count (pytest collect 기준): **41 cases** =
  - 7 web routes × 5 personas (master / member:admin agent / non-master
    human / non-master agent / unauth) = 35 (parametrize 확장)
  - + 6 standalone (TestAuthBeforeBodyValidation: create-invalid-body /
    create-malformed-json / update_scopes-invalid-body /
    change_password-invalid-body / change_password-invalid-credential /
    member:admin-agent-invalid-body) = 6
  - 합계 41
이전 보고서에 53 cases 로 잘못 기재되었던 것을 #1543 Codex 브랜치 리뷰
finding 2 에 따라 41 로 정정한다 (matrix 자체는 변경 없음 — 산수 오류 정정).
CLI 측 회귀는 별도 ``test_cli_member_master_only.py`` (24 cases) 에서 다룬다.
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
    """master-only 표면 가드 회귀용 stub.

    토큰 → member_id 매핑으로 ``authenticate`` 흉내. mutation 메서드별 호출
    회수를 추적해, 표면 가드가 service 호출을 차단했는지 확인한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}
        self._token_counter = 0
        self.register_calls: list[dict[str, object]] = []
        self.suspend_calls: list[dict[str, str]] = []
        self.reactivate_calls: list[dict[str, str]] = []
        self.revoke_calls: list[dict[str, str]] = []
        self.rotate_calls: list[dict[str, str]] = []
        self.update_scopes_calls: list[dict[str, object]] = []
        self.change_password_calls: list[dict[str, str]] = []

    def add_member(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        member_type: str = "agent",
        status: str = "active",
        scopes: list[str] | None = None,
        password_hash: str = "",
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            role=role,
            type=member_type,
            status=status,
            scopes=list(scopes) if scopes else [],
            password_hash=password_hash,
        )
        self._members[member_id] = member
        if token:
            self._tokens[token] = member_id
        return member

    async def authenticate(self, token: str) -> FakeMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("유효하지 않은 토큰")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> FakeMember | None:
        return self._members.get(member_id)

    def _assert_master_or_raise(self, caller_id: str, action: str) -> None:
        """defense-in-depth — 정상 흐름에서는 표면 가드가 먼저 차단한다."""
        caller = self._members.get(caller_id)
        if caller is None or caller.role != "master":
            raise PermissionDeniedError(
                f"'{action}'은(는) master만 수행할 수 있습니다."
            )

    async def register(self, **kwargs: object) -> tuple[FakeMember, str]:
        self.register_calls.append(dict(kwargs))
        registered_by = str(kwargs.get("registered_by", ""))
        self._assert_master_or_raise(registered_by, "register")
        member_id = str(kwargs.get("member_id", ""))
        member_type = str(kwargs.get("member_type", "agent"))
        member = FakeMember(
            member_id=member_id,
            type=member_type,
            role=str(kwargs.get("role", "default")),
        )
        self._members[member_id] = member
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"

    async def suspend(self, member_id: str, suspended_by: str = "") -> FakeMember:
        self.suspend_calls.append(
            {"member_id": member_id, "suspended_by": suspended_by}
        )
        self._assert_master_or_raise(suspended_by, "suspend")
        member = self._members[member_id]
        member.status = "suspended"
        return member

    async def reactivate(self, member_id: str, reactivated_by: str = "") -> FakeMember:
        self.reactivate_calls.append(
            {"member_id": member_id, "reactivated_by": reactivated_by}
        )
        self._assert_master_or_raise(reactivated_by, "reactivate")
        member = self._members[member_id]
        member.status = "active"
        return member

    async def revoke(self, member_id: str, revoked_by: str = "") -> FakeMember:
        self.revoke_calls.append({"member_id": member_id, "revoked_by": revoked_by})
        self._assert_master_or_raise(revoked_by, "revoke")
        member = self._members[member_id]
        member.status = "revoked"
        return member

    async def rotate_token(
        self, member_id: str, rotated_by: str = ""
    ) -> tuple[FakeMember, str]:
        self.rotate_calls.append({"member_id": member_id, "rotated_by": rotated_by})
        self._assert_master_or_raise(rotated_by, "rotate_token")
        self._token_counter += 1
        return self._members[member_id], f"ante_ak_{self._token_counter}"

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> FakeMember:
        self.update_scopes_calls.append(
            {"member_id": member_id, "scopes": list(scopes), "updated_by": updated_by}
        )
        self._assert_master_or_raise(updated_by, "update_scopes")
        member = self._members[member_id]
        member.scopes = list(scopes)
        return member

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        self.change_password_calls.append(
            {
                "member_id": member_id,
                "old_password": old_password,
                "new_password": new_password,
            }
        )
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.password_hash = new_password


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member(
        "master-user", token="master-token", role="master", member_type="human"
    )
    # ``member:admin`` scope 를 보유한 agent — 표면 가드는 거부해야 한다.
    svc.add_member(
        "agent-with-admin-scope",
        token="agent-admin-token",
        role="default",
        member_type="agent",
        scopes=["member:admin"],
    )
    # non-master human (admin role) — master 가 아니므로 표면 가드 거부.
    svc.add_member(
        "human-admin",
        token="human-admin-token",
        role="admin",
        member_type="human",
    )
    # non-master agent without scope.
    svc.add_member(
        "agent-no-scope",
        token="agent-no-scope-token",
        role="default",
        member_type="agent",
    )
    # mutation 대상 멤버
    svc.add_member("target-active", role="default", status="active")
    svc.add_member("target-suspended", role="default", status="suspended")
    svc.add_member(
        "target-human-active",
        role="default",
        member_type="human",
        status="active",
        password_hash="known-old-password",
    )
    return svc


@pytest.fixture
def client(member_service: FakeMemberService) -> TestClient:
    app = create_app(member_service=member_service)
    return TestClient(app)


# ── 라우트 헬퍼 ──────────────────────────────────────────────────────────


def _create(client: TestClient, headers: dict | None = None) -> httpx.Response:
    return client.post(
        "/api/members",
        json={"member_id": "new-agent-1543", "member_type": "agent"},
        headers=headers or {},
    )


def _suspend(client: TestClient, headers: dict | None = None) -> httpx.Response:
    return client.post("/api/members/target-active/suspend", headers=headers or {})


def _reactivate(client: TestClient, headers: dict | None = None) -> httpx.Response:
    return client.post(
        "/api/members/target-suspended/reactivate", headers=headers or {}
    )


def _revoke(client: TestClient, headers: dict | None = None) -> httpx.Response:
    return client.post("/api/members/target-active/revoke", headers=headers or {})


def _rotate(client: TestClient, headers: dict | None = None) -> httpx.Response:
    return client.post("/api/members/target-active/rotate-token", headers=headers or {})


def _update_scopes(
    client: TestClient,
    headers: dict | None = None,
    payload: dict | None = None,
) -> httpx.Response:
    return client.put(
        "/api/members/target-active/scopes",
        json=payload if payload is not None else {"scopes": ["data:read"]},
        headers=headers or {},
    )


def _change_password(
    client: TestClient,
    headers: dict | None = None,
    payload: dict | None = None,
) -> httpx.Response:
    return client.patch(
        "/api/members/target-human-active/password",
        json=payload
        if payload is not None
        else {"old_password": "known-old-password", "new_password": "new-password"},
        headers=headers or {},
    )


# (route_id, helper, calls_attr, expected_success_status)
ALL_ADMIN_MUTATION_ROUTES = [
    ("create", _create, "register_calls", 201),
    ("suspend", _suspend, "suspend_calls", 200),
    ("reactivate", _reactivate, "reactivate_calls", 200),
    ("revoke", _revoke, "revoke_calls", 200),
    ("rotate_token", _rotate, "rotate_calls", 200),
    ("update_scopes", _update_scopes, "update_scopes_calls", 200),
    ("change_password", _change_password, "change_password_calls", 200),
]


# ── master 성공 회귀 ─────────────────────────────────────────────────────


class TestMasterAllowed:
    """master Bearer 토큰 → 정상 mutation 통과."""

    @pytest.mark.parametrize(
        "name,call,calls_attr,expected_status",
        ALL_ADMIN_MUTATION_ROUTES,
        ids=[r[0] for r in ALL_ADMIN_MUTATION_ROUTES],
    )
    def test_master_bearer_succeeds(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
        expected_status: int,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer master-token"})
        assert resp.status_code == expected_status, (
            f"{name}: master Bearer 가 {expected_status} 가 아님 "
            f"({resp.status_code}: {resp.text})"
        )
        # service 까지 도달해야 한다.
        assert len(getattr(member_service, calls_attr)) >= 1, (
            f"{name}: master 통과 시 service 가 호출되어야 한다"
        )


# ── member:admin scope agent → 403 (#1543 핵심 회귀) ─────────────────────


class TestMemberAdminScopeAgent403:
    """``member:admin`` scope 보유 agent → 403 (master-only 표면 가드).

    #1511 oracle drift 의 핵심 시그니처. 이전에는 표면 가드가 ``member:admin``
    scope 를 통과시키고 ``MemberService._assert_master`` 가 런타임에서 거부했다
    (contract drift). 본 패치 이후 표면 가드에서 즉시 403 + service 미호출.
    """

    @pytest.mark.parametrize(
        "name,call,calls_attr,expected_status",
        ALL_ADMIN_MUTATION_ROUTES,
        ids=[r[0] for r in ALL_ADMIN_MUTATION_ROUTES],
    )
    def test_member_admin_scope_agent_returns_403_without_service_call(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
        expected_status: int,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer agent-admin-token"})
        assert resp.status_code == 403, (
            f"{name}: ``member:admin`` agent 가 403 이 아님 "
            f"({resp.status_code}: {resp.text})"
        )
        # 표면 가드가 service 호출 전에 차단해야 한다 (contract drift 회귀 보호).
        assert len(getattr(member_service, calls_attr)) == 0, (
            f"{name}: ``member:admin`` agent 차단 시 service mutation 호출되어선 "
            f"안 된다 — 호출 기록: {getattr(member_service, calls_attr)}"
        )


class TestNonMasterHuman403:
    """non-master human (admin role) → 403 + service 미호출."""

    @pytest.mark.parametrize(
        "name,call,calls_attr,expected_status",
        ALL_ADMIN_MUTATION_ROUTES,
        ids=[r[0] for r in ALL_ADMIN_MUTATION_ROUTES],
    )
    def test_non_master_human_returns_403_without_service_call(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
        expected_status: int,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer human-admin-token"})
        assert resp.status_code == 403, (
            f"{name}: non-master human 이 403 이 아님 ({resp.status_code}: {resp.text})"
        )
        assert len(getattr(member_service, calls_attr)) == 0


class TestNonMasterAgentNoScope403:
    """non-master agent without scope → 403 + service 미호출."""

    @pytest.mark.parametrize(
        "name,call,calls_attr,expected_status",
        ALL_ADMIN_MUTATION_ROUTES,
        ids=[r[0] for r in ALL_ADMIN_MUTATION_ROUTES],
    )
    def test_non_master_agent_returns_403_without_service_call(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
        expected_status: int,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer agent-no-scope-token"})
        assert resp.status_code == 403, (
            f"{name}: non-master agent 가 403 이 아님 ({resp.status_code}: {resp.text})"
        )
        assert len(getattr(member_service, calls_attr)) == 0


# ── unauthenticated → 401 + auth-first 회귀 ──────────────────────────────


class TestUnauthenticated401:
    """인증 없음 → 401 + service 미호출."""

    @pytest.mark.parametrize(
        "name,call,calls_attr,expected_status",
        ALL_ADMIN_MUTATION_ROUTES,
        ids=[r[0] for r in ALL_ADMIN_MUTATION_ROUTES],
    )
    def test_unauthenticated_returns_401_without_service_call(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
        expected_status: int,
    ) -> None:
        resp = call(client)
        assert resp.status_code == 401, (
            f"{name}: 인증 없음 이 401 이 아님 ({resp.status_code}: {resp.text})"
        )
        assert len(getattr(member_service, calls_attr)) == 0


class TestAuthBeforeBodyValidation:
    """인증 가드는 body validation 보다 먼저 실행된다.

    각 라우트가 raw-body 패턴으로 ``Depends(require_master_caller)`` 를 우선
    수행하는지 회귀 검증. unauthenticated + invalid body → 401 (NOT 422).
    create / update_scopes / change_password 가 raw body 파싱 패턴을 사용하므로
    핵심 대상이다.
    """

    def test_create_unauth_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post("/api/members", json={"unexpected": "field"})
        assert resp.status_code == 401, resp.text
        assert member_service.register_calls == []

    def test_create_unauth_malformed_json_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert member_service.register_calls == []

    def test_update_scopes_unauth_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"not_scopes": ["x"]},
        )
        assert resp.status_code == 401
        assert member_service.update_scopes_calls == []

    def test_change_password_unauth_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={"not_old_password": "x"},
        )
        assert resp.status_code == 401
        assert member_service.change_password_calls == []

    def test_change_password_unauth_invalid_credential_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """unauth + wrong old_password → 401 (credential check 우회 차단).

        oracle A7 (#1377) 핵심 시그니처가 #1543 master-only 정렬 이후에도
        보존되는지 확인한다.
        """
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={"old_password": "wrong", "new_password": "anything"},
        )
        assert resp.status_code == 401
        assert member_service.change_password_calls == []

    def test_member_admin_scope_agent_invalid_body_returns_403(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """``member:admin`` agent + invalid body → 403 (auth 가드가 body 보다 먼저).

        agent 는 인증은 통과하지만 표면 가드가 거부하므로 body validation 단계
        (422) 가 아닌 권한 거부 (403) 가 응답된다.
        """
        resp = client.post(
            "/api/members",
            json={"unexpected": "field"},
            headers={"Authorization": "Bearer agent-admin-token"},
        )
        assert resp.status_code == 403, resp.text
        assert member_service.register_calls == []
