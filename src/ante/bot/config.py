"""Bot 설정 및 상태 정의."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ante.account.scoping import require_account_id


class BotStatus(StrEnum):
    """봇 상태."""

    CREATED = "created"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"
    DELETED = "deleted"


BOT_STATUS_TRANSITIONS: dict[BotStatus, set[BotStatus]] = {
    BotStatus.CREATED: {BotStatus.RUNNING, BotStatus.DELETED},
    BotStatus.RUNNING: {
        BotStatus.RUNNING,
        BotStatus.STOPPING,
        BotStatus.STOPPED,
        BotStatus.ERROR,
        BotStatus.DELETED,
    },
    BotStatus.STOPPING: {
        BotStatus.RUNNING,
        BotStatus.STOPPED,
        BotStatus.ERROR,
        BotStatus.DELETED,
    },
    BotStatus.STOPPED: {
        BotStatus.RUNNING,
        BotStatus.STOPPED,
        BotStatus.ERROR,
        BotStatus.DELETED,
    },
    BotStatus.ERROR: {
        BotStatus.RUNNING,
        BotStatus.STOPPING,
        BotStatus.STOPPED,
        BotStatus.ERROR,
        BotStatus.DELETED,
    },
    BotStatus.DELETED: {
        BotStatus.STOPPED,
        BotStatus.ERROR,
        BotStatus.DELETED,
    },
}

MIN_INTERVAL_SECONDS = 10
MAX_INTERVAL_SECONDS = 3600

MIN_MAX_RESTART_ATTEMPTS = 1
MAX_MAX_RESTART_ATTEMPTS = 10
MIN_RESTART_COOLDOWN_SECONDS = 10
MAX_RESTART_COOLDOWN_SECONDS = 600
MIN_STEP_TIMEOUT_SECONDS = 5
MAX_STEP_TIMEOUT_SECONDS = 120
MIN_MAX_SIGNALS_PER_STEP = 1
MAX_MAX_SIGNALS_PER_STEP = 200


@dataclass
class BotConfig:
    """봇 설정.

    ``account_id`` 는 봇 생성 진입점에서 검증된다. fallback (`""`, ``None``,
    ``"default"``) 또는 형식 위반 값은 거부된다.
    """

    bot_id: str
    strategy_id: str
    name: str = ""
    account_id: str = ""
    interval_seconds: int = 60
    auto_restart: bool = True
    max_restart_attempts: int = 3
    restart_cooldown_seconds: int = 60
    step_timeout_seconds: int = 30
    max_signals_per_step: int = 50

    def __post_init__(self) -> None:
        self.account_id = require_account_id(self.account_id, context="BotConfig")
        validate_interval(self.interval_seconds)
        validate_runtime_controls(
            max_restart_attempts=self.max_restart_attempts,
            restart_cooldown_seconds=self.restart_cooldown_seconds,
            step_timeout_seconds=self.step_timeout_seconds,
            max_signals_per_step=self.max_signals_per_step,
        )


def validate_interval(interval: int) -> None:
    """실행 간격 범위 검증. 범위 밖이면 ValueError."""
    if interval < MIN_INTERVAL_SECONDS or interval > MAX_INTERVAL_SECONDS:
        raise ValueError(
            f"실행 간격은 {MIN_INTERVAL_SECONDS}초 이상 "
            f"{MAX_INTERVAL_SECONDS}초 이하여야 합니다. "
            f"(입력값: {interval}초)"
        )


def validate_runtime_controls(
    *,
    max_restart_attempts: int,
    restart_cooldown_seconds: int,
    step_timeout_seconds: int,
    max_signals_per_step: int,
) -> None:
    """Runtime control 4개 필드 범위 검증. 범위 밖이면 ``ValueError``."""
    if (
        max_restart_attempts < MIN_MAX_RESTART_ATTEMPTS
        or max_restart_attempts > MAX_MAX_RESTART_ATTEMPTS
    ):
        raise ValueError(
            f"max_restart_attempts는 {MIN_MAX_RESTART_ATTEMPTS} 이상 "
            f"{MAX_MAX_RESTART_ATTEMPTS} 이하여야 합니다. "
            f"(입력값: {max_restart_attempts})"
        )
    if (
        restart_cooldown_seconds < MIN_RESTART_COOLDOWN_SECONDS
        or restart_cooldown_seconds > MAX_RESTART_COOLDOWN_SECONDS
    ):
        raise ValueError(
            f"restart_cooldown_seconds는 {MIN_RESTART_COOLDOWN_SECONDS}초 이상 "
            f"{MAX_RESTART_COOLDOWN_SECONDS}초 이하여야 합니다. "
            f"(입력값: {restart_cooldown_seconds}초)"
        )
    if (
        step_timeout_seconds < MIN_STEP_TIMEOUT_SECONDS
        or step_timeout_seconds > MAX_STEP_TIMEOUT_SECONDS
    ):
        raise ValueError(
            f"step_timeout_seconds는 {MIN_STEP_TIMEOUT_SECONDS}초 이상 "
            f"{MAX_STEP_TIMEOUT_SECONDS}초 이하여야 합니다. "
            f"(입력값: {step_timeout_seconds}초)"
        )
    if (
        max_signals_per_step < MIN_MAX_SIGNALS_PER_STEP
        or max_signals_per_step > MAX_MAX_SIGNALS_PER_STEP
    ):
        raise ValueError(
            f"max_signals_per_step는 {MIN_MAX_SIGNALS_PER_STEP} 이상 "
            f"{MAX_MAX_SIGNALS_PER_STEP} 이하여야 합니다. "
            f"(입력값: {max_signals_per_step})"
        )
