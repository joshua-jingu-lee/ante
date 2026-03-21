"""QA 테스트용 메타 검증 실패 전략.

exchange 필드에 유효하지 않은 값을 설정하여
전략 검증기의 오류 감지를 테스트한다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class QaInvalidMetaStrategy(Strategy):
    """메타데이터 검증 실패를 유발하는 QA 전략."""

    meta = StrategyMeta(
        name="qa_invalid_meta",
        version=STRATEGY_VERSION,
        description="QA 테스트 전용 — 유효하지 않은 exchange",
        author="qa",
        symbols=["005930"],
        timeframe="1d",
        exchange="INVALID_EXCHANGE",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """시그널 없이 빈 리스트를 반환한다."""
        return []
