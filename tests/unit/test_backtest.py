"""Backtest Engine 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import polars as pl
import pytest

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
    timestamps = pl.datetime_range(
        datetime(2026, 1, 2, 9, 0, tzinfo=UTC),
        datetime(2026, 1, 2 + n - 1, 9, 0, tzinfo=UTC),
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

    async def test_get_indicator_returns_data(self, data_provider):
        for _ in range(5):
            data_provider.advance()
        df = await data_provider.get_indicator("005930", "sma", {"period": 5})
        assert len(df) > 0

    async def test_loaded_datasets_empty_on_init(self, loaded_store):
        """초기 상태에서 loaded_datasets는 빈 리스트."""
        provider = BacktestDataProvider(
            store=loaded_store, start_date="2026-01-01", end_date="2026-12-31"
        )
        assert provider.loaded_datasets == []

    async def test_loaded_datasets_after_single_load(self, loaded_store):
        """load() 1회 호출 후 DatasetInfo 1건 기록."""
        from ante.backtest.config import DatasetInfo

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
            commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
        # 수수료/슬리피지=0이고 avg_price 평가이므로 equity는 유지
        # balance(현금)는 감소했는지 확인
        assert result.equity_curve[0]["balance"] < result.initial_balance

    async def test_buy_sell(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuySellStrategy,
            data_provider=data_provider,
            initial_balance=10_000_000,
            commission_rate=0.0,
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
            commission_rate=0.01,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert result.trades[0].commission > 0

    async def test_slippage_applied(self, data_provider):
        data_provider.reset()
        executor = BacktestExecutor(
            strategy_cls=BuyAndHoldStrategy,
            data_provider=data_provider,
            commission_rate=0.0,
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
            commission_rate=0.0,
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
            commission_rate=0.0,
            slippage_rate=0.0,
        )
        result = await executor.run()
        assert len(result.trades) == 2
        # 매도 거래는 실제로 실행됨 (보유량 5주만 매도)


# ── BacktestService 테스트 ─────────────────────────


class TestBacktestService:
    def test_validate_config_missing_keys(self):
        service = BacktestService()
        with pytest.raises(BacktestConfigError, match="strategy_path"):
            service._validate_config({"start_date": "2026-01-01"})

    def test_validate_config_valid(self):
        service = BacktestService()
        service._validate_config(
            {
                "strategy_path": "test.py",
                "start_date": "2026-01-01",
                "end_date": "2026-06-30",
            }
        )


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
        from ante.backtest.config import BacktestConfig

        cfg = BacktestConfig(
            strategy_path="strategies/ma_cross.py",
            symbols=["005930"],
            timeframe="1d",
            start_date="2026-01-01",
            end_date="2026-06-30",
            initial_balance=10_000_000.0,
            commission_rate=0.00015,
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
        from ante.backtest.config import DatasetInfo

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
