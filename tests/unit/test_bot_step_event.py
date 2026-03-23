"""BotStepCompletedEvent 발행 및 봇 로그 API 테스트 (#786)."""

from __future__ import annotations

import asyncio

import pytest

from ante.bot import Bot, BotConfig, BotStatus
from ante.eventbus import EventBus
from ante.eventbus.events import BotStepCompletedEvent
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Signal,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

# ── Fake 구현체 ──────────────────────────────────


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        return [{"close": 100.0}]

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


# ── Fixtures ──────────────────────────────────


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def ctx():
    return StrategyContext(
        bot_id="bot1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolioView(),
        order_view=FakeOrderView(),
    )


def _make_bot(strategy_cls, eventbus, ctx, *, step_timeout=0.01, max_signals=5):
    """테스트용 Bot 생성."""
    config = BotConfig(
        bot_id="bot1",
        strategy_id="test_stg",
        account_id="test",
        interval_seconds=60,
        step_timeout_seconds=step_timeout,
        max_signals_per_step=max_signals,
    )
    config.interval_seconds = 0.01
    bot = Bot(
        config=config,
        strategy_cls=strategy_cls,
        ctx=ctx,
        eventbus=eventbus,
    )
    bot._max_consecutive_failures = 3
    return bot


# ── 이벤트 정의 테스트 ──────────────────────────────


class TestBotStepCompletedEventDefinition:
    """BotStepCompletedEvent 데이터클래스 정의 검증."""

    def test_event_fields(self):
        """필수 필드가 모두 존재해야 한다."""
        evt = BotStepCompletedEvent(
            bot_id="bot1",
            account_id="acc1",
            result="success",
            message="signals=0",
        )
        assert evt.bot_id == "bot1"
        assert evt.account_id == "acc1"
        assert evt.result == "success"
        assert evt.message == "signals=0"

    def test_event_is_frozen(self):
        """이벤트는 frozen dataclass여야 한다."""
        evt = BotStepCompletedEvent(bot_id="bot1", result="success")
        with pytest.raises(AttributeError):
            evt.bot_id = "changed"  # type: ignore[misc]

    def test_default_values(self):
        """기본값 검증."""
        evt = BotStepCompletedEvent()
        assert evt.bot_id == ""
        assert evt.account_id == ""
        assert evt.result == ""
        assert evt.message == ""


# ── _run_loop 이벤트 발행 테스트 ──────────────────────


class TestBotStepCompletedEventPublish:
    """_run_loop에서 BotStepCompletedEvent 발행 검증."""

    async def test_success_step_publishes_event(self, eventbus, ctx):
        """정상 on_step 완료 시 result='success' 이벤트 발행."""
        call_count = 0

        class OneShotStrategy(Strategy):
            meta = StrategyMeta(name="oneshot", version="0.1.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                nonlocal call_count
                call_count += 1
                if call_count >= 1:
                    bot.status = BotStatus.STOPPED
                return []

        bot = _make_bot(OneShotStrategy, eventbus, ctx)
        bot.strategy = OneShotStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        captured: list[BotStepCompletedEvent] = []
        eventbus.subscribe(BotStepCompletedEvent, lambda e: captured.append(e))

        await bot._run_loop()

        assert len(captured) == 1
        assert captured[0].bot_id == "bot1"
        assert captured[0].account_id == "test"
        assert captured[0].result == "success"
        assert "signals=0" in captured[0].message

    async def test_timeout_step_publishes_event(self, eventbus, ctx):
        """on_step 타임아웃 시 result='timeout' 이벤트 발행."""

        class TimeoutStrategy(Strategy):
            meta = StrategyMeta(name="timeout", version="0.1.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                await asyncio.sleep(9999)
                return []

        bot = _make_bot(TimeoutStrategy, eventbus, ctx)
        bot.strategy = TimeoutStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        captured: list[BotStepCompletedEvent] = []
        eventbus.subscribe(BotStepCompletedEvent, lambda e: captured.append(e))

        await bot._run_loop()

        # 3회 타임아웃 발생 (max_consecutive_failures=3)
        assert len(captured) == 3
        for evt in captured:
            assert evt.result == "timeout"
            assert evt.bot_id == "bot1"

    async def test_signal_overflow_publishes_event(self, eventbus, ctx):
        """Signal 수 초과 시 result='signal_overflow' 이벤트 발행."""
        call_count = 0

        class OverflowStrategy(Strategy):
            meta = StrategyMeta(name="overflow", version="0.1.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                nonlocal call_count
                call_count += 1
                # 매번 max보다 많은 시그널 반환
                return [
                    Signal(symbol="005930", side="buy", quantity=1.0, reason="test")
                    for _ in range(10)
                ]

        bot = _make_bot(OverflowStrategy, eventbus, ctx, max_signals=5)
        bot.strategy = OverflowStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        captured: list[BotStepCompletedEvent] = []
        eventbus.subscribe(BotStepCompletedEvent, lambda e: captured.append(e))

        await bot._run_loop()

        assert len(captured) >= 1
        for evt in captured:
            assert evt.result == "signal_overflow"
            assert "10 > 5" in evt.message

    async def test_error_step_publishes_event(self, eventbus, ctx):
        """on_step 예외 시 result='error' 이벤트 발행."""

        class ErrorStrategy(Strategy):
            meta = StrategyMeta(name="error", version="0.1.0", description="test")

            async def on_step(self, context) -> list[Signal]:
                raise ValueError("test error in on_step")

        bot = _make_bot(ErrorStrategy, eventbus, ctx)
        bot.strategy = ErrorStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        captured: list[BotStepCompletedEvent] = []
        eventbus.subscribe(BotStepCompletedEvent, lambda e: captured.append(e))

        await bot._run_loop()

        assert len(captured) == 1
        assert captured[0].result == "error"
        assert "test error in on_step" in captured[0].message


# ── 봇 로그 API 테스트 ──────────────────────────────

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeBotConfig:
    def __init__(self, bot_id, account_id="test", strategy_id="s1"):
        self.bot_id = bot_id
        self.account_id = account_id
        self.strategy_id = strategy_id


class FakeBot:
    def __init__(self, bot_id, status="running", account_id="test"):
        self.bot_id = bot_id
        self._status = status
        self.config = FakeBotConfig(bot_id, account_id=account_id)

    def get_info(self):
        return {
            "bot_id": self.bot_id,
            "name": self.bot_id,
            "status": self._status,
            "account_id": self.config.account_id,
            "strategy_id": "s1",
            "interval_seconds": 60,
            "trading_mode": "",
            "exchange": "",
            "currency": "",
            "started_at": None,
            "stopped_at": None,
            "error_message": None,
        }


class FakeBotManager:
    def __init__(self):
        self._bots: dict[str, FakeBot] = {}

    def list_bots(self):
        return [b.get_info() for b in self._bots.values()]

    def get_bot(self, bot_id):
        return self._bots.get(bot_id)


class FakeAccount:
    def __init__(self, account_id="test", status="active", credentials=None):
        self.account_id = account_id
        self.name = account_id
        self.status = status
        self.exchange = "KRX"
        self.credentials = credentials or {"app_key": "k", "app_secret": "s"}


class FakeAccountService:
    def __init__(self):
        self._accounts: dict[str, FakeAccount] = {"test": FakeAccount()}

    async def get(self, account_id):
        from ante.account.errors import AccountNotFoundError

        acct = self._accounts.get(account_id)
        if acct is None:
            raise AccountNotFoundError(f"Account not found: {account_id}")
        return acct


class TestBotLogsAPIWithEventBus:
    """EventBus 인메모리 히스토리 기반 봇 로그 API 테스트."""

    @pytest.fixture
    def eventbus_with_logs(self):
        eb = EventBus()
        return eb

    @pytest.fixture
    def bot_manager(self):
        mgr = FakeBotManager()
        mgr._bots["bot1"] = FakeBot("bot1")
        mgr._bots["bot2"] = FakeBot("bot2")
        return mgr

    @pytest.fixture
    def client(self, bot_manager, eventbus_with_logs):
        app = create_app(
            bot_manager=bot_manager,
            eventbus=eventbus_with_logs,
            account_service=FakeAccountService(),
        )
        return TestClient(app)

    async def _publish_events(self, eb):
        """테스트용 이벤트 발행."""
        await eb.publish(
            BotStepCompletedEvent(
                bot_id="bot1", account_id="test", result="success", message="signals=2"
            )
        )
        await eb.publish(
            BotStepCompletedEvent(
                bot_id="bot1", account_id="test", result="timeout", message="timeout 1"
            )
        )
        await eb.publish(
            BotStepCompletedEvent(
                bot_id="bot2", account_id="test", result="success", message="signals=0"
            )
        )

    def test_logs_returns_bot_specific_events(
        self, client, eventbus_with_logs, bot_manager
    ):
        """봇 ID로 필터링된 로그만 반환."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_events(eventbus_with_logs)
        )

        resp = client.get("/api/bots/bot1/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bot_id"] == "bot1"
        assert len(data["logs"]) == 2
        results = [log["result"] for log in data["logs"]]
        assert "success" in results
        assert "timeout" in results

    def test_logs_bot_not_found(self, client):
        """존재하지 않는 봇 → 404."""
        resp = client.get("/api/bots/nonexistent/logs")
        assert resp.status_code == 404

    def test_logs_empty_when_no_events(self, client, bot_manager):
        """이벤트가 없으면 빈 배열."""
        resp = client.get("/api/bots/bot1/logs")
        assert resp.status_code == 200
        assert resp.json()["logs"] == []

    def test_logs_limit_parameter(self, client, eventbus_with_logs, bot_manager):
        """limit 파라미터 적용."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_events(eventbus_with_logs)
        )

        resp = client.get("/api/bots/bot1/logs?limit=1")
        assert resp.status_code == 200
        # limit은 EventBus 조회에 적용되므로 bot_id 필터 전
        assert len(resp.json()["logs"]) <= 1

    def test_logs_response_structure(self, client, eventbus_with_logs, bot_manager):
        """응답 구조 검증."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_events(eventbus_with_logs)
        )

        resp = client.get("/api/bots/bot1/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "bot_id" in data
        assert "logs" in data

        for log in data["logs"]:
            assert "event_id" in log
            assert "timestamp" in log
            assert "result" in log
            assert "message" in log
