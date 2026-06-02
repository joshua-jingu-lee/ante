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
    async def test_pre_advance_ohlcv_empty(self, data_provider):
        """load 직후(pre-advance, current_idx=-1)는 OHLCV가 비어 있다(#2061)."""
        assert data_provider.current_idx == -1
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert df.is_empty()  # head(0): 첫 advance() 이전이라 노출 데이터 없음

    async def test_first_advance_exposes_first_row(self, data_provider):
        """첫 advance()가 row 0으로 전진하여 첫 행을 노출한다(#2061)."""
        assert data_provider.advance() is True
        assert data_provider.current_idx == 0  # 첫 advance가 row 0 처리
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 1  # row 0만 보임

    async def test_advance_increases_visible_data(self, data_provider):
        data_provider.advance()  # idx 0
        data_provider.advance()  # idx 1
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 2  # idx 0,1

    async def test_advance_returns_false_at_end(self, data_provider):
        for _ in range(20):
            data_provider.advance()
        assert data_provider.advance() is False

    async def test_get_current_price(self, data_provider):
        data_provider.advance()  # idx -1 -> 0: 현재가가 노출됨
        price = await data_provider.get_current_price("005930")
        assert price > 0

    async def test_get_current_price_pre_advance_unavailable(self, data_provider):
        """pre-advance(current_idx=-1)에서는 현재가가 unavailable(#2061)."""
        assert data_provider.current_idx == -1
        with pytest.raises(BacktestDataError):
            await data_provider.get_current_price("005930")

    async def test_get_current_price_no_data(self, data_provider):
        data_provider.advance()  # idx 0
        with pytest.raises(BacktestDataError):
            await data_provider.get_current_price("999999")

    async def test_get_current_timestamp(self, data_provider):
        data_provider.advance()  # idx -1 -> 0: 현재 시각이 노출됨
        ts = data_provider.get_current_timestamp()
        assert ts is not None
        assert isinstance(ts, datetime)

    async def test_get_current_timestamp_pre_advance_none(self, data_provider):
        """pre-advance(current_idx=-1)에서는 현재 시각이 None(#2061).

        음수 인덱스로 마지막 행을 잘못 반환하지 않도록 가드한다.
        """
        assert data_provider.current_idx == -1
        assert data_provider.get_current_timestamp() is None

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
        assert data_provider.current_idx == -1  # 첫 row 이전으로 복귀

    async def test_limit_respects_future_cutoff(self, data_provider):
        """limit이 현재까지 데이터보다 크면 현재까지만 반환."""
        data_provider.advance()  # idx 0
        df = await data_provider.get_ohlcv("005930", "1d", limit=100)
        assert len(df) == 1

    async def test_get_indicator_returns_computed_values(self, data_provider):
        """get_indicator()가 실제 지표 값을 계산하여 반환."""
        # 기본 데이터 10행, 모두 전진 (idx -1 시작 → 10회 advance로 idx 9 도달)
        for _ in range(10):
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
        for _ in range(30):
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
        for _ in range(40):
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
        data_provider.advance()  # idx -1 -> 0: 첫 행 노출(#2061)
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

    async def test_metrics_computed_for_no_trades(self, data_provider):
        """무거래여도 metrics는 {}가 아니라 계산 가능한 지표를 채운다(#2125).

        ``calculate_metrics`` 는 빈 거래/평탄 equity_curve에서도 core 13지표를
        산출하므로(거래 기반은 0/None, equity 기반은 equity_curve 기준),
        무거래 result도 core 13 + compat 3(총 16키)을 안정적으로 노출한다.
        """
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        result = await executor.run()

        # 무거래여도 metrics가 비어 있지 않다.
        assert result.metrics != {}
        assert len(result.trades) == 0

        # core 13지표 키가 모두 존재한다.
        core_keys = {
            "total_return",
            "annual_return",
            "sharpe_ratio",
            "max_drawdown",
            "max_drawdown_duration",
            "total_trades",
            "winning_trades",
            "losing_trades",
            "win_rate",
            "profit_factor",
            "avg_profit",
            "avg_loss",
            "total_commission",
        }
        assert core_keys <= set(result.metrics)

        # compat 3필드가 빈 거래에서 자연히 0이 된다.
        assert result.metrics["buy_trades"] == 0
        assert result.metrics["sell_trades"] == 0
        assert result.metrics["total_slippage"] == 0

        # 거래 기반 지표는 무거래 시 0/0.0이다.
        assert result.metrics["total_trades"] == 0
        assert result.metrics["win_rate"] == 0.0
        assert result.metrics["total_commission"] == 0.0

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

        slippage_rate를 nonzero(0.02)로 두어, 슬리피지가 요청 수량(10)이 아닌
        체결 수량(5) 기준임을 단독으로 검증한다(slippage=0이면 두 기준이
        모두 0.0이라 구별 불가).
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

        # slippage_rate=0.02: sell exec_price = 100*(1-0.02)=98,
        # slippage = |98-100|*5 = 10.0 (체결 5주 기준; 요청 10주면 20.0)
        slippage_rate = 0.02
        sell_commission_rate = 0.01
        executor = BacktestExecutor(
            strategy_cls=Buy5Sell10,
            data_provider=provider,
            initial_balance=10000,
            buy_commission_rate=0.0,
            sell_commission_rate=sell_commission_rate,
            slippage_rate=slippage_rate,
        )
        result = await executor.run()

        assert len(result.trades) == 2
        buy_trade = result.trades[0]
        sell_trade = result.trades[1]
        assert buy_trade.side == "buy"
        assert sell_trade.side == "sell"

        # sell exec_price = base_price * (1 - slippage_rate) = 100 * 0.98 = 98.0
        exec_price = 100.0 * (1 - slippage_rate)
        assert sell_trade.price == pytest.approx(98.0)
        assert sell_trade.price == pytest.approx(exec_price)

        # (a) 거래 수량은 요청(10)이 아닌 체결(5) 기준
        assert sell_trade.quantity == 5

        # (b) 매도 수수료는 5주 기준 (exec_price * 5 * 0.01 = 4.9),
        #     요청 10주 기준(9.8)이 아님
        expected_commission = exec_price * 5 * sell_commission_rate
        assert sell_trade.commission == pytest.approx(expected_commission)
        assert sell_trade.commission == pytest.approx(4.9)

        # (c) 슬리피지는 체결 수량(5) 기준 = |98-100|*5 = 10.0.
        #     요청 수량(10) 기준이면 20.0이라 아래 assert가 FAIL해야 한다.
        assert sell_trade.slippage == pytest.approx(abs(exec_price - 100.0) * 5)
        assert sell_trade.slippage == pytest.approx(10.0)

        # (d) balance/포지션 정합:
        #     buy 5주 @ 100*(1+0.02)=102, fee 0 → 비용 510 → 잔고 9490.0
        #     sell 5주 @ 98, fee 4.9 → 수익 98*5-4.9=485.1 → 잔고 9975.1, 포지션 0
        assert executor._positions.get("005930") is None
        # final_balance == equity_curve[-1] equity, 포지션 청산 후 현금만 남음
        assert result.equity_curve[-1]["balance"] == pytest.approx(9975.1)

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


# ── Signal 검증 테스트 (#1991, #2066 포괄) ─────────


class _OneSignalStrategy(Strategy):
    """첫 스텝에 주어진 Signal 하나만 발행하는 전략."""

    meta = StrategyMeta(name="one_signal", version="1.0", description="t")

    #: 클래스 변수로 발행할 Signal을 주입한다.
    signal: Signal

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._emitted = False

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        if not self._emitted:
            self._emitted = True
            return [self.signal]
        return []


def _make_one_signal_strategy(signal: Signal) -> type[Strategy]:
    """첫 스텝에 ``signal`` 하나만 발행하는 전략 클래스를 만든다."""
    return type(
        "InjectedOneSignalStrategy",
        (_OneSignalStrategy,),
        {"signal": signal},
    )


class TestBacktestSignalValidation:
    """무효 Signal(side/quantity)을 거래 발행 없이 skip하는지 검증.

    라이브 RuleEngine preflight와 동일 vocabulary: side ∈ {"buy","sell"},
    quantity finite & > 0. #2066(음수/0/NaN quantity)을 포괄한다.
    """

    async def _run_single_signal(self, store, signal: Signal):
        """평탄 가격(close=100) fixture에서 단일 Signal 백테스트 실행."""
        df = _make_ohlcv_df_with_closes([100.0, 100.0, 100.0, 100.0])
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        executor = BacktestExecutor(
            strategy_cls=_make_one_signal_strategy(signal),
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        return executor, result

    async def test_negative_buy_quantity_skipped(self, store):
        """Signal(side="buy", quantity=-1) → 거래 미발행 + 현금/포지션 불변."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=-1)
        )
        assert len(result.trades) == 0
        # 음수 buy가 cost를 음수로 만들어 현금을 늘리던 회귀를 차단(현금 불변).
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_nan_buy_quantity_skipped(self, store):
        """#2066: Signal(side="buy", quantity=NaN) → skip."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=float("nan"))
        )
        assert len(result.trades) == 0
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_inf_buy_quantity_skipped(self, store):
        """#2066: Signal(side="buy", quantity=inf) → skip."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=float("inf"))
        )
        assert len(result.trades) == 0
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_zero_buy_quantity_skipped(self, store):
        """#2066: Signal(side="buy", quantity=0) → skip."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=0)
        )
        assert len(result.trades) == 0
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_bool_buy_quantity_skipped(self, store):
        """정책 일치: bool quantity(True)는 수량으로 보지 않고 skip."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=True)
        )
        assert len(result.trades) == 0
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_unknown_side_skipped(self, store):
        """unknown side("foo") → skip(거래 미발행)."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="foo", quantity=1)
        )
        assert len(result.trades) == 0
        assert result.equity_curve[-1]["balance"] == pytest.approx(10_000)
        assert executor._positions == {}

    async def test_hold_side_not_routed_to_sell(self, store):
        """포지션 보유 중 Signal(side="hold", quantity=1) → 매도되지 않음.

        Repro 2 회귀(#1991): buy/sell 이외 side가 sell 분기로 라우팅되어
        포지션이 청산되고 ledger side가 hold로 기록되던 버그를 차단한다.
        hold Signal은 거래를 발행하지 않고 포지션을 그대로 유지해야 한다.
        """
        df = _make_ohlcv_df_with_closes([100.0, 100.0, 100.0, 100.0])
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        class BuyThenHold(Strategy):
            meta = StrategyMeta(name="buy_then_hold", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=1)]
                if self._step == 2:
                    return [Signal(symbol="005930", side="hold", quantity=1)]
                return []

        executor = BacktestExecutor(
            strategy_cls=BuyThenHold,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        # 매수 거래 1건만 기록되고, hold는 거래를 발행하지 않는다.
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        assert all(t.side != "hold" for t in result.trades)
        # 포지션이 hold로 청산되지 않고 유지된다(1주 보유).
        assert executor._positions["005930"]["quantity"] == 1

    async def test_valid_buy_processed(self, store):
        """회귀: 유효 Signal(side="buy", quantity=5)는 정상 처리."""
        executor, result = await self._run_single_signal(
            store, Signal(symbol="005930", side="buy", quantity=5)
        )
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        assert result.trades[0].quantity == 5
        assert executor._positions["005930"]["quantity"] == 5

    async def test_valid_sell_processed(self, store):
        """회귀: 유효 Signal(side="sell", quantity=3)은 정상 처리."""
        df = _make_ohlcv_df_with_closes([100.0, 100.0, 100.0, 100.0])
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        class BuyThenSell(Strategy):
            meta = StrategyMeta(name="buy_then_sell", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=5)]
                if self._step == 2:
                    return [Signal(symbol="005930", side="sell", quantity=3)]
                return []

        executor = BacktestExecutor(
            strategy_cls=BuyThenSell,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        assert len(result.trades) == 2
        assert result.trades[0].side == "buy"
        assert result.trades[1].side == "sell"
        assert result.trades[1].quantity == 3
        # buy 5 - sell 3 = 2주 잔여
        assert executor._positions["005930"]["quantity"] == 2

    async def test_skip_emits_warning_with_diagnostics(self, store, caplog):
        """skip 시 logger.warning에 symbol/side/quantity가 포함된다."""
        import logging

        with caplog.at_level(logging.WARNING, logger="ante.backtest.executor"):
            await self._run_single_signal(
                store, Signal(symbol="005930", side="buy", quantity=-1)
            )
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings, "무효 Signal skip 시 경고 로그가 있어야 함"
        msg = warnings[0].getMessage()
        assert "005930" in msg
        assert "buy" in msg
        assert "-1" in msg


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
        # idx0(매수)=100, idx1=110, ... 마지막 봉=150 으로 상승(#2061: 첫 on_step=row0)
        closes = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0]
        result, _ = await self._run_buy_and_hold(store, closes)

        # BuyAndHold는 첫 on_step(row 0, close=100)에서 10주 매수(#2061)
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
        avg_price = buy_trade.price  # 100 (row 0, 첫 on_step 매수 — #2061)
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
        # 매수는 row 0(첫 on_step, current_idx=0, close=100)에서 발생(#2061).
        # equity_curve[i]는 advance()로 current_idx=i 인 시점에 기록됨
        # (커서 초기값 -1 → step i가 row i 처리).
        assert len(result.equity_curve) == len(closes)  # 전 행 처리(N step)
        for i, point in enumerate(result.equity_curve):
            current_idx = i
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

    async def test_run_loads_from_data_paths_override(self, tmp_path):
        """#2000 재현: data_paths override가 실제 데이터 로딩에 반영.

        생성자 data_path는 빈 ``wrong/``, config.data_paths는 데이터가
        적재된 ``right/`` 를 가리키고 config에 ``data_path`` 는 없다.
        수정 전에는 ParquetStore가 raw config의 ``data_path`` (없으면 생성자
        기본=wrong/)를 사용해 0행을 로드했다. 수정 후에는 정규화된
        validated.data_paths[0]=right/ 에서 로드되어야 한다.
        """
        wrong = tmp_path / "wrong"
        right = tmp_path / "right"
        wrong.mkdir()
        right.mkdir()

        # right/ 에만 실제 데이터를 적재
        right_store = ParquetStore(base_path=right)
        right_store.write("005930", "1d", _make_ohlcv_df())

        service = BacktestService(data_path=str(wrong))
        config = {
            "strategy_path": "dummy.py",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "symbols": ["005930"],
            "timeframe": "1d",
            # data_path 미포함; data_paths override만 제공
            "data_paths": [str(right)],
        }

        with patch(
            "ante.backtest.service.StrategyLoader.load",
            return_value=EmptyStrategy,
        ):
            result = await service.run(config)

        # right/ 에서 로드되어 데이터가 채워졌는지 확인
        assert len(result.datasets) == 1
        assert result.datasets[0].symbol == "005930"
        assert result.datasets[0].row_count > 0
        assert len(result.equity_curve) > 0
        # result.config.data_paths 에는 사용자 override 가 그대로 남는다
        assert result.config.data_paths == [str(right)]

    async def test_run_data_path_backward_compat(self, tmp_path):
        """회귀: data_path 지정 + data_paths 미지정 → 해당 경로 로드."""
        right = tmp_path / "right"
        right.mkdir()
        right_store = ParquetStore(base_path=right)
        right_store.write("005930", "1d", _make_ohlcv_df())

        # 생성자 기본은 다른 빈 경로
        wrong = tmp_path / "wrong"
        wrong.mkdir()
        service = BacktestService(data_path=str(wrong))
        config = {
            "strategy_path": "dummy.py",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "symbols": ["005930"],
            "timeframe": "1d",
            "data_path": str(right),
        }

        with patch(
            "ante.backtest.service.StrategyLoader.load",
            return_value=EmptyStrategy,
        ):
            result = await service.run(config)

        assert len(result.datasets) == 1
        assert result.datasets[0].row_count > 0
        assert result.config.data_paths == [str(right)]

    async def test_run_uses_constructor_default_data_path(self, tmp_path):
        """회귀: data_path/data_paths 둘 다 미지정 → 생성자 기본 사용."""
        default_dir = tmp_path / "default"
        default_dir.mkdir()
        default_store = ParquetStore(base_path=default_dir)
        default_store.write("005930", "1d", _make_ohlcv_df())

        service = BacktestService(data_path=str(default_dir))
        config = {
            "strategy_path": "dummy.py",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "symbols": ["005930"],
            "timeframe": "1d",
        }

        with patch(
            "ante.backtest.service.StrategyLoader.load",
            return_value=EmptyStrategy,
        ):
            result = await service.run(config)

        assert len(result.datasets) == 1
        assert result.datasets[0].row_count > 0
        assert result.config.data_paths == [str(default_dir)]


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


# ── get_trade_history 테스트 (#2075) ──────────────


# 라이브 StrategyContext.get_trade_history 와 동일한 full dict shape.
_TRADE_HISTORY_KEYS = {
    "trade_id",
    "symbol",
    "side",
    "quantity",
    "price",
    "status",
    "order_type",
    "reason",
    "commission",
    "timestamp",
}


class _MultiTradeStrategy(Strategy):
    """여러 symbol에 걸쳐 매매를 발생시키는 테스트 전략."""

    meta = StrategyMeta(
        name="multi_trade",
        version="1.0",
        description="multi-symbol buy/sell",
    )

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self._step = 0

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        self._step += 1
        if self._step == 1:
            return [Signal(symbol="005930", side="buy", quantity=10, reason="entry-a")]
        if self._step == 2:
            return [Signal(symbol="000660", side="buy", quantity=5, reason="entry-b")]
        if self._step == 3:
            return [Signal(symbol="005930", side="sell", quantity=10, reason="exit-a")]
        return []


@pytest.fixture
async def multi_symbol_provider(store):
    """005930 / 000660 두 종목이 적재된 BacktestDataProvider."""
    for symbol in ("005930", "000660"):
        store.write(symbol, "1d", _make_ohlcv_df(symbol=symbol))
    provider = BacktestDataProvider(
        store=store,
        start_date="2026-01-01",
        end_date="2026-12-31",
    )
    provider.load("005930", "1d")
    provider.load("000660", "1d")
    return provider


class TestGetTradeHistory:
    """BacktestStrategyContext / BacktestExecutor.get_trade_history 검증."""

    async def _run_multi(self, provider):
        executor = BacktestExecutor(
            strategy_cls=_MultiTradeStrategy,
            data_provider=provider,
            initial_balance=10_000_000,
            buy_commission_rate=0.001,
            sell_commission_rate=0.001,
            slippage_rate=0.0,
        )
        await executor.run()
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=provider,
            portfolio=executor,
        )
        return executor, ctx

    async def test_full_shape_keys(self, multi_symbol_provider):
        """(a) 매매 후 full shape 키 전부를 포함한 dict 리스트 (AttributeError 없음)."""
        _executor, ctx = await self._run_multi(multi_symbol_provider)
        history = await ctx.get_trade_history()
        assert isinstance(history, list)
        assert len(history) == 3
        for entry in history:
            assert set(entry.keys()) == _TRADE_HISTORY_KEYS
            assert entry["status"] == "filled"
            assert entry["order_type"] == "market"
            assert isinstance(entry["trade_id"], str)
            assert entry["trade_id"].startswith("bt-")

    async def test_timestamp_iso_string(self, multi_symbol_provider):
        """(b) datetime timestamp는 ISO 문자열로 변환된다."""
        _executor, ctx = await self._run_multi(multi_symbol_provider)
        history = await ctx.get_trade_history()
        for entry in history:
            assert isinstance(entry["timestamp"], str)
            # ISO 8601 문자열은 fromisoformat으로 round-trip 가능해야 한다.
            datetime.fromisoformat(entry["timestamp"])

    async def test_symbol_filter_then_limit(self, multi_symbol_provider):
        """(c) symbol 필터를 limit 이전에 적용한다."""
        _executor, ctx = await self._run_multi(multi_symbol_provider)

        # 005930: buy(step1) + sell(step3) = 2건, 000660: buy(step2) = 1건
        only_a = await ctx.get_trade_history(symbol="005930")
        assert len(only_a) == 2
        assert all(e["symbol"] == "005930" for e in only_a)

        only_b = await ctx.get_trade_history(symbol="000660")
        assert len(only_b) == 1
        assert only_b[0]["symbol"] == "000660"

        # 필터를 limit 이전에 적용: 005930에 한해 limit=1이면 1건만 남는다.
        limited = await ctx.get_trade_history(symbol="005930", limit=1)
        assert len(limited) == 1
        assert limited[0]["symbol"] == "005930"
        # 최신순이므로 005930의 가장 최근 거래(sell)가 남는다.
        assert limited[0]["side"] == "sell"

    async def test_newest_first(self, multi_symbol_provider):
        """(d) 최신순: 가장 최근 거래가 [0]."""
        _executor, ctx = await self._run_multi(multi_symbol_provider)
        history = await ctx.get_trade_history()
        # 발생 순서: buy(005930) -> buy(000660) -> sell(005930)
        # 최신순이므로 역순으로 반환된다.
        assert history[0]["symbol"] == "005930"
        assert history[0]["side"] == "sell"
        assert history[0]["reason"] == "exit-a"
        assert history[-1]["symbol"] == "005930"
        assert history[-1]["side"] == "buy"
        assert history[-1]["reason"] == "entry-a"

    async def test_trade_id_deterministic_original_index(self, multi_symbol_provider):
        """trade_id는 원본 append 인덱스 기반으로 결정적이다."""
        _executor, ctx = await self._run_multi(multi_symbol_provider)
        history = await ctx.get_trade_history()
        # 최신순: 원본 인덱스 2, 1, 0 순서 -> bt-2, bt-1, bt-0
        assert [e["trade_id"] for e in history] == ["bt-2", "bt-1", "bt-0"]

    async def test_empty_when_no_trades(self, data_provider):
        """(e) 거래가 없으면 빈 리스트를 반환한다."""
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        ctx = BacktestStrategyContext(
            bot_id="test",
            data_provider=data_provider,
            portfolio=executor,
        )
        assert await ctx.get_trade_history() == []

    async def test_issue_repro_no_attribute_error(self):
        """(f) 이슈 #2075 재현 스크립트가 AttributeError 없이 동작한다.

        FakeProvider는 timestamp를 str로 반환하므로, str timestamp가
        그대로(isoformat 미적용) 유지되는 robustness도 함께 검증한다.
        """

        class FakeProvider:
            start = "2026-01-01"
            end = "2026-01-01"

            def __init__(self) -> None:
                self.i = -1

            def get_total_steps(self) -> int:
                return 1

            def advance(self) -> bool:
                self.i += 1
                return self.i < 1

            def get_current_timestamp(self) -> str:
                return "2026-01-01"

            async def get_current_price(self, symbol: str) -> float:
                return 100.0

        captured: dict[str, Any] = {}

        class TradeHistoryStrategy(Strategy):
            meta = StrategyMeta(
                name="trade_history_strategy",
                version="1.0",
                description="t",
            )

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                captured["history"] = await self.ctx.get_trade_history()
                return []

        # AttributeError 없이 완주해야 한다.
        await BacktestExecutor(TradeHistoryStrategy, FakeProvider()).run()
        assert captured["history"] == []

    async def test_str_timestamp_passthrough(self, store):
        """str timestamp 소스는 isoformat 미적용으로 그대로 유지된다."""

        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=BacktestDataProvider(
                store=store,
                start_date="2026-01-01",
                end_date="2026-12-31",
            ),
        )
        executor._trades.append(
            BacktestTrade(
                timestamp="2026-01-01",  # type: ignore[arg-type]
                symbol="005930",
                side="buy",
                quantity=1,
                price=100.0,
                commission=0.1,
                slippage=0.0,
                reason="manual",
            )
        )
        history = executor.get_trade_history()
        assert history[0]["timestamp"] == "2026-01-01"
        assert history[0]["trade_id"] == "bt-0"

    async def test_none_timestamp_passthrough(self, store):
        """None timestamp는 None으로 유지된다(라이브 None-safe parity)."""

        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=BacktestDataProvider(
                store=store,
                start_date="2026-01-01",
                end_date="2026-12-31",
            ),
        )
        executor._trades.append(
            BacktestTrade(
                timestamp=None,  # type: ignore[arg-type]
                symbol="005930",
                side="buy",
                quantity=1,
                price=100.0,
                commission=0.1,
                slippage=0.0,
                reason="manual",
            )
        )
        history = executor.get_trade_history()
        assert history[0]["timestamp"] is None


# ── get_positions PortfolioView 스키마 테스트 (#2074) ─


class TestGetPositionsSchema:
    """BacktestExecutor.get_positions가 PortfolioView 스키마(current_price/
    unrealized_pnl)를 라이브와 parity로 제공하는지 검증(#2074).

    spec docs/specs/strategy/03-04-provider-and-views.md L29:
      get_positions → {symbol: {quantity, avg_price, current_price, unrealized_pnl}}
    """

    async def test_repro_current_price_and_unrealized_pnl(self, store):
        """이슈 재현: step1 buy 1주 @100, step2 price 120.

        step2에서 context["portfolio"](run 루프가 만든 dict)와
        ctx.get_positions()(전략이 호출) 두 경로 모두 005930이
        {quantity:1, avg_price:100.0, current_price:120.0, unrealized_pnl:20.0}.
        """
        # run 루프 첫 on_step은 current_idx=0에서 일어난다(#2061: 첫 행부터 처리).
        #   step1(on_step #1) -> idx0 close=100 (매수가 100)
        #   step2(on_step #2) -> idx1 close=120 (현재가 120)
        closes = [100.0, 120.0, 120.0, 120.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        captured: dict[str, Any] = {}

        class BuyStep1CaptureStep2(Strategy):
            meta = StrategyMeta(name="buy_capture", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=1)]
                if self._step == 2:
                    # run 루프가 만든 context["portfolio"]와 ctx.get_positions()
                    # 두 경로를 step2에서 캡처한다.
                    captured["context_portfolio"] = context["portfolio"]
                    captured["ctx_positions"] = self.ctx.get_positions()
                return []

        executor = BacktestExecutor(
            strategy_cls=BuyStep1CaptureStep2,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        await executor.run()

        expected = {
            "quantity": 1,
            "avg_price": 100.0,
            "current_price": 120.0,
            "unrealized_pnl": 20.0,
        }
        # 두 경로(run 루프 dict / 전략 호출) 모두 동일 스키마/값.
        for path in ("context_portfolio", "ctx_positions"):
            positions = captured[path]
            assert "005930" in positions, path
            pos = positions["005930"]
            assert pos["quantity"] == pytest.approx(expected["quantity"]), path
            assert pos["avg_price"] == pytest.approx(expected["avg_price"]), path
            assert pos["current_price"] == pytest.approx(expected["current_price"]), (
                path
            )
            assert pos["unrealized_pnl"] == pytest.approx(expected["unrealized_pnl"]), (
                path
            )
            # 스키마 키 정확성(라이브 PortfolioView parity)
            assert set(pos.keys()) == {
                "quantity",
                "avg_price",
                "current_price",
                "unrealized_pnl",
            }, path

    async def test_price_lookup_failure_falls_back_to_avg_price(self, store):
        """가격 조회 실패/없음 → current_price=avg_price, unrealized_pnl=0.

        보유 후 get_current_price가 항상 실패(예외)하면, get_positions의
        current_price는 avg_price(매수가)로 fallback하고 unrealized_pnl=0.

        step1(첫 on_step)은 idx0(close=100)에서 매수한다(#2061).
        """
        closes = [100.0, 120.0, 120.0, 120.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        captured: dict[str, Any] = {}

        class BuyStep1CaptureStep2(Strategy):
            meta = StrategyMeta(name="buy_capture_fb", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="buy", quantity=1)]
                if self._step == 2:
                    captured["context_portfolio"] = context["portfolio"]
                    captured["ctx_positions"] = self.ctx.get_positions()
                return []

        executor = BacktestExecutor(
            strategy_cls=BuyStep1CaptureStep2,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )

        real_get_price = provider.get_current_price

        async def flaky_get_price(symbol: str) -> float:
            # 매수 체결에는 정상가가 필요하므로 보유 후(_refresh_current_prices /
            # _calculate_equity 경로)에만 실패시킨다.
            if executor._positions:
                raise BacktestDataError("simulated lookup failure")
            return await real_get_price(symbol)

        with patch.object(provider, "get_current_price", side_effect=flaky_get_price):
            await executor.run()

        for path in ("context_portfolio", "ctx_positions"):
            pos = captured[path]["005930"]
            # 현재가 조회 실패 → avg_price(매수가 100) fallback, pnl=0
            assert pos["avg_price"] == pytest.approx(100.0), path
            assert pos["current_price"] == pytest.approx(100.0), path
            assert pos["unrealized_pnl"] == pytest.approx(0.0), path

    async def test_get_positions_no_cache_falls_back_to_avg_price(self, data_provider):
        """run 루프 밖(캐시 미구성)에서 보유 포지션이 있으면 avg_price fallback.

        _current_prices가 비어 있으면 current_price=avg_price, unrealized_pnl=0
        (lookahead/provider 재호출 없이 안전한 기본값).
        """
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        # run 없이 포지션만 주입(캐시는 비어 있음).
        executor._positions["005930"] = {"quantity": 3, "avg_price": 100.0}
        positions = executor.get_positions("backtest")
        pos = positions["005930"]
        assert pos["quantity"] == 3
        assert pos["avg_price"] == pytest.approx(100.0)
        assert pos["current_price"] == pytest.approx(100.0)
        assert pos["unrealized_pnl"] == pytest.approx(0.0)

    async def test_empty_positions_returns_empty(self, data_provider):
        """보유 포지션이 없으면 빈 dict."""
        executor = BacktestExecutor(
            strategy_cls=EmptyStrategy,
            data_provider=data_provider,
        )
        assert executor.get_positions("backtest") == {}

    async def test_no_lookahead_uses_current_bar_price(self, store):
        """lookahead 방지: 매 step current_price가 그 step 현재가 기준.

        step1에서 매수(idx0 close=100)한 직후 step1의 current_price는 아직
        step1 봉 가격(100)이어야 하고, 다음 봉(idx1 close=120)을 미리 보지
        않는다. 또 이전 봉 가격이 다음 step에 stale로 남지 않는다(#2061: 첫 행부터).
        """
        closes = [100.0, 120.0, 130.0, 130.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")

        # step별로 ctx.get_positions()의 current_price를 기록한다.
        seen: list[float | None] = []

        class BuyThenObserve(Strategy):
            meta = StrategyMeta(name="buy_observe", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    # step1: on_step 시점엔 미보유 → 매수 신호. 매수 후 같은
                    # step에서 캐시는 이 step 진입 시점(미보유) 기준이라 비어 있다.
                    signals = [Signal(symbol="005930", side="buy", quantity=1)]
                    positions = self.ctx.get_positions()
                    seen.append(positions.get("005930", {}).get("current_price"))
                    return signals
                pos = self.ctx.get_positions().get("005930")
                seen.append(pos["current_price"] if pos else None)
                return []

        executor = BacktestExecutor(
            strategy_cls=BuyThenObserve,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        await executor.run()

        # step1: 매수 직전 미보유라 캐시 없음 → current_price None.
        assert seen[0] is None
        # step2: idx1 close=120 (이전 봉 100이 stale로 남지 않음).
        assert seen[1] == pytest.approx(120.0)
        # step3: idx2 close=130 (lookahead/stale 없음, 매 step 새 가격).
        assert seen[2] == pytest.approx(130.0)


# ── 첫 데이터 행(row 0) 처리 회귀 (#2061) ──────────


def _make_record_step_strategy() -> tuple[type[Strategy], list[tuple[int, Any]]]:
    """on_step마다 (current_idx, timestamp)를 공유 리스트에 기록하는 전략 클래스.

    run()이 전략 인스턴스를 내부에서 생성하므로, 관측은 클로저로 공유한다.
    """
    seen: list[tuple[int, Any]] = []

    class _RecordStepStrategy(Strategy):
        meta = StrategyMeta(name="record_step", version="1.0", description="t")

        async def on_step(self, context: dict[str, Any]) -> list[Signal]:
            # 백테스트 컨텍스트는 provider를 self.ctx._data로 보관한다.
            seen.append((self.ctx._data.current_idx, context["timestamp"]))
            return []

    return _RecordStepStrategy, seen


class TestBacktestFirstRowProcessed:
    """#2061: 첫 데이터 행(row 0)이 누락되지 않고 처리되는지 회귀.

    버그(이전): `_current_idx=0` + `advance()`가 `+=1` 먼저 → 첫 행 skip,
    1행 데이터는 on_step 0회의 빈 성공, N행은 N-1 step.
    수정 후: 커서 초기값 -1 → 첫 advance()가 row 0 → N행 전부 처리(N step).
    """

    def _build_provider(self, store, n: int) -> BacktestDataProvider:
        df = _make_ohlcv_df(n=n)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        return provider

    async def test_single_row_runs_one_step(self, store):
        """1행 데이터셋 → on_step 1회, equity_curve 길이 1 (빈 성공 아님)."""
        provider = self._build_provider(store, n=1)
        assert provider.get_total_steps() == 1

        strategy_cls, seen = _make_record_step_strategy()
        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=provider,
        )
        result = await executor.run()

        assert len(seen) == 1  # on_step 1회 (이전 버그: 0회)
        assert len(result.equity_curve) == 1  # 빈 성공이 아님
        # 첫(유일) on_step은 row 0(current_idx=0)을 본다.
        assert seen[0][0] == 0

    async def test_n_rows_run_n_steps(self, store):
        """N행 데이터셋 → N step: on_step 호출수 == equity_curve == total_steps == N."""
        n = 7
        provider = self._build_provider(store, n=n)
        assert provider.get_total_steps() == n

        progress: list[tuple[int, int]] = []

        strategy_cls, seen = _make_record_step_strategy()
        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=provider,
        )
        result = await executor.run(
            progress_callback=lambda c, t: progress.append((c, t))
        )

        # on_step 호출수 == equity_curve 길이 == total_steps == N 모두 일치.
        assert len(seen) == n
        assert len(result.equity_curve) == n
        assert provider.get_total_steps() == n
        # progress 최종 콜백은 (N, N)이어야 한다(off-by-one 아님).
        assert progress[-1] == (n, n)
        assert len(progress) == n

    async def test_first_on_step_sees_row_zero(self, store):
        """첫 on_step이 행0(current_idx=0)을 보고, 이후 단조 증가한다(#2061)."""
        n = 5
        provider = self._build_provider(store, n=n)
        cached = provider._cache["005930:1d"]
        first_ts = cached["timestamp"][0]

        strategy_cls, seen = _make_record_step_strategy()
        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=provider,
        )
        await executor.run()

        # 첫 on_step은 row 0(current_idx=0, 첫 timestamp)을 본다.
        assert seen[0][0] == 0
        assert seen[0][1] == first_ts
        # current_idx는 0..N-1로 모든 행을 한 번씩 본다.
        assert [idx for idx, _ in seen] == list(range(n))

    async def test_pre_advance_guards(self, store):
        """루프 진입 전(pre-advance, current_idx=-1) 조회 가드(#2061).

        get_current_timestamp는 None, get_ohlcv는 empty여야 한다(음수 인덱스로
        마지막 행을 잘못 반환하지 않음).
        """
        provider = self._build_provider(store, n=5)
        assert provider.current_idx == -1
        assert provider.get_current_timestamp() is None
        df = await provider.get_ohlcv("005930", "1d", limit=100)
        assert df.is_empty()


# ── on_fill follow-up 체결 테스트 (#2073) ──────────


class TestBacktestOnFillFollowUp:
    """체결 직후 strategy.on_fill(fill) 호출 + follow-up 주문 체결 검증(#2073).

    라이브 bot이 OrderFilledEvent→strategy.on_fill→follow_up을 처리하는 것과
    parity를 맞춘다. base.Strategy.on_fill 기본은 ``[]`` 이므로 override하지
    않은 전략은 추가 체결이 없다(회귀).
    """

    def _make_provider(self, store, closes=None):
        """평탄 가격(close=100) fixture provider."""
        if closes is None:
            closes = [100.0, 100.0, 100.0, 100.0]
        df = _make_ohlcv_df_with_closes(closes)
        store.write("005930", "1d", df)
        provider = BacktestDataProvider(
            store=store, start_date="2026-01-01", end_date="2026-12-31"
        )
        provider.load("005930", "1d")
        return provider

    async def test_on_fill_follow_up_executed(self, store):
        """(a) 재현: on_fill이 후속 buy를 1회 발행 → entry + follow-up 둘 다 체결.

        첫 step에 buy 5주를 발행하고, 그 체결 직후 on_fill에서 buy 3주
        follow-up을 1회만 추가 발행한다. 수정 전(루프가 on_fill 미호출)이라면
        follow-up 거래가 누락되어 trades 길이가 1이어야 한다 → 수정 후 2여야 한다.
        """
        provider = self._make_provider(store)

        # 클래스 변수로 on_fill 호출 횟수를 누적해 인스턴스 밖에서 관찰한다.
        on_fill_counter = {"calls": 0}

        class FillFollowUpStrategy(Strategy):
            meta = StrategyMeta(name="fill_follow_up", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._entered = False
                self._follow_up_emitted = False

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._entered:
                    self._entered = True
                    return [Signal(symbol="005930", side="buy", quantity=5)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                on_fill_counter["calls"] += 1
                # 무한 발행 방지: follow-up은 1회만 발행.
                if not self._follow_up_emitted:
                    self._follow_up_emitted = True
                    return [Signal(symbol="005930", side="buy", quantity=3)]
                return []

        executor = BacktestExecutor(
            strategy_cls=FillFollowUpStrategy,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        # entry(5주) + follow-up(3주) 둘 다 체결. 수정 전(on_fill 미호출)이면
        # follow-up이 누락되어 trades 길이가 1이어야 한다.
        assert len(result.trades) == 2
        assert result.trades[0].side == "buy"
        assert result.trades[0].quantity == 5
        assert result.trades[1].side == "buy"
        assert result.trades[1].quantity == 3
        # 포지션 = 5 + 3 = 8주
        assert executor._positions["005930"]["quantity"] == 8

        # on_fill은 두 체결(entry, follow-up) 각각에 대해 호출됨(>0).
        # entry 체결 1 + follow-up 체결 1 = 2회. 두 번째 on_fill은 follow-up을
        # 발행하지 않아 연쇄가 종료된다.
        assert on_fill_counter["calls"] > 0
        assert on_fill_counter["calls"] == 2

    async def test_on_fill_called_per_fill(self, store):
        """on_fill 호출 카운트>0: 각 체결마다 정확히 호출되는지 추적."""
        provider = self._make_provider(store)

        calls: list[dict[str, Any]] = []

        class RecordOnFill(Strategy):
            meta = StrategyMeta(name="record_on_fill", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._entered = False
                self._followed = False

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._entered:
                    self._entered = True
                    return [Signal(symbol="005930", side="buy", quantity=5)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                calls.append(fill)
                if not self._followed:
                    self._followed = True
                    return [Signal(symbol="005930", side="buy", quantity=2)]
                return []

        executor = BacktestExecutor(
            strategy_cls=RecordOnFill,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        await executor.run()

        # 체결 2건(entry + follow-up) → on_fill 2회 호출(>0).
        assert len(calls) == 2
        # fill dict는 라이브 bot on_fill shape와 동일 키 집합을 가진다.
        for fill in calls:
            assert set(fill) == {
                "order_id",
                "symbol",
                "side",
                "quantity",
                "price",
                "timestamp",
                "fill_dedup_key",
            }
            assert fill["symbol"] == "005930"
            assert fill["side"] == "buy"
            assert fill["fill_dedup_key"] == ""
        # order_id는 결정적 시퀀스(bt-1, bt-2).
        assert calls[0]["order_id"] == "bt-1"
        assert calls[1]["order_id"] == "bt-2"
        # entry 5주, follow-up 2주
        assert calls[0]["quantity"] == 5
        assert calls[1]["quantity"] == 2

    async def test_default_on_fill_no_extra_fills(self, store):
        """(b) on_fill 미override(기본 []) → 추가 체결 없음(기존 동작 회귀)."""
        provider = self._make_provider(store)

        # BuyAndHoldStrategy는 on_fill을 override하지 않는다(base 기본 []).
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        # entry 1건만, follow-up 없음.
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        assert executor._positions["005930"]["quantity"] == 10

    async def test_no_fill_buy_does_not_invoke_on_fill(self, store):
        """(c) no-fill: 잔고 부족 buy → fill None → on_fill 미호출."""
        provider = self._make_provider(store)

        on_fill_calls = 0

        class InsufficientBuy(Strategy):
            meta = StrategyMeta(name="insufficient_buy", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._entered = False

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._entered:
                    self._entered = True
                    # 잔고 100인데 매우 큰 수량 → 잔고 부족으로 no-fill.
                    return [Signal(symbol="005930", side="buy", quantity=1_000)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                nonlocal on_fill_calls
                on_fill_calls += 1
                return []

        executor = BacktestExecutor(
            strategy_cls=InsufficientBuy,
            data_provider=provider,
            initial_balance=100,  # 잔고 부족
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        assert len(result.trades) == 0
        assert on_fill_calls == 0

    async def test_no_fill_sell_does_not_invoke_on_fill(self, store):
        """(c') no-fill: 보유 없는 sell → fill None → on_fill 미호출."""
        provider = self._make_provider(store)

        on_fill_calls = 0

        class SellNothing(Strategy):
            meta = StrategyMeta(name="sell_nothing", version="1.0", description="t")

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._tried = False

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._tried:
                    self._tried = True
                    # 보유 0인데 매도 → executed_qty <= 0 → no-fill.
                    return [Signal(symbol="005930", side="sell", quantity=5)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                nonlocal on_fill_calls
                on_fill_calls += 1
                return []

        executor = BacktestExecutor(
            strategy_cls=SellNothing,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        assert len(result.trades) == 0
        assert on_fill_calls == 0

    async def test_skip_signal_does_not_invoke_on_fill(self, store):
        """(d) skip: invalid/hold signal → fill None → on_fill 미호출."""
        provider = self._make_provider(store)

        on_fill_calls = 0

        class HoldThenInvalid(Strategy):
            meta = StrategyMeta(
                name="hold_then_invalid", version="1.0", description="t"
            )

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._step = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                self._step += 1
                if self._step == 1:
                    return [Signal(symbol="005930", side="hold", quantity=1)]
                if self._step == 2:
                    # invalid quantity
                    return [Signal(symbol="005930", side="buy", quantity=-1)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                nonlocal on_fill_calls
                on_fill_calls += 1
                return []

        executor = BacktestExecutor(
            strategy_cls=HoldThenInvalid,
            data_provider=provider,
            initial_balance=10_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        assert len(result.trades) == 0
        assert on_fill_calls == 0

    async def test_infinite_follow_up_truncated_at_cap(self, store, monkeypatch):
        """(e) 무한 follow-up: on_fill이 매 호출 buy 발행 → cap에서 정확히 truncate.

        on_fill이 매번 follow-up buy를 발행해도 _MAX_FOLLOW_UP_FILLS_PER_STEP
        cap에서 끊겨 무한루프 없이 종료된다. cap을 작게(5) monkeypatch해 테스트가
        빠르게 끝나도록 한다(타임아웃 가드).

        cap은 **follow-up 연쇄에만** 적용된다(on_step 신호는 cap 없이 전부 체결).
        따라서 한 step의 총 체결은 ``entry(on_step) 1 + follow-up cap``개다. cap
        검사는 다음 follow-up 체결을 실행하기 전에 ``follow_up_fills >= cap`` 으로
        선검사하므로(#2073), follow-up 체결은 **정확히 cap개**다(cap+1번째는 실행
        되지 않는다).
        """
        import ante.backtest.executor as executor_mod

        monkeypatch.setattr(executor_mod, "_MAX_FOLLOW_UP_FILLS_PER_STEP", 5)

        provider = self._make_provider(store)

        class InfiniteFollowUp(Strategy):
            meta = StrategyMeta(
                name="infinite_follow_up", version="1.0", description="t"
            )

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._entered = False
                self.on_fill_calls = 0

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._entered:
                    self._entered = True
                    return [Signal(symbol="005930", side="buy", quantity=1)]
                return []

            async def on_fill(self, fill: dict[str, Any]) -> list[Signal]:
                self.on_fill_calls += 1
                # 매 호출마다 follow-up buy를 무한 발행.
                return [Signal(symbol="005930", side="buy", quantity=1)]

        # 잔고를 넉넉히 두어 cap에 닿을 때까지 모든 buy가 체결되게 한다.
        executor = BacktestExecutor(
            strategy_cls=InfiniteFollowUp,
            data_provider=provider,
            initial_balance=1_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        # 무한루프면 여기서 hang → 테스트 타임아웃. 정상 종료해야 한다.
        result = await executor.run()

        # cap=5(monkeypatch)는 follow-up 연쇄에만 적용된다. entry(on_step) 1건은
        # cap 없이 체결되고, 그 뒤 follow-up은 다음 체결 실행 전 선검사
        # (follow_up_fills >= cap)로 break하므로 **정확히 cap(=5)** 개만 체결된다
        # (cap+1번째 follow-up 체결은 실행되지 않음 — #2073). 첫 step만 on_step이
        # buy를 발행하고 이후 step은 _entered=True라 추가 entry가 없으므로, 총
        # 체결은 정확히 1 + cap이다(무한 누적/무한루프 없음). 정상 종료 + cap
        # 정확성이 핵심 검증.
        assert len(result.trades) == 1 + executor_mod._MAX_FOLLOW_UP_FILLS_PER_STEP
        # entry 체결 + cap에 도달한 모든 follow-up 체결마다 on_fill이 호출되었다.
        # cap+1번째 follow-up 체결 시도는 막혔으므로 on_fill 호출도 1+cap회를
        # 넘지 않는다.

    async def test_on_step_signals_not_capped(self, store, monkeypatch):
        """(f) 회귀 락: on_step 신호는 cap 미적용 → cap 초과해도 전부 체결(#2073).

        cap(_MAX_FOLLOW_UP_FILLS_PER_STEP)을 작게(3) monkeypatch한 뒤, on_step이
        cap을 초과하는 5개의 buy 신호를 반환한다. on_fill은 follow-up을 발행하지
        않는다(기본 []). cap이 follow-up 연쇄에만 적용되므로 on_step 신호 5개는
        모두 체결되어야 한다(cap=3에서 truncate되면 안 됨).

        이 테스트는 "cap이 최초 on_step 신호 체결부터 적용·카운트하던" 회귀
        (전략이 한 step에 cap 초과 on_step 신호를 정상 반환하면 follow-up이
        없어도 조용히 truncate)를 lock한다.
        """
        import ante.backtest.executor as executor_mod

        monkeypatch.setattr(executor_mod, "_MAX_FOLLOW_UP_FILLS_PER_STEP", 3)

        provider = self._make_provider(store)

        class ManyOnStepSignals(Strategy):
            meta = StrategyMeta(
                name="many_on_step_signals", version="1.0", description="t"
            )

            def __init__(self, ctx: Any) -> None:
                super().__init__(ctx)
                self._entered = False

            async def on_step(self, context: dict[str, Any]) -> list[Signal]:
                if not self._entered:
                    self._entered = True
                    # cap(=3)을 초과하는 5개의 on_step buy 신호.
                    return [
                        Signal(symbol="005930", side="buy", quantity=1)
                        for _ in range(5)
                    ]
                return []

            # on_fill은 follow-up을 발행하지 않는다(base 기본 []).

        executor = BacktestExecutor(
            strategy_cls=ManyOnStepSignals,
            data_provider=provider,
            initial_balance=1_000_000,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()

        # on_step 신호 5개는 cap(=3)과 무관하게 모두 체결된다(cap은 follow-up
        # 전용). 회귀 시(cap이 on_step에도 적용) trades 길이가 3으로 truncate된다.
        assert len(result.trades) == 5
        assert all(t.side == "buy" for t in result.trades)
        # 5주 누적 포지션.
        assert executor._positions["005930"]["quantity"] == 5
