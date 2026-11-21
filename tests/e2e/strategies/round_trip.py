"""e2e 왕복 전략: 지정가로 한 주 사고, 보유가 생기면 지정가로 판다."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

SYMBOL = "000001"
BUY_PRICE = 70000
SELL_PRICE = 71000


class RoundTrip(Strategy):
    """보유 상태로 스텝을 정한다: 산 적 없으면 매수, 보유가 있으면 매도."""

    meta = StrategyMeta(
        name="e2e_round_trip",
        version="0.1.0",
        description="e2e round trip",
        author_name="agent",
        author_id="agent",
        symbols=[SYMBOL],
        timeframe="1d",
        exchange="TEST",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """보유가 있으면 팔고, 아직 사지 않았으면 산다."""
        held = context["portfolio"].get(SYMBOL, {}).get("quantity", 0)
        if held > 0:
            return [
                Signal(
                    symbol=SYMBOL,
                    side="sell",
                    quantity=1,
                    order_type="limit",
                    price=SELL_PRICE,
                )
            ]
        if not getattr(self, "_bought", False):
            self._bought = True
            return [
                Signal(
                    symbol=SYMBOL,
                    side="buy",
                    quantity=1,
                    order_type="limit",
                    price=BUY_PRICE,
                )
            ]
        return []
