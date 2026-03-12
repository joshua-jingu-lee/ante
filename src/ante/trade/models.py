"""Trade 모듈 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class TradeType(StrEnum):
    """거래 유형."""

    BUY = "buy"
    SELL = "sell"


class TradeStatus(StrEnum):
    """거래 상태."""

    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"
    ADJUSTED = "adjusted"


@dataclass
class TradeRecord:
    """개별 거래 기록."""

    trade_id: UUID
    bot_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    status: TradeStatus
    order_type: str = ""
    reason: str = ""
    commission: float = 0.0
    timestamp: datetime | None = None
    order_id: str | None = None


@dataclass
class PositionSnapshot:
    """특정 시점의 포지션 상태."""

    bot_id: str
    symbol: str
    quantity: float
    avg_entry_price: float
    realized_pnl: float = 0.0
    updated_at: str = ""


@dataclass
class PerformanceMetrics:
    """봇/전략 성과 지표."""

    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    total_commission: float = 0.0
    net_pnl: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_amount: float = 0.0
    sharpe_ratio: float | None = None
    first_trade_at: datetime | None = None
    last_trade_at: datetime | None = None
    active_days: int = 0
