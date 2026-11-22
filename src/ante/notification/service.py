"""NotificationService — 알림 라우팅 + 필터링."""

from __future__ import annotations

import logging
from datetime import time
from typing import TYPE_CHECKING, Any, cast

from ante.notification.base import NotificationAdapter, NotificationLevel

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


def parse_quiet_hours(value: str) -> tuple[time, time] | None:
    """``"HH:MM-HH:MM"`` 형식 문자열을 ``(time, time)`` 으로 변환.

    잘못된 형식이면 ``None`` 을 반환하고 경고 로그를 남긴다.
    """
    try:
        start_str, end_str = value.split("-", 1)
        sh, sm = start_str.strip().split(":")
        eh, em = end_str.strip().split(":")
        return time(int(sh), int(sm)), time(int(eh), int(em))
    except Exception:
        logger.warning("quiet_hours 파싱 실패 (무음 비활성 유지): %r", value)
        return None


_SUPPRESSED = object()


class NotificationService:
    """알림 라우팅 및 필터링 서비스.

    NotificationEvent 단일 구독으로 모든 알림을 처리한다.
    각 모듈이 NotificationEvent를 직접 발행하면,
    이 서비스가 필터링 → 중복 억제 → 발송을 담당한다.
    """

    def __init__(
        self,
        adapter: NotificationAdapter,
        eventbus: EventBus,
        min_level: NotificationLevel = NotificationLevel.INFO,
        quiet_start: time | None = None,
        quiet_end: time | None = None,
        dedup_window: float = 60.0,
        telegram_enabled: bool = True,
    ) -> None:
        self._adapter = adapter
        self._eventbus = eventbus
        self._min_level = min_level
        self._quiet_start = quiet_start
        self._quiet_end = quiet_end
        self._dedup_window = dedup_window
        self._telegram_enabled = telegram_enabled
        self._dedup_cache: dict[str, tuple[float, int]] = {}

    def subscribe(self) -> None:
        """이벤트 구독 등록 — NotificationEvent + ConfigChangedEvent."""
        from ante.eventbus.events import ConfigChangedEvent, NotificationEvent

        self._eventbus.subscribe(NotificationEvent, self._on_notification, priority=0)
        self._eventbus.subscribe(ConfigChangedEvent, self._on_config_changed)

    async def _on_config_changed(self, event: object) -> None:
        """``notification.*`` 키 변경 시 설정을 갱신한다."""
        from ante.eventbus.events import ConfigChangedEvent

        if not isinstance(event, ConfigChangedEvent):
            return

        if event.key == "notification.telegram_enabled":
            self._telegram_enabled = str(event.new_value).strip('"') == "true"
            logger.info("telegram_enabled 갱신: %s", self._telegram_enabled)
            return

        if event.key == "notification.min_level":
            import json

            try:
                raw = json.loads(event.new_value)
            except (json.JSONDecodeError, TypeError):
                raw = event.new_value
            try:
                self._min_level = NotificationLevel(str(raw))
            except ValueError:
                logger.warning("notification.min_level 무시: 유효하지 않은 값 %r", raw)
                return
            logger.info("notification.min_level 갱신: %s", self._min_level)
            return

        if event.key != "notification.quiet_hours":
            return

        import json

        try:
            raw = json.loads(event.new_value)
        except (json.JSONDecodeError, TypeError):
            raw = event.new_value

        if not raw:
            self._quiet_start = None
            self._quiet_end = None
            logger.info("무음 시간대 비활성화")
            return

        result = parse_quiet_hours(str(raw))
        if result:
            self._quiet_start, self._quiet_end = result
            logger.info("무음 시간대 갱신: %s-%s", self._quiet_start, self._quiet_end)
        else:
            self._quiet_start = None
            self._quiet_end = None

    def _make_dedup_key(self, level: NotificationLevel, message: str) -> str:
        """중복 방지 키 생성: level + message_hash."""
        import hashlib

        msg_hash = hashlib.md5(message.encode()).hexdigest()[:12]
        return f"{level}:{msg_hash}"

    def _check_dedup(self, level: NotificationLevel, message: str) -> str | object:
        """중복 여부 확인."""
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

        suffix = ""
        if key in self._dedup_cache:
            _, suppressed = self._dedup_cache[key]
            if suppressed > 0:
                suffix = f" ({suppressed}건 억제됨)"
        self._dedup_cache[key] = (now, 0)
        return suffix

    async def _send(
        self,
        level: NotificationLevel,
        message: str,
    ) -> bool:
        """send() 호출."""
        dedup_result = self._check_dedup(level, message)
        if dedup_result is _SUPPRESSED:
            logger.debug("알림 억제 (중복): %s", message[:50])
            return False

        if dedup_result:
            message = message + str(dedup_result)

        try:
            return await self._adapter.send(level, message)
        except Exception as e:
            logger.warning("알림 발송 실패: %s", e)
            return False

    async def _send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """send_rich() 호출."""
        dedup_result = self._check_dedup(level, body or title)
        if dedup_result is _SUPPRESSED:
            logger.debug("알림 억제 (중복): %s", (body or title)[:50])
            return False

        if dedup_result:
            body = (body or "") + str(dedup_result)

        try:
            return await self._adapter.send_rich(
                level=level, title=title, body=body, metadata=metadata
            )
        except Exception as e:
            logger.warning("알림 발송 실패: %s", e)
            return False

    async def _send_with_buttons(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        buttons: list[Any],
    ) -> bool:
        """send_with_buttons() 호출."""
        dedup_result = self._check_dedup(level, body or title)
        if dedup_result is _SUPPRESSED:
            logger.debug("알림 억제 (중복): %s", (body or title)[:50])
            return False

        if dedup_result:
            body = (body or "") + str(dedup_result)

        try:
            if hasattr(self._adapter, "send_with_buttons"):
                message = f"*{title}*\n{body}" if body else f"*{title}*"
                return cast(
                    "bool",
                    await self._adapter.send_with_buttons(level, message, buttons),
                )
            else:
                return await self._adapter.send_rich(
                    level=level, title=title, body=body
                )
        except Exception as e:
            logger.warning("알림 발송 실패: %s", e)
            return False

    async def _on_notification(self, event: object) -> None:
        """NotificationEvent 단일 핸들러."""
        from ante.eventbus.events import NotificationEvent

        if not isinstance(event, NotificationEvent):
            return

        level = NotificationLevel(event.level)
        if not self._should_send(level):
            return

        if event.buttons:
            await self._send_with_buttons(
                level=level,
                title=event.title,
                body=event.message,
                buttons=event.buttons,
            )
        else:
            await self._send_rich(
                level=level,
                title=event.title,
                body=event.message,
            )

    def _should_send(self, level: NotificationLevel) -> bool:
        """알림 발송 여부. CRITICAL은 항상 발송."""
        if level == NotificationLevel.CRITICAL:
            return True

        if not self._telegram_enabled:
            return False

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
