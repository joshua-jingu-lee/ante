"""StrategyContext.get_trade_history() 테스트."""

import pytest

from ante.strategy.base import (
    DataProvider,
    OrderView,
    PortfolioView,
    TradeHistoryView,
)
from ante.strategy.context import StrategyContext


class FakeDataProvider(DataProvider):
    async def get_ohlcv(self, symbol, timeframe="1d", limit=100):
        import polars as pl

        return pl.DataFrame()

    async def get_current_price(self, symbol):
        return 0.0

    async def get_indicator(self, symbol, indicator, params=None):
        return {}


class FakePortfolio(PortfolioView):
    def get_positions(self, bot_id):
        return {}

    def get_balance(self, bot_id):
        return {"allocated": 0.0, "available": 0.0}


class FakeOrderView(OrderView):
    def get_open_orders(self, bot_id):
        return []


class FakeTradeHistory(TradeHistoryView):
    def __init__(self, trades=None):
        self._trades = trades or []

    async def get_trade_history(self, bot_id, symbol=None, limit=50):
        result = [t for t in self._trades if t["bot_id"] == bot_id]
        if symbol:
            result = [t for t in result if t["symbol"] == symbol]
        return result[:limit]


@pytest.fixture
def trades():
    return [
        {
            "bot_id": "bot-1",
            "trade_id": "t1",
            "symbol": "005930",
            "side": "buy",
            "quantity": 10.0,
            "price": 70000.0,
        },
        {
            "bot_id": "bot-1",
            "trade_id": "t2",
            "symbol": "035720",
            "side": "buy",
            "quantity": 5.0,
            "price": 50000.0,
        },
        {
            "bot_id": "bot-2",
            "trade_id": "t3",
            "symbol": "005930",
            "side": "sell",
            "quantity": 3.0,
            "price": 72000.0,
        },
    ]


@pytest.fixture
def ctx(trades):
    return StrategyContext(
        bot_id="bot-1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolio(),
        order_view=FakeOrderView(),
        trade_history=FakeTradeHistory(trades),
    )


async def test_get_trade_history(ctx):
    """봇의 거래 이력을 조회한다."""
    result = await ctx.get_trade_history()
    assert len(result) == 2
    assert all(t["bot_id"] == "bot-1" for t in result)


async def test_get_trade_history_filter_symbol(ctx):
    """symbol 필터가 동작한다."""
    result = await ctx.get_trade_history(symbol="005930")
    assert len(result) == 1
    assert result[0]["symbol"] == "005930"


async def test_get_trade_history_limit(ctx):
    """limit이 반환 건수를 제한한다."""
    result = await ctx.get_trade_history(limit=1)
    assert len(result) == 1


async def test_get_trade_history_no_provider():
    """trade_history 미주입 시 빈 리스트 반환."""
    ctx = StrategyContext(
        bot_id="bot-1",
        data_provider=FakeDataProvider(),
        portfolio=FakePortfolio(),
        order_view=FakeOrderView(),
    )
    result = await ctx.get_trade_history()
    assert result == []
