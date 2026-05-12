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


class TestBotLogsPagination1437R1:
    """#1437 fix loop r1 회귀 — Codex P2 (페이지네이션 전 limit 조회 broken).

    r0 구현은 ``store.query(limit=limit)`` 호출로 store에서 ``LIMIT limit``
    만 fetch한 뒤 in-memory에서 ``[offset:offset+limit]`` 슬라이스했다. 따라서
    ``offset=10&limit=10`` 같은 2페이지 요청 시 store가 10개만 가져오고 그 중
    10번째 이후를 슬라이스하므로 결과가 비거나 짧고, ``total`` 역시 처음 limit
    범위로만 카운트되었다.

    r1은 EventHistoryStore 경로에서 ``_BOT_LOGS_FETCH_HARD_CAP``(=10000)으로
    매칭 가능 범위 전체를 fetch한 뒤 in-memory에서 ``bot_id`` 필터 + total +
    페이지 슬라이스를 계산한다. 본 클래스는 30개 로그 mock으로 2페이지가
    정상 동작하고 ``total`` 이 limit 범위 외도 포함하는지 검증한다.
    """

    @pytest.fixture
    def bot_manager(self):
        mgr = FakeBotManager()
        mgr._bots["bot1"] = FakeBot("bot1")
        return mgr

    @pytest.fixture
    def event_history_store(self):
        """30개 BotStepCompletedEvent 로그를 영속 저장한 fake store.

        실제 ``EventHistoryStore``를 ``Database`` (file-backed SQLite)와 함께
        쓰면 페이지네이션 + filter SQL 동작도 함께 검증할 수 있다.
        """
        from datetime import UTC, datetime, timedelta

        from ante.core import Database
        from ante.eventbus.history import EventHistoryStore

        async def _setup():
            import tempfile

            tmpdir = tempfile.mkdtemp(prefix="ante-test-")
            db = Database(f"{tmpdir}/event.db")
            await db.connect()
            store = EventHistoryStore(db=db)
            await store.initialize()
            base = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
            for i in range(30):
                ts = base + timedelta(minutes=i)
                await store.record(
                    BotStepCompletedEvent(
                        bot_id="bot1",
                        account_id="test",
                        result="success",
                        message=f"step-{i}",
                        timestamp=ts,
                    )
                )
            return store, db

        store, db = asyncio.get_event_loop().run_until_complete(_setup())
        yield store
        asyncio.get_event_loop().run_until_complete(db.close())

    @pytest.fixture
    def client(self, bot_manager, event_history_store):
        app = create_app(
            bot_manager=bot_manager,
            event_history_store=event_history_store,
            account_service=FakeAccountService(),
            member_service=make_master_member_service(),
        )
        return make_authed_client(app)

    def test_offset_10_limit_10_returns_second_page(self, client):
        """``offset=10&limit=10`` → 30 중 2페이지(11..20번째) 정상 반환.

        r0 회귀: store가 10개만 fetch 후 [10:20] 슬라이스 → 빈 페이지.
        r1 fix: store에서 매칭 가능 범위 전체 fetch → [10:20] 슬라이스로 10개.
        """
        resp = client.get("/api/bots/bot1/logs?offset=10&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 30
        assert len(data["logs"]) == 10

    def test_total_covers_full_match_set(self, client):
        """``total`` 이 limit 범위 외 row까지 포함한 전체 매칭 개수.

        r0 회귀: ``len(filtered)``가 store fetch limit으로 잘렸음. r1 fix:
        매칭 가능 범위 전체 fetch 후 in-memory bot_id 필터 카운트.
        """
        # limit이 작아도 total은 전체 30.
        resp = client.get("/api/bots/bot1/logs?limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 30
        assert len(data["logs"]) == 5

    def test_third_page_offset_20_limit_10(self, client):
        """``offset=20&limit=10`` → 30 중 3페이지(21..30번째) 정상."""
        resp = client.get("/api/bots/bot1/logs?offset=20&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 30
        assert len(data["logs"]) == 10

    def test_offset_past_total_returns_empty_with_total_preserved(self, client):
        """``offset=100`` (total 초과) → 빈 페이지 + total=30 보존."""
        resp = client.get("/api/bots/bot1/logs?offset=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 30
        assert data["logs"] == []


class TestBotLogsTimezoneNormalization1437R1:
    """#1437 fix loop r1 회귀 — Codex P2 (Timezone 정규화 누락).

    r0 구현은 ``start_date``/``end_date`` 입력 문자열을 그대로 보존하고
    in-memory ``timestamp >= start_date`` 사전식 비교에 사용했다. 저장된
    storage timestamp는 UTC ISO 문자열인데, 입력이 ``+09:00`` 같은 zone
    offset suffix를 포함하면 ASCII 정렬 규칙으로 실제 UTC 시간 관계와
    어긋난다.

    예: 입력 ``2026-05-10T09:00:00+09:00`` (UTC ``00:00``) → storage
    ``2026-05-10T00:30:00+00:00`` (UTC ``00:30``) 는 ``>=`` 입력보다 30분
    뒤이지만, ASCII 비교에서 ``"2026-05-10T00:30:00+00:00"`` <
    ``"2026-05-10T09:00:00+09:00"`` (``0`` < ``9``) 로 평가되어 누락.

    r1 fix: ``_validate_iso_date_param``이 입력을 UTC tz-aware datetime으로
    정규화한 뒤 ``EventHistoryStore``에 SQL filter로 넘기므로, storage suffix
    (``+00:00``) 와 일치하고 datetime 비교 시맨틱이 보존된다.
    """

    @pytest.fixture
    def bot_manager(self):
        mgr = FakeBotManager()
        mgr._bots["bot1"] = FakeBot("bot1")
        return mgr

    @pytest.fixture
    def event_history_store(self):
        """timezone 검증용 로그 fixture.

        bot1 로그를 다음 UTC 시각에 저장:
          - 2026-05-09T15:00:00Z (전날, 한국시간 2026-05-10 00:00 KST)
          - 2026-05-09T23:30:00Z (전날 자정 30분 전, 한국시간 2026-05-10 08:30 KST)
          - 2026-05-10T00:30:00Z (다음날 새벽 30분, 한국시간 2026-05-10 09:30 KST)
          - 2026-05-10T05:00:00Z (한국시간 2026-05-10 14:00 KST)
          - 2026-05-10T23:30:00Z (한국시간 2026-05-11 08:30 KST)
        """
        from datetime import UTC, datetime

        from ante.core import Database
        from ante.eventbus.history import EventHistoryStore

        async def _setup():
            import tempfile

            tmpdir = tempfile.mkdtemp(prefix="ante-test-")
            db = Database(f"{tmpdir}/event.db")
            await db.connect()
            store = EventHistoryStore(db=db)
            await store.initialize()
            for hh, mm in [(15, 0), (23, 30)]:
                await store.record(
                    BotStepCompletedEvent(
                        bot_id="bot1",
                        account_id="test",
                        result="success",
                        message=f"05-09T{hh:02d}:{mm:02d}",
                        timestamp=datetime(2026, 5, 9, hh, mm, 0, tzinfo=UTC),
                    )
                )
            for hh, mm in [(0, 30), (5, 0), (23, 30)]:
                await store.record(
                    BotStepCompletedEvent(
                        bot_id="bot1",
                        account_id="test",
                        result="success",
                        message=f"05-10T{hh:02d}:{mm:02d}",
                        timestamp=datetime(2026, 5, 10, hh, mm, 0, tzinfo=UTC),
                    )
                )
            return store, db

        store, db = asyncio.get_event_loop().run_until_complete(_setup())
        yield store
        asyncio.get_event_loop().run_until_complete(db.close())

    @pytest.fixture
    def client(self, bot_manager, event_history_store):
        app = create_app(
            bot_manager=bot_manager,
            event_history_store=event_history_store,
            account_service=FakeAccountService(),
            member_service=make_master_member_service(),
        )
        return make_authed_client(app)

    def test_start_date_with_positive_offset_normalizes_to_utc(self, client):
        """``start_date=2026-05-10T09:00:00+09:00`` (= UTC 2026-05-10T00:00)
        입력 시 UTC ``00:30`` 로그가 정상 포함된다.

        r0 회귀: 입력 문자열 그대로 ``timestamp >= "2026-05-10T09:00:00+09:00"``
        사전식 비교 → ``"2026-05-10T00:30:00+00:00"`` < (input) → 누락. r1:
        UTC tz-aware로 정규화 → datetime 비교에서 storage 00:30 > input 00:00
        → 포함.
        """
        # URL에서 ``+`` 는 space 인코딩이므로 ``%2B`` 로 escape.
        resp = client.get("/api/bots/bot1/logs?start_date=2026-05-10T09:00:00%2B09:00")
        assert resp.status_code == 200
        data = resp.json()
        # UTC 2026-05-10 00:00 이상: 00:30, 05:00, 23:30 → 3개.
        messages = sorted(log["message"] for log in data["logs"])
        assert data["total"] == 3
        assert messages == [
            "05-10T00:30",
            "05-10T05:00",
            "05-10T23:30",
        ]

    def test_end_date_with_negative_offset_normalizes_to_utc(self, client):
        """``end_date=2026-05-10T00:00:00-05:00`` (= UTC 2026-05-10T05:00).
        같은 시각의 storage 로그가 inclusive upper bound로 포함된다.
        """
        # ``-05:00``은 URL에서 그대로 사용 가능 (RFC 3986 unreserved).
        resp = client.get("/api/bots/bot1/logs?end_date=2026-05-10T00:00:00-05:00")
        assert resp.status_code == 200
        data = resp.json()
        # UTC 2026-05-10 05:00 이하: 05-09 15:00/23:30 + 05-10 00:30/05:00 → 4개.
        messages = sorted(log["message"] for log in data["logs"])
        assert data["total"] == 4
        assert messages == [
            "05-09T15:00",
            "05-09T23:30",
            "05-10T00:30",
            "05-10T05:00",
        ]

    def test_date_only_start_normalizes_to_utc_midnight(self, client):
        """``start_date=2026-05-10`` (date-only) → UTC ``T00:00:00`` 정규화.

        UTC 2026-05-10 00:00 이상 logs (00:30, 05:00, 23:30) → 3개.
        """
        resp = client.get("/api/bots/bot1/logs?start_date=2026-05-10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3

    def test_date_only_end_extends_to_end_of_day_utc(self, client):
        """``end_date=2026-05-10`` (date-only) → UTC ``T23:59:59.999999`` 확장.

        UTC 2026-05-10 23:59:59.999999 이하 logs (00:30, 05:00, 23:30) 포함 +
        05-09 15:00, 23:30 도 포함(과거) → 총 5개.
        """
        resp = client.get("/api/bots/bot1/logs?end_date=2026-05-10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5

    def test_z_suffix_equivalent_to_plus_zero(self, client):
        """``Z`` suffix와 ``+00:00`` offset이 동일 결과를 낸다."""
        r1 = client.get("/api/bots/bot1/logs?start_date=2026-05-10T00:00:00Z")
        r2 = client.get("/api/bots/bot1/logs?start_date=2026-05-10T00:00:00%2B00:00")
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["total"] == r2.json()["total"]
        assert r1.json()["total"] == 3


class TestBotLogsSqlPayloadFilter1437R2:
    """#1437 fix loop r2 회귀 — Codex P2 (hard cap silent miss + 위치 인자
    오바인딩).

    r1은 두 가지 silent failure가 남아있었다:

    (1) ``EventHistoryStore.query`` 시그니처가 ``until``을 ``limit`` 앞 위치
        인자로 추가해 ``query(type, since, 50)`` 같은 세 번째 위치 인자
        ``50`` 이 ``limit`` 대신 ``until``로 잘못 바인딩되었다.
    (2) ``_BOT_LOGS_FETCH_HARD_CAP=10000``으로 매칭 가능 범위를 한번에
        fetch한 뒤 in-memory ``bot_id`` 필터를 적용하므로, 다른 봇의 로그가
        cap을 먼저 채우면 특정 봇의 로그가 결과에서 누락될 수 있었다
        (여러 봇이 병렬로 step을 찍는 환경에서 silent under-count).

    r2는 (1) ``until``/``offset``/``payload_filter``를 keyword-only로
    옮기고, (2) ``EventHistoryStore``에 SQL JSON1 ``payload_filter``를
    추가해 ``bot_id``를 SQL 단계에서 필터링한다 → hard cap 제거.

    본 클래스는 다른 봇의 대량 로그(>= 기존 cap의 일부)가 있어도 특정
    봇의 로그가 정확하게 반환되는지를 web 레이어에서 검증한다.
    """

    @pytest.fixture
    def bot_manager(self):
        mgr = FakeBotManager()
        mgr._bots["target-bot"] = FakeBot("target-bot")
        return mgr

    @pytest.fixture
    def event_history_store(self):
        """target-bot 로그 5건 + 다른 봇 로그 200건 (target 로그가 fetch
        순서상 가장 오래된 시점에 위치하도록 배치).

        ``ORDER BY id DESC``로 fetch하면 다른 봇 200건이 먼저 나오고
        target-bot 5건이 뒤에 위치한다. r1의 fetch hard cap (작게
        시뮬레이션) 이라면 다른 봇 로그가 cap을 채워 target 로그가
        누락되지만, r2는 SQL JSON1 ``payload_filter``로 SQL 단계 필터링
        하므로 cap 무관하게 정확.
        """
        from datetime import UTC, datetime, timedelta

        from ante.core import Database
        from ante.eventbus.history import EventHistoryStore

        async def _setup():
            import tempfile

            tmpdir = tempfile.mkdtemp(prefix="ante-test-")
            db = Database(f"{tmpdir}/event.db")
            await db.connect()
            store = EventHistoryStore(db=db)
            await store.initialize()
            base = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
            # target-bot 5건 (가장 먼저 기록 → 가장 작은 id).
            for i in range(5):
                ts = base + timedelta(seconds=i)
                await store.record(
                    BotStepCompletedEvent(
                        bot_id="target-bot",
                        account_id="test",
                        result="success",
                        message=f"target-{i}",
                        timestamp=ts,
                    )
                )
            # 다른 봇 200건 (target보다 뒤 → 더 큰 id, ORDER BY id DESC에서
            # 먼저 fetch됨). r1의 cap=10000보다는 적지만 cap-relative
            # 회귀 유닛 테스트로 충분.
            for i in range(200):
                ts = base + timedelta(minutes=1, seconds=i)
                await store.record(
                    BotStepCompletedEvent(
                        bot_id=f"other-{i}",
                        account_id="test",
                        result="success",
                        message=f"other-step-{i}",
                        timestamp=ts,
                    )
                )
            return store, db

        store, db = asyncio.get_event_loop().run_until_complete(_setup())
        yield store
        asyncio.get_event_loop().run_until_complete(db.close())

    @pytest.fixture
    def client(self, bot_manager, event_history_store):
        app = create_app(
            bot_manager=bot_manager,
            event_history_store=event_history_store,
            account_service=FakeAccountService(),
            member_service=make_master_member_service(),
        )
        return make_authed_client(app)

    def test_target_logs_returned_despite_other_bot_volume(self, client):
        """다른 봇 로그가 다수 있어도 target-bot 로그 5건 모두 반환.

        r2: SQL JSON1 ``payload_filter``로 ``bot_id='target-bot'``을 SQL
        단계 필터링 → ``total=5``, 페이지 ``logs``에 5건 모두.
        """
        resp = client.get("/api/bots/target-bot/logs?limit=100")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["logs"]) == 5
        # message는 ORDER BY id DESC라 target-4 → target-0 순.
        messages = [log["message"] for log in data["logs"]]
        assert messages == ["target-4", "target-3", "target-2", "target-1", "target-0"]

    def test_target_logs_total_accurate_under_small_limit(self, client):
        """``limit=2`` 페이지로 잘라도 ``total=5`` 정확히 보존.

        r1 회귀 시나리오: in-memory pagination + hard cap → ``total`` 이
        다른 봇 로그로 cap에 묶일 위험. r2: SQL ``COUNT(*)`` + JSON1
        payload_filter로 정확.
        """
        resp = client.get("/api/bots/target-bot/logs?limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["logs"]) == 2

    def test_target_logs_offset_pagination_isolated_from_other_bots(self, client):
        """``offset=2&limit=2`` → target 5건 중 2..3 번째만 (다른 봇 로그
        영향 없음).

        SQL OFFSET이 payload_filter 이후에 적용되므로 다른 봇 로그가
        offset 카운트에 끼어들지 않는다.
        """
        resp = client.get("/api/bots/target-bot/logs?offset=2&limit=2")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 5
        assert len(data["logs"]) == 2
        messages = [log["message"] for log in data["logs"]]
        # ORDER BY id DESC: target-4,3,2,1,0 → offset=2: target-2, target-1.
        assert messages == ["target-2", "target-1"]


class TestEventHistoryStoreSignatureCompat1437R2:
    """#1437 r2 — ``EventHistoryStore.query`` 시그니처 회귀.

    r1은 ``until``을 ``limit`` 앞 위치 인자로 추가해 기존 caller
    ``store.query(event_type, since, 50)`` 의 세 번째 위치 인자 ``50``이
    ``limit`` 대신 ``until``로 잘못 바인딩되는 silent failure가 있었다.
    r2는 ``until``/``offset``/``payload_filter``를 keyword-only로 옮기고
    ``limit``을 세 번째 위치 인자 자리에 유지한다.
    """

    def test_query_three_positional_args_binds_third_to_limit(self):
        """``store.query(event_type, since, 50)`` 형태로 호출 시 세 번째
        위치 인자 ``50``이 ``limit``으로 안전하게 바인딩된다.

        r1 회귀: ``50``이 ``until``로 바인딩되어 datetime 비교가 깨졌다.
        r2 fix: ``until`` keyword-only.
        """
        from datetime import UTC, datetime, timedelta

        from ante.core import Database
        from ante.eventbus.events import OrderRequestEvent
        from ante.eventbus.history import EventHistoryStore

        async def _check():
            import tempfile

            tmpdir = tempfile.mkdtemp(prefix="ante-test-")
            db = Database(f"{tmpdir}/event.db")
            await db.connect()
            store = EventHistoryStore(db=db)
            await store.initialize()
            base = datetime(2026, 5, 10, 0, 0, 0, tzinfo=UTC)
            for i in range(7):
                ts = base + timedelta(seconds=i)
                await store.record(
                    OrderRequestEvent(symbol=str(i), account_id="acc", timestamp=ts)
                )
            # 세 번째 위치 인자가 limit이어야 한다.
            rows = await store.query("OrderRequestEvent", None, 3)
            await db.close()
            return rows

        rows = asyncio.get_event_loop().run_until_complete(_check())
        # 3건 반환, 모두 OrderRequestEvent.
        assert len(rows) == 3
        assert all(r["event_type"] == "OrderRequestEvent" for r in rows)
