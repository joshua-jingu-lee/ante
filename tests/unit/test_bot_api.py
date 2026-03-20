"""봇 CRUD API 테스트."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeBot:
    """테스트용 Bot stub."""

    def __init__(
        self, bot_id: str, status: str = "created", strategy_id: str = "s1"
    ) -> None:
        self.bot_id = bot_id
        self._status = status
        self._strategy_id = strategy_id

    @property
    def status(self) -> str:
        return self._status

    def get_info(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "name": self.bot_id,
            "status": self._status,
            "account_id": "test",
            "strategy_id": self._strategy_id,
            "interval_seconds": 60,
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

    async def create_bot(
        self, config: object, strategy_cls: object, **kwargs: object
    ) -> FakeBot:
        from ante.bot.exceptions import BotError

        bot_id = getattr(config, "bot_id", "")
        strategy_id = getattr(config, "strategy_id", "")
        if bot_id in self._bots:
            raise BotError(f"Bot already exists: {bot_id}")
        bot = FakeBot(bot_id=bot_id, strategy_id=strategy_id)
        self._bots[bot_id] = bot
        return bot

    async def start_bot(self, bot_id: str) -> None:
        bot = self._bots.get(bot_id)
        if bot:
            bot._status = "running"

    async def stop_bot(self, bot_id: str) -> None:
        bot = self._bots.get(bot_id)
        if bot:
            bot._status = "stopped"

    async def delete_bot(self, bot_id: str) -> None:
        if bot_id in self._bots:
            del self._bots[bot_id]


class FakeBotBudget:
    """테스트용 BotBudget stub."""

    def __init__(
        self,
        bot_id: str,
        allocated: float = 0.0,
        spent: float = 0.0,
        reserved: float = 0.0,
        available: float = 0.0,
    ) -> None:
        self.bot_id = bot_id
        self.allocated = allocated
        self.spent = spent
        self.reserved = reserved
        self.available = available


class FakeTreasury:
    """테스트용 Treasury stub."""

    def __init__(self) -> None:
        self._budgets: dict[str, FakeBotBudget] = {}

    def get_budget(self, bot_id: str) -> FakeBotBudget | None:
        return self._budgets.get(bot_id)


class FakePositionSnapshot:
    """테스트용 PositionSnapshot stub."""

    def __init__(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        realized_pnl: float = 0.0,
    ) -> None:
        self.bot_id = bot_id
        self.symbol = symbol
        self.quantity = quantity
        self.avg_entry_price = avg_entry_price
        self.realized_pnl = realized_pnl


class FakeTradeService:
    """테스트용 TradeService stub."""

    def __init__(self) -> None:
        self._positions: dict[str, list[FakePositionSnapshot]] = {}

    async def get_positions(
        self, bot_id: str, include_closed: bool = False
    ) -> list[FakePositionSnapshot]:
        return self._positions.get(bot_id, [])


@pytest.fixture
def bot_manager():
    return FakeBotManager()


@pytest.fixture
def treasury():
    return FakeTreasury()


@pytest.fixture
def trade_service():
    return FakeTradeService()


@pytest.fixture
def client(bot_manager):
    app = create_app(bot_manager=bot_manager)
    return TestClient(app)


@pytest.fixture
def client_with_services(bot_manager, treasury, trade_service):
    app = create_app(
        bot_manager=bot_manager,
        treasury=treasury,
        trade_service=trade_service,
    )
    return TestClient(app)


class TestListBots:
    def test_empty_list(self, client):
        """봇 없을 때 빈 목록."""
        resp = client.get("/api/bots")
        assert resp.status_code == 200
        assert resp.json()["bots"] == []

    def test_list_with_bots(self, client, bot_manager):
        """봇 목록 반환."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        resp = client.get("/api/bots")
        assert resp.status_code == 200
        assert len(resp.json()["bots"]) == 1
        assert resp.json()["bots"][0]["bot_id"] == "bot-1"


class TestGetBot:
    def test_get_existing(self, client, bot_manager):
        """봇 상세 조회."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        resp = client.get("/api/bots/bot-1")
        assert resp.status_code == 200
        assert resp.json()["bot"]["bot_id"] == "bot-1"

    def test_get_nonexistent(self, client):
        """존재하지 않는 봇 → 404."""
        resp = client.get("/api/bots/nonexistent")
        assert resp.status_code == 404


class TestStartStopBot:
    def test_start_bot(self, client, bot_manager):
        """봇 시작."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="created")
        resp = client.post("/api/bots/bot-1/start")
        assert resp.status_code == 200
        assert resp.json()["bot"]["status"] == "running"

    def test_stop_bot(self, client, bot_manager):
        """봇 중지."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="running")
        resp = client.post("/api/bots/bot-1/stop")
        assert resp.status_code == 200
        assert resp.json()["bot"]["status"] == "stopped"

    def test_start_nonexistent(self, client):
        """존재하지 않는 봇 시작 → 404."""
        resp = client.post("/api/bots/nonexistent/start")
        assert resp.status_code == 404

    def test_stop_nonexistent(self, client):
        """존재하지 않는 봇 중지 → 404."""
        resp = client.post("/api/bots/nonexistent/stop")
        assert resp.status_code == 404


class TestDeleteBot:
    def test_delete_bot(self, client, bot_manager):
        """봇 삭제."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.delete("/api/bots/bot-1")
        assert resp.status_code == 204
        assert bot_manager.get_bot("bot-1") is None

    def test_delete_nonexistent(self, client):
        """존재하지 않는 봇 삭제 → 404."""
        resp = client.delete("/api/bots/nonexistent")
        assert resp.status_code == 404


class TestGetBotWithBudget:
    def test_budget_included(self, client_with_services, bot_manager, treasury):
        """봇 상세 조회 시 예산 정보 포함."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        treasury._budgets["bot-1"] = FakeBotBudget(
            bot_id="bot-1",
            allocated=15_000_000,
            spent=5_000_000,
            reserved=1_500_000,
            available=8_500_000,
        )
        resp = client_with_services.get("/api/bots/bot-1")
        assert resp.status_code == 200
        budget = resp.json()["bot"]["budget"]
        assert budget["allocated"] == 15_000_000
        assert budget["spent"] == 5_000_000
        assert budget["reserved"] == 1_500_000
        assert budget["available"] == 8_500_000

    def test_no_budget(self, client_with_services, bot_manager):
        """예산 미할당 봇은 budget 필드 없음."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        resp = client_with_services.get("/api/bots/bot-1")
        assert resp.status_code == 200
        assert "budget" not in resp.json()["bot"]


class TestGetBotWithPositions:
    def test_positions_included(self, client_with_services, bot_manager, trade_service):
        """봇 상세 조회 시 포지션 정보 포함."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        trade_service._positions["bot-1"] = [
            FakePositionSnapshot("bot-1", "005930", 50, 72300.0, 0.0),
            FakePositionSnapshot("bot-1", "035420", 15, 210000.0, 0.0),
            FakePositionSnapshot("bot-1", "035720", 0, 0.0, 45000.0),
        ]
        resp = client_with_services.get("/api/bots/bot-1")
        assert resp.status_code == 200
        positions = resp.json()["bot"]["positions"]
        assert len(positions) == 3
        assert positions[0]["symbol"] == "005930"
        assert positions[0]["quantity"] == 50
        assert positions[0]["avg_entry_price"] == 72300.0
        # 청산 완료 종목
        assert positions[2]["quantity"] == 0
        assert positions[2]["realized_pnl"] == 45000.0

    def test_no_positions(self, client_with_services, bot_manager, trade_service):
        """포지션 없는 봇은 빈 배열."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        resp = client_with_services.get("/api/bots/bot-1")
        assert resp.status_code == 200
        assert resp.json()["bot"]["positions"] == []

    def test_no_trade_service(self, client, bot_manager):
        """trade_service 없으면 positions 필드 없음."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")
        resp = client.get("/api/bots/bot-1")
        assert resp.status_code == 200
        assert "positions" not in resp.json()["bot"]


class TestBotLifecycle:
    def test_start_stop_lifecycle(self, client, bot_manager):
        """봇 시작 → 중지 lifecycle."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1")

        # start
        resp = client.post("/api/bots/bot-1/start")
        assert resp.status_code == 200
        assert resp.json()["bot"]["status"] == "running"

        # stop
        resp = client.post("/api/bots/bot-1/stop")
        assert resp.status_code == 200
        assert resp.json()["bot"]["status"] == "stopped"

        # delete
        resp = client.delete("/api/bots/bot-1")
        assert resp.status_code == 204
