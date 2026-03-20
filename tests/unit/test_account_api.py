"""Account REST API 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import (  # noqa: E402
    AccountDeletedError,
    AccountNotFoundError,
    InvalidBrokerTypeError,
)
from ante.account.models import Account, AccountStatus, TradingMode  # noqa: E402
from ante.web.app import create_app  # noqa: E402


class FakeAccountService:
    """테스트용 AccountService 모의 객체."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}
        self._audit_logs: list[dict[str, Any]] = []
        self._deleted: set[str] = set()

    async def create(self, account: Account) -> Account:
        if account.account_id in self._accounts:
            from ante.account.errors import AccountAlreadyExistsError

            raise AccountAlreadyExistsError(
                f"계좌 '{account.account_id}'가 이미 존재합니다."
            )
        from ante.account.presets import BROKER_PRESETS

        if account.broker_type not in BROKER_PRESETS:
            raise InvalidBrokerTypeError(
                f"유효하지 않은 broker_type: '{account.broker_type}'"
            )
        now = datetime.now(UTC)
        account.created_at = now
        account.updated_at = now
        self._accounts[account.account_id] = account
        return account

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        accounts = list(self._accounts.values())
        if status is not None:
            accounts = [a for a in accounts if a.status == status]
        return accounts

    async def update(self, account_id: str, **fields: Any) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 수정할 수 없습니다."
            )
        for key, value in fields.items():
            setattr(account, key, value)
        account.updated_at = datetime.now(UTC)
        return account

    async def suspend(self, account_id: str, reason: str, suspended_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        self._accounts[account_id].status = AccountStatus.SUSPENDED

    async def activate(self, account_id: str, activated_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        account = self._accounts[account_id]
        if account.status == AccountStatus.DELETED:
            raise AccountDeletedError(
                f"삭제된 계좌 '{account_id}'는 활성화할 수 없습니다."
            )
        account.status = AccountStatus.ACTIVE

    async def delete(self, account_id: str, deleted_by: str) -> None:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        self._accounts[account_id].status = AccountStatus.DELETED
        self._deleted.add(account_id)
        del self._accounts[account_id]

    async def get_broker(self, account_id: str) -> Any:
        """브로커 인스턴스 반환 모의. kis-overseas는 미등록."""
        account = await self.get(account_id)
        # test, kis-domestic만 등록됨
        if account.broker_type not in ("test", "kis-domestic"):
            raise InvalidBrokerTypeError(
                f"broker_type '{account.broker_type}'은 BROKER_REGISTRY에 "
                f"등록되지 않았습니다."
            )
        return object()  # 더미 브로커


class FakeAuditLogger:
    """테스트용 감사 로거."""

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)


@pytest.fixture
def account_service() -> FakeAccountService:
    return FakeAccountService()


@pytest.fixture
def audit_logger() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def app(account_service: FakeAccountService, audit_logger: FakeAuditLogger):
    return create_app(
        account_service=account_service,
        audit_logger=audit_logger,
    )


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


def _make_account(
    account_id: str = "test-account",
    broker_type: str = "test",
) -> Account:
    """테스트용 Account 생성 헬퍼."""
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=TradingMode.VIRTUAL,
        broker_type=broker_type,
        credentials={"secret_key": "hidden"},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestListAccounts:
    """GET /api/accounts."""

    def test_empty_list(self, client: TestClient) -> None:
        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert data["accounts"] == []

    def test_list_with_accounts(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["account_id"] == "test-account"

    def test_list_filter_by_status(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        a1 = _make_account("a1")
        a2 = _make_account("a2")
        a2.status = AccountStatus.SUSPENDED
        account_service._accounts["a1"] = a1
        account_service._accounts["a2"] = a2

        resp = client.get("/api/accounts?status=active")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["accounts"]) == 1
        assert data["accounts"][0]["account_id"] == "a1"

    def test_list_invalid_status(self, client: TestClient) -> None:
        resp = client.get("/api/accounts?status=invalid")
        assert resp.status_code == 400


class TestCreateAccount:
    """POST /api/accounts."""

    def test_create_success(
        self,
        client: TestClient,
        audit_logger: FakeAuditLogger,
    ) -> None:
        resp = client.post(
            "/api/accounts",
            json={
                "account_id": "new-test",
                "name": "새 테스트 계좌",
                "broker_type": "test",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["account"]["account_id"] == "new-test"
        assert data["account"]["broker_type"] == "test"
        # 감사 로그 확인
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.create"
        ]
        assert len(route_logs) == 1

    def test_create_duplicate(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account("existing")
        account_service._accounts["existing"] = account

        resp = client.post(
            "/api/accounts",
            json={
                "account_id": "existing",
                "name": "중복 계좌",
                "broker_type": "test",
            },
        )
        assert resp.status_code == 409

    def test_create_overseas_account_rejected(self, client: TestClient) -> None:
        """kis-overseas broker_type은 BROKER_REGISTRY에 미등록이므로 거부."""
        resp = client.post(
            "/api/accounts",
            json={
                "account_id": "us-stock",
                "name": "미국 주식",
                "broker_type": "kis-overseas",
            },
        )
        assert resp.status_code == 400
        data = resp.json()
        assert "BROKER_REGISTRY" in data["detail"]


class TestGetAccount:
    """GET /api/accounts/:id."""

    def test_get_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts/test-account")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["account_id"] == "test-account"

    def test_get_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/accounts/nonexistent")
        assert resp.status_code == 404

    def test_account_no_credentials_in_response(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """응답에 credentials가 포함되지 않아야 한다."""
        account = _make_account()
        account.credentials = {"app_key": "secret123", "app_secret": "secret456"}
        account_service._accounts[account.account_id] = account

        resp = client.get("/api/accounts/test-account")
        assert resp.status_code == 200
        data = resp.json()
        assert "credentials" not in data["account"]


class TestUpdateAccount:
    """PUT /api/accounts/:id."""

    def test_update_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put(
            "/api/accounts/test-account",
            json={"name": "변경된 이름"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["name"] == "변경된 이름"
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.update"
        ]
        assert len(route_logs) == 1

    def test_update_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/accounts/nonexistent",
            json={"name": "변경"},
        )
        assert resp.status_code == 404

    def test_update_no_fields(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.put("/api/accounts/test-account", json={})
        assert resp.status_code == 400


class TestSuspendAccount:
    """POST /api/accounts/:id/suspend."""

    def test_suspend_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.post(
            "/api/accounts/test-account/suspend",
            json={"reason": "테스트 정지"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["status"] == "suspended"
        assert "정지" in data["message"]
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.suspend"
        ]
        assert len(route_logs) == 1

    def test_suspend_not_found(self, client: TestClient) -> None:
        resp = client.post(
            "/api/accounts/nonexistent/suspend",
            json={"reason": "없는 계좌"},
        )
        assert resp.status_code == 404


class TestActivateAccount:
    """POST /api/accounts/:id/activate."""

    def test_activate_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account.status = AccountStatus.SUSPENDED
        account_service._accounts[account.account_id] = account

        resp = client.post("/api/accounts/test-account/activate")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account"]["status"] == "active"
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.activate"
        ]
        assert len(route_logs) == 1

    def test_activate_not_found(self, client: TestClient) -> None:
        resp = client.post("/api/accounts/nonexistent/activate")
        assert resp.status_code == 404


class TestDeleteAccount:
    """DELETE /api/accounts/:id."""

    def test_delete_success(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        account = _make_account()
        account_service._accounts[account.account_id] = account

        resp = client.delete("/api/accounts/test-account")
        assert resp.status_code == 204
        assert "test-account" not in account_service._accounts
        route_logs = [
            log for log in audit_logger.logs if log["action"] == "account.delete"
        ]
        assert len(route_logs) == 1

    def test_delete_not_found(self, client: TestClient) -> None:
        resp = client.delete("/api/accounts/nonexistent")
        assert resp.status_code == 404
