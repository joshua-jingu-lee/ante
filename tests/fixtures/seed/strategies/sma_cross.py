"""E2E 테스트용 더미 SMA 크로스 전략."""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Strategy, StrategyMeta


class SmaCross(Strategy):
    """SMA 5/20 크로스오버 — E2E 테스트용 더미 구현."""

    meta = StrategyMeta(
        name="SMA 크로스",
        version="1.0.0",
        description="SMA 5/20 크로스오버 전략 (테스트용)",
        author="test",
    )

    async def on_step(self, context: dict[str, Any]) -> list:
        """시그널 없이 빈 리스트 반환."""
        return []
