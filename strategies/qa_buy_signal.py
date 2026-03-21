"""QA 테스트용 매수 시그널 전략.

항상 BUY 시그널을 반환하여 매수 시그널 처리 파이프라인을 검증한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaBuySignalStrategy(Strategy):
    """항상 매수 시그널을 반환하는 QA 전략."""

    meta = StrategyMeta(
        name="qa_buy_signal",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 — 항상 BUY 시그널 반환",
        author="qa",
        symbols=["005930"],
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """항상 매수 시그널 1건을 반환한다."""
        return [
            Signal(
                symbol="005930",
                side="buy",
                quantity=1.0,
                order_type="market",
                reason="QA 테스트 — 항상 매수",
            )
        ]
