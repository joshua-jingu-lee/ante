"""백테스트 성과 지표 계산 유틸리티."""

from __future__ import annotations

import math
from typing import Any


def calculate_metrics(
    trades: list[Any],
    equity_curve: list[dict],
    initial_balance: float,
    final_balance: float,
) -> dict[str, Any]:
    """백테스트 결과에서 상세 성과 지표를 계산한다.

    Args:
        trades: BacktestTrade 리스트
        equity_curve: [{"timestamp": str, "equity": float}, ...] 리스트
        initial_balance: 초기 자금
        final_balance: 최종 자산

    Returns:
        성과 지표 dict
    """
    metrics: dict[str, Any] = {}

    # ── 수익률 ────────────────────────────────────────
    total_return = (
        (final_balance - initial_balance) / initial_balance * 100
        if initial_balance > 0
        else 0.0
    )
    metrics["total_return"] = round(total_return, 4)

    # 연환산 수익률
    metrics["annual_return"] = round(_annual_return(equity_curve, total_return), 4)

    # ── Equity Curve 기반 지표 ────────────────────────
    equities = [e["equity"] for e in equity_curve] if equity_curve else []

    sharpe = _sharpe_ratio(equities)
    metrics["sharpe_ratio"] = round(sharpe, 4) if sharpe is not None else None

    mdd, mdd_duration = _max_drawdown(equities)
    metrics["max_drawdown"] = round(mdd, 4)
    metrics["max_drawdown_duration"] = mdd_duration

    # ── 거래 기반 지표 ────────────────────────────────
    sell_trades = [t for t in trades if t.side == "sell"]

    # 매도 거래별 손익 추정 (간이: 동일 종목 buy-sell 매칭)
    pnl_list = _estimate_trade_pnl(trades)

    winning = [p for p in pnl_list if p > 0]
    losing = [p for p in pnl_list if p < 0]

    total_trades = len(sell_trades)
    winning_trades = len(winning)
    losing_trades = len(losing)

    total_profit = sum(winning) if winning else 0.0
    total_loss = abs(sum(losing)) if losing else 0.0
    total_commission = sum(t.commission for t in trades)

    metrics["total_trades"] = total_trades
    metrics["winning_trades"] = winning_trades
    metrics["losing_trades"] = losing_trades
    metrics["win_rate"] = (
        round(winning_trades / total_trades * 100, 2) if total_trades > 0 else 0.0
    )
    metrics["profit_factor"] = (
        round(total_profit / total_loss, 4)
        if total_loss > 0
        else float("inf")
        if total_profit > 0
        else 0.0
    )
    metrics["avg_profit"] = (
        round(total_profit / winning_trades, 2) if winning_trades > 0 else 0.0
    )
    metrics["avg_loss"] = (
        round(total_loss / losing_trades, 2) if losing_trades > 0 else 0.0
    )
    metrics["total_commission"] = round(total_commission, 2)

    return metrics


def _annual_return(equity_curve: list[dict], total_return: float) -> float:
    """연환산 수익률 계산."""
    if len(equity_curve) < 2:
        return total_return

    days = len(equity_curve)
    if days <= 0:
        return total_return

    # (1 + r) ^ (252/days) - 1
    r = total_return / 100
    if r <= -1:
        return -100.0

    annual = ((1 + r) ** (252 / days) - 1) * 100
    return annual


def _sharpe_ratio(equities: list[float]) -> float | None:
    """Sharpe ratio (일간 수익률 기준, 무위험 이자율 0)."""
    if len(equities) < 2:
        return None

    daily_returns: list[float] = []
    for i in range(1, len(equities)):
        if equities[i - 1] > 0:
            daily_returns.append((equities[i] - equities[i - 1]) / equities[i - 1])

    if len(daily_returns) < 2:
        return None

    mean_r = sum(daily_returns) / len(daily_returns)
    variance = sum((r - mean_r) ** 2 for r in daily_returns) / (len(daily_returns) - 1)
    std_r = math.sqrt(variance)

    if std_r == 0:
        return None

    return (mean_r / std_r) * math.sqrt(252)


def _max_drawdown(
    equities: list[float],
) -> tuple[float, int]:
    """최대 낙폭(%) 및 MDD 지속 기간(일).

    Returns:
        (max_drawdown_pct, max_drawdown_duration_days)
    """
    if not equities:
        return 0.0, 0

    peak = equities[0]
    max_dd = 0.0
    max_dd_duration = 0
    current_dd_start = 0
    in_drawdown = False

    for i, equity in enumerate(equities):
        if equity >= peak:
            if in_drawdown:
                duration = i - current_dd_start
                if duration > max_dd_duration:
                    max_dd_duration = duration
                in_drawdown = False
            peak = equity
        else:
            if not in_drawdown:
                current_dd_start = i
                in_drawdown = True
            dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

    # 끝까지 drawdown 상태인 경우
    if in_drawdown:
        duration = len(equities) - current_dd_start
        if duration > max_dd_duration:
            max_dd_duration = duration

    return max_dd, max_dd_duration


def _estimate_trade_pnl(trades: list[Any]) -> list[float]:
    """거래 리스트에서 매도별 손익을 추정.

    FIFO 방식: 종목별 buy 평균 단가 → sell 시 손익 계산.
    """
    # 종목별 buy 평균 단가 추적
    positions: dict[str, dict[str, float]] = {}
    pnl_list: list[float] = []

    for trade in trades:
        symbol = trade.symbol
        if trade.side == "buy":
            if symbol not in positions:
                positions[symbol] = {"quantity": 0, "total_cost": 0.0}
            pos = positions[symbol]
            pos["quantity"] += trade.quantity
            pos["total_cost"] += trade.price * trade.quantity
        elif trade.side == "sell":
            pos = positions.get(symbol)
            if pos and pos["quantity"] > 0:
                avg_cost = pos["total_cost"] / pos["quantity"]
                pnl = (trade.price - avg_cost) * trade.quantity
                pnl -= trade.commission
                pnl_list.append(pnl)

                sell_qty = min(trade.quantity, pos["quantity"])
                pos["total_cost"] -= avg_cost * sell_qty
                pos["quantity"] -= sell_qty
                if pos["quantity"] <= 0:
                    del positions[symbol]

    return pnl_list
