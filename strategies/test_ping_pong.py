"""핑퐁 전략 (테스트용).

매 스텝마다 보유 여부를 확인하여:
- 미보유 시 매수
- 보유 시 매도
를 반복하여 거래 파이프라인 전체를 검증한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class TestPingPongStrategy(Strategy):
    """보유 여부에 따라 매수/매도를 번갈아 반복하는 테스트 전략."""

    meta = StrategyMeta(
        name="test_ping_pong",
        version=STRATEGY_VERSION,
        description="보유→매도, 미보유→매수를 반복하는 거래 테스트 전략",
        author_name="master",
        author_id="master",
        symbols=["005930"],  # 삼성전자
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """보유 상태에 따라 매수 또는 매도 시그널을 반환."""
        symbol = "005930"

        positions = self.ctx.get_positions()
        has_position = bool(positions and positions.get(symbol))

        if has_position:
            return [
                Signal(
                    symbol=symbol,
                    side="sell",
                    quantity=1.0,
                    order_type="market",
                    reason="핑퐁 매도 — 보유 중이므로 매도",
                )
            ]
        else:
            return [
                Signal(
                    symbol=symbol,
                    side="buy",
                    quantity=1.0,
                    order_type="market",
                    reason="핑퐁 매수 — 미보유이므로 매수",
                )
            ]

    def get_rationale(self) -> str:
        return "거래 파이프라인 E2E 검증용. 매 스텝 반드시 1건의 주문을 발생시킨다."

    def get_risks(self) -> list[str]:
        return ["테스트 전용 — 수수료 손실 불가피"]
