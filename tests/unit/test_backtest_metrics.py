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
from ante.backtest.result import resample_equity_curve_daily


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

    def test_buy_commission_only_classified_as_loss(self):
        """이슈 repro(#1990): 매수 수수료만으로 손실인 거래가 losing으로 분류.

        buy(price=100, qty=1, commission=10) + sell(price=100, qty=1,
        commission=0) → pnl=-10 → losing_trades=1, winning_trades=0,
        win_rate=0, avg_loss≈10.
        (기존: 매수 수수료 미반영 pnl=0 → winning/losing 어느 쪽도 아님)
        """
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 1, 100, 10),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 1, 100, 0),
        ]
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10000},
            {"timestamp": "2024-01-05", "equity": 9990},
        ]

        metrics = calculate_metrics(
            trades=trades,
            equity_curve=equity_curve,
            initial_balance=10000,
            final_balance=9990,
        )

        assert metrics["total_trades"] == 1
        assert metrics["winning_trades"] == 0
        assert metrics["losing_trades"] == 1
        assert metrics["win_rate"] == 0.0
        assert metrics["avg_loss"] == pytest.approx(10.0)

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


# ── Intraday 일별 리샘플 (#2013) ──────────────────
#
# annual_return / Sharpe는 "일(day)" 단위가 전제이므로 calculate_metrics가
# equity_curve를 한 번 일별 리샘플(threshold=0)한 뒤 헬퍼에 넘긴다.
# intraday(하루 여러 bar) 백테스트에서 bar 개수를 일수로 오인하던 왜곡을
# 수정하면서, 1d(날짜당 1봉) 백테스트는 결과가 불변(backward compat)이어야 한다.


class TestCalculateMetricsDailyResample:
    def test_intraday_annual_return_uses_distinct_dates(self):
        """intraday(5m, 2일치) → annual_return이 bar 수가 아닌 distinct 날짜 수 기준."""
        # 하루 여러 bar, 2 캘린더 날짜
        equity_curve = [
            {"timestamp": "2024-01-01T09:00:00", "equity": 10_000_000},
            {"timestamp": "2024-01-01T09:05:00", "equity": 10_010_000},
            {"timestamp": "2024-01-01T15:30:00", "equity": 10_100_000},
            {"timestamp": "2024-01-02T09:00:00", "equity": 10_120_000},
            {"timestamp": "2024-01-02T09:05:00", "equity": 10_150_000},
            {"timestamp": "2024-01-02T15:30:00", "equity": 10_200_000},
        ]
        metrics = calculate_metrics(
            trades=[],
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_200_000,
        )
        # total_return = 2.0% → days=2(distinct 날짜) 기준 연환산.
        # bar 수(6)가 아니라 날짜 수(2)를 일수로 사용해야 한다.
        # (1 + 0.02) ** (252/2) - 1) * 100 ≈ 1112.3322
        assert metrics["annual_return"] == pytest.approx(1112.3322, abs=1e-3)
        # bar 수(6) 기준이라면 ~129.7244 → 그 값이 아님을 확인.
        assert metrics["annual_return"] != pytest.approx(129.7244, abs=1e-3)

    def test_intraday_sharpe_uses_daily_returns(self):
        """intraday(3일치) → Sharpe가 bar-간이 아닌 일간 수익률 기준."""
        # 하루 여러 bar, 3 캘린더 날짜 (일별 마지막: 10.1M, 10.2M, 10.3M)
        equity_curve = [
            {"timestamp": "2024-01-01T09:00:00", "equity": 10_000_000},
            {"timestamp": "2024-01-01T15:30:00", "equity": 10_100_000},
            {"timestamp": "2024-01-02T09:00:00", "equity": 10_050_000},
            {"timestamp": "2024-01-02T15:30:00", "equity": 10_200_000},
            {"timestamp": "2024-01-03T09:00:00", "equity": 10_180_000},
            {"timestamp": "2024-01-03T15:30:00", "equity": 10_300_000},
        ]
        metrics = calculate_metrics(
            trades=[],
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_300_000,
        )
        # 일별 종가 [10.1M, 10.2M, 10.3M] 기준 일간 수익률로 계산.
        daily_equities = [10_100_000, 10_200_000, 10_300_000]
        expected = _sharpe_ratio(daily_equities)
        assert metrics["sharpe_ratio"] == pytest.approx(round(expected, 4))
        # bar-간 수익률(6포인트) 기준이라면 ~10.7058 → 그 값이 아님.
        assert metrics["sharpe_ratio"] != pytest.approx(10.7058, abs=1e-3)

    def test_one_day_backward_compat(self):
        """1d(날짜당 1봉) → annual_return/sharpe가 리샘플 전과 동일(회귀 락)."""
        equity_curve = [
            {"timestamp": "2024-01-01", "equity": 10_000_000},
            {"timestamp": "2024-01-02", "equity": 10_050_000},
            {"timestamp": "2024-01-03", "equity": 10_030_000},
            {"timestamp": "2024-01-04", "equity": 10_200_000},
        ]
        total_return = (10_200_000 - 10_000_000) / 10_000_000 * 100

        metrics = calculate_metrics(
            trades=[],
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_200_000,
        )
        # 날짜당 1봉이므로 리샘플 결과 == 원본 → 헬퍼 직접 호출과 동일해야 함.
        expected_annual = round(_annual_return(equity_curve, total_return), 4)
        expected_sharpe = _sharpe_ratio([e["equity"] for e in equity_curve])
        assert metrics["annual_return"] == expected_annual
        assert metrics["sharpe_ratio"] == pytest.approx(round(expected_sharpe, 4))

    def test_single_date_intraday_sharpe_none(self):
        """단일 날짜 intraday → daily 1포인트 → sharpe None(크래시 없음)."""
        equity_curve = [
            {"timestamp": "2024-01-01T09:00:00", "equity": 10_000_000},
            {"timestamp": "2024-01-01T09:05:00", "equity": 10_010_000},
            {"timestamp": "2024-01-01T15:30:00", "equity": 10_100_000},
        ]
        metrics = calculate_metrics(
            trades=[],
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_100_000,
        )
        assert metrics["sharpe_ratio"] is None

    def test_same_date_points_fold_to_last(self):
        """같은 날짜의 여러 포인트가 마지막 값으로 접힌다(chronological fold)."""
        curve = [
            {"timestamp": "2024-01-01T09:00", "equity": 100},
            {"timestamp": "2024-01-01T15:00", "equity": 200},
            {"timestamp": "2024-01-02T09:00", "equity": 300},
            {"timestamp": "2024-01-02T15:00", "equity": 400},
        ]
        daily = resample_equity_curve_daily(curve, threshold=0)
        # 날짜별 마지막 포인트만, 시간순 유지
        assert [p["equity"] for p in daily] == [200, 400]

    def test_max_drawdown_uses_raw_bars(self):
        """max_drawdown은 raw 봉 기준 — intraday 낙폭이 일별 리샘플로 약화되지 않음."""
        # intraday 10% 낙폭 후 종가에서 회복 → 일별 리샘플하면 MDD=0이 되어버림.
        equity_curve = [
            {"timestamp": "2024-01-01T09:00:00", "equity": 10_000_000},
            {"timestamp": "2024-01-01T12:00:00", "equity": 9_000_000},
            {"timestamp": "2024-01-01T15:30:00", "equity": 10_050_000},
            {"timestamp": "2024-01-02T15:30:00", "equity": 10_100_000},
        ]
        metrics = calculate_metrics(
            trades=[],
            equity_curve=equity_curve,
            initial_balance=10_000_000,
            final_balance=10_100_000,
        )
        # raw 봉 peak=10.0M, trough=9.0M → MDD=10% (일별 리샘플이면 0%가 됨)
        assert metrics["max_drawdown"] == pytest.approx(10.0)


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

    def test_buy_commission_only_round_trip_is_loss(self):
        """이슈 repro(#1990): 매수 수수료 때문에만 손실인 round-trip.

        buy(price=100, qty=1, commission=10) + sell(price=100, qty=1,
        commission=0) → 매수 수수료가 원가에 포함되어 pnl=-10.0.
        (기존: 매수 수수료 미반영으로 pnl=0.0 → 손익 어느 쪽도 아님)
        """
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 1, 100, 10),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 1, 100, 0),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        # avg_cost = (100*1 + 10) / 1 = 110 → (100 - 110)*1 - 0 = -10
        assert pnl[0] == pytest.approx(-10.0)

    def test_both_buy_and_sell_commission(self):
        """매수·매도 수수료 모두 반영.

        buy(commission=5) + sell(commission=5), 동일가 → pnl=-10.
        """
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 1, 100, 5),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 1, 100, 5),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        # avg_cost = (100 + 5) / 1 = 105 → (100 - 105)*1 - 5 = -10
        assert pnl[0] == pytest.approx(-10.0)

    def test_profitable_trade_with_buy_commission_in_cost(self):
        """이익 거래 — 매수 수수료가 avg_cost에 amortize.

        buy(price=100, qty=1, commission=1) + sell(price=120, qty=1,
        commission=1) → avg_cost=101 → (120-101)*1 - 1 = 18.
        """
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 1, 100, 1),
            FakeTrade(datetime(2024, 1, 5), "A", "sell", 1, 120, 1),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        assert pnl[0] == pytest.approx(18.0)

    def test_partial_sell_amortizes_buy_commission(self):
        """다중 매수 후 부분 매도 — 매수 수수료가 수량에 일관되게 amortize.

        buy1(price=100, qty=10, commission=20) +
        buy2(price=120, qty=10, commission=20) →
          total_cost = (100*10+20) + (120*10+20) = 1020 + 1220 = 2240
          quantity   = 20 → avg_cost = 112.0
        sell(price=130, qty=5, commission=2) →
          pnl = (130 - 112)*5 - 2 = 88.0
        남은 포지션: quantity=15, total_cost = 2240 - 112*5 = 1680
          (avg_cost가 여전히 112.0으로 일관 — 매수 수수료 포함 유지)
        """
        trades = [
            FakeTrade(datetime(2024, 1, 1), "A", "buy", 10, 100, 20),
            FakeTrade(datetime(2024, 1, 2), "A", "buy", 10, 120, 20),
            FakeTrade(datetime(2024, 1, 3), "A", "sell", 5, 130, 2),
        ]
        pnl = _estimate_trade_pnl(trades)
        assert len(pnl) == 1
        assert pnl[0] == pytest.approx(88.0)


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
