"""QA 테스트용 다중 종목 전략.

여러 심볼을 대상으로 하는 전략의 등록 및 조회를 검증한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaMultiSymbolStrategy(Strategy):
    """다중 종목을 대상으로 하는 QA 전략."""

    meta = StrategyMeta(
        name="qa_multi_symbol",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 — 다중 종목 전략",
        author_name="qa",
        author_id="qa",
        symbols=["005930", "000660", "035420"],
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """시그널 없이 빈 리스트를 반환한다."""
        return []
