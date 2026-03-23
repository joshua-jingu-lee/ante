"""봇 삭제 시 handle_positions 옵션 테스트.

Refs #796
"""

import asyncio

import pytest

from ante.bot import BotConfig, BotManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderRequestEvent
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)

# -- Fake 구현체 --


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
    meta = StrategyMeta(name="simple", version="1.0.0", description="test")

    async def on_step(self, context):
        return []


class FakePositionSnapshot:
    """테스트용 PositionSnapshot stub."""

    def __init__(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float = 0.0,
        exchange: str = "KRX",
    ) -> None:
        self.bot_id = bot_id
        self.symbol = symbol
        self.quantity = quantity
        self.avg_entry_price = avg_entry_price
        self.exchange = exchange


class FakeTradeService:
    """테스트용 TradeService stub."""

    def __init__(self) -> None:
        self._positions: dict[str, list[FakePositionSnapshot]] = {}

    async def get_positions(
        self, bot_id: str, include_closed: bool = False
    ) -> list[FakePositionSnapshot]:
        return self._positions.get(bot_id, [])


# -- Fixtures --


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
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    try:
        await asyncio.wait_for(database.close(), timeout=5.0)
    except TimeoutError:
        pass


@pytest.fixture
def trade_service():
    return FakeTradeService()


@pytest.fixture
async def manager(eventbus, db, trade_service):
    m = BotManager(eventbus=eventbus, db=db, trade_service=trade_service)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


@pytest.fixture
async def manager_no_trade(eventbus, db):
    """TradeService 없는 BotManager."""
    m = BotManager(eventbus=eventbus, db=db)
    await m.initialize()
    yield m
    for bot in list(m._bots.values()):
        if bot._task and not bot._task.done():
            bot._task.cancel()
    try:
        await asyncio.wait_for(m.stop_all(), timeout=5.0)
    except TimeoutError:
        pass


# -- Tests --


class TestDeleteBotHandlePositions:
    """delete_bot handle_positions 파라미터 검증."""

    async def test_keep_default_no_orders(self, manager, ctx, eventbus, trade_service):
        """기본값(keep) 시 청산 주문이 발행되지 않는다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        trade_service._positions["bot1"] = [
            FakePositionSnapshot("bot1", "005930", 50),
        ]

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1")

        assert manager.get_bot("bot1") is None
        assert len(published) == 0

    async def test_liquidate_publishes_sell_orders(
        self, manager, ctx, eventbus, trade_service
    ):
        """liquidate 시 보유 포지션에 대해 시장가 매도 주문을 발행한다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        trade_service._positions["bot1"] = [
            FakePositionSnapshot("bot1", "005930", 50),
            FakePositionSnapshot("bot1", "035420", 15),
        ]

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1", handle_positions="liquidate")

        assert manager.get_bot("bot1") is None
        assert len(published) == 2

        # 주문 내용 검증
        symbols = {e.symbol for e in published}
        assert symbols == {"005930", "035420"}
        for event in published:
            assert event.side == "sell"
            assert event.order_type == "market"
            assert event.bot_id == "bot1"
            assert event.account_id == "test"
            assert event.strategy_id == "s1"

        # 수량 검증
        qty_map = {e.symbol: e.quantity for e in published}
        assert qty_map["005930"] == 50
        assert qty_map["035420"] == 15

    async def test_liquidate_skips_zero_quantity(
        self, manager, ctx, eventbus, trade_service
    ):
        """quantity=0 포지션은 청산 주문 대상에서 제외한다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        trade_service._positions["bot1"] = [
            FakePositionSnapshot("bot1", "005930", 50),
            FakePositionSnapshot("bot1", "035720", 0),  # 이미 청산됨
        ]

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1", handle_positions="liquidate")

        assert len(published) == 1
        assert published[0].symbol == "005930"

    async def test_liquidate_no_positions(self, manager, ctx, eventbus, trade_service):
        """보유 포지션 없으면 주문 없이 삭제된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1", handle_positions="liquidate")

        assert manager.get_bot("bot1") is None
        assert len(published) == 0

    async def test_liquidate_without_trade_service(
        self, manager_no_trade, ctx, eventbus
    ):
        """TradeService 미설정 시에도 삭제는 정상 진행된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager_no_trade.create_bot(config, SimpleStrategy, ctx)

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager_no_trade.delete_bot("bot1", handle_positions="liquidate")

        assert manager_no_trade.get_bot("bot1") is None
        assert len(published) == 0

    async def test_invalid_handle_positions_raises(self, manager, ctx):
        """잘못된 handle_positions 값은 BotError를 발생시킨다."""
        from ante.bot.exceptions import BotError

        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        with pytest.raises(BotError, match="handle_positions"):
            await manager.delete_bot("bot1", handle_positions="invalid")

        # 봇이 삭제되지 않았는지 확인
        assert manager.get_bot("bot1") is not None

    async def test_liquidate_order_includes_exchange(
        self, manager, ctx, eventbus, trade_service
    ):
        """청산 주문에 포지션의 exchange가 포함된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        trade_service._positions["bot1"] = [
            FakePositionSnapshot("bot1", "AAPL", 10, exchange="NASDAQ"),
        ]

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1", handle_positions="liquidate")

        assert len(published) == 1
        assert published[0].exchange == "NASDAQ"

    async def test_liquidate_reason_includes_bot_id(
        self, manager, ctx, eventbus, trade_service
    ):
        """청산 주문의 reason에 bot_id가 포함된다."""
        config = BotConfig(bot_id="bot1", strategy_id="s1", account_id="test")
        await manager.create_bot(config, SimpleStrategy, ctx)

        trade_service._positions["bot1"] = [
            FakePositionSnapshot("bot1", "005930", 50),
        ]

        published: list[OrderRequestEvent] = []
        eventbus.subscribe(OrderRequestEvent, lambda e: published.append(e))

        await manager.delete_bot("bot1", handle_positions="liquidate")

        assert "bot1" in published[0].reason
