"""QA 테스트용 외부 시그널 수신 전략.

accepts_external_signals=True 설정으로 외부 시그널 수신 전략의
등록 및 검증을 테스트한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaExternalSignalStrategy(Strategy):
    """외부 시그널을 수신하는 QA 전략."""

    meta = StrategyMeta(
        name="qa_external_signal",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 — 외부 시그널 수신 전략",
        author="qa",
        symbols=["005930"],
        timeframe="1d",
        exchange="KRX",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """시그널 없이 빈 리스트를 반환한다."""
        return []

    async def on_data(self, data: dict[str, Any]) -> list[Signal]:
        """외부 데이터 수신 시 처리한다."""
        return []
