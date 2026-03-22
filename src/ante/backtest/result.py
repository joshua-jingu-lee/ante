"""Backtest 결과 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime

from ante.backtest.config import BacktestConfig, DatasetInfo


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
    config: BacktestConfig = field(default_factory=BacktestConfig)
    datasets: list[DatasetInfo] = field(default_factory=list)

    def to_dict(self, *, resample_equity: bool = False) -> dict:
        """결과를 딕셔너리로 변환.

        Args:
            resample_equity: True이면 equity_curve를 일봉 기준으로
                리샘플링한다. 포인트 수가 ``_RESAMPLE_THRESHOLD`` 이하이면
                리샘플링을 생략한다.
        """
        curve = self.equity_curve
        if resample_equity:
            curve = resample_equity_curve_daily(curve)
        return {
            "strategy": f"{self.strategy_name}_v{self.strategy_version}",
            "period": f"{self.start_date} ~ {self.end_date}",
            "initial_balance": self.initial_balance,
            "final_balance": self.final_balance,
            "total_return_pct": round(self.total_return, 2),
            "total_trades": len(self.trades),
            "metrics": self.metrics,
            "equity_curve": curve,
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
            "config": asdict(self.config),
            "datasets": [asdict(d) for d in self.datasets],
        }


# 포인트 수가 이 값 이하이면 리샘플링을 생략한다 (일봉 2년치 ~ 500).
_RESAMPLE_THRESHOLD = 500


def resample_equity_curve_daily(
    curve: list[dict],
    *,
    threshold: int = _RESAMPLE_THRESHOLD,
) -> list[dict]:
    """equity_curve를 일봉 기준으로 리샘플링한다.

    동일 날짜에 여러 포인트가 있으면 마지막 포인트(종가 시점)만 남긴다.
    포인트 수가 *threshold* 이하이면 원본을 그대로 반환한다.

    ``timestamp`` 키가 있으면 앞 10자(YYYY-MM-DD)를 날짜로 사용하고,
    ``date`` 키가 있으면 그대로 사용한다.
    """
    if len(curve) <= threshold:
        return curve

    # 동일 날짜의 마지막 포인트를 대표값으로 선택
    daily: dict[str, dict] = {}
    for point in curve:
        date_key = _extract_date(point)
        if date_key:
            daily[date_key] = point

    return list(daily.values())


def _extract_date(point: dict) -> str:
    """포인트에서 날짜 문자열(YYYY-MM-DD)을 추출."""
    if "date" in point:
        return str(point["date"])[:10]
    ts = point.get("timestamp", "")
    return str(ts)[:10] if ts else ""
