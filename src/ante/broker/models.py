"""Broker 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommissionInfo:
    """증권사별 수수료율 정보.

    buy_commission_rate: 매수 수수료율 (예: 0.00015 = 0.015%)
    sell_commission_rate: 매도 수수료율 (세금 포함, 예: 0.00195 = 0.195%)

    변경 이유: 기존 commission_rate + sell_tax_rate 분리 방식은 국내주식 전용이었다.
    해외주식은 매도 세금 구조가 다르므로, 매수/매도 총비용을 각각 단일 필드로
    표현하여 시장에 무관하게 동일한 인터페이스를 제공한다.
    """

    buy_commission_rate: float = 0.00015
    sell_commission_rate: float = 0.00195

    def calculate(self, side: str, filled_value: float) -> float:
        """체결 금액 기반 수수료 계산.

        매수: filled_value × buy_commission_rate
        매도: filled_value × sell_commission_rate
        """
        if side == "sell":
            return filled_value * self.sell_commission_rate
        return filled_value * self.buy_commission_rate
