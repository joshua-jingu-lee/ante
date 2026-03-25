"""Treasury is_virtual: Account.trading_mode 기반 판정 테스트 (Refs #990)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.account.models import Account, TradingMode  # noqa: E402
from ante.web.app import create_app  # noqa: E402


@dataclass
class FakeBudget:
    bot_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeTreasury:
    """테스트용 Treasury stub."""

    def __init__(self, account_id: str = "domestic") -> None:
        self._balance: float = 0.0
        self.account_id = account_id

    def get_summary(self) -> dict:
        return {"account_balance": self._balance}

    def list_budgets(self) -> list[FakeBudget]:
        return []

    @property
    def account_balance(self) -> float:
        return self._balance

    async def set_account_balance(self, balance: float) -> None:
        self._balance = balance

    async def get_latest_snapshot(self) -> None:
        return None


def _make_account(
    account_id: str = "domestic",
    trading_mode: TradingMode = TradingMode.VIRTUAL,
) -> Account:
    return Account(
        account_id=account_id,
        name="test",
        exchange="KRX",
        currency="KRW",
        trading_mode=trading_mode,
    )


class TestIsVirtualFromTradingMode:
    """is_virtual이 Account.trading_mode 기반으로 결정되는지 확인."""

    def test_virtual_account_returns_is_virtual_true(self):
        """trading_mode=VIRTUAL 계좌는 is_virtual=True."""
        treasury = FakeTreasury(account_id="domestic")
        account_service = AsyncMock()
        account_service.get.return_value = _make_account(
            "domestic", TradingMode.VIRTUAL
        )

        app = create_app(treasury=treasury, account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_virtual"] is True

    def test_live_account_returns_is_virtual_false(self):
        """trading_mode=LIVE 계좌는 is_virtual=False."""
        treasury = FakeTreasury(account_id="domestic")
        account_service = AsyncMock()
        account_service.get.return_value = _make_account("domestic", TradingMode.LIVE)

        app = create_app(treasury=treasury, account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_virtual"] is False

    def test_live_is_paper_true_returns_is_virtual_false(self):
        """LIVE + is_paper=true 조합에서 is_virtual=False (수용 조건 #2)."""
        treasury = FakeTreasury(account_id="domestic")
        account_service = AsyncMock()
        account = _make_account("domestic", TradingMode.LIVE)
        account.broker_config = {"is_paper": True}
        account_service.get.return_value = account

        # config에 is_paper=True가 있더라도 is_virtual=False 이어야 한다
        app = create_app(treasury=treasury, account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_virtual"] is False

    def test_no_account_service_defaults_to_virtual(self):
        """account_service가 없으면 is_virtual=True (안전 기본값)."""
        treasury = FakeTreasury(account_id="domestic")

        app = create_app(treasury=treasury)
        client = TestClient(app)

        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_virtual"] is True

    def test_account_not_found_defaults_to_virtual(self):
        """account_service.get()이 None 반환 시 is_virtual=True."""
        treasury = FakeTreasury(account_id="unknown")
        account_service = AsyncMock()
        account_service.get.return_value = None

        app = create_app(treasury=treasury, account_service=account_service)
        client = TestClient(app)

        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_virtual"] is True
