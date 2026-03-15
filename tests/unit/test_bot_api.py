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
            "bot_type": "paper",
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


@pytest.fixture
def bot_manager():
    return FakeBotManager()


@pytest.fixture
def client(bot_manager):
    app = create_app(bot_manager=bot_manager)
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
