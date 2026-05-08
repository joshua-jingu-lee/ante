"""BotManager — stop 이벤트 구독 통합 테스트 (#1336).

본 모듈은 BotManager 가 봇을 등록할 때 ``StopOrderRegisteredEvent`` /
``StopOrderTriggeredEvent`` / ``StopOrderExpiredEvent`` 를
``Bot.on_order_update`` 에 연결하고, 발행 시 전략 ``on_order_update``
dict 가 ``status="stop_*"`` 로 도달하는지를 잠근다. 구독 누락은 본
이슈가 막으려는 핵심 회귀 (missing terminal event) 이므로 발행 → 전략
호출 end-to-end 패스를 검증한다.
"""

from __future__ import annotations

import asyncio

import polars as pl
import pytest

from ante.bot import BotConfig, BotManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    StopOrderExpiredEvent,
    StopOrderRegisteredEvent,
    StopOrderTriggeredEvent,
)
from ante.strategy import (
    DataProvider,
    OrderView,
    PortfolioView,
    Strategy,
    StrategyContext,
    StrategyMeta,
)


class _FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):  # type: ignore[override]
        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):  # type: ignore[override]
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):  # type: ignore[override]
        return {}


class _FakePortfolio(PortfolioView):
    def get_positions(self, bot_id):  # type: ignore[override]
        return {}

    def get_balance(self, bot_id):  # type: ignore[override]
        return {"total": 1.0, "available": 1.0}


class _FakeOrders(OrderView):
    def get_open_orders(self, bot_id):  # type: ignore[override]
        return []


class _CapturingStrategy(Strategy):
    meta = StrategyMeta(name="capture", version="1.0.0", description="test")

    def __init__(self, ctx: StrategyContext) -> None:
        super().__init__(ctx=ctx)
        self.updates: list[dict] = []

    async def on_step(self, context):  # type: ignore[override]
        return []

    async def on_order_update(self, update):  # type: ignore[override]
        self.updates.append(update)


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def ctx() -> StrategyContext:
    return StrategyContext(
        bot_id="bot-1336",
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolio(),
        order_view=_FakeOrders(),
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
async def manager(eventbus: EventBus, db: Database) -> BotManager:
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


async def test_stop_registered_reaches_strategy(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    """``StopOrderRegisteredEvent`` 발행 → 전략 ``on_order_update`` 호출."""
    config = BotConfig(
        bot_id="bot-1336",
        strategy_id="strat-1336",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = StopOrderRegisteredEvent(
        account_id="acc-test",
        stop_order_id="stop-001",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=49000.0,
    )
    await eventbus.publish(event)

    assert len(strategy.updates) == 1
    update = strategy.updates[0]
    assert update["status"] == "stop_registered"
    assert update["order_id"] == "stop-001"
    assert update["stop_order_id"] == "stop-001"


async def test_stop_triggered_reaches_strategy(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    config = BotConfig(
        bot_id="bot-1336",
        strategy_id="strat-1336",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = StopOrderTriggeredEvent(
        account_id="acc-test",
        stop_order_id="stop-002",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        side="sell",
        quantity=10.0,
        trigger_price=48500.0,
        converted_order_type="market",
    )
    await eventbus.publish(event)

    assert len(strategy.updates) == 1
    update = strategy.updates[0]
    assert update["status"] == "stop_triggered"
    assert update["order_id"] == "stop-002"
    assert update["trigger_price"] == 48500.0
    assert update["converted_order_type"] == "market"


async def test_stop_expired_reaches_strategy(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    config = BotConfig(
        bot_id="bot-1336",
        strategy_id="strat-1336",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = StopOrderExpiredEvent(
        account_id="acc-test",
        stop_order_id="stop-003",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        reason="session_ended",
    )
    await eventbus.publish(event)

    assert len(strategy.updates) == 1
    update = strategy.updates[0]
    assert update["status"] == "stop_expired"
    assert update["order_id"] == "stop-003"
    assert update["reason"] == "session_ended"


async def test_stop_event_for_other_bot_ignored(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    config = BotConfig(
        bot_id="bot-1336",
        strategy_id="strat-1336",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = StopOrderRegisteredEvent(
        account_id="acc-test",
        stop_order_id="stop-other",
        bot_id="bot-other",
        strategy_id="strat-other",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=49000.0,
    )
    await eventbus.publish(event)

    assert strategy.updates == []
