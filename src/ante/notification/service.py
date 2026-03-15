"""NotificationService — 알림 라우팅 + 필터링 + 이력 저장."""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING

from ante.notification.base import NotificationAdapter, NotificationLevel
from ante.notification.templates import (
    BOT_ERROR,
    CIRCUIT_BREAKER,
    ORDER_CANCEL_FAILED,
    ORDER_FILLED,
    POSITION_MISMATCH,
    RESTART_EXHAUSTED,
    TRADING_STATE_CHANGED,
)

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


_SUPPRESSED = object()  # 중복 억제 센티널


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
        dedup_window: float = 60.0,
    ) -> None:
        self._adapter = adapter
        self._eventbus = eventbus
        self._min_level = min_level
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._instrument_service = instrument_service
        self._db = db
        self._dedup_window = dedup_window
        # {dedup_key: (last_sent_timestamp, suppressed_count)}
        self._dedup_cache: dict[str, tuple[float, int]] = {}

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
            PositionMismatchEvent,
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
        self._eventbus.subscribe(
            PositionMismatchEvent,
            self._on_position_mismatch,
            priority=0,
        )

    def _make_dedup_key(self, level: NotificationLevel, message: str) -> str:
        """중복 방지 키 생성: level + message_hash."""
        import hashlib

        msg_hash = hashlib.md5(  # noqa: S324
            message.encode()
        ).hexdigest()[:12]
        return f"{level}:{msg_hash}"

    def _check_dedup(self, level: NotificationLevel, message: str) -> str | object:
        """중복 여부 확인.

        Returns:
            _SUPPRESSED: 억제 (발송 안 함)
            "": 발송 허용 (부기 없음)
            "(N건 억제됨)": 발송 허용 + 이전 억제 건수 부기
        """
        import time as time_mod

        if level == NotificationLevel.CRITICAL:
            return ""

        key = self._make_dedup_key(level, message)
        now = time_mod.monotonic()

        if key in self._dedup_cache:
            last_sent, suppressed = self._dedup_cache[key]
            if now - last_sent < self._dedup_window:
                self._dedup_cache[key] = (last_sent, suppressed + 1)
                return _SUPPRESSED

        # 발송 허용
        suffix = ""
        if key in self._dedup_cache:
            _, suppressed = self._dedup_cache[key]
            if suppressed > 0:
                suffix = f" ({suppressed}건 억제됨)"
        self._dedup_cache[key] = (now, 0)
        return suffix

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
        dedup_result = self._check_dedup(level, message)
        if dedup_result is _SUPPRESSED:
            logger.debug("알림 억제 (중복): %s", message[:50])
            return False

        if dedup_result:
            message = message + dedup_result

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
        dedup_result = self._check_dedup(level, body or title)
        if dedup_result is _SUPPRESSED:
            logger.debug("알림 억제 (중복): %s", (body or title)[:50])
            return False

        if dedup_result:
            body = (body or "") + dedup_result

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

    async def _on_position_mismatch(self, event: object) -> None:
        """포지션 불일치 감지 알림 (critical)."""
        from ante.eventbus.events import PositionMismatchEvent

        if not isinstance(event, PositionMismatchEvent):
            return

        msg = POSITION_MISMATCH.format(
            bot_id=event.bot_id,
            symbol=event.symbol,
            internal_qty=event.internal_qty,
            broker_qty=event.broker_qty,
            reason=event.reason,
        )
        await self._send_and_record(
            NotificationLevel.CRITICAL,
            msg,
            event_type="PositionMismatchEvent",
            bot_id=event.bot_id,
        )

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 자동 알림."""
        from ante.eventbus.events import BotErrorEvent

        if not isinstance(event, BotErrorEvent):
            return

        msg = BOT_ERROR.format(
            bot_id=event.bot_id,
            error_message=event.error_message,
        )
        await self._send_and_record(
            NotificationLevel.ERROR,
            msg,
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

        msg = ORDER_FILLED.format(
            bot_id=event.bot_id,
            display=display,
            side=event.side,
            quantity=event.quantity,
            price=event.price,
        )
        await self._send_and_record(
            NotificationLevel.INFO,
            msg,
            event_type="OrderFilledEvent",
            bot_id=event.bot_id,
        )

    async def _on_trading_state_changed(self, event: object) -> None:
        """거래 상태 변경 알림."""
        from ante.eventbus.events import TradingStateChangedEvent

        if not isinstance(event, TradingStateChangedEvent):
            return

        msg = TRADING_STATE_CHANGED.format(
            old_state=event.old_state,
            new_state=event.new_state,
            reason=event.reason,
        )
        await self._send_and_record(
            NotificationLevel.CRITICAL,
            msg,
            event_type="TradingStateChangedEvent",
        )

    async def _on_restart_exhausted(self, event: object) -> None:
        """봇 재시작 한도 소진 알림."""
        from ante.eventbus.events import BotRestartExhaustedEvent

        if not isinstance(event, BotRestartExhaustedEvent):
            return

        msg = RESTART_EXHAUSTED.format(
            bot_id=event.bot_id,
            restart_attempts=event.restart_attempts,
            last_error=event.last_error,
        )
        await self._send_and_record(
            NotificationLevel.ERROR,
            msg,
            event_type="BotRestartExhaustedEvent",
            bot_id=event.bot_id,
        )

    async def _on_order_cancel_failed(self, event: object) -> None:
        """주문 취소 실패 알림."""
        from ante.eventbus.events import OrderCancelFailedEvent

        if not isinstance(event, OrderCancelFailedEvent):
            return

        msg = ORDER_CANCEL_FAILED.format(
            bot_id=event.bot_id,
            order_id=event.order_id,
            error_message=event.error_message,
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

        msg = CIRCUIT_BREAKER.format(
            broker=event.broker,
            old_state=event.old_state,
            new_state=event.new_state,
            reason=event.reason,
        )
        await self._send_and_record(
            level,
            msg,
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
