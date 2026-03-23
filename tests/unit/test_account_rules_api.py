"""Account Rules REST API 단위 테스트.

GET /api/accounts/{account_id}/rules
PUT /api/accounts/{account_id}/rules/{rule_type}
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.errors import AccountNotFoundError  # noqa: E402
from ante.account.models import Account, AccountStatus, TradingMode  # noqa: E402
from ante.web.app import create_app  # noqa: E402


class FakeAccountService:
    """테스트용 AccountService 모의 객체."""

    def __init__(self) -> None:
        self._accounts: dict[str, Account] = {}

    async def get(self, account_id: str) -> Account:
        if account_id not in self._accounts:
            raise AccountNotFoundError(f"계좌 '{account_id}'를 찾을 수 없습니다.")
        return self._accounts[account_id]

    async def list(self, status: AccountStatus | None = None) -> list[Account]:
        return list(self._accounts.values())


class FakeAuditLogger:
    """테스트용 감사 로거."""

    def __init__(self) -> None:
        self.logs: list[dict[str, Any]] = []

    async def log(self, **kwargs: Any) -> None:
        self.logs.append(kwargs)


class FakeDynamicConfig:
    """테스트용 DynamicConfigService 모의 객체."""

    _MISSING = object()

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}

    async def get(self, key: str, default: Any = _MISSING) -> Any:
        if key not in self._store:
            if default is not self._MISSING:
                return default
            from ante.config.exceptions import ConfigError

            raise ConfigError(f"Dynamic config not found: {key}")
        return self._store[key]

    async def set(
        self, key: str, value: Any, category: str, changed_by: str = "system"
    ) -> None:
        self._store[key] = value

    async def exists(self, key: str) -> bool:
        return key in self._store

    async def get_all(self) -> list[dict[str, Any]]:
        return [{"key": k, "value": v} for k, v in self._store.items()]


class FakeConfig:
    """테스트용 정적 Config 모의 객체."""

    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self._data = data or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)


def _make_account(account_id: str = "test-account") -> Account:
    return Account(
        account_id=account_id,
        name="테스트 계좌",
        exchange="TEST",
        currency="KRW",
        timezone="Asia/Seoul",
        trading_hours_start="00:00",
        trading_hours_end="23:59",
        trading_mode=TradingMode.VIRTUAL,
        broker_type="test",
        credentials={},
        buy_commission_rate=Decimal("0"),
        sell_commission_rate=Decimal("0"),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _add_account(service: FakeAccountService, account_id: str = "acct-1") -> Account:
    """테스트용 계좌를 직접 삽입하는 헬퍼."""
    account = _make_account(account_id)
    service._accounts[account_id] = account
    return account


@pytest.fixture
def account_service() -> FakeAccountService:
    return FakeAccountService()


@pytest.fixture
def audit_logger() -> FakeAuditLogger:
    return FakeAuditLogger()


@pytest.fixture
def dynamic_config() -> FakeDynamicConfig:
    return FakeDynamicConfig()


@pytest.fixture
def static_config() -> FakeConfig:
    return FakeConfig()


@pytest.fixture
def app(
    account_service: FakeAccountService,
    audit_logger: FakeAuditLogger,
    dynamic_config: FakeDynamicConfig,
    static_config: FakeConfig,
):
    return create_app(
        account_service=account_service,
        audit_logger=audit_logger,
        dynamic_config=dynamic_config,
        config=static_config,
    )


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


class TestGetAccountRules:
    """GET /api/accounts/{account_id}/rules."""

    def test_account_not_found(self, client: TestClient) -> None:
        resp = client.get("/api/accounts/nonexistent/rules")
        assert resp.status_code == 404

    def test_empty_rules(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-1"
        assert data["rules"] == []

    def test_rules_from_dynamic_config(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")
        dynamic_config._store["accounts.acct-1.rules"] = [
            {
                "type": "daily_loss_limit",
                "enabled": True,
                "max_daily_loss_percent": 0.05,
            },
            {
                "type": "trading_hours",
                "enabled": False,
                "allowed_hours": "09:00-15:30",
            },
        ]

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 2
        assert data["rules"][0]["type"] == "daily_loss_limit"
        assert data["rules"][0]["enabled"] is True
        assert data["rules"][0]["params"]["max_daily_loss_percent"] == 0.05
        assert data["rules"][1]["type"] == "trading_hours"
        assert data["rules"][1]["enabled"] is False

    def test_rules_from_static_config_fallback(
        self,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """DynamicConfig에 없으면 정적 Config에서 읽는다."""
        _add_account(account_service, "acct-1")

        static_config = FakeConfig(
            {
                "accounts.acct-1.rules": [
                    {
                        "type": "total_exposure_limit",
                        "enabled": True,
                        "max_exposure_percent": 0.20,
                    },
                ]
            }
        )
        app = create_app(
            account_service=account_service,
            audit_logger=audit_logger,
            dynamic_config=FakeDynamicConfig(),
            config=static_config,
        )
        client = TestClient(app)

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["type"] == "total_exposure_limit"
        assert data["rules"][0]["params"]["max_exposure_percent"] == 0.20

    def test_unknown_rule_types_filtered(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        """RULE_REGISTRY에 없는 룰 타입은 필터링된다."""
        _add_account(account_service, "acct-1")
        dynamic_config._store["accounts.acct-1.rules"] = [
            {"type": "daily_loss_limit", "enabled": True},
            {"type": "unknown_rule_xyz", "enabled": True},
        ]

        resp = client.get("/api/accounts/acct-1/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["rules"]) == 1
        assert data["rules"][0]["type"] == "daily_loss_limit"


class TestUpdateAccountRule:
    """PUT /api/accounts/{account_id}/rules/{rule_type}."""

    def test_account_not_found(self, client: TestClient) -> None:
        resp = client.put(
            "/api/accounts/nonexistent/rules/daily_loss_limit",
            json={"enabled": True, "params": {}},
        )
        assert resp.status_code == 404

    def test_unknown_rule_type(
        self, client: TestClient, account_service: FakeAccountService
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/nonexistent_rule",
            json={"enabled": True, "params": {}},
        )
        assert resp.status_code == 400
        assert "nonexistent_rule" in resp.json()["detail"]

    def test_add_new_rule(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": True, "params": {"max_daily_loss_percent": 0.03}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-1"
        assert data["rule_type"] == "daily_loss_limit"
        assert data["rule"]["type"] == "daily_loss_limit"
        assert data["rule"]["enabled"] is True
        assert data["rule"]["params"]["max_daily_loss_percent"] == 0.03

        # DynamicConfig에 저장되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 1
        assert stored[0]["type"] == "daily_loss_limit"

    def test_update_existing_rule(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        dynamic_config: FakeDynamicConfig,
    ) -> None:
        _add_account(account_service, "acct-1")

        # 기존 룰 설정
        dynamic_config._store["accounts.acct-1.rules"] = [
            {
                "type": "daily_loss_limit",
                "enabled": True,
                "max_daily_loss_percent": 0.05,
            },
            {
                "type": "trading_hours",
                "enabled": True,
            },
        ]

        # daily_loss_limit 업데이트
        resp = client.put(
            "/api/accounts/acct-1/rules/daily_loss_limit",
            json={"enabled": False, "params": {"max_daily_loss_percent": 0.10}},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["rule"]["enabled"] is False
        assert data["rule"]["params"]["max_daily_loss_percent"] == 0.10

        # trading_hours는 그대로, daily_loss_limit만 변경되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 2
        daily_loss = next(r for r in stored if r["type"] == "daily_loss_limit")
        assert daily_loss["enabled"] is False
        assert daily_loss["max_daily_loss_percent"] == 0.10
        trading_hours = next(r for r in stored if r["type"] == "trading_hours")
        assert trading_hours["enabled"] is True

    def test_audit_log_created(
        self,
        client: TestClient,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        _add_account(account_service, "acct-1")

        resp = client.put(
            "/api/accounts/acct-1/rules/position_size",
            json={"enabled": True, "params": {"max_position_percent": 0.15}},
        )
        assert resp.status_code == 200

        # AuditMiddleware도 로그를 남기므로 action으로 필터링
        rule_logs = [
            lg for lg in audit_logger.logs if lg.get("action") == "account.rule.update"
        ]
        assert len(rule_logs) == 1
        log = rule_logs[0]
        assert "position_size" in log["resource"]

    def test_all_rule_types_accepted(
        self,
        client: TestClient,
        account_service: FakeAccountService,
    ) -> None:
        """RULE_REGISTRY에 등록된 모든 룰 타입이 PUT으로 수정 가능하다."""
        from ante.rule.engine import RULE_REGISTRY

        _add_account(account_service, "acct-1")

        for rule_type in RULE_REGISTRY:
            resp = client.put(
                f"/api/accounts/acct-1/rules/{rule_type}",
                json={"enabled": True, "params": {}},
            )
            assert resp.status_code == 200, f"Failed for rule_type={rule_type}"
            assert resp.json()["rule_type"] == rule_type

    def test_static_config_fallback_on_update(
        self,
        account_service: FakeAccountService,
        audit_logger: FakeAuditLogger,
    ) -> None:
        """정적 Config에 있는 룰이 업데이트되면 DynamicConfig에 저장된다."""
        _add_account(account_service, "acct-1")

        static_config = FakeConfig(
            {
                "accounts.acct-1.rules": [
                    {
                        "type": "total_exposure_limit",
                        "enabled": True,
                        "max_exposure_percent": 0.20,
                    },
                ]
            }
        )
        dynamic_config = FakeDynamicConfig()
        app = create_app(
            account_service=account_service,
            audit_logger=audit_logger,
            dynamic_config=dynamic_config,
            config=static_config,
        )
        client = TestClient(app)

        resp = client.put(
            "/api/accounts/acct-1/rules/total_exposure_limit",
            json={"enabled": False, "params": {"max_exposure_percent": 0.30}},
        )
        assert resp.status_code == 200

        # DynamicConfig에 저장되었는지 확인
        stored = dynamic_config._store["accounts.acct-1.rules"]
        assert len(stored) == 1
        assert stored[0]["max_exposure_percent"] == 0.30
        assert stored[0]["enabled"] is False
