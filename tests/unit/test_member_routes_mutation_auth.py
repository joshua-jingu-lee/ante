"""POST/PUT/PATCH /api/members/{id}/* mutation 인증 가드 테스트
(issue #1351 + #1377).

수정 대상 mutation route는 인증된 master 호출자만 사용할 수 있어야 한다.
- ``POST /api/members/{id}/suspend``
- ``POST /api/members/{id}/reactivate``
- ``POST /api/members/{id}/revoke``
- ``POST /api/members/{id}/rotate-token``
- ``PUT  /api/members/{id}/scopes``
- ``PATCH /api/members/{id}/password`` (#1377 — oracle A7 finding)

각 라우트 × 인증 시나리오:
- Authorization 헤더 없음 + 세션 쿠키 없음 → 401
- invalid Bearer token → 401
- invalid 세션 쿠키 → 401
- ``session_service`` is None 배포 + Bearer 없음 → 401 (cookie fallback skip)
- 정상 Bearer master → 200
- 정상 ante_session master → 200 + ``request.state.member_id`` 갱신
- 인증된 non-master → 403 (PermissionDeniedError 매핑)
- master + 존재하지 않는 member → 404

401 응답 시 service mutation은 호출되지 않아야 한다 (early return).
특히 ``change_password``는 unauth + invalid old_password 조합에서 401이
credential check보다 우선되어야 한다 (#1377 oracle A7 시그니처).

#1339의 ``test_member_routes_create_auth.py`` 패턴을 그대로 답습한다.
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

    토큰 → member_id 매핑으로 ``authenticate``를 흉내내고, mutation 메서드별
    호출 횟수를 추적한다. 실 서비스의 master 검증을 모방해 caller가 master가
    아니면 ``PermissionDeniedError``를 raise한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}  # token → member_id
        self._token_counter = 0
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
        password_hash: str = "",
    ) -> FakeMember:
        member = FakeMember(
            member_id=member_id,
            role=role,
            type=member_type,
            status=status,
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
        """``require_master_caller`` 가 caller role 검증에 사용한다 (#1377).

        change_password 는 web layer ``require_master_caller`` 의존성을 사용하므로
        fake service 도 ``get`` 을 노출해야 한다 (#1352 / #1376 패턴).
        """
        return self._members.get(member_id)

    def _assert_master_or_raise(self, caller_id: str, action: str) -> None:
        caller = self._members.get(caller_id)
        if caller is None or caller.role != "master":
            raise PermissionDeniedError(
                f"'{action}'은(는) master만 수행할 수 있습니다."
            )

    async def suspend(self, member_id: str, suspended_by: str = "") -> FakeMember:
        self.suspend_calls.append(
            {"member_id": member_id, "suspended_by": suspended_by}
        )
        self._assert_master_or_raise(suspended_by, "suspend")
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.status = "suspended"
        return member

    async def reactivate(self, member_id: str, reactivated_by: str = "") -> FakeMember:
        self.reactivate_calls.append(
            {"member_id": member_id, "reactivated_by": reactivated_by}
        )
        self._assert_master_or_raise(reactivated_by, "reactivate")
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.status = "active"
        return member

    async def revoke(self, member_id: str, revoked_by: str = "") -> FakeMember:
        self.revoke_calls.append({"member_id": member_id, "revoked_by": revoked_by})
        self._assert_master_or_raise(revoked_by, "revoke")
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.status = "revoked"
        return member

    async def rotate_token(
        self, member_id: str, rotated_by: str = ""
    ) -> tuple[FakeMember, str]:
        self.rotate_calls.append({"member_id": member_id, "rotated_by": rotated_by})
        self._assert_master_or_raise(rotated_by, "rotate_token")
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        self._token_counter += 1
        return member, f"ante_ak_{self._token_counter}"

    async def update_scopes(
        self, member_id: str, scopes: list[str], updated_by: str = ""
    ) -> FakeMember:
        self.update_scopes_calls.append(
            {"member_id": member_id, "scopes": list(scopes), "updated_by": updated_by}
        )
        self._assert_master_or_raise(updated_by, "update_scopes")
        member = self._members.get(member_id)
        if member is None:
            raise ValueError(f"멤버를 찾을 수 없습니다: {member_id}")
        member.scopes = list(scopes)
        return member

    async def change_password(
        self, member_id: str, old_password: str, new_password: str
    ) -> None:
        """비밀번호 변경 stub.

        실 ``MemberService.change_password`` 의 credential check 흐름을 모방한다:
        멤버가 없으면 ``ValueError`` (→ 404), human이 아니면 ``PermissionError``
        (→ 403), old password 불일치면 ``PermissionError`` (→ 403).

        호출 기록 (``change_password_calls``) 을 남겨, 인증 가드 (401/403) 가
        credential check 보다 먼저 차단되었는지 확인할 수 있다.
        """
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
        if member.type != "human":
            raise PermissionError("human 멤버만 비밀번호를 변경할 수 있습니다")
        if member.password_hash and member.password_hash != old_password:
            raise PermissionError("현재 패스워드가 일치하지 않습니다")
        member.password_hash = new_password


class FakeSessionService:
    def __init__(self) -> None:
        self._sessions: dict[str, str] = {}
        self.validate_calls: list[str] = []

    def add_session(self, session_id: str, member_id: str) -> None:
        self._sessions[session_id] = member_id

    async def validate(self, session_id: str) -> dict | None:
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
    # mutation 대상 멤버
    svc.add_member("target-active", role="default", status="active")
    svc.add_member("target-suspended", role="default", status="suspended")
    # change_password 대상 (human + password_hash)
    svc.add_member(
        "target-human-active",
        role="default",
        member_type="human",
        status="active",
        password_hash="known-old-password",
    )
    return svc


@pytest.fixture
def session_service() -> FakeSessionService:
    svc = FakeSessionService()
    svc.add_session("master-session-id", member_id="master-user")
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


@pytest.fixture
def client_no_session_service(
    member_service: FakeMemberService,
) -> TestClient:
    """session_service가 None인 배포 분기 시뮬레이션."""
    app = create_app(member_service=member_service)
    return TestClient(app)


# ── 라우트별 호출 헬퍼 ────────────────────────────────────────────────


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
    """PATCH /api/members/{id}/password helper (#1377).

    기본 payload는 정상 호출 시 통과하는 payload (``known-old-password``).
    인증 매트릭스에서 ``unauth_with_invalid_old_password`` 시나리오는 explicit
    하게 invalid old password를 보내, 인증 가드가 credential check를 우회
    차단하는지 확인한다.
    """
    return client.patch(
        "/api/members/target-human-active/password",
        json=payload
        if payload is not None
        else {"old_password": "known-old-password", "new_password": "new-password"},
        headers=headers or {},
    )


MUTATION_ROUTES = [
    ("suspend", _suspend, "suspend_calls"),
    ("reactivate", _reactivate, "reactivate_calls"),
    ("revoke", _revoke, "revoke_calls"),
    ("rotate_token", _rotate, "rotate_calls"),
    ("update_scopes", _update_scopes, "update_scopes_calls"),
    ("change_password", _change_password, "change_password_calls"),
]

# ``change_password`` 는 ``require_master_caller`` 의존성을 web layer 에서
# 사용하므로 non-master 호출은 service 도달 없이 403 으로 차단된다 (#1377).
# 기존 5개 mutation route 는 ``_resolve_caller_or_401`` 만 사용하고 master 검증을
# service 위임 (PermissionDeniedError → 403) 하는 차이가 있어, ``TestNonMaster403``
# 의 `len(calls) == 1` invariant 가 다르다. ``TestNonMaster403`` parametrize 는
# 기존 5개로 한정하고, change_password 는 ``TestChangePasswordNonMaster403`` 에서
# 별도 검증한다.
NON_MASTER_VIA_SERVICE_ROUTES = MUTATION_ROUTES[:-1]


# ── 401: 인증 자체가 없는 케이스 ────────────────────────────────────────


class TestNoAuth401:
    """Authorization 헤더 + 세션 쿠키 모두 없음 → 401."""

    @pytest.mark.parametrize(
        "name,call,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_without_any_auth(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
    ) -> None:
        resp = call(client)
        assert resp.status_code == 401, (
            f"{name}: 인증 없는 호출이 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert getattr(member_service, calls_attr) == [], (
            f"{name}: 401 차단 시 service mutation이 호출되어선 안 된다"
        )


class TestInvalidBearerToken401:
    """invalid Bearer token → 401, mutation 미호출."""

    @pytest.mark.parametrize(
        "name,call,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_with_invalid_bearer(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer invalid-token"})
        assert resp.status_code == 401, (
            f"{name}: invalid Bearer가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert getattr(member_service, calls_attr) == []


class TestInvalidSessionCookie401:
    """등록되지 않은 ``ante_session`` 쿠키 → 401."""

    @pytest.mark.parametrize(
        "name,call,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_with_invalid_session_cookie(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        session_service: FakeSessionService,
        name: str,
        call,
        calls_attr: str,
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        resp = call(client)
        assert resp.status_code == 401, (
            f"{name}: invalid 세션 쿠키가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert getattr(member_service, calls_attr) == []
        assert "unknown-session-id" in session_service.validate_calls
        client.cookies.delete("ante_session")


class TestSessionServiceNoneFallbackSkip:
    """``session_service is None`` 배포 분기 + Bearer 없음 → 401 (cookie skip)."""

    @pytest.mark.parametrize(
        "name,call,calls_attr",
        MUTATION_ROUTES,
        ids=[r[0] for r in MUTATION_ROUTES],
    )
    def test_returns_401_when_session_service_none_and_no_bearer(
        self,
        client_no_session_service: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
    ) -> None:
        # 쿠키를 보내도 session_service가 None이면 fallback이 동작하지 않아야 한다.
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        resp = call(client_no_session_service)
        assert resp.status_code == 401, (
            f"{name}: session_service None + 쿠키만 있으면 401이어야 함 "
            f"({resp.status_code}: {resp.text})"
        )
        assert getattr(member_service, calls_attr) == []
        client_no_session_service.cookies.delete("ante_session")


# ── 200: 정상 인증 케이스 ────────────────────────────────────────────────


class TestBearerMasterSuccess:
    """master Bearer 토큰 → 200."""

    def test_suspend_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members/target-active/suspend",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["status"] == "suspended"
        assert member_service.suspend_calls[-1]["suspended_by"] == "master-user"

    def test_reactivate_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members/target-suspended/reactivate",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["status"] == "active"
        assert member_service.reactivate_calls[-1]["reactivated_by"] == "master-user"

    def test_revoke_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members/target-active/revoke",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["status"] == "revoked"
        assert member_service.revoke_calls[-1]["revoked_by"] == "master-user"

    def test_rotate_token_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.post(
            "/api/members/target-active/rotate-token",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert "token" in data
        assert data["token"].startswith("ante_ak_")
        assert member_service.rotate_calls[-1]["rotated_by"] == "master-user"

    def test_update_scopes_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.put(
            "/api/members/target-active/scopes",
            headers={"Authorization": "Bearer master-token"},
            json={"scopes": ["trade:read", "trade:write"]},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["scopes"] == ["trade:read", "trade:write"]
        assert member_service.update_scopes_calls[-1]["updated_by"] == "master-user"

    def test_change_password_with_master_bearer_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """master Bearer + 정상 payload → 200 (#1377)."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            headers={"Authorization": "Bearer master-token"},
            json={
                "old_password": "known-old-password",
                "new_password": "new-strong-password",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
        # service까지 도달했는지 확인
        assert len(member_service.change_password_calls) == 1
        assert (
            member_service.change_password_calls[-1]["member_id"]
            == "target-human-active"
        )


class TestSessionCookieMasterSuccess:
    """master ``ante_session`` 쿠키 → 200 + ``request.state.member_id`` 갱신."""

    def test_suspend_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/members/target-active/suspend")
        assert resp.status_code == 200, resp.text
        # caller 결정 후 service에 master-user가 전달돼야 한다 →
        # request.state.member_id가 캡처되어 audit에 master-user가 들어가야 한다.
        assert member_service.suspend_calls[-1]["suspended_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_reactivate_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/members/target-suspended/reactivate")
        assert resp.status_code == 200, resp.text
        assert member_service.reactivate_calls[-1]["reactivated_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_revoke_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/members/target-active/revoke")
        assert resp.status_code == 200, resp.text
        assert member_service.revoke_calls[-1]["revoked_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_rotate_token_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.post("/api/members/target-active/rotate-token")
        assert resp.status_code == 200, resp.text
        assert member_service.rotate_calls[-1]["rotated_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_update_scopes_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"scopes": ["data:read"]},
        )
        assert resp.status_code == 200, resp.text
        assert member_service.update_scopes_calls[-1]["updated_by"] == "master-user"
        client.cookies.delete("ante_session")

    def test_change_password_with_master_session_cookie_succeeds(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """master ante_session 쿠키 → 200 (#1377)."""
        client.cookies.set("ante_session", "master-session-id")
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={
                "old_password": "known-old-password",
                "new_password": "new-strong-password",
            },
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["ok"] is True
        assert len(member_service.change_password_calls) == 1
        client.cookies.delete("ante_session")


# ── 403: 인증된 non-master ─────────────────────────────────────────────────


class TestNonMaster403:
    """인증된 non-master → 403 (PermissionDeniedError 매핑).

    기존 5개 mutation route (suspend / reactivate / revoke / rotate_token /
    update_scopes) 는 ``_resolve_caller_or_401`` 만 web layer 에서 적용하고,
    master 검증은 service 가 ``PermissionDeniedError`` 를 raise 해 처리한다.
    그래서 svc.* 가 1회 호출된 뒤 403 이 반환된다.

    ``change_password`` 는 ``require_master_caller`` 의존성으로 web layer 에서
    먼저 403 을 raise 하므로 동작이 다르다. ``TestChangePasswordNonMaster403``
    에서 별도로 검증한다 (#1377 oracle A7 finding scope 결정).
    """

    @pytest.mark.parametrize(
        "name,call,calls_attr",
        NON_MASTER_VIA_SERVICE_ROUTES,
        ids=[r[0] for r in NON_MASTER_VIA_SERVICE_ROUTES],
    )
    def test_non_master_bearer_returns_403(
        self,
        client: TestClient,
        member_service: FakeMemberService,
        name: str,
        call,
        calls_attr: str,
    ) -> None:
        resp = call(client, headers={"Authorization": "Bearer agent-token"})
        assert resp.status_code == 403, (
            f"{name}: non-master Bearer가 403이 아님 ({resp.status_code}: {resp.text})"
        )
        # 인증 자체는 통과 → service 호출은 일어나야 한다.
        assert len(getattr(member_service, calls_attr)) == 1


# ── 404: master + missing member ──────────────────────────────────────────


class TestMasterMissingMember404:
    """master 인증 통과 + 존재하지 않는 멤버 → 404."""

    def test_suspend_missing_member_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/members/no-such-member/suspend",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_reactivate_missing_member_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/members/no-such-member/reactivate",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_revoke_missing_member_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/members/no-such-member/revoke",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_rotate_token_missing_member_returns_404(self, client: TestClient) -> None:
        resp = client.post(
            "/api/members/no-such-member/rotate-token",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 404

    def test_update_scopes_missing_member_returns_404(self, client: TestClient) -> None:
        resp = client.put(
            "/api/members/no-such-member/scopes",
            headers={"Authorization": "Bearer master-token"},
            json={"scopes": ["data:read"]},
        )
        assert resp.status_code == 404

    def test_change_password_missing_member_returns_404(
        self, client: TestClient
    ) -> None:
        """master 인증 통과 + 존재하지 않는 멤버 → 404 (#1377)."""
        resp = client.patch(
            "/api/members/no-such-member/password",
            headers={"Authorization": "Bearer master-token"},
            json={"old_password": "x", "new_password": "y"},
        )
        assert resp.status_code == 404


# ── update_scopes raw body 패턴: 401 우선 ────────────────────────────────


class TestUpdateScopesAuthFirstOverBodyValidation:
    """``update_scopes``는 ``create_member``와 동일하게 인증 가드가 body
    validation보다 먼저 실행되어야 한다 (#1351 — Codex Plan Review).

    Authorization 없음 + body invalid → 401 (NOT 422).
    """

    def test_update_scopes_unauth_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        # 필수 필드 ``scopes`` 누락된 invalid body.
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"not_scopes": ["x"]},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert member_service.update_scopes_calls == []

    def test_update_scopes_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.put(
            "/api/members/target-active/scopes",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert member_service.update_scopes_calls == []

    def test_update_scopes_master_invalid_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + body 누락 → 422 (정상 검증 경로)."""
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"not_scopes": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert member_service.update_scopes_calls == []

    def test_update_scopes_master_non_json_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + JSON 파싱 실패 → 422."""
        resp = client.put(
            "/api/members/target-active/scopes",
            content=b"not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert member_service.update_scopes_calls == []

    def test_update_scopes_master_empty_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + empty body → 422."""
        resp = client.put(
            "/api/members/target-active/scopes",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert member_service.update_scopes_calls == []


# ── update_scopes extra="forbid" 회귀 (#1351 2차 fix — Finding P2) ──────


class TestUpdateScopesExtraForbid:
    """``ScopesUpdateRequest``는 ``extra="forbid"``를 강제한다.

    OpenAPI ``MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA``가 ``additionalProperties:
    false``를 선언하므로, 런타임 모델도 미지정 필드를 거부해 contract와 동작이
    어긋나지 않도록 한다 (#1351 2차 Codex review FAIL — Finding P2).
    """

    def test_update_scopes_rejects_unknown_field_with_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """master 인증 통과 + 미지정 필드(extra=forbid) → 422."""
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"scopes": ["data:read"], "unexpected": True},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422, (
            f"미지정 필드는 OpenAPI additionalProperties:false에 따라 422여야 함 "
            f"({resp.status_code}: {resp.text})"
        )
        assert member_service.update_scopes_calls == []

    def test_update_scopes_accepts_canonical_payload(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """기존 정상 payload({"scopes": [...]})는 200을 유지한다."""
        resp = client.put(
            "/api/members/target-active/scopes",
            json={"scopes": ["data:read"]},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["member"]["scopes"] == ["data:read"]
        assert member_service.update_scopes_calls[-1]["scopes"] == ["data:read"]


# ── change_password 전용: auth-first 401 + credential check 우회 보호 (#1377) ─


class TestChangePasswordAuthFirstOverCredentialCheck:
    """``change_password``는 ``update_scopes``와 동일하게 인증 가드가 body
    validation 및 credential check 보다 먼저 실행되어야 한다 (#1377 — oracle
    A7 finding).

    핵심 시그니처: 인증 없이 ``invalid old_password``를 보내도 credential
    check (``svc.change_password``) 까지 도달하지 않고 401로 차단되어야 한다.
    이 시나리오는 #1377 finding 의 ``raw_signature`` 와 직접 대응한다.
    """

    def test_unauth_with_invalid_old_password_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 없음 + invalid old password → 401 (credential check 우회 차단).

        oracle A7 finding 핵심: 이전에는 svc.change_password 가 호출되어
        ``현재 패스워드가 일치하지 않습니다`` 로 403 을 반환했다 (credential
        check 도달). 본 패치는 인증 가드가 우선되어 401 을 반환하고
        ``svc.change_password`` 는 호출되지 않아야 한다.
        """
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={
                "old_password": "oracle-known-wrong-password",
                "new_password": "oracle-unused-new-password",
            },
        )
        assert resp.status_code == 401, (
            f"인증 가드가 credential check 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        # mock spy: svc.change_password 가 호출되지 않았어야 한다.
        assert member_service.change_password_calls == [], (
            "401 차단 시 svc.change_password 는 호출되지 않아야 한다 "
            f"(credential check 우회 보호) — 호출 기록: "
            f"{member_service.change_password_calls}"
        )

    def test_unauth_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 없음 + body invalid (필수 필드 누락) → 401 (NOT 422)."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={"not_old_password": "x"},
        )
        assert resp.status_code == 401, (
            f"인증 가드가 body validation 보다 먼저 실행되어야 한다 — "
            f"got {resp.status_code}: {resp.text}"
        )
        assert member_service.change_password_calls == []

    def test_unauth_malformed_json_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 없음 + JSON 파싱 실패 → 401 (NOT 422)."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            content=b"not-json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401
        assert member_service.change_password_calls == []

    def test_invalid_bearer_invalid_body_returns_401(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """invalid Bearer + body invalid → 401."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401
        assert member_service.change_password_calls == []

    def test_master_invalid_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + body 누락 → 422 (정상 검증 경로)."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={"not_old_password": "x"},
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422
        assert member_service.change_password_calls == []

    def test_master_non_json_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + JSON 파싱 실패 → 422."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            content=b"not-json",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert member_service.change_password_calls == []

    def test_master_empty_body_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """인증 통과 + empty body → 422."""
        resp = client.patch(
            "/api/members/target-human-active/password",
            content=b"",
            headers={
                "Authorization": "Bearer master-token",
                "Content-Type": "application/json",
            },
        )
        assert resp.status_code == 422
        assert member_service.change_password_calls == []

    def test_master_unknown_field_returns_422(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        """master 인증 통과 + unknown field (extra=forbid) → 422.

        OpenAPI ``PASSWORD_CHANGE_REQUEST_SCHEMA``가 ``additionalProperties:
        false``를 선언하므로 런타임 모델도 ``extra="forbid"``로 동일하게
        강제한다 (#1351 P2 패턴 답습).
        """
        resp = client.patch(
            "/api/members/target-human-active/password",
            json={
                "old_password": "known-old-password",
                "new_password": "new-pw",
                "unexpected": True,
            },
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 422, (
            f"미지정 필드는 OpenAPI additionalProperties:false 에 따라 422 — "
            f"({resp.status_code}: {resp.text})"
        )
        assert member_service.change_password_calls == []


class TestChangePasswordNonMaster403:
    """인증된 non-master → 403 (master-only — #1377 scope decision).

    self-change use case (caller_id == member_id) 는 follow-up 이슈에서
    별도 다룬다 (Non-Goals).
    """

    def test_non_master_bearer_returns_403(
        self, client: TestClient, member_service: FakeMemberService
    ) -> None:
        resp = client.patch(
            "/api/members/target-human-active/password",
            headers={"Authorization": "Bearer agent-token"},
            json={
                "old_password": "known-old-password",
                "new_password": "new-pw",
            },
        )
        assert resp.status_code == 403, (
            f"non-master Bearer 가 403 이 아님 ({resp.status_code}: {resp.text})"
        )
        # require_master_caller 가 403 으로 차단 → svc.change_password 미호출.
        assert member_service.change_password_calls == [], (
            "403 차단 시 svc.change_password 는 호출되지 않아야 한다 "
            f"(credential check 우회 보호) — 호출 기록: "
            f"{member_service.change_password_calls}"
        )


# ── OpenAPI 응답에 401 추가 회귀 ─────────────────────────────────────────


class TestOpenAPIResponses401:
    """6개 mutation route의 OpenAPI ``responses``에 401 항목이 있어야 한다.

    ``frontend/openapi.json`` codegen 산출물이 401 분기를 인식할 수 있도록
    contract에 명시해야 한다(#1351 risk: contract-drift; #1377 답습).
    """

    @pytest.mark.parametrize(
        "path,method",
        [
            ("/api/members/{member_id}/suspend", "post"),
            ("/api/members/{member_id}/reactivate", "post"),
            ("/api/members/{member_id}/revoke", "post"),
            ("/api/members/{member_id}/rotate-token", "post"),
            ("/api/members/{member_id}/scopes", "put"),
            ("/api/members/{member_id}/password", "patch"),
        ],
    )
    def test_openapi_lists_401_response(self, path: str, method: str) -> None:
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"][path][method]
        responses = operation.get("responses", {})
        assert "401" in responses, (
            f"{method.upper()} {path} 응답에 401 항목이 없음: "
            f"{sorted(responses.keys())}"
        )
