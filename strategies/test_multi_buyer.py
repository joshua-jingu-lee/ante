"""다종목 소량 매수 전략 (테스트용).

매 스텝마다 여러 종목에 대해 소량 매수 시그널을 발생시켜
다종목 동시 주문 처리를 검증한다.
보유 종목이 3개 이상이면 전량 매도로 전환한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"

SYMBOLS = ["005930", "000660", "035720"]  # 삼성전자, SK하이닉스, 카카오


class TestMultiBuyerStrategy(Strategy):
    """다종목 매수 후 일괄 매도를 반복하는 테스트 전략."""

    meta = StrategyMeta(
        name="test_multi_buyer",
        version=STRATEGY_VERSION,
        description="3종목 소량 매수 후 일괄 매도 반복 (거래 테스트)",
        author_name="master",
        author_id="master",
        symbols=SYMBOLS,
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """보유 종목 수에 따라 매수 또는 일괄 매도."""
        positions = self.ctx.get_positions()
        held = [s for s in SYMBOLS if positions and positions.get(s)]

        if len(held) >= 3:
            # 전종목 보유 → 일괄 매도
            return [
                Signal(
                    symbol=s,
                    side="sell",
                    quantity=1.0,
                    order_type="market",
                    reason=f"일괄 매도 — {len(held)}종목 보유 중",
                )
                for s in held
            ]
        else:
            # 미보유 종목 매수
            to_buy = [s for s in SYMBOLS if s not in held]
            return [
                Signal(
                    symbol=s,
                    side="buy",
                    quantity=1.0,
                    order_type="market",
                    reason=f"다종목 매수 — {len(to_buy)}종목 추가 매수",
                )
                for s in to_buy
            ]

    def get_rationale(self) -> str:
        return "다종목 동시 주문 처리 및 포지션 관리 파이프라인 검증용."

    def get_risks(self) -> list[str]:
        return ["테스트 전용 — 수수료 및 슬리피지 손실 불가피"]
