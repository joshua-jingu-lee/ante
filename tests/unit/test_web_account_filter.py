"""기존 API 엔드포인트의 account_id 필터 테스트.

이슈 #575: Web API — 기존 엔드포인트 account_id 연동.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402

# ── Stubs ───────────────────────────────────────────


class FakeBot:
    """테스트용 Bot stub."""

    def __init__(
        self,
        bot_id: str,
        account_id: str = "test",
        status: str = "created",
        strategy_id: str = "s1",
    ) -> None:
        self.bot_id = bot_id
        self._status = status
        self._strategy_id = strategy_id
        self._account_id = account_id

    def get_info(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "name": self.bot_id,
            "status": self._status,
            "account_id": self._account_id,
            "strategy_id": self._strategy_id,
            "interval_seconds": 60,
            "trading_mode": "",
            "exchange": "",
            "currency": "",
            "started_at": None,
            "stopped_at": None,
            "error_message": None,
        }


class FakeBotManager:
    """테스트용 BotManager stub."""

    def __init__(self) -> None:
        self._bots: dict[str, FakeBot] = {}

    def list_bots(self) -> list[dict]:
        return [b.get_info() for b in self._bots.values()]

    def get_bot(self, bot_id: str) -> FakeBot | None:
        return self._bots.get(bot_id)


class FakeTreasury:
    """테스트용 Treasury stub."""

    def __init__(
        self,
        account_id: str = "default",
        currency: str = "KRW",
    ) -> None:
        self.account_id = account_id
        self.currency = currency
        self.buy_commission_rate = 0.00015
        self.sell_commission_rate = 0.00195
        self._db = None

    def get_summary(self) -> dict:
        return {
            "total_balance": 10_000_000.0,
            "unallocated": 5_000_000.0,
            "total_allocated": 5_000_000.0,
            "total_evaluation": 10_500_000.0,
            "total_profit_loss": 500_000.0,
        }

    def list_budgets(self) -> list:
        return []

    def get_budget(self, bot_id: str) -> None:
        return None

    async def get_latest_snapshot(self) -> None:
        return None


class FakeTreasuryManager:
    """테스트용 TreasuryManager stub."""

    def __init__(self) -> None:
        self._treasuries: dict[str, FakeTreasury] = {}

    def get(self, account_id: str) -> FakeTreasury:
        if account_id not in self._treasuries:
            raise KeyError(f"Treasury not found: account_id={account_id}")
        return self._treasuries[account_id]

    def list_all(self) -> list[FakeTreasury]:
        return list(self._treasuries.values())


class FakeTradeRecord:
    """테스트용 TradeRecord stub."""

    def __init__(
        self,
        trade_id: str,
        bot_id: str,
        account_id: str = "test",
        symbol: str = "005930",
        side: str = "buy",
        quantity: float = 10.0,
        price: float = 70000.0,
        status: str = "filled",
        created_at: str = "2025-01-01T00:00:00",
    ) -> None:
        self.trade_id = trade_id
        self.bot_id = bot_id
        self.account_id = account_id
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.price = price
        self.status = status
        self.created_at = created_at
        self.timestamp = created_at
        self.strategy_id = "s1"
        self.order_type = "market"
        self.reason = ""
        self.commission = 0.0
        self.order_id = None
        self.currency = "KRW"
        self.exchange = "KRX"


class FakeTradeService:
    """테스트용 TradeService stub."""

    def __init__(self) -> None:
        self._trades: list[FakeTradeRecord] = []

    async def get_trades(
        self,
        account_id: str | None = None,
        bot_id: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
        **kwargs: object,
    ) -> list[FakeTradeRecord]:
        result = self._trades
        if account_id:
            result = [t for t in result if t.account_id == account_id]
        if bot_id:
            result = [t for t in result if t.bot_id == bot_id]
        if symbol:
            result = [t for t in result if t.symbol == symbol]
        return result[:limit]


# ── Fixtures ───────────────────────────────────────


@pytest.fixture
def bot_manager():
    mgr = FakeBotManager()
    mgr._bots["bot-a"] = FakeBot("bot-a", account_id="acct-1")
    mgr._bots["bot-b"] = FakeBot("bot-b", account_id="acct-2")
    mgr._bots["bot-c"] = FakeBot("bot-c", account_id="acct-1")
    return mgr


@pytest.fixture
def treasury():
    return FakeTreasury(account_id="default", currency="KRW")


@pytest.fixture
def treasury_manager():
    mgr = FakeTreasuryManager()
    mgr._treasuries["acct-1"] = FakeTreasury(account_id="acct-1", currency="KRW")
    mgr._treasuries["acct-2"] = FakeTreasury(account_id="acct-2", currency="USD")
    return mgr


@pytest.fixture
def trade_service():
    svc = FakeTradeService()
    svc._trades = [
        FakeTradeRecord("t1", "bot-a", account_id="acct-1", symbol="005930"),
        FakeTradeRecord("t2", "bot-b", account_id="acct-2", symbol="AAPL"),
        FakeTradeRecord("t3", "bot-c", account_id="acct-1", symbol="035720"),
    ]
    return svc


@pytest.fixture
def client(bot_manager, treasury, treasury_manager, trade_service):
    app = create_app(
        bot_manager=bot_manager,
        treasury=treasury,
        treasury_manager=treasury_manager,
        trade_service=trade_service,
    )
    return TestClient(app)


# ── Tests: Bots ────────────────────────────────────


class TestBotsAccountFilter:
    def test_filter_by_account_id(self, client):
        """account_id로 봇 필터링."""
        resp = client.get("/api/bots?account_id=acct-1")
        assert resp.status_code == 200
        bots = resp.json()["bots"]
        assert len(bots) == 2
        assert all(b["account_id"] == "acct-1" for b in bots)

    def test_filter_by_account_id_no_match(self, client):
        """일치하는 account_id 없으면 빈 목록."""
        resp = client.get("/api/bots?account_id=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["bots"] == []

    def test_no_filter_returns_all(self, client):
        """account_id 미지정 시 전체 반환 (하위 호환)."""
        resp = client.get("/api/bots")
        assert resp.status_code == 200
        assert len(resp.json()["bots"]) == 3

    def test_bot_response_has_account_id(self, client):
        """봇 응답에 account_id 필드 포함."""
        resp = client.get("/api/bots")
        assert resp.status_code == 200
        for bot in resp.json()["bots"]:
            assert "account_id" in bot


# ── Tests: Treasury ────────────────────────────────


class TestTreasuryAccountFilter:
    def test_filter_by_account_id(self, client):
        """account_id로 특정 계좌 Treasury 조회."""
        resp = client.get("/api/treasury?account_id=acct-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-1"
        assert data["currency"] == "KRW"

    def test_filter_by_account_id_usd(self, client):
        """USD 계좌 Treasury 조회."""
        resp = client.get("/api/treasury?account_id=acct-2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["account_id"] == "acct-2"
        assert data["currency"] == "USD"

    def test_no_filter_returns_default(self, client):
        """account_id 미지정 시 기본 Treasury 반환 (하위 호환)."""
        resp = client.get("/api/treasury")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_balance"] == 10_000_000.0

    def test_nonexistent_account(self, client):
        """존재하지 않는 account_id → 404."""
        resp = client.get("/api/treasury?account_id=nonexistent")
        assert resp.status_code == 404


# ── Tests: Trades ──────────────────────────────────


class TestTradesAccountFilter:
    def test_filter_by_account_id(self, client):
        """account_id로 거래 필터링."""
        resp = client.get("/api/trades?account_id=acct-1")
        assert resp.status_code == 200
        trades = resp.json()["trades"]
        assert len(trades) == 2
        assert all(t["account_id"] == "acct-1" for t in trades)

    def test_no_filter_returns_all(self, client):
        """account_id 미지정 시 전체 반환 (하위 호환)."""
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        assert len(resp.json()["trades"]) == 3

    def test_trade_response_has_account_id(self, client):
        """거래 응답에 account_id 필드 포함."""
        resp = client.get("/api/trades")
        assert resp.status_code == 200
        for trade in resp.json()["trades"]:
            assert "account_id" in trade


# ── Tests: Portfolio ──────────────────────────────


class TestPortfolioAccountFilter:
    def test_value_no_filter(self, client):
        """account_id 미지정 시 기본 Treasury 사용 (하위 호환)."""
        resp = client.get("/api/portfolio/value")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 10_500_000.0

    def test_value_with_account_id(self, client):
        """account_id 지정 시 해당 계좌 Treasury 사용."""
        resp = client.get("/api/portfolio/value?account_id=acct-1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_value"] == 10_500_000.0

    def test_value_nonexistent_account(self, client):
        """존재하지 않는 account_id → 404."""
        resp = client.get("/api/portfolio/value?account_id=nonexistent")
        assert resp.status_code == 404

    def test_history_with_nonexistent_account(self, client):
        """존재하지 않는 account_id로 필터하면 404."""
        resp = client.get("/api/portfolio/history?account_id=nonexistent")
        assert resp.status_code == 404
