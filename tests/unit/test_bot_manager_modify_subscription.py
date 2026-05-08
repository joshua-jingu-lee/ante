"""BotManager `OrderModifyRejectedEvent` 구독 통합 테스트 (#1331).

본 모듈은 BotManager가 봇을 등록할 때 ``OrderModifyRejectedEvent`` 를
``Bot.on_order_update`` 에 연결하고, 발행 시 전략의
``on_order_update`` dict 에 ``status="modify_rejected"`` 가 전달되는지를
잠근다. 등록 누락은 본 PR이 막으려는 핵심 회귀이므로 발행 → 전략 호출
end-to-end 패스를 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.bot import BotConfig, BotManager
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyRejectedEvent
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
        import polars as pl

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
    """``on_order_update`` 호출을 기록하는 테스트 전략."""

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
        bot_id="bot-1331",
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


async def test_modify_rejected_reaches_strategy(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    """``OrderModifyRejectedEvent`` 발행 → 전략 ``on_order_update`` 호출."""
    config = BotConfig(
        bot_id="bot-1331",
        strategy_id="strat-1331",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)

    # 전략 인스턴스화는 ``Bot.start`` 시점에 일어나므로, 본 테스트는
    # 전략 객체를 미리 instantiate하고 bot에 직접 attach한다.
    # ``on_order_update`` dispatch는 strategy 존재 + bot_id 매칭만 본다.
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = OrderModifyRejectedEvent(
        account_id="acc-test",
        order_id="ord-1331",
        bot_id="bot-1331",
        strategy_id="strat-1331",
        symbol="005930",
        side="buy",
        quantity=10.0,
        price=50000.0,
        reason="modify_not_implemented",
    )
    await eventbus.publish(event)

    assert len(strategy.updates) == 1
    update = strategy.updates[0]
    assert update["status"] == "modify_rejected"
    assert update["order_id"] == "ord-1331"
    assert update["symbol"] == "005930"
    assert update["side"] == "buy"
    assert update["reason"] == "modify_not_implemented"


async def test_modify_rejected_other_bot_ignored(
    manager: BotManager, ctx: StrategyContext, eventbus: EventBus
) -> None:
    """다른 ``bot_id`` 의 거부 통보는 봇 전략에 전달되지 않는다."""
    config = BotConfig(
        bot_id="bot-1331",
        strategy_id="strat-1331",
        account_id="acc-test",
    )
    bot = await manager.create_bot(config, _CapturingStrategy, ctx)
    strategy = _CapturingStrategy(ctx=ctx)
    bot.strategy = strategy

    event = OrderModifyRejectedEvent(
        account_id="acc-test",
        order_id="ord-other",
        bot_id="bot-other",
        strategy_id="strat-other",
        symbol="005930",
        side="sell",
        quantity=1.0,
        price=1.0,
        reason="modify_not_implemented",
    )
    await eventbus.publish(event)

    assert strategy.updates == []
