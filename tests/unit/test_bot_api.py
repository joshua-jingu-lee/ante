"""봇 CRUD API 테스트."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeBotConfig:
    """테스트용 BotConfig stub."""

    def __init__(
        self, bot_id: str, account_id: str = "test", strategy_id: str = "s1"
    ) -> None:
        self.bot_id = bot_id
        self.account_id = account_id
        self.strategy_id = strategy_id


class FakeBot:
    """테스트용 Bot stub."""

    def __init__(
        self,
        bot_id: str,
        status: str = "created",
        strategy_id: str = "s1",
        account_id: str = "test",
    ) -> None:
        self.bot_id = bot_id
        self._status = status
        self._strategy_id = strategy_id
        self._name = bot_id
        self._interval_seconds = 60
        self.config = FakeBotConfig(
            bot_id, account_id=account_id, strategy_id=strategy_id
        )

    @property
    def status(self) -> str:
        return self._status

    def get_info(self) -> dict:
        return {
            "bot_id": self.bot_id,
            "name": self._name,
            "status": self._status,
            "account_id": self.config.account_id,
            "strategy_id": self._strategy_id,
            "interval_seconds": self._interval_seconds,
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

    async def delete_bot(self, bot_id: str, handle_positions: str = "keep") -> None:
        self.last_delete_handle_positions = handle_positions
        if bot_id in self._bots:
            del self._bots[bot_id]

    async def update_bot(self, bot_id: str, **kwargs: object) -> FakeBot:
        from ante.bot.exceptions import BotError

        bot = self._bots.get(bot_id)
        if bot is None:
            raise BotError(f"Bot not found: {bot_id}")
        if bot._status not in ("created", "stopped", "error"):
            raise BotError(
                f"봇 설정은 중지 상태에서만 수정할 수 있습니다: {bot_id} "
                f"(현재: {bot._status})"
            )
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if "name" in updates:
            bot.config.bot_id = bot.config.bot_id  # keep bot_id
            # Update the name returned by get_info
            bot._name = updates["name"]
        if "interval_seconds" in updates:
            bot._interval_seconds = updates["interval_seconds"]
        if "strategy_id" in updates:
            bot._strategy_id = updates["strategy_id"]
            bot.config.strategy_id = updates["strategy_id"]
        return bot


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

    async def get_latest_snapshot(self) -> None:
        return None


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
def default_account_service():
    """기본 테스트 계좌(인증정보 포함) AccountService."""
    svc = FakeAccountService()
    svc._accounts["test"] = FakeAccount(
        "test",
        status="active",
        credentials={"app_key": "test-key", "app_secret": "test-secret"},
    )
    return svc


@pytest.fixture
def client(bot_manager, default_account_service):
    app = create_app(
        bot_manager=bot_manager,
        account_service=default_account_service,
    )
    return TestClient(app)


@pytest.fixture
def client_with_services(bot_manager, treasury, trade_service, default_account_service):
    app = create_app(
        bot_manager=bot_manager,
        treasury=treasury,
        trade_service=trade_service,
        account_service=default_account_service,
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


class TestStartBotCredentialCheck:
    """봇 시작 시 계좌 인증정보 검증 테스트."""

    @pytest.fixture
    def no_credentials_account_service(self):
        """인증정보 없는 계좌 AccountService."""
        svc = FakeAccountService()
        svc._accounts["test"] = FakeAccount("test", status="active", credentials={})
        return svc

    @pytest.fixture
    def client_no_credentials(self, bot_manager, no_credentials_account_service):
        app = create_app(
            bot_manager=bot_manager,
            account_service=no_credentials_account_service,
        )
        return TestClient(app)

    def test_start_bot_without_credentials_returns_422(
        self, client_no_credentials, bot_manager
    ):
        """인증정보 없는 계좌의 봇 시작 → 422."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="created")
        resp = client_no_credentials.post("/api/bots/bot-1/start")
        assert resp.status_code == 422
        assert "app_key" in resp.json()["detail"]

    def test_start_bot_with_empty_app_key_returns_422(self, bot_manager):
        """app_key가 빈 문자열인 계좌의 봇 시작 → 422."""
        svc = FakeAccountService()
        svc._accounts["test"] = FakeAccount(
            "test", status="active", credentials={"app_key": ""}
        )
        app = create_app(bot_manager=bot_manager, account_service=svc)
        client = TestClient(app)
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="created")
        resp = client.post("/api/bots/bot-1/start")
        assert resp.status_code == 422

    def test_start_bot_with_credentials_succeeds(self, client, bot_manager):
        """인증정보 있는 계좌의 봇 시작 → 200."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="created")
        resp = client.post("/api/bots/bot-1/start")
        assert resp.status_code == 200
        assert resp.json()["bot"]["status"] == "running"


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


class FakeAccount:
    """테스트용 Account stub."""

    def __init__(
        self,
        account_id: str = "test",
        status: str = "active",
        exchange: str = "KRX",
        credentials: dict | None = None,
    ) -> None:
        self.account_id = account_id
        self.name = account_id
        self.status = status
        self.exchange = exchange
        self.credentials = credentials if credentials is not None else {}


class FakeAccountService:
    """테스트용 AccountService stub."""

    def __init__(self) -> None:
        self._accounts: dict[str, FakeAccount] = {}

    async def get(self, account_id: str) -> FakeAccount:
        from ante.account.errors import AccountNotFoundError

        account = self._accounts.get(account_id)
        if account is None:
            raise AccountNotFoundError(f"Account not found: {account_id}")
        return account


class FakeStrategyRecord:
    """테스트용 StrategyRecord stub."""

    def __init__(
        self,
        strategy_id: str = "s1",
        filepath: str = "/tmp/s1.py",
        name: str = "",
        author: str = "test",
    ) -> None:
        self.strategy_id = strategy_id
        self.filepath = filepath
        self.name = name or strategy_id
        self.version = "0.1.0"
        self.author = author
        self.description = "test strategy"


class FakeStrategyRegistry:
    """테스트용 StrategyRegistry stub."""

    def __init__(self) -> None:
        self._strategies: dict[str, FakeStrategyRecord] = {}

    async def get(self, strategy_id: str) -> FakeStrategyRecord | None:
        return self._strategies.get(strategy_id)

    async def get_by_name(self, name: str) -> list[FakeStrategyRecord]:
        return [r for r in self._strategies.values() if r.name == name]


class TestCreateBotAccountStatus:
    """봇 생성 시 계좌 상태 검증 테스트."""

    @pytest.fixture
    def account_service(self):
        svc = FakeAccountService()
        svc._accounts["test"] = FakeAccount("test", status="active")
        return svc

    @pytest.fixture
    def suspended_account_service(self):
        svc = FakeAccountService()
        svc._accounts["test"] = FakeAccount("test", status="suspended")
        return svc

    @pytest.fixture
    def strategy_registry(self):
        reg = FakeStrategyRegistry()
        reg._strategies["s1"] = FakeStrategyRecord("s1")
        return reg

    @pytest.fixture
    def client_suspended(
        self, bot_manager, suspended_account_service, strategy_registry
    ):
        app = create_app(
            bot_manager=bot_manager,
            account_service=suspended_account_service,
            strategy_registry=strategy_registry,
        )
        return TestClient(app)

    def test_create_bot_suspended_account_returns_409(self, client_suspended):
        """정지된 계좌에서 봇 생성 → 409 Conflict."""
        resp = client_suspended.post(
            "/api/bots",
            json={
                "bot_id": "bot-1",
                "strategy_id": "s1",
                "account_id": "test",
            },
        )
        assert resp.status_code == 409
        assert "suspended" in resp.json()["detail"]

    def test_create_bot_deleted_account_returns_409(
        self, bot_manager, strategy_registry
    ):
        """삭제된 계좌에서 봇 생성 → 409 Conflict."""
        account_svc = FakeAccountService()
        account_svc._accounts["deleted-acc"] = FakeAccount(
            "deleted-acc", status="deleted"
        )
        app = create_app(
            bot_manager=bot_manager,
            account_service=account_svc,
            strategy_registry=strategy_registry,
        )
        client = TestClient(app)
        resp = client.post(
            "/api/bots",
            json={
                "bot_id": "bot-1",
                "strategy_id": "s1",
                "account_id": "deleted-acc",
            },
        )
        assert resp.status_code == 409
        assert "deleted" in resp.json()["detail"]


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


class TestListBotsStrategyName:
    """list_bots 응답에 strategy_name, strategy_author_name 포함 테스트."""

    @pytest.fixture
    def strategy_registry(self):
        reg = FakeStrategyRegistry()
        reg._strategies["s1"] = FakeStrategyRecord(
            "s1", name="MyStrategy", author="alice"
        )
        return reg

    @pytest.fixture
    def client_with_registry(
        self, bot_manager, default_account_service, strategy_registry
    ):
        app = create_app(
            bot_manager=bot_manager,
            account_service=default_account_service,
            strategy_registry=strategy_registry,
        )
        return TestClient(app)

    def test_strategy_name_included(self, client_with_registry, bot_manager):
        """봇 목록에 strategy_name, strategy_author_name 포함."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="s1")
        resp = client_with_registry.get("/api/bots")
        assert resp.status_code == 200
        bot = resp.json()["bots"][0]
        assert bot["strategy_name"] == "MyStrategy"
        assert bot["strategy_author_name"] == "alice"

    def test_strategy_not_found_returns_null(self, client_with_registry, bot_manager):
        """레지스트리에 없는 전략이면 strategy_name은 null."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="unknown")
        resp = client_with_registry.get("/api/bots")
        assert resp.status_code == 200
        bot = resp.json()["bots"][0]
        assert bot["strategy_name"] is None
        assert bot["strategy_author_name"] is None

    def test_no_registry_returns_null(self, client, bot_manager):
        """레지스트리 없으면 strategy_name은 null."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="s1")
        resp = client.get("/api/bots")
        assert resp.status_code == 200
        bot = resp.json()["bots"][0]
        assert bot["strategy_name"] is None
        assert bot["strategy_author_name"] is None


class TestGetBotStrategyName:
    """get_bot 응답에 strategy_name, strategy_author_name 포함 테스트."""

    @pytest.fixture
    def strategy_registry(self):
        reg = FakeStrategyRegistry()
        reg._strategies["s1"] = FakeStrategyRecord(
            "s1", name="MyStrategy", author="alice"
        )
        return reg

    @pytest.fixture
    def client_with_registry(
        self, bot_manager, default_account_service, strategy_registry
    ):
        app = create_app(
            bot_manager=bot_manager,
            account_service=default_account_service,
            strategy_registry=strategy_registry,
        )
        return TestClient(app)

    def test_strategy_name_included(self, client_with_registry, bot_manager):
        """봇 상세 조회에 strategy_name, strategy_author_name 포함."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="s1")
        resp = client_with_registry.get("/api/bots/bot-1")
        assert resp.status_code == 200
        bot = resp.json()["bot"]
        assert bot["strategy_name"] == "MyStrategy"
        assert bot["strategy_author_name"] == "alice"
        # strategy 상세 객체도 여전히 포함
        assert bot["strategy"]["name"] == "MyStrategy"

    def test_strategy_not_found_returns_null(self, client_with_registry, bot_manager):
        """레지스트리에 없는 전략이면 strategy_name은 null."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="unknown")
        resp = client_with_registry.get("/api/bots/bot-1")
        assert resp.status_code == 200
        bot = resp.json()["bot"]
        assert bot["strategy_name"] is None
        assert bot["strategy_author_name"] is None

    def test_no_registry_returns_null(self, client, bot_manager):
        """레지스트리 없으면 strategy_name은 null."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", strategy_id="s1")
        resp = client.get("/api/bots/bot-1")
        assert resp.status_code == 200
        bot = resp.json()["bot"]
        assert bot["strategy_name"] is None
        assert bot["strategy_author_name"] is None


class TestDeleteBotHandlePositions:
    """DELETE /api/bots/{id}?handle_positions 테스트."""

    def test_delete_keep_default(self, client, bot_manager):
        """기본값(keep)으로 봇 삭제."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.delete("/api/bots/bot-1")
        assert resp.status_code == 204
        assert bot_manager.last_delete_handle_positions == "keep"

    def test_delete_keep_explicit(self, client, bot_manager):
        """handle_positions=keep 명시적 전달."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.delete("/api/bots/bot-1?handle_positions=keep")
        assert resp.status_code == 204
        assert bot_manager.last_delete_handle_positions == "keep"

    def test_delete_liquidate(self, client, bot_manager):
        """handle_positions=liquidate로 봇 삭제."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.delete("/api/bots/bot-1?handle_positions=liquidate")
        assert resp.status_code == 204
        assert bot_manager.last_delete_handle_positions == "liquidate"

    def test_delete_invalid_handle_positions(self, client, bot_manager):
        """잘못된 handle_positions 값 -> 422."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.delete("/api/bots/bot-1?handle_positions=invalid")
        assert resp.status_code == 422
        assert "handle_positions" in resp.json()["detail"]

    def test_delete_nonexistent_with_liquidate(self, client):
        """존재하지 않는 봇에 liquidate -> 404."""
        resp = client.delete("/api/bots/nonexistent?handle_positions=liquidate")
        assert resp.status_code == 404


class TestDeleteBotAuditLog:
    """봇 삭제 감사 로그에 handle_positions 기록 테스트."""

    @pytest.fixture
    def audit_logs(self):
        return []

    @pytest.fixture
    def fake_audit_logger(self, audit_logs):
        class _FakeAuditLogger:
            async def log(self, **kwargs):
                audit_logs.append(kwargs)

        return _FakeAuditLogger()

    @pytest.fixture
    def client_with_audit(
        self, bot_manager, default_account_service, fake_audit_logger
    ):
        app = create_app(
            bot_manager=bot_manager,
            account_service=default_account_service,
            audit_logger=fake_audit_logger,
        )
        return TestClient(app)

    def test_audit_log_records_keep(self, client_with_audit, bot_manager, audit_logs):
        """감사 로그에 handle_positions=keep 기록."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client_with_audit.delete("/api/bots/bot-1")
        assert resp.status_code == 204
        delete_logs = [
            entry for entry in audit_logs if entry.get("action") == "bot.delete"
        ]
        assert len(delete_logs) == 1
        assert delete_logs[0]["detail"] == "handle_positions=keep"

    def test_audit_log_records_liquidate(
        self, client_with_audit, bot_manager, audit_logs
    ):
        """감사 로그에 handle_positions=liquidate 기록."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client_with_audit.delete("/api/bots/bot-1?handle_positions=liquidate")
        assert resp.status_code == 204
        delete_logs = [
            entry for entry in audit_logs if entry.get("action") == "bot.delete"
        ]
        assert len(delete_logs) == 1
        assert delete_logs[0]["detail"] == "handle_positions=liquidate"


class TestUpdateBot:
    """PUT /api/bots/{bot_id} 봇 설정 수정 테스트."""

    def test_update_name(self, client, bot_manager):
        """이름 변경."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"name": "새 이름"})
        assert resp.status_code == 200
        assert resp.json()["bot"]["name"] == "새 이름"

    def test_update_interval_seconds(self, client, bot_manager):
        """실행 간격 변경."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"interval_seconds": 120})
        assert resp.status_code == 200
        assert resp.json()["bot"]["interval_seconds"] == 120

    def test_update_nonexistent_bot_returns_404(self, client):
        """존재하지 않는 봇 수정 -> 404."""
        resp = client.put("/api/bots/nonexistent", json={"name": "x"})
        assert resp.status_code == 404

    def test_update_running_bot_returns_409(self, client, bot_manager):
        """실행 중인 봇 수정 -> 409."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="running")
        resp = client.put("/api/bots/bot-1", json={"name": "x"})
        assert resp.status_code == 409
        assert "중지 상태" in resp.json()["detail"]

    def test_update_created_bot_allowed(self, client, bot_manager):
        """created 상태 봇 수정 허용."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="created")
        resp = client.put("/api/bots/bot-1", json={"name": "updated"})
        assert resp.status_code == 200

    def test_update_error_bot_allowed(self, client, bot_manager):
        """error 상태 봇 수정 허용."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="error")
        resp = client.put("/api/bots/bot-1", json={"name": "fixed"})
        assert resp.status_code == 200

    def test_empty_body_returns_current(self, client, bot_manager):
        """빈 body면 현재 상태 반환."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={})
        assert resp.status_code == 200
        assert resp.json()["bot"]["bot_id"] == "bot-1"

    def test_interval_below_min_returns_422(self, client, bot_manager):
        """interval_seconds < 10 -> 422 (validation error)."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"interval_seconds": 5})
        assert resp.status_code == 422

    def test_interval_above_max_returns_422(self, client, bot_manager):
        """interval_seconds > 3600 -> 422 (validation error)."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"interval_seconds": 7200})
        assert resp.status_code == 422

    def test_budget_zero_or_negative_returns_422(self, client, bot_manager):
        """budget <= 0 -> 422 (validation error)."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"budget": 0})
        assert resp.status_code == 422
        resp = client.put("/api/bots/bot-1", json={"budget": -100})
        assert resp.status_code == 422

    def test_budget_treasury_error_returns_422(
        self, bot_manager, default_account_service
    ):
        """budget 변경 시 TreasuryError 발생하면 500이 아닌 422 반환."""
        from ante.treasury.exceptions import InsufficientFundsError

        async def update_bot_with_treasury_error(bot_id, **kwargs):
            bot = bot_manager._bots.get(bot_id)
            if bot is None:
                from ante.bot.exceptions import BotError

                raise BotError(f"Bot not found: {bot_id}")
            if "budget" in kwargs:
                raise InsufficientFundsError(
                    "미할당 잔액 부족: 필요 2,000,000, 가용 500,000"
                )
            return bot

        bot_manager.update_bot = update_bot_with_treasury_error
        app = create_app(
            bot_manager=bot_manager,
            account_service=default_account_service,
        )
        client = TestClient(app)
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"budget": 2000000})
        assert resp.status_code == 422
        assert "잔액 부족" in resp.json()["detail"]

    def test_budget_update_success(self, client, bot_manager):
        """budget 변경 성공 시 200 반환."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"budget": 2000000})
        assert resp.status_code == 200


class TestUpdateBotStrategy:
    """PUT /api/bots/{bot_id} 전략 변경 테스트."""

    @pytest.fixture
    def strategy_registry(self):
        reg = FakeStrategyRegistry()
        reg._strategies["s1"] = FakeStrategyRecord("s1", name="OldStrategy")
        reg._strategies["s2"] = FakeStrategyRecord("s2", name="NewStrategy")
        return reg

    @pytest.fixture
    def client_with_registry(
        self, bot_manager, strategy_registry, default_account_service
    ):
        app = create_app(
            bot_manager=bot_manager,
            strategy_registry=strategy_registry,
            account_service=default_account_service,
        )
        return TestClient(app)

    def test_update_strategy_name(
        self, client_with_registry, bot_manager, strategy_registry
    ):
        """strategy_name으로 전략 변경 성공."""
        bot_manager._bots["bot-1"] = FakeBot(
            "bot-1", status="stopped", strategy_id="s1"
        )
        resp = client_with_registry.put(
            "/api/bots/bot-1", json={"strategy_name": "NewStrategy"}
        )
        assert resp.status_code == 200
        assert bot_manager._bots["bot-1"]._strategy_id == "s2"

    def test_update_strategy_name_not_found(self, client_with_registry, bot_manager):
        """존재하지 않는 전략 이름 -> 404."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client_with_registry.put(
            "/api/bots/bot-1", json={"strategy_name": "NonExistent"}
        )
        assert resp.status_code == 404
        assert "전략을 찾을 수 없습니다" in resp.json()["detail"]

    def test_update_strategy_without_registry(self, client, bot_manager):
        """strategy_registry가 없을 때 strategy_name 전달 -> 503."""
        bot_manager._bots["bot-1"] = FakeBot("bot-1", status="stopped")
        resp = client.put("/api/bots/bot-1", json={"strategy_name": "SomeStrategy"})
        assert resp.status_code == 503
