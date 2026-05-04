"""자금관리 API 확장 테스트 (봇별 예산 목록 + 잔고 설정)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeBudget:
    """테스트용 BotBudget."""

    bot_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeTreasury:
    """테스트용 Treasury stub."""

    def __init__(self) -> None:
        self._balance: float = 0.0
        self._budgets: list[FakeBudget] = []

    def list_budgets(self) -> list[FakeBudget]:
        return list(self._budgets)

    @property
    def account_balance(self) -> float:
        return self._balance

    async def set_account_balance(self, balance: float) -> None:
        self._balance = balance

    def get_summary(self) -> dict:
        return {"account_balance": self._balance}

    async def get_latest_snapshot(self) -> None:
        return None


@pytest.fixture
def treasury():
    return FakeTreasury()


@pytest.fixture
def client(treasury):
    app = create_app(treasury=treasury)
    return TestClient(app)


class TestListBudgets:
    def test_empty_budgets(self, client):
        """봇이 없을 때 빈 목록."""
        resp = client.get("/api/treasury/budgets")
        assert resp.status_code == 200
        data = resp.json()
        assert data["budgets"] == []

    def test_budgets_with_data(self, client, treasury):
        """봇별 예산 데이터 반환."""
        treasury._budgets = [
            FakeBudget(
                bot_id="bot-1",
                allocated=1_000_000,
                available=800_000,
                reserved=100_000,
                spent=100_000,
            ),
            FakeBudget(
                bot_id="bot-2",
                allocated=500_000,
                available=500_000,
            ),
        ]
        resp = client.get("/api/treasury/budgets")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["budgets"]) == 2
        assert data["budgets"][0]["bot_id"] == "bot-1"
        assert data["budgets"][0]["allocated"] == 1_000_000
        assert data["budgets"][0]["available"] == 800_000
        assert data["budgets"][0]["reserved"] == 100_000
        assert data["budgets"][1]["bot_id"] == "bot-2"
        assert data["budgets"][1]["allocated"] == 500_000


class TestSetBalance:
    def test_set_balance(self, client, treasury):
        """잔고 설정 후 반영 확인."""
        resp = client.post(
            "/api/treasury/balance",
            json={"balance": 10_000_000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_balance"] == 10_000_000
        assert "updated_at" in data
        assert treasury.account_balance == 10_000_000

    def test_set_balance_updates_summary(self, client, treasury):
        """잔고 설정 후 summary에 반영."""
        client.post("/api/treasury/balance", json={"balance": 5_000_000})
        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        assert resp.json()["account_balance"] == 5_000_000

    def test_set_zero_balance(self, client, treasury):
        """잔고 0으로 설정."""
        resp = client.post(
            "/api/treasury/balance",
            json={"balance": 0},
        )
        assert resp.status_code == 200
        assert resp.json()["total_balance"] == 0


class FakeTreasuryManager:
    """테스트용 TreasuryManager stub."""

    def __init__(self, treasuries: list[FakeTreasury] | None = None) -> None:
        self._treasuries: list[FakeTreasury] = treasuries or []

    def list_all(self) -> list[FakeTreasury]:
        return list(self._treasuries)

    def get(self, account_id: str) -> FakeTreasury:
        for t in self._treasuries:
            if getattr(t, "account_id", None) == account_id:
                return t
        raise KeyError(f"Treasury not found: {account_id}")


class TestTreasuryFallback:
    """treasury_manager fallback 테스트 (이슈 #641)."""

    def test_treasury_manager_fallback(self):
        """treasury 미설정 시 treasury_manager에서 첫 번째 인스턴스 반환."""
        fake_treasury = FakeTreasury()
        manager = FakeTreasuryManager(treasuries=[fake_treasury])
        app = create_app(treasury_manager=manager)
        client = TestClient(app)

        resp = client.get("/api/treasury/budgets")
        assert resp.status_code == 200

    def test_no_treasury_no_manager_returns_503(self):
        """treasury도 treasury_manager도 없으면 503."""
        app = create_app()
        client = TestClient(app)

        resp = client.get("/api/treasury/budgets")
        assert resp.status_code == 503

    def test_empty_manager_returns_503(self):
        """treasury_manager에 Treasury가 없으면 503."""
        manager = FakeTreasuryManager(treasuries=[])
        app = create_app(treasury_manager=manager)
        client = TestClient(app)

        resp = client.get("/api/treasury/budgets")
        assert resp.status_code == 503


class TestTreasuryAllAccountAggregate:
    """#1218 — Web treasury query 정책 정렬 회귀 테스트.

    account_id 미지정 query는 default Treasury로 떨어지지 않고, 응답 schema는 보존하면서
    의미만 정렬한다. single-detail (snapshot/{date})에서 미지정 + treasury_manager 다중
    계좌 시나리오는 명시 실패 정책을 검증한다.
    """

    def test_all_account_aggregate_summary_when_no_account_id(self, client, treasury):
        """?account_id 미지정 시 default Treasury 응답 (현재 분기/schema 보존)."""
        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        # 응답 schema는 그대로 — total_balance/account_balance/is_virtual 등.
        data = resp.json()
        assert "account_balance" in data or "total_balance" in data

    def test_summary_account_id_resolved_when_explicit(self, client, treasury):
        """?account_id=... 명시 시 해당 계좌의 Treasury를 선택한다."""
        treasury.account_id = "acc-1"
        treasury.currency = "KRW"
        manager = FakeTreasuryManager(treasuries=[treasury])
        app = create_app(treasury=treasury, treasury_manager=manager)
        c = TestClient(app)

        resp = c.get("/api/treasury?account_id=acc-1")
        assert resp.status_code == 200

    def test_summary_unknown_account_id_returns_404(self):
        """?account_id=... 가 manager에 없으면 404."""
        treasury = FakeTreasury()
        treasury.account_id = "acc-1"
        treasury.currency = "KRW"
        manager = FakeTreasuryManager(treasuries=[treasury])
        app = create_app(treasury=treasury, treasury_manager=manager)
        c = TestClient(app)

        resp = c.get("/api/treasury?account_id=acc-unknown")
        assert resp.status_code == 404

    def test_snapshot_by_date_unknown_account_returns_404(self):
        """단일-detail snapshot은 account_id 가 manager에 없으면 404 (명시 실패)."""
        treasury = FakeTreasury()
        treasury.account_id = "acc-1"
        manager = FakeTreasuryManager(treasuries=[treasury])
        app = create_app(treasury=treasury, treasury_manager=manager)
        c = TestClient(app)

        resp = c.get("/api/treasury/snapshots/2026-03-21?account_id=acc-unknown")
        assert resp.status_code == 404
