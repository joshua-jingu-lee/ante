"""NotificationService — 알림 라우팅 + 필터링."""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING

from ante.notification.base import NotificationAdapter, NotificationLevel

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService

logger = logging.getLogger(__name__)


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
    ) -> None:
        self._adapter = adapter
        self._eventbus = eventbus
        self._min_level = min_level
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._instrument_service = instrument_service

    def subscribe(self) -> None:
        """이벤트 구독 등록."""
        from ante.eventbus.events import (
            BotErrorEvent,
            NotificationEvent,
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

    async def _on_notification(self, event: object) -> None:
        """NotificationEvent 처리."""
        from ante.eventbus.events import NotificationEvent

        if not isinstance(event, NotificationEvent):
            return

        level = NotificationLevel(event.level)
        if self._should_send(level):
            await self._adapter.send_rich(
                level=level,
                title=event.message,
                body=event.detail,
                metadata=event.metadata or None,
            )

    async def _on_bot_error(self, event: object) -> None:
        """봇 에러 자동 알림."""
        from ante.eventbus.events import BotErrorEvent

        if not isinstance(event, BotErrorEvent):
            return

        await self._adapter.send(
            NotificationLevel.ERROR,
            f"봇 에러 [{event.bot_id}]: {event.error_message}",
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

        await self._adapter.send(
            NotificationLevel.INFO,
            f"체결 [{event.bot_id}] {display} "
            f"{event.side} {event.quantity}주 @ {event.price:,.0f}원",
        )

    async def _on_trading_state_changed(self, event: object) -> None:
        """거래 상태 변경 알림."""
        from ante.eventbus.events import TradingStateChangedEvent

        if not isinstance(event, TradingStateChangedEvent):
            return

        await self._adapter.send(
            NotificationLevel.CRITICAL,
            f"거래 상태 변경: {event.old_state} → {event.new_state} ({event.reason})",
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
