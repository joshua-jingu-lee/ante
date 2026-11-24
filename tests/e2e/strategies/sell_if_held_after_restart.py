"""e2e 재시작 전략: 프로세스마다 한 번만 움직인다 — 보유가 있으면 팔고, 없으면 산다."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

SYMBOL = "000001"
BUY_PRICE = 70000
SELL_PRICE = 71000


class SellIfHeldAfterRestart(Strategy):
    """재시작 뒤 첫 스텝이 보유를 보면 매도, 보지 못하면 다시 매수한다."""

    meta = StrategyMeta(
        name="e2e_sell_if_held_after_restart",
        version="0.1.0",
        description="e2e sell if held after restart",
        author_name="agent",
        author_id="agent",
        symbols=[SYMBOL],
        timeframe="1d",
        exchange="TEST",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """이 프로세스에서 아직 움직이지 않았을 때만 보유에 따라 사거나 판다."""
        if getattr(self, "_acted", False):
            return []
        self._acted = True
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
        return [
            Signal(
                symbol=SYMBOL,
                side="buy",
                quantity=1,
                order_type="limit",
                price=BUY_PRICE,
            )
        ]
