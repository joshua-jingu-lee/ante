"""``GET /api/audit`` 인증 가드 테스트 (issue #1359).

oracle A7 시그니처에서 발견된 ``list_audit_logs`` 라우트는 인증 없이도
감사 로그 목록을 200으로 반환하고 있었다. 본 PR은 #1352에서 도입된
``require_master_caller`` dependency를 ``GET /api/audit`` 에 적용해
인증되지 않은 호출자가 감사 로그를 읽지 못하도록 막는다.

각 인증 시나리오:
- Authorization 헤더 + 세션 쿠키 모두 없음 → 401
- invalid Bearer token → 401
- invalid 세션 쿠키 → 401
- ``session_service`` is None 배포 + Bearer 없음 → 401 (cookie fallback skip)
- 정상 Bearer master → 200
- 정상 ante_session master → 200
- 인증된 non-master Bearer → 403

401/403 응답 시 ``AuditLogger.query`` 는 호출되지 않아야 한다 (early return).

#1352 ``test_runtime_mutation_auth.py`` 패턴을 그대로 답습한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ── Member / Session fakes (#1352 패턴) ──────────────────────────────────


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


class FakeMemberService:
    """테스트용 MemberService stub (#1352 동일 패턴).

    토큰 → member_id 매핑으로 ``authenticate``를 흉내내고, ``get`` 메서드는
    ``require_master_caller`` dependency가 호출하므로 정확한 ``Member`` 형태를
    반환해야 한다.
    """

    def __init__(self) -> None:
        self._members: dict[str, FakeMember] = {}
        self._tokens: dict[str, str] = {}

    def add_member(
        self,
        member_id: str,
        token: str = "",
        role: str = "default",
        member_type: str = "agent",
    ) -> FakeMember:
        member = FakeMember(member_id=member_id, role=role, type=member_type)
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
        return {"member_id": member_id, "created_at": "2026-05-09 00:00:00"}


# ── audit_logger fake ───────────────────────────────────────────────────


def _make_audit_logger() -> AsyncMock:
    """query/count call_args를 추적할 수 있는 mock audit logger."""
    mock = AsyncMock()
    mock.query = AsyncMock(
        return_value=[
            {
                "id": 1,
                "member_id": "agent-01",
                "action": "bot.create",
                "resource": "bot:bot-1",
                "detail": "",
                "ip": "127.0.0.1",
                "created_at": "2026-05-09T00:00:00",
            }
        ]
    )
    mock.count = AsyncMock(return_value=1)
    return mock


# ── fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def member_service() -> FakeMemberService:
    svc = FakeMemberService()
    svc.add_member("master-user", token="master-token", role="master")
    svc.add_member("agent-01", token="agent-token", role="default")
    return svc


@pytest.fixture
def session_service() -> FakeSessionService:
    svc = FakeSessionService()
    svc.add_session("master-session-id", member_id="master-user")
    svc.add_session("agent-session-id", member_id="agent-01")
    return svc


@pytest.fixture
def audit_logger() -> AsyncMock:
    return _make_audit_logger()


@pytest.fixture
def client(
    member_service: FakeMemberService,
    session_service: FakeSessionService,
    audit_logger: AsyncMock,
) -> TestClient:
    app = create_app(
        member_service=member_service,
        session_service=session_service,
        audit_logger=audit_logger,
    )
    return TestClient(app)


@pytest.fixture
def client_no_session_service(
    member_service: FakeMemberService,
    audit_logger: AsyncMock,
) -> TestClient:
    """``session_service is None`` 배포 분기 시뮬레이션."""
    app = create_app(
        member_service=member_service,
        audit_logger=audit_logger,
    )
    return TestClient(app)


# ── 401: 인증 자체가 없는 케이스 ──────────────────────────────────────


class TestNoAuth401:
    """Authorization 헤더 + 세션 쿠키 모두 없음 → 401."""

    def test_returns_401_without_any_auth(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        resp = client.get("/api/audit?limit=1")
        assert resp.status_code == 401, (
            f"인증 없는 호출이 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0, (
            "401 차단 시 audit_logger.query가 호출되어선 안 된다"
        )
        assert audit_logger.count.await_count == 0


class TestInvalidBearerToken401:
    """invalid Bearer token → 401, audit query 미호출."""

    def test_returns_401_with_invalid_bearer(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        resp = client.get(
            "/api/audit?limit=1",
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401, (
            f"invalid Bearer가 401이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0
        assert audit_logger.count.await_count == 0


class TestInvalidSessionCookie401:
    """등록되지 않은 ``ante_session`` 쿠키 → 401."""

    def test_returns_401_with_invalid_session_cookie(
        self,
        client: TestClient,
        audit_logger: AsyncMock,
        session_service: FakeSessionService,
    ) -> None:
        client.cookies.set("ante_session", "unknown-session-id")
        try:
            resp = client.get("/api/audit?limit=1")
            assert resp.status_code == 401, (
                f"invalid 세션 쿠키가 401이 아님 ({resp.status_code}: {resp.text})"
            )
            assert audit_logger.query.await_count == 0
            assert audit_logger.count.await_count == 0
            assert "unknown-session-id" in session_service.validate_calls
        finally:
            client.cookies.delete("ante_session")


class TestSessionServiceNoneFallbackSkip:
    """``session_service is None`` 배포 분기 + Bearer 없음 → 401."""

    def test_returns_401_when_session_service_none_and_no_bearer(
        self,
        client_no_session_service: TestClient,
        audit_logger: AsyncMock,
    ) -> None:
        client_no_session_service.cookies.set("ante_session", "any-session-id")
        try:
            resp = client_no_session_service.get("/api/audit?limit=1")
            assert resp.status_code == 401, (
                f"session_service None + 쿠키만 있으면 401이어야 함 "
                f"({resp.status_code}: {resp.text})"
            )
            assert audit_logger.query.await_count == 0
            assert audit_logger.count.await_count == 0
        finally:
            client_no_session_service.cookies.delete("ante_session")


# ── 200: 정상 인증 케이스 ───────────────────────────────────────────────


class TestBearerMasterSuccess:
    """master Bearer 토큰 → 200."""

    def test_audit_with_master_bearer_succeeds(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        resp = client.get(
            "/api/audit?limit=1",
            headers={"Authorization": "Bearer master-token"},
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert "logs" in body
        assert "total" in body
        assert audit_logger.query.await_count == 1
        assert audit_logger.count.await_count == 1


class TestSessionCookieMasterSuccess:
    """master ``ante_session`` 쿠키 → 200."""

    def test_audit_with_master_session_cookie_succeeds(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        client.cookies.set("ante_session", "master-session-id")
        try:
            resp = client.get("/api/audit?limit=1")
            assert resp.status_code == 200, resp.text
            body = resp.json()
            assert "logs" in body
            assert "total" in body
            assert audit_logger.query.await_count == 1
            assert audit_logger.count.await_count == 1
        finally:
            client.cookies.delete("ante_session")


# ── 403: 인증된 non-master ─────────────────────────────────────────────


class TestNonMaster403:
    """인증된 non-master → 403, audit query 미호출."""

    def test_non_master_bearer_returns_403(
        self, client: TestClient, audit_logger: AsyncMock
    ) -> None:
        resp = client.get(
            "/api/audit?limit=1",
            headers={"Authorization": "Bearer agent-token"},
        )
        assert resp.status_code == 403, (
            f"non-master Bearer가 403이 아님 ({resp.status_code}: {resp.text})"
        )
        assert audit_logger.query.await_count == 0, (
            "403 차단 시 audit_logger.query가 호출되어선 안 된다"
        )
        assert audit_logger.count.await_count == 0


# ── OpenAPI 응답 401/403 회귀 ──────────────────────────────────────────


class TestOpenAPIResponses401403:
    """``GET /api/audit`` OpenAPI ``responses``에 401/403 항목이 있어야 한다.

    ``frontend/openapi.json`` codegen 산출물이 401/403 분기를 인식할 수 있도록
    contract에 명시해야 한다 (#1352와 동일한 contract-drift risk).
    """

    def test_openapi_lists_401_response(self) -> None:
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"]["/api/audit"]["get"]
        responses = operation.get("responses", {})
        assert "401" in responses, (
            f"GET /api/audit 응답에 401 항목이 없음: {sorted(responses.keys())}"
        )

    def test_openapi_lists_403_response(self) -> None:
        app = create_app()
        schema = app.openapi()
        operation = schema["paths"]["/api/audit"]["get"]
        responses = operation.get("responses", {})
        assert "403" in responses, (
            f"GET /api/audit 응답에 403 항목이 없음: {sorted(responses.keys())}"
        )
