"""감사 로그 연동 테스트 — AuditMiddleware + 핸들러 명시적 호출."""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.member.models import MemberRole  # noqa: E402
from ante.web.app import create_app  # noqa: E402

# 인증 가드(#1352) — POST /api/treasury/balance에 master 인증이 필요해졌다.
# 본 모듈은 audit 통합을 검증하므로 master 토큰을 default header로 적용한다.
_MASTER_HEADERS = {"Authorization": "Bearer master-token"}


@dataclass
class _StubMember:
    member_id: str
    role: str = "default"
    type: str = "agent"
    org: str = "default"
    name: str = ""
    emoji: str = ""
    status: str = "active"
    scopes: list[str] = dc_field(default_factory=list)


class _StubMemberService:
    def __init__(self) -> None:
        self._members: dict[str, _StubMember] = {
            "master-user": _StubMember(
                member_id="master-user", role=MemberRole.MASTER.value
            ),
        }
        self._tokens: dict[str, str] = {"master-token": "master-user"}

    async def authenticate(self, token: str) -> _StubMember:
        member_id = self._tokens.get(token)
        if member_id is None:
            raise PermissionError("invalid token")
        return self._members[member_id]

    async def update_last_active(self, member_id: str) -> None:
        return None

    async def get(self, member_id: str) -> _StubMember | None:
        return self._members.get(member_id)


def _new_member_service() -> _StubMemberService:
    return _StubMemberService()


@pytest.fixture
def audit_logger():
    """Mock AuditLogger."""
    mock = AsyncMock()
    mock.log = AsyncMock()
    return mock


@pytest.fixture
def app(audit_logger):
    """audit_logger가 주입된 앱."""
    return create_app(audit_logger=audit_logger)


@pytest.fixture
def client(app):
    return TestClient(app)


# ── AuditMiddleware 테스트 ──────────────────────────


class TestAuditMiddleware:
    """미들웨어가 상태 변경 요청을 자동 기록한다."""

    def test_post_success_logged(self, client, audit_logger):
        """POST 성공 시 미들웨어가 api:post 액션으로 기록한다."""
        # system/halt는 account_service 없이 503 → 미들웨어 기록 안 됨
        # health는 GET → 미들웨어 기록 안 됨
        # 503은 성공이 아니므로 기록 안 됨
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        # GET이므로 미들웨어 호출 없어야 함
        middleware_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action", "").startswith("api:")
        ]
        assert len(middleware_calls) == 0

    def test_get_not_logged_by_middleware(self, client, audit_logger):
        """GET 요청은 미들웨어가 기록하지 않는다."""
        client.get("/api/system/status")
        middleware_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action", "").startswith("api:")
        ]
        assert len(middleware_calls) == 0

    def test_failed_request_not_logged(self, client, audit_logger):
        """실패(4xx/5xx) 응답은 미들웨어가 기록하지 않는다."""
        # account_service가 없으므로 503 → 기록 안 됨
        resp = client.post(
            "/api/system/halt",
            json={"reason": "test"},
        )
        assert resp.status_code == 503
        middleware_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action", "").startswith("api:")
        ]
        assert len(middleware_calls) == 0


# ── 핸들러 명시적 호출 테스트 ──────────────────────────


class TestHandlerAuditLog:
    """각 라우트 핸들러의 명시적 audit 호출을 검증한다."""

    def test_login_audit(self, audit_logger):
        """로그인 성공 시 auth.login 감사 로그가 기록된다."""
        from types import SimpleNamespace

        member_obj = SimpleNamespace(member_id="user-01", name="User 1", type="human")
        member_mock = AsyncMock()
        member_mock.authenticate_password = AsyncMock(return_value=member_obj)
        member_mock.update_last_active = AsyncMock()

        session_mock = AsyncMock()
        session_mock.create = AsyncMock(return_value="sess-123")

        app = create_app(
            audit_logger=audit_logger,
            member_service=member_mock,
            session_service=session_mock,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/auth/login",
            json={"member_id": "user-01", "password": "pw123"},
        )
        assert resp.status_code == 200

        # 핸들러 명시적 호출 확인
        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "auth.login"
        ]
        assert len(handler_calls) == 1
        assert handler_calls[0].kwargs["member_id"] == "user-01"
        assert handler_calls[0].kwargs["resource"] == "member:user-01"

        # 미들웨어도 기록 (api:post)
        mw_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "api:post"
        ]
        assert len(mw_calls) == 1

    def test_logout_audit(self, audit_logger):
        """로그아웃 시 auth.logout 감사 로그가 기록된다."""
        session_mock = AsyncMock()
        session_mock.validate = AsyncMock(
            return_value={"member_id": "user-01", "created_at": "2026-01-01T00:00:00"}
        )
        session_mock.delete = AsyncMock()

        app = create_app(
            audit_logger=audit_logger,
            session_service=session_mock,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/auth/logout",
            cookies={"ante_session": "sess-123"},
        )
        assert resp.status_code == 200

        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "auth.logout"
        ]
        assert len(handler_calls) == 1
        assert handler_calls[0].kwargs["member_id"] == "user-01"

    def test_halt_audit(self, audit_logger):
        """halt 시 system.halt 감사 로그가 기록된다."""
        account_service_mock = AsyncMock()
        account_service_mock.suspend_all = AsyncMock(
            return_value=[
                {
                    "account_id": "domestic",
                    "previous_status": "active",
                    "status": "suspended",
                    "changed": True,
                }
            ]
        )

        app = create_app(
            audit_logger=audit_logger,
            account_service=account_service_mock,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/system/halt",
            json={"reason": "emergency"},
        )
        assert resp.status_code == 200

        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "system.halt"
        ]
        assert len(handler_calls) == 1
        assert handler_calls[0].kwargs["resource"] == "system:kill_switch"
        assert handler_calls[0].kwargs["detail"] == "emergency"

    def test_clear_halt_audit(self, audit_logger):
        """clear-halt 시 system.clear_halt 감사 로그가 기록된다 (Refs #1213).

        SSOT: ``docs/specs/audit/audit.md``. action=``system.clear_halt``,
        resource=``system:kill_switch`` 유지.
        """
        account_service_mock = AsyncMock()
        account_service_mock.activate_all = AsyncMock(
            return_value=[
                {
                    "account_id": "domestic",
                    "previous_status": "suspended",
                    "status": "active",
                    "changed": True,
                }
            ]
        )

        app = create_app(
            audit_logger=audit_logger,
            account_service=account_service_mock,
        )
        client = TestClient(app)

        resp = client.post(
            "/api/system/clear-halt",
            json={"reason": "recovered"},
        )
        assert resp.status_code == 200

        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "system.clear_halt"
        ]
        assert len(handler_calls) == 1
        # audit resource 명칭은 그대로 유지 (Refs #1213 명시적 비변경)
        assert handler_calls[0].kwargs["resource"] == "system:kill_switch"
        # legacy system.activate 감사 로그는 더 이상 발생하지 않는다.
        legacy_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "system.activate"
        ]
        assert len(legacy_calls) == 0

    def test_config_update_audit(self, audit_logger):
        """설정 변경 시 config.update 감사 로그가 기록된다 (master 인증, #1373)."""
        config_mock = AsyncMock()
        config_mock.exists = AsyncMock(return_value=True)
        config_mock.get = AsyncMock(return_value=0.05)
        config_mock.set = AsyncMock()

        app = create_app(
            audit_logger=audit_logger,
            dynamic_config=config_mock,
            member_service=_new_member_service(),
        )
        client = TestClient(app)
        client.headers.update(_MASTER_HEADERS)

        resp = client.put(
            "/api/config/risk.max_mdd",
            json={"value": 0.10},
        )
        assert resp.status_code == 200

        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "config.update"
        ]
        assert len(handler_calls) == 1
        assert handler_calls[0].kwargs["resource"] == "config:risk.max_mdd"

    def test_treasury_set_balance_audit(self, audit_logger):
        """잔고 설정 시 treasury.set_balance 감사 로그가 기록된다."""
        treasury_mock = AsyncMock()
        treasury_mock.set_account_balance = AsyncMock()
        treasury_mock.account_balance = 10_000_000.0

        app = create_app(
            audit_logger=audit_logger,
            treasury=treasury_mock,
            member_service=_new_member_service(),
        )
        client = TestClient(app)
        client.headers.update(_MASTER_HEADERS)

        resp = client.post(
            "/api/treasury/balance",
            json={"balance": 10_000_000},
        )
        assert resp.status_code == 200

        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "treasury.set_balance"
        ]
        assert len(handler_calls) == 1
        assert handler_calls[0].kwargs["resource"] == "treasury"

    def test_dual_recording(self, audit_logger):
        """핸들러 + 미들웨어 이중 기록이 동작한다 (master 인증, #1373)."""
        config_mock = AsyncMock()
        config_mock.exists = AsyncMock(return_value=True)
        config_mock.get = AsyncMock(return_value="old")
        config_mock.set = AsyncMock()

        app = create_app(
            audit_logger=audit_logger,
            dynamic_config=config_mock,
            member_service=_new_member_service(),
        )
        client = TestClient(app)
        client.headers.update(_MASTER_HEADERS)

        resp = client.put(
            "/api/config/test.key",
            json={"value": "new"},
        )
        assert resp.status_code == 200

        # 핸들러 기록
        handler_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "config.update"
        ]
        assert len(handler_calls) == 1

        # 미들웨어 기록
        mw_calls = [
            c
            for c in audit_logger.log.call_args_list
            if c.kwargs.get("action") == "api:put"
        ]
        assert len(mw_calls) == 1

        # 총 2건 기록 (이중 구조)
        assert audit_logger.log.call_count == 2
