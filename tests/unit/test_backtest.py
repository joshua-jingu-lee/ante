"""Backtest Engine 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import patch

import polars as pl
import pytest

from ante.backtest.config import BacktestConfig, DatasetInfo
from ante.backtest.context import BacktestStrategyContext
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.exceptions import (
    BacktestConfigError,
    BacktestDataError,
    BacktestError,
)
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult, BacktestTrade
from ante.backtest.service import BacktestService
from ante.data.store import ParquetStore
from ante.strategy.base import Signal, Strategy, StrategyMeta

# ── Helper: 테스트용 전략 ────────────────────────────


class BuyAndHoldStrategy(Strategy):
    """테스트용 매수 후 보유 전략."""

    meta = StrategyMeta(
        name="buy_and_hold",
        version="1.0",
        description="Test buy and hold strategy",
    )

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._bought = False

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        if not self._bought:
            self._bought = True
            return [Signal(symbol="005930", side="buy", quantity=10, reason="initial")]
        return []


class BuySellStrategy(Strategy):
    """매수 후 매도 전략."""

    meta = StrategyMeta(
        name="buy_sell",
        version="1.0",
        description="Buy then sell",
    )

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._step = 0

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        self._step += 1
        if self._step == 1:
            return [Signal(symbol="005930", side="buy", quantity=10)]
        if self._step == 3:
            return [Signal(symbol="005930", side="sell", quantity=10)]
        return []


class EmptyStrategy(Strategy):
    """아무것도 하지 않는 전략."""

    meta = StrategyMeta(
        name="empty",
        version="1.0",
        description="Does nothing",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        return []


# ── Fixtures ────────────────────────────────────────


def _make_ohlcv_df(
    symbol: str = "005930",
    n: int = 10,
    base_price: float = 50000.0,
) -> pl.DataFrame:
    """테스트용 OHLCV DataFrame."""
    from datetime import timedelta

    start = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(days=n - 1),
        interval="1d",
        eager=True,
        time_zone="UTC",
    )
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [base_price + i * 100 for i in range(n)],
            "high": [base_price + i * 100 + 50 for i in range(n)],
            "low": [base_price + i * 100 - 50 for i in range(n)],
            "close": [base_price + i * 100 + 25 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )


def _make_ohlcv_df_with_closes(
    closes: list[float],
    symbol: str = "005930",
) -> pl.DataFrame:
    """명시한 종가 시퀀스를 갖는 테스트용 OHLCV DataFrame.

    비평탄(상승/하락 혼합) 가격으로 mark-to-market 평가를 검증할 때 사용한다.
    """
    from datetime import timedelta

    n = len(closes)
    start = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    timestamps = pl.datetime_range(
        start,
        start + timedelta(days=n - 1),
        interval="1d",
        eager=True,
        time_zone="UTC",
    )
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [c - 25 for c in closes],
            "high": [c + 50 for c in closes],
            "low": [c - 50 for c in closes],
            "close": list(closes),
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )


@pytest.fixture
def data_dir(tmp_path):
    return tmp_path / "data"


@pytest.fixture
def store(data_dir):
    return ParquetStore(base_path=data_dir)


@pytest.fixture
async def loaded_store(store):
    """데이터가 미리 적재된 store."""
    df = _make_ohlcv_df()
    store.write("005930", "1d", df)
    return store


@pytest.fixture
async def data_provider(loaded_store):
    provider = BacktestDataProvider(
        store=loaded_store,
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    provider.load("005930", "1d")
    return provider


# ── BacktestTrade / BacktestResult 테스트 ───────────


class TestBacktestResult:
    def test_trade_frozen(self):
        trade = BacktestTrade(
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000.0,
            commission=75.0,
            slippage=50.0,
        )
        assert trade.symbol == "005930"
        assert trade.reason == ""

    def test_result_to_dict(self):
        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
        )
        d = result.to_dict()
        assert d["strategy"] == "test_v1.0"
        assert d["total_return_pct"] == 5.0
        assert d["total_trades"] == 0
        assert "config" in d
        assert "datasets" in d

    def test_result_to_dict_with_trades(self):
        trade = BacktestTrade(
            timestamp=datetime(2026, 1, 2, tzinfo=UTC),
            symbol="005930",
            side="buy",
            quantity=10,
            price=50000.0,
            commission=75.0,
            slippage=50.0,
            reason="test",
        )
        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
            trades=[trade],
        )
        d = result.to_dict()
        assert d["total_trades"] == 1
        assert d["trades"][0]["symbol"] == "005930"


# ── BacktestDataProvider 테스트 ────────────────────


class TestBacktestDataProvider:
    async def test_load_and_get_ohlcv(self, data_provider):
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 1  # current_idx=0, 첫 행만 보임

    async def test_advance_increases_visible_data(self, data_provider):
        data_provider.advance()
        data_provider.advance()
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 3  # idx 0,1,2

    async def test_advance_returns_false_at_end(self, data_provider):
        for _ in range(20):
            data_provider.advance()
        assert data_provider.advance() is False

    async def test_get_current_price(self, data_provider):
        price = await data_provider.get_current_price("005930")
        assert price > 0

    async def test_get_current_price_no_data(self, data_provider):
        with pytest.raises(BacktestDataError):
            await data_provider.get_current_price("999999")

    async def test_get_current_timestamp(self, data_provider):
        ts = data_provider.get_current_timestamp()
        assert ts is not None
        assert isinstance(ts, datetime)

    async def test_get_current_timestamp_empty_cache(self, store):
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        assert provider.get_current_timestamp() is None

    async def test_get_total_steps(self, data_provider):
        assert data_provider.get_total_steps() == 10

    async def test_reset(self, data_provider):
        data_provider.advance()
        data_provider.advance()
        data_provider.reset()
        assert data_provider.current_idx == 0

    async def test_limit_respects_future_cutoff(self, data_provider):
        """limit이 현재까지 데이터보다 크면 현재까지만 반환."""
        data_provider.advance()
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 2

    async def test_get_indicator_returns_computed_values(self, data_provider):
        """get_indicator()가 실제 지표 값을 계산하여 반환."""
        # 기본 데이터 10행, 모두 전진
        for _ in range(9):
            data_provider.advance()
        result = await data_provider.get_indicator("005930", "sma", {"length": 5})
        assert isinstance(result, dict)
        assert "sma" in result
        assert len(result["sma"]) == 10  # 10 rows visible

    async def test_get_indicator_rsi(self, loaded_store):
        """RSI 지표 계산 확인."""
        # RSI length=14 이므로 충분한 데이터 필요
        df = _make_ohlcv_df(n=30)
        loaded_store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        for _ in range(29):
            provider.advance()
        result = await provider.get_indicator("005930", "rsi", {"length": 14})
        assert isinstance(result, dict)
        assert "rsi" in result

    async def test_get_indicator_multi_output(self, loaded_store):
        """MACD 등 다중 출력 지표 계산 확인."""
        df = _make_ohlcv_df(n=40)
        loaded_store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        for _ in range(39):
            provider.advance()
        result = await provider.get_indicator("005930", "macd")
        assert isinstance(result, dict)
        assert "macd" in result
        assert "signal" in result
        assert "hist" in result

    async def test_get_indicator_unknown_raises(self, data_provider):
        """미지원 지표는 ValueError 발생."""
        data_provider.advance()
        with pytest.raises(ValueError, match="Unknown indicator"):
            await data_provider.get_indicator("005930", "unknown_indicator")

    async def test_loaded_datasets_empty_on_init(self, loaded_store):
        """초기 상태에서 loaded_datasets는 빈 리스트."""
        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        assert provider.loaded_datasets == []

    async def test_loaded_datasets_after_single_load(self, loaded_store):
        """load() 1회 호출 후 DatasetInfo 1건 기록."""

        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        datasets = provider.loaded_datasets
        assert len(datasets) == 1
        info = datasets[0]
        assert isinstance(info, DatasetInfo)
        assert info.symbol == "005930"
        assert info.timeframe == "1d"
        assert info.row_count == 10
        assert info.start_date != ""
        assert info.end_date != ""
        assert info.file_count >= 1

    async def test_loaded_datasets_after_multiple_loads(self, loaded_store):
        """load() 여러 번 호출 시 DatasetInfo가 누적된다."""
        # 두 번째 심볼 데이터도 적재
        df = _make_ohlcv_df(symbol="000660", n=5, base_price=100000.0)
        loaded_store.write("000660", "1d", df)

        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        provider.load("000660", "1d")

        datasets = provider.loaded_datasets
        assert len(datasets) == 2
        assert datasets[0].symbol == "005930"
        assert datasets[0].row_count == 10
        assert datasets[1].symbol == "000660"
        assert datasets[1].row_count == 5

    async def test_loaded_datasets_after_reset(self, data_provider):
        """reset() 호출 시 loaded_datasets가 초기화된다."""
        assert len(data_provider.loaded_datasets) >= 1
        data_provider.reset()
        assert data_provider.loaded_datasets == []

    async def test_loaded_datasets_returns_copy(self, data_provider):
        """loaded_datasets는 내부 리스트의 복사본을 반환한다."""
        datasets1 = data_provider.loaded_datasets
        datasets2 = data_provider.loaded_datasets
        assert datasets1 == datasets2
        assert datasets1 is not datasets2


# ── BacktestStrategyContext 테스트 ─────────────────


class TestBacktestStrategyContext:
    async def test_get_ohlcv(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        df = await ctx.get_ohlcv("005930")
        assert len(df) >= 1

    async def test_get_positions_empty(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        assert ctx.get_positions() == {}

    async def test_get_balance(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        balance = ctx.get_balance()
        assert balance["total"] == 10_000_000

    async def test_open_orders_empty(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        assert ctx.get_open_orders() == []

    async def test_log(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        ctx.log("test message")  # should not raise


# ── BacktestExecutor 테스트 ────────────────────────


class TestBacktestExecutor:
    async def test_empty_strategy(self, data_provider):
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        result = await executor.run()
        assert result.total_return == 0.0
        assert len(result.trades) == 0
        assert result.initial_balance == result.final_balance

    async def test_buy_and_hold(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        # balance(현금)는 매수로 감소했는지 확인
        assert result.equity_curve[0]["balance"] < result.initial_balance
        # 미청산 포지션을 현재가(mark-to-market)로 평가한다.
        # _make_ohlcv_df의 close는 단조 상승하므로, 매수 후 미실현이익이
        # 발생하여 final_balance가 매수 시점 원가 기반 평가보다 커진다.
        buy_price = result.trades[0].price
        qty = result.trades[0].quantity
        cost_basis_equity = result.equity_curve[-1]["balance"] + qty * buy_price
        # final_balance == 마지막 시뮬레이션 봉 equity (lookahead 없음)
        assert result.final_balance == result.equity_curve[-1]["equity"]
        # 현재가 기반 평가가 원가 기반보다 크다(가격 상승 fixture)
        assert result.final_balance > cost_basis_equity

    async def test_buy_sell(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuySellStrategy,
            data_provider=data_provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 2
        assert result.trades[0].side == "buy"
        assert result.trades[1].side == "sell"

    async def test_commission_applied(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            buy_commission_rate=0.01,
            sell_commission_rate=0.01,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert result.trades[0].commission > 0

    async def test_slippage_applied(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.01,
        )
        result = await executor.run()
        assert result.trades[0].slippage > 0

    async def test_equity_curve_recorded(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        result = await executor.run()
        assert len(result.equity_curve) > 0

    async def test_metrics_with_trades(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuySellStrategy,
            data_provider=data_provider,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert result.metrics["total_trades"] == 1  # 매도 기준 거래 횟수
        assert result.metrics["buy_trades"] == 1
        assert result.metrics["sell_trades"] == 1
        assert "sharpe_ratio" in result.metrics
        assert "max_drawdown" in result.metrics
        assert "win_rate" in result.metrics

    async def test_metrics_empty_for_no_trades(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        result = await executor.run()
        assert result.metrics == {}

    async def test_result_to_dict(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuySellStrategy,
            data_provider=data_provider,
        )
        result = await executor.run()
        d = result.to_dict()
        assert "strategy" in d
        assert "total_return_pct" in d
        assert "trades" in d
        assert "config" in d
        assert "datasets" in d

    async def test_insufficient_balance_skips_buy(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            initial_balance=100,  # 잔고 부족
        )
        result = await executor.run()
        assert len(result.trades) == 0

    async def test_sell_more_than_held(self, data_provider):
        """보유량 이상 매도 시 보유량만큼만 매도."""
        data_provider.reset()

        class SellTooMuch(Strategy):
            meta = StrategyMeta(name="sell_too_much", version="1.0", description="t")

            def __init__(self, ctx):
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context):
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=5)]
                if self._step == 2:
                    return [Signal(symbol="005930", side="sell", quantity=100)]
                return []

        executor = BacktestExecutor(
            strategy_cls=SellTooMuch,
            data_provider=data_provider,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 2
        # 매도 거래는 실제로 실행됨 (보유량 5주만 매도)

    async def test_oversell_uses_executed_qty_for_fee_and_trade(self, store):
        """#1989: 보유 초과 매도 시 수수료/슬리피지/거래 수량이 체결 수량 기준.

        5주 보유 중 10주 매도 요청 → 보유분 5주만 체결되어야 하며,
        commission/slippage/BacktestTrade.quantity 모두 요청 수량(10)이 아닌
        체결 수량(5) 기준이어야 한다.
        """

        class Buy5Sell10(Strategy):
            meta = StrategyMeta(name="buy5_sell10", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=5)]
                if self._step == 2:
                    return [Signal(symbol="005930", side="sell", quantity=10)]
                return []

        # 평탄 가격 fixture(close=100), 4행 → 슬리피지/수수료 검증 결정적
        closes = [100.0, 100.0, 100.0, 100.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        executor = BacktestExecutor(
            strategy_cls=Buy5Sell10,
            data_provider=provider,
            initial_balance=10000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.01,
            slippage_rate=0.0,
        )
        result = await executor.run()

        assert len(result.trades) == 2
        buy_trade = result.trades[0]
        sell_trade = result.trades[1]
        assert buy_trade.side == "buy"
        assert sell_trade.side == "sell"

        exec_price = sell_trade.price  # slippage=0 → 100.0

        # (a) 거래 수량은 요청(10)이 아닌 체결(5) 기준
        assert sell_trade.quantity == 5

        # (b) 매도 수수료는 5주 기준 (exec_price * 5 * 0.01), 요청 10주(10.0) 아님
        assert sell_trade.commission == pytest.approx(exec_price * 5 * 0.01)
        assert sell_trade.commission == pytest.approx(5.0)

        # (c) 슬리피지도 5주 기준 (slippage_rate=0 → 0.0)
        assert sell_trade.slippage == pytest.approx(abs(exec_price - 100.0) * 5)
        assert sell_trade.slippage == pytest.approx(0.0)

        # (d) balance/포지션 정합: buy 5@100(fee 0) → -500,
        #     sell 5@100 fee 1% → +500-5=+495 → 잔고 9995.0, 포지션 0
        assert executor._positions.get("005930") is None
        # final_balance == equity_curve[-1] equity, 포지션 청산 후 현금만 남음
        assert result.equity_curve[-1]["balance"] == pytest.approx(9995.0)

    async def test_buy_path_unchanged_with_fees(self, data_provider):
        """#1989 회귀: buy 경로는 signal.quantity==executed_qty이므로 동작 불변.

        매수 수수료/슬리피지가 요청 수량 기준으로 정확히 기록되는지 확인한다.
        """
        data_provider.reset()
        buy_rate = 0.001
        slip_rate = 0.01
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            initial_balance=10_000_000,
            buy_commission_rate=buy_rate,
            sell_commission_rate=0.0,
            slippage_rate=slip_rate,
        )
        result = await executor.run()

        assert len(result.trades) == 1
        buy_trade = result.trades[0]
        assert buy_trade.side == "buy"
        # BuyAndHold는 10주 매수 → 체결 수량 == 요청 수량
        assert buy_trade.quantity == 10
        exec_price = buy_trade.price
        # 수수료 = exec_price * 10 * buy_rate (요청==체결)
        assert buy_trade.commission == pytest.approx(exec_price * 10 * buy_rate)
        # 슬리피지 = |exec_price - base_price| * 10
        base_price = exec_price / (1 + slip_rate)
        assert buy_trade.slippage == pytest.approx(abs(exec_price - base_price) * 10)

    async def test_executor_split_commission(self, data_provider):
        """매수/매도 수수료율이 각각 독립 적용되는지 검증."""
        data_provider.reset()
        buy_rate = 0.001
        sell_rate = 0.005
        executor = BacktestExecutor(
            strategy_cls=BuySellStrategy,
            data_provider=data_provider,
            initial_balance=10_000_000,
            buy_commission_rate=buy_rate,
            sell_commission_rate=sell_rate,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 2

        buy_trade = result.trades[0]
        sell_trade = result.trades[1]
        assert buy_trade.side == "buy"
        assert sell_trade.side == "sell"

        # 매수 수수료 = price * qty * buy_rate
        expected_buy_comm = buy_trade.price * buy_trade.quantity * buy_rate
        assert abs(buy_trade.commission - expected_buy_comm) < 0.01

        # 매도 수수료 = price * qty * sell_rate
        expected_sell_comm = sell_trade.price * sell_trade.quantity * sell_rate
        assert abs(sell_trade.commission - expected_sell_comm) < 0.01

        # 매수/매도 수수료율이 다르므로 수수료 비율도 다름
        assert buy_trade.commission != sell_trade.commission


# ── Mark-to-Market 평가 테스트 (#1987) ─────────────


class TestBacktestMarkToMarket:
    """미청산 포지션을 현재가로 평가하는지 검증."""

    async def _run_buy_and_hold(self, store, closes, **executor_kwargs):
        """closes 시퀀스로 데이터를 적재하고 BuyAndHold 백테스트 실행."""
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
            **executor_kwargs,
        )
        result = await executor.run()
        return result, provider

    async def test_open_position_valued_at_current_price_gain(self, store):
        """(a) 진입 후 가격 상승 — final_balance가 현재가 미실현이익 반영."""
        # idx0=100, idx1(매수)=110, ... 마지막 봉=150 으로 상승
        closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        result, _ = await self._run_buy_and_hold(store, closes)

        # BuyAndHold는 idx1(close=110)에서 10주 매수
        buy_trade = result.trades[0]
        assert buy_trade.side == "buy"
        qty = buy_trade.quantity
        avg_price = buy_trade.price
        last_price = closes[-1]

        # 원가(avg_price) 기반 평가가 아니라 현재가 기반이어야 함
        cash = result.equity_curve[-1]["balance"]
        cost_basis_equity = cash + qty * avg_price
        market_equity = cash + qty * last_price

        assert last_price > avg_price  # fixture 상승 전제
        assert result.final_balance == pytest.approx(market_equity)
        assert result.final_balance != pytest.approx(cost_basis_equity)
        assert result.final_balance > cost_basis_equity

        # total_return도 현재가 기반
        expected_return = (
            (market_equity - result.initial_balance) / result.initial_balance * 100
        )
        assert result.total_return == pytest.approx(expected_return)

    async def test_open_position_valued_at_current_price_loss(self, store):
        """(a') 진입 후 가격 하락 — 미실현손실도 반영(avg_price 아님)."""
        closes = [100.0, 110.0, 90.0, 80.0, 70.0, 60.0]
        result, _ = await self._run_buy_and_hold(store, closes)

        buy_trade = result.trades[0]
        qty = buy_trade.quantity
        avg_price = buy_trade.price  # 110
        last_price = closes[-1]  # 60

        cash = result.equity_curve[-1]["balance"]
        market_equity = cash + qty * last_price
        cost_basis_equity = cash + qty * avg_price

        assert last_price < avg_price  # 하락 전제
        assert result.final_balance == pytest.approx(market_equity)
        assert result.final_balance < cost_basis_equity

    async def test_equity_curve_step_uses_current_price(self, store):
        """(b) equity_curve의 각 step equity가 해당 step 현재가 기반."""
        closes = [100.0, 110.0, 120.0, 130.0, 140.0]
        result, _ = await self._run_buy_and_hold(store, closes)

        buy_trade = result.trades[0]
        qty = buy_trade.quantity  # 10
        # 매수는 idx1(첫 on_step, current_idx=1, close=110)에서 발생
        # equity_curve[i]는 advance()로 current_idx=i+1 인 시점에 기록됨
        for i, point in enumerate(result.equity_curve):
            current_idx = i + 1
            expected_close = closes[current_idx]
            expected_equity = point["balance"] + qty * expected_close
            assert point["equity"] == pytest.approx(expected_equity), (
                f"step {i}: equity {point['equity']} != "
                f"cash + qty*close({expected_close})"
            )

    async def test_price_lookup_failure_falls_back_to_avg_price(self, store, caplog):
        """(c) 가격 조회 실패(None/0/raise) 시 avg_price fallback + 경고 로그."""
        import logging

        closes = [100.0, 110.0, 120.0, 130.0, 140.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )

        # get_current_price를 None 반환 / 예외 / 0 으로 번갈아 실패시킴
        call_count = {"n": 0}
        real_get_price = provider.get_current_price

        async def flaky_get_price(symbol: str) -> float:
            # _execute_signal(매수 체결)에는 정상가가 필요하므로
            # 포지션 보유 후(_calculate_equity 경로)에만 실패시킨다.
            if executor._positions:
                call_count["n"] += 1
                mode = call_count["n"] % 3
                if mode == 0:
                    return None  # type: ignore[return-value]
                if mode == 1:
                    raise BacktestDataError("simulated lookup failure")
                return 0.0
            return await real_get_price(symbol)

        with patch.object(provider, "get_current_price", side_effect=flaky_get_price):
            with caplog.at_level(logging.WARNING, logger="ante.backtest.executor"):
                result = await executor.run()

        buy_trade = result.trades[0]
        qty = buy_trade.quantity
        avg_price = buy_trade.price

        # 모든 평가가 실패했으므로 avg_price(원가) fallback
        cash = result.equity_curve[-1]["balance"]
        assert result.final_balance == pytest.approx(cash + qty * avg_price)

        # 경고 로그에 symbol이 포함되어야 함(조용히 숨기지 않음)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "가격 조회 실패 시 경고 로그가 있어야 함"
        assert any("005930" in r.getMessage() for r in warnings)

    async def test_no_lookahead_final_valuation_reuses_last_bar(self, store):
        """(d) 불균등 길이 데이터셋 회귀 + final valuation lookahead 차단.

        - final_balance == equity_curve[-1]["equity"]
        - 루프 종료 후 advance()가 올린 미래 봉 가격을 쓰지 않음
          (final valuation에서 get_current_price를 재호출하지 않음을 lock)
        """
        # 두 심볼: 길이가 다름(005930=4행, 000660=8행).
        # get_total_steps/advance는 min 길이(=4)를 따르므로
        # 시뮬레이션은 005930 idx0..3 까지만 진행된다.
        df_a = _make_ohlcv_df_with_closes([100.0, 110.0, 120.0, 130.0], symbol="005930")
        df_b = _make_ohlcv_df_with_closes(
            [200.0, 210.0, 220.0, 230.0, 240.0, 250.0, 260.0, 270.0],
            symbol="000660",
        )
        store.write("005930", "1d", df_a)
        store.write("000660", "1d", df_b)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        provider.load("000660", "1d")

        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )

        # get_current_price 호출 추적: 마지막 호출 시점의 current_idx를 기록
        idx_at_call: list[int] = []
        real_get_price = provider.get_current_price

        async def tracking_get_price(symbol: str) -> float:
            idx_at_call.append(provider.current_idx)
            return await real_get_price(symbol)

        with patch.object(
            provider, "get_current_price", side_effect=tracking_get_price
        ):
            result = await executor.run()

        # final_balance는 마지막 시뮬레이션 봉 equity 재사용 (재계산 아님)
        assert result.final_balance == result.equity_curve[-1]["equity"]

        # 시뮬레이션은 min 길이(4) 기준. 마지막 평가 봉은 005930 idx=3 (close=130).
        # get_current_price는 current_idx <= 3 인 시점에서만 호출되어야 한다.
        # (루프 종료 후 advance()로 current_idx=4가 된 뒤 재호출되면 lookahead)
        assert idx_at_call, "get_current_price가 호출되어야 함"
        assert max(idx_at_call) <= 3, (
            f"final valuation이 미래 봉(current_idx>3)을 참조함: {idx_at_call}"
        )

        # 005930 마지막 평가가는 idx=3 close=130 (idx=4는 데이터 없음/미래)
        buy_trade = result.trades[0]
        qty = buy_trade.quantity
        cash = result.equity_curve[-1]["balance"]
        assert result.final_balance == pytest.approx(cash + qty * 130.0)


# ── BacktestService 테스트 ─────────────────────────


class TestBacktestService:
    def test_validate_config_missing_keys(self):
        service = BacktestService()
        with pytest.raises(BacktestConfigError, match="strategy_path"):
            service._validate_config({"start_date": "2026-01-01"})

    def test_validate_config_returns_backtest_config(self):

        service = BacktestService()
        result = service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "symbols": ["005930"],
            }
        )
        assert isinstance(result, BacktestConfig)
        assert result.strategy_path == "test.py"
        assert result.start_date == "2026-01-01"
        assert result.end_date == "2026-06-30"
        assert result.symbols == ["005930"]

    def test_validate_config_default_values(self):
        """buy/sell commission 기본값 검증."""
        service = BacktestService()
        result = service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            }
        )
        assert result.buy_commission_rate == 0.00015
        assert result.sell_commission_rate == 0.00195
        assert result.slippage_rate == 0.001
        assert result.initial_balance == 10_000_000.0
        assert result.timeframe == "1d"

    def test_validate_config_commission_rate_backward_compat(self):
        """기존 commission_rate 키가 buy_commission_rate로 매핑."""
        service = BacktestService()
        result = service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "commission_rate": 0.005,
            }
        )
        assert result.buy_commission_rate == 0.005
        assert result.sell_commission_rate == 0.00195

    def test_validate_config_data_path_backward_compat(self):
        """data_path -> data_paths 하위호환."""
        service = BacktestService(data_path="default/")
        result = service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "data_path": "custom/data/",
            }
        )
        assert result.data_paths == ["custom/data/"]

    def test_validate_config_data_paths_preferred(self):
        """data_paths가 있으면 data_path보다 우선."""
        service = BacktestService()
        result = service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
                "data_path": "ignored/",
                "data_paths": ["a/", "b/"],
            }
        )
        assert result.data_paths == ["a/", "b/"]

    async def test_run_injects_config_and_datasets(self, loaded_store, data_dir):
        """run() 후 result.config=BacktestConfig, datasets=list[DatasetInfo]."""
        service = BacktestService(data_path=str(data_dir))

        config = {
            "strategy_path": "dummy.py",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "symbols": ["005930"],
            "timeframe": "1d",
            "data_path": str(data_dir),
        }

        with patch(
            "ante.backtest.service.StrategyLoader.load",
            return_value=EmptyStrategy,
        ):
            result = await service.run(config)

        # config는 BacktestConfig 인스턴스
        assert isinstance(result.config, BacktestConfig)
        assert result.config.strategy_path == "dummy.py"
        assert result.config.symbols == ["005930"]
        assert result.config.start_date == "2026-01-01"
        assert result.config.end_date == "2026-12-31"

        # datasets는 list이고 DatasetInfo 원소를 포함
        assert isinstance(result.datasets, list)
        assert len(result.datasets) == 1
        assert isinstance(result.datasets[0], DatasetInfo)
        assert result.datasets[0].symbol == "005930"
        assert result.datasets[0].timeframe == "1d"
        assert result.datasets[0].row_count > 0


# ── Exceptions 테스트 ──────────────────────────────


class TestExceptions:
    def test_backtest_error_hierarchy(self):
        assert issubclass(BacktestConfigError, BacktestError)
        assert issubclass(BacktestDataError, BacktestError)

    def test_backtest_error_message(self):
        err = BacktestError("test error")
        assert str(err) == "test error"


# ── BacktestResult config/datasets 필드 테스트 ────


class TestBacktestResultConfigFields:
    def test_result_default_config(self):
        """기본 생성 시 config == BacktestConfig(), datasets == []."""
        from ante.backtest.config import BacktestConfig  # noqa: F811

        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_000_000,
            total_return=0.0,
        )
        assert result.config == BacktestConfig()
        assert result.datasets == []

    def test_result_to_dict_with_config(self):
        """config 설정된 결과의 to_dict() 검증."""

        cfg = BacktestConfig(
            strategy_path="strategies/ma_cross.py",
            symbols=["005930"],
            timeframe="1d",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000.0,
            buy_commission_rate=0.00015,
            sell_commission_rate=0.00195,
            slippage_rate=0.001,
        )
        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
            config=cfg,
        )
        d = result.to_dict()
        assert d["config"]["strategy_path"] == "strategies/ma_cross.py"
        assert d["config"]["symbols"] == ["005930"]
        assert d["config"]["timeframe"] == "1d"
        assert d["config"]["initial_balance"] == 10_000_000.0

    def test_result_to_dict_with_datasets(self):
        """datasets 포함된 결과의 to_dict() 검증."""

        ds = DatasetInfo(
            symbol="005930",
            timeframe="1d",
            row_count=1200,
            start_date="2020-01-02",
            end_date="2024-12-30",
            data_dir="data/ohlcv/1d/KRX/005930",
            file_count=60,
        )
        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
            datasets=[ds],
        )
        d = result.to_dict()
        assert len(d["datasets"]) == 1
        assert d["datasets"][0]["symbol"] == "005930"
        assert d["datasets"][0]["row_count"] == 1200
        assert d["datasets"][0]["file_count"] == 60

    def test_result_backward_compatible(self):
        """기존 키들이 여전히 존재하는지 확인."""
        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
        )
        d = result.to_dict()
        expected_keys = {
            "strategy",
            "period",
            "initial_balance",
            "final_balance",
            "total_return_pct",
            "total_trades",
            "metrics",
            "equity_curve",
            "trades",
            "config",
            "datasets",
        }
        assert set(d.keys()) == expected_keys
