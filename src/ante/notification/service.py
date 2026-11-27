"""NotificationService — 알림 라우팅 + 필터링."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from datetime import time
from typing import TYPE_CHECKING, Any, cast

from ante.core import clock
from ante.notification.base import NotificationAdapter, NotificationLevel

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.eventbus.events import NotificationEvent

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
        self._queue: deque[NotificationEvent] = deque()
        self._deferring = False
        self._drain_task: asyncio.Task[None] | None = None

    @property
    def adapter(self) -> NotificationAdapter:
        """알림을 보내는 어댑터."""
        return self._adapter

    def subscribe(self, *, defer: bool = False) -> None:
        """이벤트 구독 등록. ``defer=True``이면 ``release`` 전까지 알림을 쌓는다."""
        from ante.eventbus.events import ConfigChangedEvent, NotificationEvent

        self._deferring = defer
        self._eventbus.subscribe(NotificationEvent, self._on_notification, priority=0)
        self._eventbus.subscribe(ConfigChangedEvent, self._on_config_changed)

    def release(self) -> None:
        """쌓인 알림을 보내는 작업자를 시작하고 쌓기를 끝낸다."""
        if self._drain_task is None or self._drain_task.done():
            self._drain_task = asyncio.create_task(self._drain())
        self._deferring = False

    async def stop(self, grace: float = 5.0) -> None:
        """쌓인 알림 전송을 최대 ``grace``초 기다린 뒤 작업자를 멈춘다."""
        task = self._drain_task
        if task is not None and not task.done():
            done, _ = await asyncio.wait({task}, timeout=grace)
            if not done:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        if self._queue:
            logger.warning(
                "NotificationService 정지 — 보내지 못한 알림 %d건을 버림",
                len(self._queue),
            )
            self._queue.clear()

    async def _drain(self) -> None:
        """큐의 맨 앞을 보낸 뒤에 꺼내기를 큐가 빌 때까지 반복한다."""
        while self._queue:
            try:
                await self._dispatch(self._queue[0])
            except Exception:
                logger.exception("쌓인 알림 전송 실패 — 다음 알림으로 넘어감")
            self._queue.popleft()

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
        if level == NotificationLevel.CRITICAL:
            return ""

        key = self._make_dedup_key(level, message)
        now = clock.monotonic()

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
        """NotificationEvent 단일 핸들러 — 큐에 붙이거나 바로 보낸다."""
        from ante.eventbus.events import NotificationEvent

        if not isinstance(event, NotificationEvent):
            return

        if self._deferring or (
            self._queue and event.level != NotificationLevel.CRITICAL
        ):
            self._queue.append(event)
            return
        await self._dispatch(event)

    async def _dispatch(self, event: NotificationEvent) -> None:
        """필터 → 중복 억제 → 전송."""
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
            now = clock.now(None).time()
            if self._quiet_start <= self._quiet_end:
                if self._quiet_start <= now <= self._quiet_end:
                    return False
            else:
                if now >= self._quiet_start or now <= self._quiet_end:
                    return False

        return True
