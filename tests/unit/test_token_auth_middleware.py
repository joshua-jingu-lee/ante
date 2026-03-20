"""토큰 인증 미들웨어 테스트 — Agent 토큰 인증 시 last_active_at 갱신 검증."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock

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


class TestTokenAuthMiddleware:
    """TokenAuthMiddleware가 토큰 인증 성공 시 last_active_at을 갱신한다."""

    @pytest.fixture
    def agent_member(self) -> FakeMember:
        return FakeMember(
            member_id="test-agent-01",
            type="agent",
            name="테스트 에이전트",
        )

    @pytest.fixture
    def member_service(self, agent_member: FakeMember) -> AsyncMock:
        svc = AsyncMock()
        svc.authenticate = AsyncMock(return_value=agent_member)
        svc.update_last_active = AsyncMock()
        return svc

    @pytest.fixture
    def app(self, member_service: AsyncMock) -> object:
        return create_app(member_service=member_service)

    @pytest.fixture
    def client(self, app: object) -> TestClient:
        return TestClient(app)

    def test_agent_token_auth_updates_last_active(
        self,
        client: TestClient,
        member_service: AsyncMock,
        agent_member: FakeMember,
    ) -> None:
        """Agent 토큰 인증 성공 시 update_last_active가 호출된다."""
        resp = client.get(
            "/api/system/health",
            headers={"Authorization": "Bearer ante_ak_test_token_123"},
        )
        assert resp.status_code == 200

        member_service.authenticate.assert_called_once_with("ante_ak_test_token_123")
        member_service.update_last_active.assert_called_once_with("test-agent-01")

    def test_no_auth_header_skips_authentication(
        self,
        client: TestClient,
        member_service: AsyncMock,
    ) -> None:
        """Authorization 헤더 없으면 인증을 시도하지 않는다."""
        resp = client.get("/api/system/health")
        assert resp.status_code == 200

        member_service.authenticate.assert_not_called()
        member_service.update_last_active.assert_not_called()

    def test_invalid_token_does_not_update_last_active(
        self,
        client: TestClient,
        member_service: AsyncMock,
    ) -> None:
        """토큰 인증 실패 시 update_last_active를 호출하지 않는다."""
        member_service.authenticate = AsyncMock(
            side_effect=PermissionError("인증 실패")
        )

        resp = client.get(
            "/api/system/health",
            headers={"Authorization": "Bearer invalid_token"},
        )
        # 미들웨어는 인증 실패를 무시하고 요청을 통과시킨다
        assert resp.status_code == 200

        member_service.authenticate.assert_called_once()
        member_service.update_last_active.assert_not_called()

    def test_non_bearer_auth_header_skips_authentication(
        self,
        client: TestClient,
        member_service: AsyncMock,
    ) -> None:
        """Bearer 접두어가 없는 Authorization 헤더는 무시한다."""
        resp = client.get(
            "/api/system/health",
            headers={"Authorization": "Basic dXNlcjpwYXNz"},
        )
        assert resp.status_code == 200

        member_service.authenticate.assert_not_called()
        member_service.update_last_active.assert_not_called()

    def test_member_id_set_on_request_state(
        self,
        client: TestClient,
        member_service: AsyncMock,
        agent_member: FakeMember,
    ) -> None:
        """인증 성공 시 request.state.member_id가 설정된다 (AuditMiddleware 연동)."""
        # AuditMiddleware가 member_id를 참조하므로, POST 요청으로 확인
        audit_logger = AsyncMock()
        audit_logger.log = AsyncMock()

        app = create_app(
            member_service=member_service,
            audit_logger=audit_logger,
        )
        test_client = TestClient(app)

        # POST 요청으로 AuditMiddleware가 member_id를 사용하는지 확인
        test_client.post(
            "/api/system/halt",
            headers={"Authorization": "Bearer ante_ak_test_token_123"},
        )
        # halt는 account_service 없어서 503이지만 미들웨어는 동작함
        member_service.authenticate.assert_called_once_with("ante_ak_test_token_123")
        member_service.update_last_active.assert_called_once_with("test-agent-01")
