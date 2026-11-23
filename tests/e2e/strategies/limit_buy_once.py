"""e2e 매수 전략: 지정가로 한 번만 사고 그 뒤로는 아무것도 하지 않는다."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

SYMBOL = "000001"
BUY_PRICE = 70000
BUY_QUANTITY = 1


class LimitBuyOnce(Strategy):
    """첫 스텝에 지정가 매수 신호를 한 번 내고, 그 뒤로는 신호를 내지 않는다."""

    meta = StrategyMeta(
        name="e2e_limit_buy_once",
        version="0.1.0",
        description="e2e limit buy once",
        author_name="agent",
        author_id="agent",
        symbols=[SYMBOL],
        timeframe="1d",
        exchange="TEST",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """아직 신호를 낸 적이 없으면 한 주를 지정가로 산다."""
        if getattr(self, "_sent", False):
            return []
        self._sent = True
        return [
            Signal(
                symbol=SYMBOL,
                side="buy",
                quantity=BUY_QUANTITY,
                order_type="limit",
                price=BUY_PRICE,
            )
        ]
