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


# 실행 간격 제한
MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 3600


@dataclass
class BotConfig:
    """봇 설정."""

    bot_id: str
    strategy_id: str
    bot_type: str = "live"
    interval_seconds: int = 60
    paper_initial_balance: float = 10_000_000.0
    exchange: str = "KRX"
    auto_restart: bool = True
    max_restart_attempts: int = 3
    restart_cooldown_seconds: int = 60
    step_timeout_seconds: int = 30
    max_signals_per_step: int = 50

    def __post_init__(self) -> None:
        validate_interval(self.interval_seconds)


def validate_interval(interval: int) -> None:
    """실행 간격 범위 검증. 범위 밖이면 ValueError."""
    if interval < MIN_INTERVAL_SECONDS or interval > MAX_INTERVAL_SECONDS:
        raise ValueError(
            f"실행 간격은 {MIN_INTERVAL_SECONDS}초 이상 "
            f"{MAX_INTERVAL_SECONDS}초 이하여야 합니다. "
            f"(입력값: {interval}초)"
        )
