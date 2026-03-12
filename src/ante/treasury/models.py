"""Treasury 데이터 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass
class BotBudget:
    """봇별 예산 상태."""

    bot_id: str
    allocated: float = 0.0
    available: float = 0.0
    reserved: float = 0.0
    spent: float = 0.0
    returned: float = 0.0
    last_updated: datetime = field(default_factory=lambda: datetime.now(UTC))
