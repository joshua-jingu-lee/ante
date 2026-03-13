"""Backtest 결과 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class BacktestTrade:
    """백테스트 거래 기록."""

    timestamp: datetime
    symbol: str
    side: str  # "buy" | "sell"
    quantity: float
    price: float
    commission: float
    slippage: float
    reason: str = ""
    exchange: str = "KRX"


@dataclass
class BacktestResult:
    """백테스트 결과."""

    strategy_name: str
    strategy_version: str
    start_date: str
    end_date: str
    initial_balance: float
    final_balance: float
    total_return: float
    trades: list[BacktestTrade] = field(default_factory=list)
    equity_curve: list[dict] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        """결과를 딕셔너리로 변환."""
        return {
            "strategy": f"{self.strategy_name}_v{self.strategy_version}",
            "period": f"{self.start_date} ~ {self.end_date}",
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "total_return_pct": round(self.total_return, 2),
            "total_trades": len(self.trades),
            "metrics": self.metrics,
            "trades": [
                {
                    "timestamp": str(t.timestamp),
                    "symbol": t.symbol,
                    "side": t.side,
                    "quantity": t.quantity,
                    "price": t.price,
                    "commission": t.commission,
                    "slippage": t.slippage,
                    "reason": t.reason,
                }
                for t in self.trades
            ],
        }
