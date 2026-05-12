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
        import polars as pl

        return pl.DataFrame({"close": [100.0]})

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
        evt = BotStepCompletedEvent(
            bot_id="bot1", result="success", account_id="acc-test"
        )
        with pytest.raises(AttributeError):
            evt.bot_id = "changed"  # type: ignore[misc]

    def test_default_values(self):
        """account_id 명시 시 다른 필드는 기본값 ''을 갖는다."""
        evt = BotStepCompletedEvent(account_id="acc-test")
        assert evt.bot_id == ""
        assert evt.account_id == "acc-test"
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


from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


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
            member_service=make_master_member_service(),
        )
        return make_authed_client(app)

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
        # #1437: total 키 추가
        assert "total" in data
        assert data["total"] == len(data["logs"])

        for log in data["logs"]:
            assert "event_id" in log
            assert "timestamp" in log
            assert "result" in log
            assert "message" in log


class TestBotLogsContractDrift1437:
    """#1437 회귀 테스트 — total + offset/start_date/end_date 추가.

    spec ``docs/specs/web-api/05-resource-endpoints.md:42``는 응답에
    ``{logs, total}``과 query params ``limit/offset/start_date/end_date``를
    명시한다. 이전 구현은 ``{bot_id, logs}`` + ``limit`` only로 드리프트했다.
    """

    @pytest.fixture
    def eventbus_with_logs(self):
        return EventBus()

    @pytest.fixture
    def bot_manager(self):
        mgr = FakeBotManager()
        mgr._bots["bot1"] = FakeBot("bot1")
        return mgr

    @pytest.fixture
    def client(self, bot_manager, eventbus_with_logs):
        app = create_app(
            bot_manager=bot_manager,
            eventbus=eventbus_with_logs,
            account_service=FakeAccountService(),
            member_service=make_master_member_service(),
        )
        return make_authed_client(app)

    async def _publish_n_events(self, eb, n):
        """bot1 대상 BotStepCompletedEvent를 n개 발행."""
        for i in range(n):
            await eb.publish(
                BotStepCompletedEvent(
                    bot_id="bot1",
                    account_id="test",
                    result="success",
                    message=f"step-{i}",
                )
            )

    def test_response_has_total_key(self, client, eventbus_with_logs):
        """기존 호출 ``GET /api/bots/bot1/logs``에 ``total`` 키 존재 (회귀 방지)."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 3)
        )
        resp = client.get("/api/bots/bot1/logs")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert data["total"] == 3
        assert len(data["logs"]) == 3

    def test_offset_pagination(self, client, eventbus_with_logs):
        """``offset=1`` → fetched 4개 중 1..3 (총 3개) + total=4.

        Note: ``event_history_store.query`` / ``eventbus.get_history``의
        signature를 변경하지 않는 한 (Non-Goal #1437), ``limit``은 store
        조회량 상한 역할도 겸한다. ``offset``은 그 이후 in-memory 슬라이스다.
        실제 페이지네이션은 store 시그니처 확장 이슈에서 정리한다.
        """
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 4)
        )
        # limit=10 (>= 4) → store에서 4개 모두 fetch, offset=1로 3개 반환.
        resp = client.get("/api/bots/bot1/logs?offset=1&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 4
        assert len(data["logs"]) == 3

    def test_offset_beyond_total_returns_empty_logs(self, client, eventbus_with_logs):
        """``offset``이 ``total`` 초과 시 빈 페이지 + total 보존."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 2)
        )
        resp = client.get("/api/bots/bot1/logs?offset=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["logs"] == []

    def test_start_date_filters_by_iso_date(self, client, eventbus_with_logs):
        """``start_date=2099-01-01`` → 미래 lower bound로 모든 이벤트 제외."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 3)
        )
        resp = client.get("/api/bots/bot1/logs?start_date=2099-01-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["logs"] == []

    def test_end_date_filters_by_iso_date(self, client, eventbus_with_logs):
        """``end_date=1970-01-01`` → 과거 upper bound로 모든 이벤트 제외."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 3)
        )
        resp = client.get("/api/bots/bot1/logs?end_date=1970-01-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["logs"] == []

    def test_start_date_includes_recent_events(self, client, eventbus_with_logs):
        """``start_date=1970-01-01`` → 모든 이벤트 포함."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 3)
        )
        resp = client.get("/api/bots/bot1/logs?start_date=1970-01-01")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_end_date_inclusive_date_only_extends_to_end_of_day(
        self, client, eventbus_with_logs
    ):
        """``end_date=2099-12-31`` (date-only) → ``T23:59:59`` 확장으로
        같은 날짜 모든 이벤트 포함 (audit #1414 패턴 답습)."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 3)
        )
        resp = client.get("/api/bots/bot1/logs?end_date=2099-12-31")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_invalid_start_date_returns_422(self, client):
        """``start_date=invalid`` → 422."""
        resp = client.get("/api/bots/bot1/logs?start_date=invalid")
        assert resp.status_code == 422

    def test_invalid_end_date_returns_422(self, client):
        """``end_date=not-a-date`` → 422."""
        resp = client.get("/api/bots/bot1/logs?end_date=not-a-date")
        assert resp.status_code == 422

    def test_start_date_iso_datetime_with_z_accepted(self, client, eventbus_with_logs):
        """``start_date=2099-01-01T00:00:00Z`` (ISO datetime + Z) 허용."""
        asyncio.get_event_loop().run_until_complete(
            self._publish_n_events(eventbus_with_logs, 1)
        )
        resp = client.get("/api/bots/bot1/logs?start_date=2099-01-01T00:00:00Z")
        assert resp.status_code == 200
        # 미래 시각 lower bound → 결과 없음
        assert resp.json()["total"] == 0

    def test_negative_offset_returns_422(self, client):
        """``offset=-1`` → FastAPI ``ge=0`` 검증으로 422."""
        resp = client.get("/api/bots/bot1/logs?offset=-1")
        assert resp.status_code == 422
