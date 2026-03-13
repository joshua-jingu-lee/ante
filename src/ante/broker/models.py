"""Broker 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CommissionInfo:
    """증권사별 수수료율 정보.

    commission_rate: 매매 수수료율 (예: 0.00015 = 0.015%)
    sell_tax_rate: 매도 세금율 (증권거래세 + 농특세, 예: 0.0023 = 0.23%)
    """

    commission_rate: float = 0.00015
    sell_tax_rate: float = 0.0023

    def calculate(self, side: str, filled_value: float) -> float:
        """체결 금액 기반 수수료 계산.

        매수: filled_value × commission_rate
        매도: filled_value × (commission_rate + sell_tax_rate)
        """
        if side == "sell":
            return filled_value * (self.commission_rate + self.sell_tax_rate)
        return filled_value * self.commission_rate
