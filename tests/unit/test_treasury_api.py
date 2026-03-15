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
