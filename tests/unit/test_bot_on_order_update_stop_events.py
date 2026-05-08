"""Bot.on_order_update — stop 주문 이벤트 분기 (#1336).

stop / stop_limit 주문 등록·발동·만료 통보가 일반 ``on_order_update``
콜백으로 변환되어 strategy 에 전달되는지 회귀로 보호한다.
"""

from __future__ import annotations

import polars as pl
import pytest

from ante.bot import Bot, BotConfig
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
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        return pl.DataFrame({"close": [100.0]})

    async def get_current_price(self, symbol):
        return 100.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class _FakePortfolioView(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"total": 1000000.0, "available": 500000.0}


class _FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class _RecordStrategy(Strategy):
    meta = StrategyMeta(name="rec", version="1.0.0", description="test")
    updates: list[dict] = []

    async def on_step(self, context):
        return []

    async def on_order_update(self, update):
        self.updates.append(update)


@pytest.fixture
def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
def ctx() -> StrategyContext:
    return StrategyContext(
        bot_id="bot1",
        data_provider=_FakeDataProvider(),
        portfolio=_FakePortfolioView(),
        order_view=_FakeOrderView(),
    )


@pytest.fixture
def simple_config() -> BotConfig:
    return BotConfig(
        bot_id="bot1",
        strategy_id="rec_v1.0.0",
        interval_seconds=10,
        account_id="acc-test",
    )


@pytest.fixture
def record_strategy_cls() -> type[_RecordStrategy]:
    # 테스트마다 updates 리스트가 격리되도록 서브클래스 생성
    class S(_RecordStrategy):
        updates: list[dict] = []

    return S


class TestStopRegisteredUpdate:
    async def test_stop_registered_event_dispatched_to_strategy(
        self,
        eventbus: EventBus,
        ctx: StrategyContext,
        simple_config: BotConfig,
        record_strategy_cls: type[_RecordStrategy],
    ) -> None:
        bot = Bot(
            config=simple_config,
            strategy_cls=record_strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            StopOrderRegisteredEvent(
                account_id="acc-test",
                stop_order_id="stop-001",
                bot_id="bot1",
                strategy_id="rec_v1.0.0",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                limit_price=None,
            )
        )

        assert len(record_strategy_cls.updates) == 1
        u = record_strategy_cls.updates[0]
        assert u["order_id"] == "stop-001"
        assert u["stop_order_id"] == "stop-001"
        assert u["status"] == "stop_registered"
        assert u["symbol"] == "005930"
        assert u["side"] == "sell"
        assert u["quantity"] == 10.0
        assert u["stop_price"] == 49000.0
        assert u["limit_price"] is None

        await bot.stop()

    async def test_stop_registered_event_for_other_bot_ignored(
        self,
        eventbus: EventBus,
        ctx: StrategyContext,
        simple_config: BotConfig,
        record_strategy_cls: type[_RecordStrategy],
    ) -> None:
        bot = Bot(
            config=simple_config,
            strategy_cls=record_strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            StopOrderRegisteredEvent(
                account_id="acc-test",
                stop_order_id="stop-001",
                bot_id="other-bot",
                strategy_id="rec_v1.0.0",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
            )
        )

        assert record_strategy_cls.updates == []
        await bot.stop()


class TestStopTriggeredUpdate:
    async def test_stop_triggered_event_dispatched_to_strategy(
        self,
        eventbus: EventBus,
        ctx: StrategyContext,
        simple_config: BotConfig,
        record_strategy_cls: type[_RecordStrategy],
    ) -> None:
        bot = Bot(
            config=simple_config,
            strategy_cls=record_strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            StopOrderTriggeredEvent(
                account_id="acc-test",
                stop_order_id="stop-001",
                bot_id="bot1",
                strategy_id="rec_v1.0.0",
                symbol="005930",
                side="sell",
                quantity=10.0,
                trigger_price=48500.0,
                converted_order_type="market",
            )
        )

        assert len(record_strategy_cls.updates) == 1
        u = record_strategy_cls.updates[0]
        assert u["order_id"] == "stop-001"
        assert u["stop_order_id"] == "stop-001"
        assert u["status"] == "stop_triggered"
        assert u["symbol"] == "005930"
        assert u["side"] == "sell"
        assert u["quantity"] == 10.0
        assert u["trigger_price"] == 48500.0
        assert u["converted_order_type"] == "market"

        await bot.stop()


class TestStopExpiredUpdate:
    async def test_stop_expired_event_dispatched_to_strategy(
        self,
        eventbus: EventBus,
        ctx: StrategyContext,
        simple_config: BotConfig,
        record_strategy_cls: type[_RecordStrategy],
    ) -> None:
        bot = Bot(
            config=simple_config,
            strategy_cls=record_strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            StopOrderExpiredEvent(
                account_id="acc-test",
                stop_order_id="stop-001",
                bot_id="bot1",
                strategy_id="rec_v1.0.0",
                symbol="005930",
                reason="session_ended",
            )
        )

        assert len(record_strategy_cls.updates) == 1
        u = record_strategy_cls.updates[0]
        assert u["order_id"] == "stop-001"
        assert u["stop_order_id"] == "stop-001"
        assert u["status"] == "stop_expired"
        assert u["symbol"] == "005930"
        assert u["reason"] == "session_ended"

        await bot.stop()

    async def test_stop_expired_manager_stopped_reason(
        self,
        eventbus: EventBus,
        ctx: StrategyContext,
        simple_config: BotConfig,
        record_strategy_cls: type[_RecordStrategy],
    ) -> None:
        bot = Bot(
            config=simple_config,
            strategy_cls=record_strategy_cls,
            ctx=ctx,
            eventbus=eventbus,
        )
        await bot.start()

        await bot.on_order_update(
            StopOrderExpiredEvent(
                account_id="acc-test",
                stop_order_id="stop-002",
                bot_id="bot1",
                strategy_id="rec_v1.0.0",
                symbol="005930",
                reason="manager_stopped",
            )
        )

        assert len(record_strategy_cls.updates) == 1
        assert record_strategy_cls.updates[0]["reason"] == "manager_stopped"
        assert record_strategy_cls.updates[0]["status"] == "stop_expired"

        await bot.stop()
