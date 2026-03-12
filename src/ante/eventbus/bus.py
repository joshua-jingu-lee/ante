"""EventBus — 타입 기반 이벤트 발행/구독."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from inspect import isawaitable
from typing import Any

from ante.eventbus.events import Event

logger = logging.getLogger(__name__)

EventHandler = Callable[[Any], Awaitable[None] | None]


class EventBus:
    """타입 기반 이벤트 발행/구독 인프라.

    - 타입 기반 라우팅: 이벤트 클래스 타입으로 핸들러 매칭
    - 우선순위 기반 순차 실행: priority가 높을수록 먼저 실행
    - 핸들러 에러 격리: 한 핸들러의 예외가 다른 핸들러를 막지 않음
    - 인메모리 히스토리: 최근 N건 링버퍼
    """

    def __init__(self, history_size: int = 1000) -> None:
        self._handlers: dict[type[Event], list[tuple[int, EventHandler]]] = {}
        self._history: list[Event] = []
        self._history_size = history_size
        self._middlewares: list[EventHandler] = []

    def use(self, middleware: EventHandler) -> None:
        """글로벌 미들웨어 등록. 모든 이벤트에 대해 호출된다."""
        self._middlewares.append(middleware)

    def subscribe(
        self,
        event_type: type[Event],
        handler: EventHandler,
        priority: int = 0,
    ) -> None:
        """이벤트 타입에 핸들러 등록. priority가 높을수록 먼저 실행."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append((priority, handler))
        self._handlers[event_type].sort(key=lambda x: x[0], reverse=True)
        logger.debug(
            "핸들러 등록: %s → %s (priority=%d)",
            event_type.__name__,
            handler.__qualname__,
            priority,
        )

    def unsubscribe(
        self,
        event_type: type[Event],
        handler: EventHandler,
    ) -> None:
        """핸들러 등록 해제."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                (p, h) for p, h in self._handlers[event_type] if h != handler
            ]

    async def publish(self, event: Event) -> None:
        """이벤트를 모든 구독 핸들러에 순차 전달 + 히스토리 기록."""
        self._record_history(event)

        # 글로벌 미들웨어 실행 (로깅, SQLite 영속화 등)
        for mw in self._middlewares:
            try:
                result = mw(event)
                if isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "미들웨어 에러: %s for %s",
                    mw.__qualname__,
                    type(event).__name__,
                )

        handlers = self._handlers.get(type(event), [])
        if not handlers:
            logger.debug("구독자 없는 이벤트: %s", type(event).__name__)
            return

        for priority, handler in handlers:
            try:
                result = handler(event)
                if isawaitable(result):
                    await result
            except Exception:
                logger.exception(
                    "핸들러 에러: %s for %s",
                    handler.__qualname__,
                    type(event).__name__,
                )

        logger.debug(
            "이벤트 처리 완료: %s (%d 핸들러)",
            type(event).__name__,
            len(handlers),
        )

    def _record_history(self, event: Event) -> None:
        """인메모리 링버퍼에 이벤트 기록."""
        self._history.append(event)
        if len(self._history) > self._history_size:
            self._history = self._history[-self._history_size :]

    def get_history(
        self,
        event_type: type[Event] | None = None,
        limit: int = 100,
    ) -> list[Event]:
        """이벤트 히스토리 조회.

        Args:
            event_type: 특정 이벤트 타입으로 필터링 (None이면 전체)
            limit: 최대 반환 건수

        Returns:
            최신순 이벤트 리스트
        """
        events = self._history
        if event_type is not None:
            events = [e for e in events if isinstance(e, event_type)]
        return list(reversed(events[-limit:]))

    def get_handlers(self, event_type: type[Event]) -> list[tuple[int, EventHandler]]:
        """특정 이벤트 타입의 등록된 핸들러 목록."""
        return list(self._handlers.get(event_type, []))
