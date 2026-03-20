"""QA 테스트용 최소 샘플 전략.

전략 검증 API(/api/strategies/validate)의 정상 동작을 확인하기 위한
최소 구현체다. 실제 매매 로직은 포함하지 않는다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaSampleStrategy(Strategy):
    """QA 검증용 샘플 전략."""

    meta = StrategyMeta(
        name="qa_sample",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 샘플 전략",
        author="qa",
        symbols=["005930"],
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """시그널 없이 빈 리스트를 반환한다."""
        return []
