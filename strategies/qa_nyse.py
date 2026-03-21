"""QA 테스트용 해외(NYSE) 시장 전략.

exchange="NYSE" 설정으로 해외 시장 전략의 등록 및 조회를 검증한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaNyseStrategy(Strategy):
    """NYSE 시장을 대상으로 하는 QA 전략."""

    meta = StrategyMeta(
        name="qa_nyse",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 — NYSE 시장 전략",
        author="qa",
        symbols=["AAPL"],
        timeframe="1d",
        exchange="NYSE",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """시그널 없이 빈 리스트를 반환한다."""
        return []
