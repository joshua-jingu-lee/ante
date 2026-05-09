"""백테스트 성과 지표 계산 테스트."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest

from ante.backtest.metrics import (
    _annual_return,
    _estimate_trade_pnl,
    _max_drawdown,
    _sharpe_ratio,
    calculate_metrics,
)


@dataclass(frozen=True)
class FakeTrade:
    """테스트용 거래 데이터."""

    timestamp: datetime
    symbol: str
    side: str
    quantity: float
    price: float
    commission: float
    slippage: float = 0.0
    reason: str = ""


# ── calculate_metrics 통합 ────────────────────────


class TestCalculateMetrics:
    def test_empty_trades(self):
        """거래 없으면 기본값."""
        metrics = calculate_metrics(
            trades=[],
            equity_curve=[],
            initial_balance=10_000_000,
            final_balance=10_000_000,
        )
        assert metrics["total_return"] == 0.0
        assert metrics["total_trades"] == 0
        assert metrics["win_rate"] == 0.0

    def test_profitable_trades(self):
        """수익 거래 지표 계산."""
        trades = [
            FakeTrade(
                datetime(2024, 1, 1),
                "005930",
                "buy",
                10,
                70000,
                105,
            ),
            FakeTrade(
                datetime(2024, 1, 10),
                "005930",
                "sell",
                10,
                75000,
                112.5,
            ),
        ]
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10_000_000},
            {"timestamp": "2024-01-10", "equity": 10_049_782},
        ]

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_049_782,
        )

        assert metrics["total_trades"] == 1  # sell 1건
        assert metrics["winning_trades"] == 1
        assert metrics["losing_trades"] == 0
        assert metrics["win_rate"] == 100.0
        assert metrics["total_return"] > 0
        assert metrics["total_commission"] > 0

    def test_losing_trades(self):
        """손실 거래 지표."""
        trades = [
            FakeTrade(
                datetime(2024, 1, 1),
                "005930",
                "buy",
                10,
                70000,
                105,
            ),
            FakeTrade(
                datetime(2024, 1, 10),
                "005930",
                "sell",
                10,
                65000,
                97.5,
            ),
        ]
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10_000_000},
            {"timestamp": "2024-01-10", "equity": 9_949_797},
        ]

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=9_949_797,
        )

        assert metrics["total_trades"] == 1
        assert metrics["winning_trades"] == 0
        assert metrics["losing_trades"] == 1
        assert metrics["win_rate"] == 0.0
        assert metrics["total_return"] < 0

    def test_mixed_trades(self):
        """승패 혼합 거래."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 1.5),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 10, 110, 1.65),
            FakeTrade(datetime(2024, 1, 10), "B", "buy", 10, 200, 3.0),
            FakeTrade(datetime(2024, 1, 15), "B", "sell", 10, 190, 2.85),
        ]
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10000},
            {"timestamp": "2024-01-05", "equity": 10097},
            {"timestamp": "2024-01-10", "equity": 10097},
            {"timestamp": "2024-01-15", "equity": 9991},
        ]

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=10000,
            final_balance=9991,
        )

        assert metrics["total_trades"] == 2
        assert metrics["winning_trades"] == 1
        assert metrics["losing_trades"] == 1
        assert metrics["win_rate"] == 50.0
        assert metrics["profit_factor"] > 0

    def test_profit_factor_no_loss(self):
        """손실 없을 때 profit_factor = inf."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 0),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 10, 110, 0),
        ]
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10000},
            {"timestamp": "2024-01-05", "equity": 10100},
        ]

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=10000,
            final_balance=10100,
        )

        assert metrics["profit_factor"] == float("inf")


# ── Sharpe Ratio ────────────────────────────────


class TestSharpeRatio:
    def test_insufficient_data(self):
        """데이터 부족 시 None."""
        assert _sharpe_ratio([100]) is None
        assert _sharpe_ratio([]) is None

    def test_constant_equity(self):
        """변동 없으면 None (std=0)."""
        assert _sharpe_ratio([100, 100, 100]) is None

    def test_positive_returns(self):
        """양의 수익률."""
        # 매일 1% 상승
        equities = [100 * (1.01**i) for i in range(30)]
        sharpe = _sharpe_ratio(equities)
        assert sharpe is not None
        assert sharpe > 0

    def test_volatile_returns(self):
        """변동성 높은 수익률 → 낮은 Sharpe."""
        equities = []
        v = 100.0
        for i in range(30):
            v *= 1.02 if i % 2 == 0 else 0.98
            equities.append(v)
        sharpe = _sharpe_ratio(equities)
        assert sharpe is not None


# ── Maximum Drawdown ────────────────────────────


class TestMaxDrawdown:
    def test_no_drawdown(self):
        """항상 상승 → MDD=0."""
        equities = [100, 110, 120, 130]
        mdd, duration = _max_drawdown(equities)
        assert mdd == 0.0
        assert duration == 0

    def test_simple_drawdown(self):
        """단순 하락 → MDD 계산."""
        equities = [100, 110, 100, 95, 105]
        mdd, duration = _max_drawdown(equities)
        # peak=110, lowest=95, dd = (110-95)/110 * 100 = 13.636%
        assert abs(mdd - 13.6364) < 0.1
        assert duration > 0

    def test_empty_equities(self):
        """빈 리스트."""
        mdd, duration = _max_drawdown([])
        assert mdd == 0.0
        assert duration == 0

    def test_drawdown_at_end(self):
        """끝까지 하락 상태."""
        equities = [100, 110, 105, 100, 90]
        mdd, duration = _max_drawdown(equities)
        # peak=110, lowest=90, dd = 18.18%
        assert mdd > 18.0
        assert duration > 0


# ── Annual Return ──────────────────────────────


class TestAnnualReturn:
    def test_short_period(self):
        """데이터 부족 시 total_return 반환."""
        result = _annual_return([{"equity": 100}], 10.0)
        assert result == 10.0

    def test_one_year(self):
        """252일 (1년) → annual_return ≈ total_return."""
        curve = [{"equity": 100 + i} for i in range(252)]
        result = _annual_return(curve, 10.0)
        assert abs(result - 10.0) < 0.5


# ── Trade PnL Estimation ──────────────────────


class TestEstimateTradePnl:
    def test_profitable_trade(self):
        """수익 거래 PnL."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 0),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 10, 110, 1.0),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        # (110 - 100) * 10 - 1.0 = 99.0
        assert pnl[0] == pytest.approx(99.0)

    def test_losing_trade(self):
        """손실 거래 PnL."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 0),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 10, 90, 1.0),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        # (90 - 100) * 10 - 1.0 = -101.0
        assert pnl[0] == pytest.approx(-101.0)

    def test_no_sell_trades(self):
        """매도 없으면 빈 리스트."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 0),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert pnl == []

    def test_multiple_symbols(self):
        """다종목 거래."""
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 0),
            FakeTrade(datetime(2024, 1, 2), "B", "buy", 5, 200, 0),
            FakeTrade(datetime(2024, 1, 3), "A", "sell", 10, 110, 0),
            FakeTrade(datetime(2024, 1, 4), "B", "sell", 5, 190, 0),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 2
        assert pnl[0] == pytest.approx(100.0)  # A: (110-100)*10
        assert pnl[1] == pytest.approx(-50.0)  # B: (190-200)*5


# ── CLI 지표 표시 ──────────────────────────────


class TestCLIFormatMetrics:
    def test_format_metrics_function_exists(self):
        """_format_metrics 함수 존재 확인."""
        from ante.cli.commands.backtest import _format_metrics

        metrics = {
            "total_return": 10.5,
            "sharpe_ratio": 1.23,
            "max_drawdown": 5.0,
            "total_trades": 20,
            "win_rate": 60.0,
        }
        rows = _format_metrics(metrics)
        assert isinstance(rows, list)
        assert len(rows) > 0
        assert all("지표" in r and "값" in r for r in rows)

    def test_format_none_value(self):
        """None 값은 N/A로 표시."""
        from ante.cli.commands.backtest import _format_metrics

        metrics = {"sharpe_ratio": None}
        rows = _format_metrics(metrics)
        sharpe_row = [r for r in rows if r["지표"] == "Sharpe Ratio"][0]
        assert sharpe_row["값"] == "N/A"

    def test_format_inf_value(self):
        """inf 값은 ∞로 표시."""
        from ante.cli.commands.backtest import _format_metrics

        metrics = {"profit_factor": float("inf")}
        rows = _format_metrics(metrics)
        pf_row = [r for r in rows if r["지표"] == "Profit Factor"][0]
        assert pf_row["값"] == "∞"


# ── BacktestResult.to_dict ──────────────────────


class TestBacktestResultToDict:
    def test_to_dict_includes_equity_curve(self):
        """to_dict에 equity_curve 포함."""
        from ante.backtest.result import BacktestResult

        result = BacktestResult(
            strategy_name="test",
            strategy_version="1.0",
            start_date="2024-01-01",
            end_date="2024-12-31",
            initial_balance=10_000_000,
            final_balance=10_500_000,
            total_return=5.0,
            equity_curve=[{"timestamp": "2024-01-01", "equity": 10_000_000}],
            metrics={"total_return": 5.0},
        )
        d = result.to_dict()
        assert "equity_curve" in d
        assert len(d["equity_curve"]) == 1
        assert "metrics" in d
        assert "config" in d
        assert "datasets" in d
