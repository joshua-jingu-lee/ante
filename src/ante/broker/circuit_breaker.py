"""Circuit Breaker — 연속 실패 시 API 호출 차단.

상태 머신:
  CLOSED (정상) → 연속 N회 실패 → OPEN (차단)
  OPEN → recovery_timeout 후 → HALF_OPEN (시험)
  HALF_OPEN → 1회 성공 → CLOSED / 실패 → OPEN
"""

from __future__ import annotations

import logging
import time
from enum import StrEnum
from typing import TYPE_CHECKING

from ante.broker.exceptions import CircuitOpenError

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    """Circuit breaker 상태."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """Circuit breaker 구현.

    Args:
        failure_threshold: OPEN 전환까지 연속 실패 횟수 (기본 5)
        recovery_timeout: OPEN → HALF_OPEN 대기 시간 초 (기본 60)
        eventbus: 상태 변경 이벤트 발행용 (선택)
        name: 식별자 (로깅/이벤트용)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        eventbus: EventBus | None = None,
        name: str = "kis",
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._eventbus = eventbus
        self._name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0.0

    @property
    def state(self) -> CircuitState:
        """현재 상태 (OPEN → HALF_OPEN 자동 전환 포함)."""
        if self._state == CircuitState.OPEN:
            elapsed = time.monotonic() - self._last_failure_time
            if elapsed >= self._recovery_timeout:
                self._transition(CircuitState.HALF_OPEN, "recovery_timeout 경과")
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    def check(self) -> None:
        """API 호출 전 상태 확인. OPEN이면 CircuitOpenError."""
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitOpenError(
                f"Circuit breaker OPEN — {self._failure_count}회 연속 실패, "
                f"{self._recovery_timeout:.0f}초 후 재시도"
            )

    def record_success(self) -> None:
        """성공 기록 → CLOSED로 복귀."""
        if self._state != CircuitState.CLOSED:
            self._transition(CircuitState.CLOSED, "API 호출 성공")
        self._failure_count = 0

    def record_failure(self) -> None:
        """실패 기록 → threshold 도달 시 OPEN."""
        self._failure_count += 1
        self._last_failure_time = time.monotonic()

        if self._state == CircuitState.HALF_OPEN:
            self._transition(CircuitState.OPEN, "HALF_OPEN 시험 실패")
        elif (
            self._state == CircuitState.CLOSED
            and self._failure_count >= self._failure_threshold
        ):
            self._transition(
                CircuitState.OPEN,
                f"연속 {self._failure_count}회 실패",
            )

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        """상태 전환 + 이벤트 발행."""
        old_state = self._state
        self._state = new_state
        logger.warning(
            "CircuitBreaker[%s] %s → %s (%s)",
            self._name,
            old_state.value,
            new_state.value,
            reason,
        )

        if self._eventbus:
            self._publish_event(old_state, new_state, reason)

    def _publish_event(
        self,
        old_state: CircuitState,
        new_state: CircuitState,
        reason: str,
    ) -> None:
        """CircuitBreakerEvent 발행 (fire-and-forget)."""
        import asyncio

        from ante.eventbus.events import CircuitBreakerEvent

        event = CircuitBreakerEvent(
            broker=self._name,
            old_state=old_state.value,
            new_state=new_state.value,
            failure_count=self._failure_count,
            reason=reason,
        )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._eventbus.publish(event))  # type: ignore[union-attr]
        except RuntimeError:
            # 이벤트 루프가 없는 경우 (테스트 등) 무시
            pass
