"""Ante strategy template.

Copy this file when creating a new strategy, then replace the metadata and
signal logic with the strategy's actual intent.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.1.0"


class MyStrategy(Strategy):
    """Minimal strategy skeleton."""

    meta = StrategyMeta(
        name="my_strategy",
        version=STRATEGY_VERSION,
        description="Describe the strategy idea in one sentence.",
        author_name="agent",
        author_id="agent",
        symbols=["005930"],
        timeframe="1d",
        exchange="KRX",
    )

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """Return zero or more signals for the current bot step."""
        return []
