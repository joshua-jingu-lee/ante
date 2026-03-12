"""Bot 설정 및 상태 정의."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BotStatus(StrEnum):
    """봇 상태."""

    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass
class BotConfig:
    """봇 설정."""

    bot_id: str
    strategy_id: str
    bot_type: str = "live"
    interval_seconds: int = 60
    symbols: list[str] | None = None
    paper_initial_balance: float = 10_000_000.0
