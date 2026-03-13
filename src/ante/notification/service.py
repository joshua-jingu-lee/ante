"""NotificationService — 알림 라우팅 + 필터링 + 이력 저장."""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING

from ante.notification.base import NotificationAdapter, NotificationLevel

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService

logger = logging.getLogger(__name__)

NOTIFICATION_HISTORY_SCHEMA = """
CREATE TABLE IF NOT EXISTS notification_history (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    level         TEXT NOT NULL,
    title         TEXT DEFAULT '',
    message       TEXT NOT NULL,
    adapter_type  TEXT NOT NULL,
    success       BOOLEAN NOT NULL,
    error_message TEXT DEFAULT '',
    event_type    TEXT DEFAULT '',
    bot_id        TEXT DEFAULT '',
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notification_history_created
    ON notification_history(created_at);
CREATE INDEX IF NOT EXISTS idx_notification_history_level
    ON notification_history(level);
"""


class NotificationService:
    """알림 라우팅 및 필터링 서비스."""

    def __init__(
        self,
        adapter: NotificationAdapter,
        eventbus: EventBus,
        min_level: NotificationLevel = NotificationLevel.INFO,
        quiet_start: time | None = None,
        quiet_end: time | None = None,
        instrument_service: InstrumentService | None = None,
        db: Database | None = None,
    ) -> None:
        self._adapter = adapter
        self._eventbus = eventbus
        self._min_level = min_level
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._instrument_service = instrument_service
        self._db = db

    async def initialize(self) -> None:
        """notification_history 테이블 스키마 생성."""
        if self._db:
            await self._db.execute_script(NOTIFICATION_HISTORY_SCHEMA)
            logger.debug("notification_history 테이블 초기화 완료")

    def subscribe(self) -> None:
        """이벤트 구독 등록."""
        from ante.eventbus.events import (
            BotErrorEvent,
            BotRestartExhaustedEvent,
            CircuitBreakerEvent,
            NotificationEvent,
            OrderCancelFailedEvent,
            OrderFilledEvent,
            TradingStateChangedEvent,
        )

        self._eventbus.subscribe(NotificationEvent, self._on_notification, priority=0)
        self._eventbus.subscribe(BotErrorEvent, self._on_bot_error, priority=0)
        self._eventbus.subscribe(OrderFilledEvent, self._on_order_filled, priority=0)
        self._eventbus.subscribe(
            TradingStateChangedEvent,
            self._on_trading_state_changed,
            priority=0,
        )
        self._eventbus.subscribe(
            BotRestartExhaustedEvent,
            self._on_restart_exhausted,
            priority=0,
        )
        self._eventbus.subscribe(
            OrderCancelFailedEvent,
            self._on_order_cancel_failed,
            priority=0,
        )
        self._eventbus.subscribe(
            CircuitBreakerEvent,
            self._on_circuit_breaker,
            priority=0,
        )

    async def _send_and_record(
        self,
        level: NotificationLevel,
        message: str,
        *,
        title: str = "",
        event_type: str = "",
        bot_id: str = "",
    ) -> bool:
        """send() 호출 후 이력 기록."""
        success = False
        error_message = ""
        try:
            success = await self._adapter.send(level, message)
        except Exception as e:
            error_message = str(e)
            logger.warning("알림 발송 실패: %s", e)

        await self._record_history(
            level=level,
            title=title,
            message=message,
            success=success,
            error_message=error_message,
            event_type=event_type,
            bot_id=bot_id,
        )
        return success

    async def _send_rich_and_record(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        *,
        metadata: dict | None = None,
        event_type: str = "",
        bot_id: str = "",
    ) -> bool:
        """send_rich() 호출 후 이력 기록."""
        success = False
        error_message = ""
        try:
            success = await self._adapter.send_rich(
                level=level, title=title, body=body, metadata=metadata
            )
        except Exception as e:
            error_message = str(e)
            logger.warning("알림 발송 실패: %s", e)

        await self._record_history(
            level=level,
            title=title,
            message=body or title,
            success=success,
            error_message=error_message,
            event_type=event_type,
            bot_id=bot_id,
        )
        return success

    async def _record_history(
        self,
        *,
        level: NotificationLevel,
        title: str,
        message: str,
        success: bool,
        error_message: str = "",
        event_type: str = "",
        bot_id: str = "",
    ) -> None:
        """알림 이력을 DB에 기록."""
        if not self._db:
            return

        try:
            await self._db.execute(
                """INSERT INTO notification_history
                   (level, title, message, adapter_type, success,
                    error_message, event_type, bot_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(level),
                    title,
                    message,
                    type(self._adapter).__name__,
                    success,
                    error_message,
                    event_type,
                    bot_id,
                ),
            )
        except Exception:
            logger.exception("알림 이력 기록 실패")

    async def get_history(
        self,
        *,
        limit: int = 50,
        level: str | None = None,
        success_only: bool | None = None,
    ) -> list[dict]:
        """알림 이력 조회."""
        if not self._db:
            return []

        query = "SELECT * FROM notification_history WHERE 1=1"
        params: list[object] = []

        if level:
            query += " AND level = ?"
            params.append(level)

        if success_only is not None:
            query += " AND success = ?"
            params.append(success_only)

        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        return await self._db.fetch_all(query, tuple(params))

    async def _on_notification(self, event: object) -> None:
        """NotificationEvent 처리."""
        from ante.eventbus.events import NotificationEvent

        if not isinstance(event, NotificationEvent):
            return

        level = NotificationLevel(event.level)
        if self._should_send(level):
            await self._send_rich_and_record(
                level=level,
                title=event.message,
                body=event.detail,
                metadata=event.metadata or None,
                event_type="NotificationEvent",
            )

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 자동 알림."""
        from ante.eventbus.events import BotErrorEvent

        if not isinstance(event, BotErrorEvent):
            return

        await self._send_and_record(
            NotificationLevel.ERROR,
            f"봇 에러 [{event.bot_id}]: {event.error_message}",
            event_type="BotErrorEvent",
            bot_id=event.bot_id,
        )

    async def _on_order_filled(self, event: object) -> None:
        """체결 완료 알림."""
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return

        if not self._should_send(NotificationLevel.INFO):
            return

        display = event.symbol
        if self._instrument_service:
            name = self._instrument_service.get_name(event.symbol, event.exchange)
            if name != event.symbol:
                display = f"{event.symbol}({name})"

        await self._send_and_record(
            NotificationLevel.INFO,
            f"체결 [{event.bot_id}] {display} "
            f"{event.side} {event.quantity}주 @ {event.price:,.0f}원",
            event_type="OrderFilledEvent",
            bot_id=event.bot_id,
        )

    async def _on_trading_state_changed(self, event: object) -> None:
        """거래 상태 변경 알림."""
        from ante.eventbus.events import TradingStateChangedEvent

        if not isinstance(event, TradingStateChangedEvent):
            return

        await self._send_and_record(
            NotificationLevel.CRITICAL,
            f"거래 상태 변경: {event.old_state} → {event.new_state} ({event.reason})",
            event_type="TradingStateChangedEvent",
        )

    async def _on_restart_exhausted(self, event: object) -> None:
        """봇 재시작 한도 소진 알림."""
        from ante.eventbus.events import BotRestartExhaustedEvent

        if not isinstance(event, BotRestartExhaustedEvent):
            return

        await self._send_and_record(
            NotificationLevel.ERROR,
            f"봇 재시작 한도 소진 [{event.bot_id}] "
            f"{event.restart_attempts}회 시도: {event.last_error}",
            event_type="BotRestartExhaustedEvent",
            bot_id=event.bot_id,
        )

    async def _on_order_cancel_failed(self, event: object) -> None:
        """주문 취소 실패 알림."""
        from ante.eventbus.events import OrderCancelFailedEvent

        if not isinstance(event, OrderCancelFailedEvent):
            return

        msg = (
            f"주문 취소 실패 [{event.bot_id}] "
            f"주문={event.order_id}: {event.error_message}"
        )
        await self._send_and_record(
            NotificationLevel.ERROR,
            msg,
            event_type="OrderCancelFailedEvent",
            bot_id=event.bot_id,
        )

    async def _on_circuit_breaker(self, event: object) -> None:
        """Circuit breaker 상태 변경 알림."""
        from ante.eventbus.events import CircuitBreakerEvent

        if not isinstance(event, CircuitBreakerEvent):
            return

        level = NotificationLevel.WARNING
        if event.new_state == "open":
            level = NotificationLevel.ERROR

        await self._send_and_record(
            level,
            f"Circuit Breaker [{event.broker}] "
            f"{event.old_state} → {event.new_state} ({event.reason})",
            event_type="CircuitBreakerEvent",
        )

    def _should_send(self, level: NotificationLevel) -> bool:
        """알림 발송 여부. CRITICAL은 항상 발송."""
        if level == NotificationLevel.CRITICAL:
            return True

        level_order = {
            NotificationLevel.CRITICAL: 0,
            NotificationLevel.ERROR: 1,
            NotificationLevel.WARNING: 2,
            NotificationLevel.INFO: 3,
        }
        if level_order.get(level, 3) > level_order.get(self._min_level, 3):
            return False

        if self._quiet_start and self._quiet_end:
            from datetime import datetime

            now = datetime.now().time()
            if self._quiet_start <= self._quiet_end:
                if self._quiet_start <= now <= self._quiet_end:
                    return False
            else:
                if now >= self._quiet_start or now <= self._quiet_end:
                    return False

        return True
