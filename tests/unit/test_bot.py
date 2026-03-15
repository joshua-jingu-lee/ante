"""Bot 모듈 단위 테스트."""

import asyncio

import pytest

from ante.bot import Bot, BotConfig, BotError, BotManager, BotStatus
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotErrorEvent,
    BotStartedEvent,
    BotStopEvent,
    BotStoppedEvent,
    OrderCancelEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    TradingStateChangedEvent,
)
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


class SimpleStrategy(Strategy):
    """테스트용 간단한 전략."""

    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class BuyStrategy(Strategy):
    """매수 시그널을 반환하는 전략."""

    meta = StrategyMeta(name="buy", version="1.0.0", description="test")

    async def on_step(self, context):
        return [
            Signal(
                symbol="005930",
                side="buy",
                quantity=10.0,
                reason="test buy",
            )
        ]


class ErrorStrategy(Strategy):
    """에러를 발생시키는 전략."""

    meta = StrategyMeta(name="error", version="1.0.0", description="test")
    call_count = 0

    async def on_step(self, context):
        ErrorStrategy.call_count += 1
        raise RuntimeError("strategy error")


class FillReactStrategy(Strategy):
    """체결 시 후속 시그널을 반환하는 전략."""

    meta = StrategyMeta(name="fill_react", version="1.0.0", description="test")

    async def on_step(self, context):
        return []

    async def on_fill(self, fill):
        return [
            Signal(
                symbol=fill["symbol"],
                side="sell",
                quantity=fill["quantity"],
                reason="stop loss after fill",
            )
        ]


# ── Fixtures ─────────────────────────────────────


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


@pytest.fixture
def simple_config():
    return BotConfig(
        bot_id="bot1",
        strategy_id="simple_v1.0.0",
        interval_seconds=10,  # 테스트용: 최소 유효 간격
    )


# ── BotConfig / BotStatus ────────────────────────


class TestBotConfig:
    def test_defaults(self):
        """BotConfig 기본값."""
        c = BotConfig(bot_id="b1", strategy_id="s1")
        assert c.name == ""
        assert c.bot_type == "live"
        assert c.interval_seconds == 60

    def test_name_field(self):
        """BotConfig name 필드 설정."""
        c = BotConfig(bot_id="b1", strategy_id="s1", name="테스트 봇")
        assert c.name == "테스트 봇"

    def test_bot_status_values(self):
        """BotStatus 값."""
        assert BotStatus.CREATED == "created"
        assert BotStatus.RUNNING == "running"
        assert BotStatus.ERROR == "error"
        assert BotStatus.DELETED == "deleted"

    def test_interval_min_valid(self):
        """최소 간격 10초 허용."""
        c = BotConfig(bot_id="b1", strategy_id="s1", interval_seconds=10)
        assert c.interval_seconds == 10

    def test_interval_max_valid(self):
        """최대 간격 3600초 허용."""
        c = BotConfig(bot_id="b1", strategy_id="s1", interval_seconds=3600)
        assert c.interval_seconds == 3600

    def test_interval_below_min_raises(self):
        """10초 미만이면 ValueError."""
        with pytest.raises(ValueError, match="10초 이상"):
            BotConfig(bot_id="b1", strategy_id="s1", interval_seconds=5)

    def test_interval_above_max_raises(self):
        """3600초 초과면 ValueError."""
        with pytest.raises(ValueError, match="3600초 이하"):
            BotConfig(bot_id="b1", strategy_id="s1", interval_seconds=7200)

    def test_interval_zero_raises(self):
        """0초면 ValueError."""
        with pytest.raises(ValueError):
            BotConfig(bot_id="b1", strategy_id="s1", interval_seconds=0)


# ── Bot 생명주기 ─────────────────────────────────


class TestBot:
    async def test_start_publishes_event(self, eventbus, ctx, simple_config):
        """봇 시작 시 BotStartedEvent 발행."""
        received = []
        eventbus.subscribe(BotStartedEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        assert bot.status == BotStatus.RUNNING
        assert len(received) == 1
        assert received[0].bot_id == "bot1"

        await bot.stop()

    async def test_stop_publishes_event(self, eventbus, ctx, simple_config):
        """봇 중지 시 BotStoppedEvent 발행."""
        received = []
        eventbus.subscribe(BotStoppedEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await bot.stop()

        assert bot.status == BotStatus.STOPPED
        assert len(received) == 1

    async def test_stop_idempotent(self, eventbus, ctx, simple_config):
        """이미 중지된 봇은 다시 중지해도 무시."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await bot.stop()
        await bot.stop()  # 두 번째 호출은 무시
        assert bot.status == BotStatus.STOPPED

    async def test_signal_to_order_event(self, eventbus, ctx):
        """전략 Signal → OrderRequestEvent 변환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="buy_v1.0.0",
            interval_seconds=10,
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=BuyStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        # 루프가 한 번 실행될 시간을 줌
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].symbol == "005930"
        assert received[0].side == "buy"
        assert received[0].quantity == 10.0
        assert received[0].bot_id == "bot1"

    async def test_error_isolation(self, eventbus, ctx):
        """전략 에러 시 봇만 ERROR 상태로 전환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="error_v1.0.0",
            interval_seconds=10,
        )
        received = []
        eventbus.subscribe(BotErrorEvent, lambda e: received.append(e))

        ErrorStrategy.call_count = 0
        bot = Bot(
            config=config,
            strategy_cls=ErrorStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await asyncio.sleep(0.05)

        assert bot.status == BotStatus.ERROR
        assert bot.error_message == "strategy error"
        assert len(received) >= 1

    async def test_on_order_filled(self, eventbus, ctx, simple_config):
        """체결 통보 → 전략 on_fill() 호출 → 후속 Signal 발행."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="fill_react_v1.0.0",
            interval_seconds=999,  # 루프 호출 방지
        )
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        # 체결 이벤트 전달
        await bot.on_order_filled(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="fill_react_v1.0.0",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
            )
        )

        assert len(received) == 1
        assert received[0].side == "sell"
        assert received[0].reason == "stop loss after fill"

        await bot.stop()

    async def test_on_order_filled_ignores_other_bot(
        self, eventbus, ctx, simple_config
    ):
        """다른 봇의 체결 이벤트는 무시."""
        received = []
        eventbus.subscribe(OrderRequestEvent, lambda e: received.append(e))

        bot = Bot(
            config=simple_config,
            strategy_cls=FillReactStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_filled(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="other_bot",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50000.0,
                order_type="market",
            )
        )

        assert len(received) == 0
        await bot.stop()

    async def test_on_order_update_rejected(self, eventbus, ctx, simple_config):
        """주문 거부 통보 → 전략 on_order_update() 호출."""
        updates = []

        class TrackStrategy(Strategy):
            meta = StrategyMeta(name="t", version="1.0.0", description="t")

            async def on_step(self, context):
                return []

            async def on_order_update(self, update):
                updates.append(update)

        bot = Bot(
            config=simple_config,
            strategy_cls=TrackStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            OrderRejectedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                order_type="market",
                reason="insufficient funds",
            )
        )

        assert len(updates) == 1
        assert updates[0]["status"] == "rejected"
        assert updates[0]["reason"] == "insufficient funds"

        await bot.stop()

    async def test_drain_actions_cancel(self, eventbus, ctx, simple_config):
        """전략이 cancel_order() → OrderCancelEvent 발행."""

        class CancelStrategy(Strategy):
            meta = StrategyMeta(name="c", version="1.0.0", description="c")

            async def on_step(self, context):
                self.ctx.cancel_order("ord1", reason="test cancel")
                return []

        received = []
        eventbus.subscribe(OrderCancelEvent, lambda e: received.append(e))

        bot = Bot(
            config=BotConfig(
                bot_id="bot1",
                strategy_id="c_v1.0.0",
                interval_seconds=10,
            ),
            strategy_cls=CancelStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()
        await asyncio.sleep(0.05)
        await bot.stop()

        assert len(received) >= 1
        assert received[0].order_id == "ord1"
        assert received[0].reason == "test cancel"

    def test_get_info(self, eventbus, ctx, simple_config):
        """봇 상태 정보 반환."""
        bot = Bot(
            config=simple_config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert info["bot_id"] == "bot1"
        assert info["name"] == ""
        assert info["status"] == "created"

    def test_get_info_with_name(self, eventbus, ctx):
        """이름이 설정된 봇의 정보 반환."""
        config = BotConfig(
            bot_id="bot1",
            strategy_id="s1",
            name="모멘텀 봇",
            interval_seconds=10,
        )
        bot = Bot(
            config=config,
            strategy_cls=SimpleStrategy,
            ctx=ctx,
            eventbus=eventbus,
        )
        info = bot.get_info()
        assert info["name"] == "모멘텀 봇"


# ── BotManager ───────────────────────────────────


class TestBotManager:
    @pytest.fixture
    async def db(self, tmp_path):
        database = Database(str(tmp_path / "test.db"))
        await database.connect()
        yield database
        await database.close()

    @pytest.fixture
    async def manager(self, eventbus, db):
        m = BotManager(eventbus=eventbus, db=db)
        await m.initialize()
        return m

    async def test_create_bot(self, manager, eventbus, ctx):
        """봇 생성."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        bot = await manager.create_bot(config, SimpleStrategy, ctx)
        assert bot.status == BotStatus.CREATED
        assert manager.get_bot("bot1") is bot

    async def test_create_duplicate_raises(self, manager, eventbus, ctx):
        """중복 봇 생성 시 에러."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        with pytest.raises(BotError, match="already exists"):
            await manager.create_bot(config, SimpleStrategy, ctx)

    async def test_start_and_stop(self, manager, eventbus, ctx):
        """봇 시작/중지."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.stop_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_remove_bot(self, manager, eventbus, ctx):
        """봇 삭제 (하위 호환 — remove_bot은 delete_bot 별칭)."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.remove_bot("bot1")
        assert manager.get_bot("bot1") is None

    async def test_delete_bot_soft_delete(self, manager, eventbus, ctx, db):
        """delete_bot은 DB 레코드를 삭제하지 않고 status를 deleted로 변경."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.delete_bot("bot1")

        # 메모리에서는 제거
        assert manager.get_bot("bot1") is None

        # DB에는 레코드가 남아있고 status가 deleted
        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["status"] == "deleted"

    async def test_delete_bot_stops_running(self, manager, eventbus, ctx, db):
        """실행 중인 봇 삭제 시 먼저 중지 후 deleted 처리."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")
        assert manager.get_bot("bot1").status == BotStatus.RUNNING

        await manager.delete_bot("bot1")
        assert manager.get_bot("bot1") is None

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row["status"] == "deleted"

    async def test_stop_all(self, manager, eventbus):
        """전체 봇 중지."""
        for i in range(3):
            ctx = StrategyContext(
                bot_id=f"bot{i}",
                data_provider=FakeDataProvider(),
                portfolio=FakePortfolioView(),
                order_view=FakeOrderView(),
            )
            config = BotConfig(
                bot_id=f"bot{i}",
                strategy_id=f"s{i}",
                interval_seconds=999,
            )
            await manager.create_bot(config, SimpleStrategy, ctx)
            await manager.start_bot(f"bot{i}")

        await manager.stop_all()
        for i in range(3):
            assert manager.get_bot(f"bot{i}").status == BotStatus.STOPPED

    async def test_list_bots(self, manager, eventbus, ctx):
        """봇 목록 조회."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)
        bots = manager.list_bots()
        assert len(bots) == 1
        assert bots[0]["bot_id"] == "bot1"

    async def test_bot_stop_event(self, manager, eventbus, ctx):
        """BotStopEvent 수신 시 봇 중지."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await eventbus.publish(BotStopEvent(bot_id="bot1", reason="rule violation"))

        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_halt_stops_all(self, manager, eventbus, ctx):
        """TradingStateChanged → HALTED 시 전체 봇 중지."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", interval_seconds=999)
        await manager.create_bot(config, SimpleStrategy, ctx)
        await manager.start_bot("bot1")

        await eventbus.publish(
            TradingStateChangedEvent(
                old_state="active",
                new_state="halted",
                reason="critical",
            )
        )

        assert manager.get_bot("bot1").status == BotStatus.STOPPED

    async def test_not_found_raises(self, manager):
        """존재하지 않는 봇 시작 시 에러."""
        with pytest.raises(BotError, match="not found"):
            await manager.start_bot("nonexistent")

    async def test_single_bot_per_strategy_running(self, manager, eventbus):
        """실행 중인 봇의 전략으로 새 봇 생성 시 에러."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(bot_id="bot1", strategy_id="same_stg", interval_seconds=999)
        config2 = BotConfig(bot_id="bot2", strategy_id="same_stg", interval_seconds=999)
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")

        with pytest.raises(BotError, match="이미 봇"):
            await manager.create_bot(config2, SimpleStrategy, ctx2)

        await manager.stop_bot("bot1")

    async def test_single_bot_per_strategy_stopped_reuse(self, manager, eventbus):
        """중지된 봇의 전략은 재사용 가능."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(bot_id="bot1", strategy_id="same_stg", interval_seconds=999)
        config2 = BotConfig(bot_id="bot2", strategy_id="same_stg", interval_seconds=999)
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")
        await manager.stop_bot("bot1")

        # stopped 상태이므로 같은 전략으로 생성 가능
        bot2 = await manager.create_bot(config2, SimpleStrategy, ctx2)
        assert bot2.status == BotStatus.CREATED

    async def test_single_bot_per_strategy_different_strategy(self, manager, eventbus):
        """다른 전략이면 봇 생성 정상."""
        ctx1 = StrategyContext(
            bot_id="bot1",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        ctx2 = StrategyContext(
            bot_id="bot2",
            data_provider=FakeDataProvider(),
            portfolio=FakePortfolioView(),
            order_view=FakeOrderView(),
        )
        config1 = BotConfig(bot_id="bot1", strategy_id="stg_a", interval_seconds=999)
        config2 = BotConfig(bot_id="bot2", strategy_id="stg_b", interval_seconds=999)
        await manager.create_bot(config1, SimpleStrategy, ctx1)
        await manager.start_bot("bot1")

        bot2 = await manager.create_bot(config2, SimpleStrategy, ctx2)
        assert bot2.status == BotStatus.CREATED

        await manager.stop_bot("bot1")

    async def test_bot_config_persisted(self, manager, eventbus, ctx, db):
        """봇 설정이 DB에 저장됨."""
        config = BotConfig(bot_id="bot1", strategy_id="s1")
        await manager.create_bot(config, SimpleStrategy, ctx)

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["strategy_id"] == "s1"

    async def test_bot_name_persisted(self, manager, eventbus, ctx, db):
        """봇 이름이 DB에 저장됨."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", name="모멘텀 봇")
        await manager.create_bot(config, SimpleStrategy, ctx)

        row = await db.fetch_one("SELECT * FROM bots WHERE bot_id = 'bot1'")
        assert row is not None
        assert row["name"] == "모멘텀 봇"
