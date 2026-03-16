"""E2E 테스트용 샘플 전략 — 매일 고정 매수.

매 스텝마다 지정 종목을 고정 수량만큼 매수 시그널을 생성한다.
실제 전략이 아닌 E2E 파이프라인 검증용이다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta


class DailyFixedBuy(Strategy):
    """매일 고정 매수 전략 (E2E 테스트용)."""

    meta = StrategyMeta(
        name="DailyFixedBuy",
        version="0.1.0",
        description="매일 고정 금액 매수 전략 (E2E 테스트용)",
        author="seed",
        symbols=["005930"],
        timeframe="1d",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """매 스텝마다 삼성전자 1주 시장가 매수."""
        return [
            Signal(
                symbol="005930",
                side="buy",
                quantity=1,
                order_type="market",
                reason="E2E 테스트: 매일 고정 매수",
            )
        ]
