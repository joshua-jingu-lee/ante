"""e2e 시장가 매수 전략: 첫 스텝에 시장가로 두 주를 사고 그 뒤로는 사지 않는다."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

SYMBOL = "000001"


class MarketBuyTwo(Strategy):
    """한 번만 두 주의 시장가 매수 시그널을 낸다."""

    meta = StrategyMeta(
        name="e2e_market_buy_two",
        version="0.1.0",
        description="e2e market buy two",
        author_name="agent",
        author_id="agent",
        symbols=[SYMBOL],
        timeframe="1d",
        exchange="TEST",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """아직 사지 않았으면 시장가로 두 주를 산다."""
        if getattr(self, "_bought", False):
            return []
        self._bought = True
        return [Signal(symbol=SYMBOL, side="buy", quantity=2, order_type="market")]
