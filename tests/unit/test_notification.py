"""Notification 모듈 단위 테스트.

NotificationService는 NotificationEvent 단일 구독으로 동작한다.
개별 도메인 이벤트 핸들러는 제거되었으며,
각 모듈이 NotificationEvent를 직접 발행하는 구조.
"""

import asyncio
import inspect
from datetime import time

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import NotificationEvent
from ante.notification.base import NotificationAdapter, NotificationLevel
from ante.notification.service import NotificationService
from ante.notification.telegram import LEVEL_EMOJI, TelegramAdapter

# ── NotificationLevel ────────────────────────────────


class TestNotificationLevel:
    def test_values(self):
        """레벨 값."""
        assert NotificationLevel.CRITICAL == "critical"
        assert NotificationLevel.ERROR == "error"
        assert NotificationLevel.WARNING == "warning"
        assert NotificationLevel.INFO == "info"

    def test_ordering(self):
        """레벨 비교 가능."""
        levels = [
            NotificationLevel.CRITICAL,
            NotificationLevel.ERROR,
            NotificationLevel.WARNING,
            NotificationLevel.INFO,
        ]
        assert len(levels) == 4


# ── NotificationAdapter ABC ──────────────────────────


class TestNotificationAdapterABC:
    def test_cannot_instantiate(self):
        """ABC 직접 인스턴스화 불가."""
        with pytest.raises(TypeError):
            NotificationAdapter()


# ── TelegramAdapter ──────────────────────────────────


class TestTelegramAdapter:
    def test_init(self):
        """초기화."""
        adapter = TelegramAdapter("token123", "chat456")
        assert adapter._bot_token == "token123"
        assert adapter._chat_id == "chat456"

    def test_level_emoji_mapping(self):
        """레벨별 이모지 매핑."""
        assert LEVEL_EMOJI[NotificationLevel.CRITICAL] is not None
        assert LEVEL_EMOJI[NotificationLevel.ERROR] is not None
        assert LEVEL_EMOJI[NotificationLevel.WARNING] is not None
        assert LEVEL_EMOJI[NotificationLevel.INFO] is not None


# ── MockAdapter ──────────────────────────────────────


class MockAdapter(NotificationAdapter):
    """테스트용 Mock 어댑터 (send_with_buttons 지원)."""

    def __init__(self) -> None:
        self.sent: list[tuple[NotificationLevel, str]] = []
        self.sent_rich: list[dict] = []
        self.sent_buttons: list[dict] = []

    async def send(self, level: NotificationLevel, message: str) -> bool:
        self.sent.append((level, message))
        return True

    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        self.sent_rich.append(
            {
                "level": level,
                "title": title,
                "body": body,
                "metadata": metadata,
            }
        )
        return True

    async def send_with_buttons(
        self,
        level: NotificationLevel,
        message: str,
        buttons: list[list[dict]],
    ) -> bool:
        self.sent_buttons.append(
            {
                "level": level,
                "message": message,
                "buttons": buttons,
            }
        )
        return True


class BasicMockAdapter(NotificationAdapter):
    """send_with_buttons 미지원 어댑터."""

    def __init__(self) -> None:
        self.sent_rich: list[dict] = []

    async def send(self, level: NotificationLevel, message: str) -> bool:
        return True

    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        self.sent_rich.append({"title": title, "body": body})
        return True


# ── NotificationService ──────────────────────────────


class TestNotificationService:
    @pytest.fixture
    def adapter(self):
        return MockAdapter()

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def service(self, adapter, eventbus):
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
        )
        svc.subscribe()
        return svc

    async def test_notification_event(self, service, eventbus, adapter):
        """NotificationEvent → send_rich 호출."""
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="테스트 알림",
                message="상세 내용",
            )
        )
        assert len(adapter.sent_rich) == 1
        assert adapter.sent_rich[0]["title"] == "테스트 알림"
        assert adapter.sent_rich[0]["body"] == "상세 내용"

    async def test_notification_with_category(self, service, eventbus, adapter):
        """category 포함 알림."""
        await eventbus.publish(
            NotificationEvent(
                level="warning",
                title="대사 불일치",
                message="3건 보정",
                category="broker",
            )
        )
        assert len(adapter.sent_rich) == 1
        assert adapter.sent_rich[0]["title"] == "대사 불일치"
        assert adapter.sent_rich[0]["body"] == "3건 보정"

    async def test_notification_with_buttons(self, service, eventbus, adapter):
        """buttons 포함 알림 → send_with_buttons 호출."""
        buttons = [
            [
                {"text": "승인", "callback_data": "approve:1"},
                {"text": "거절", "callback_data": "reject:1"},
            ]
        ]
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="결재 요청",
                message="봇 등록 결재",
                category="approval",
                buttons=buttons,
            )
        )
        assert len(adapter.sent_buttons) == 1
        assert adapter.sent_buttons[0]["buttons"] == buttons
        assert "결재 요청" in adapter.sent_buttons[0]["message"]
        # send_rich는 호출되지 않음
        assert len(adapter.sent_rich) == 0

    async def test_notification_buttons_fallback_to_send_rich(self, eventbus):
        """send_with_buttons 미지원 어댑터 → send_rich fallback."""
        adapter = BasicMockAdapter()
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        svc.subscribe()

        buttons = [[{"text": "OK", "callback_data": "ok"}]]
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="테스트",
                message="본문",
                buttons=buttons,
            )
        )
        # send_with_buttons 없으므로 send_rich fallback
        assert len(adapter.sent_rich) == 1
        assert adapter.sent_rich[0]["title"] == "테스트"

    async def test_error_level_notification(self, service, eventbus, adapter):
        """ERROR 레벨 NotificationEvent 발송."""
        await eventbus.publish(
            NotificationEvent(
                level="error",
                title="봇 에러",
                message="Connection timeout",
                category="bot",
            )
        )
        assert len(adapter.sent_rich) == 1
        assert adapter.sent_rich[0]["level"] == NotificationLevel.ERROR
        assert adapter.sent_rich[0]["title"] == "봇 에러"

    async def test_critical_level_notification(self, service, eventbus, adapter):
        """CRITICAL 레벨 NotificationEvent 발송."""
        await eventbus.publish(
            NotificationEvent(
                level="critical",
                title="거래 상태 변경",
                message="active → halted (일일 손실 한도 초과)",
                category="system",
            )
        )
        assert len(adapter.sent_rich) == 1
        assert adapter.sent_rich[0]["level"] == NotificationLevel.CRITICAL

    async def test_min_level_filter(self, adapter, eventbus):
        """min_level 이하만 발송."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            min_level=NotificationLevel.ERROR,
        )
        svc.subscribe()

        # INFO 레벨 알림 — 필터됨
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="필터 테스트",
            )
        )
        assert len(adapter.sent_rich) == 0

        # ERROR 레벨 알림 — 발송됨
        await eventbus.publish(
            NotificationEvent(
                level="error",
                title="에러 알림",
            )
        )
        assert len(adapter.sent_rich) == 1

    async def test_critical_always_sent(self, adapter, eventbus):
        """CRITICAL은 min_level 무시하고 항상 발송."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            min_level=NotificationLevel.ERROR,
        )
        svc.subscribe()

        await eventbus.publish(
            NotificationEvent(
                level="critical",
                title="긴급",
            )
        )
        assert len(adapter.sent_rich) == 1

    async def test_quiet_hours_blocks(self, adapter, eventbus):
        """quiet_hours 동안 비긴급 알림 차단."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            quiet_start=time(0, 0),
            quiet_end=time(23, 59),
        )
        svc.subscribe()

        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="조용한 시간",
            )
        )
        assert len(adapter.sent_rich) == 0

    async def test_quiet_hours_allows_critical(self, adapter, eventbus):
        """quiet_hours 중에도 CRITICAL은 발송."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            quiet_start=time(0, 0),
            quiet_end=time(23, 59),
        )
        svc.subscribe()

        await eventbus.publish(
            NotificationEvent(
                level="critical",
                title="긴급 알림",
            )
        )
        assert len(adapter.sent_rich) == 1

    async def test_subscribe_registers_events(self, adapter, eventbus):
        """subscribe()는 NotificationEvent + ConfigChangedEvent를 구독한다."""
        from ante.eventbus.events import ConfigChangedEvent

        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        svc.subscribe()

        handlers = eventbus._handlers
        assert NotificationEvent in handlers
        assert ConfigChangedEvent in handlers
        assert len(handlers) == 2

    async def test_no_instrument_service_dependency(self):
        """생성자에 instrument_service 파라미터가 없다."""
        sig = inspect.signature(NotificationService.__init__)
        param_names = list(sig.parameters.keys())
        assert "instrument_service" not in param_names

    async def test_telegram_disabled_blocks_non_critical(self, adapter, eventbus):
        """telegram_enabled=False이면 비긴급 알림을 발송하지 않는다 (Refs #997)."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            telegram_enabled=False,
        )
        svc.subscribe()

        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="테스트 알림",
                message="발송되지 않아야 함",
            )
        )
        assert len(adapter.sent_rich) == 0

    async def test_telegram_disabled_allows_critical(self, adapter, eventbus):
        """telegram_enabled=False여도 CRITICAL은 발송된다 (Refs #997)."""
        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            telegram_enabled=False,
        )
        svc.subscribe()

        await eventbus.publish(
            NotificationEvent(
                level="critical",
                title="긴급 알림",
                message="이것은 발송되어야 함",
            )
        )
        assert len(adapter.sent_rich) == 1

    async def test_telegram_enabled_config_change(self, adapter, eventbus):
        """ConfigChangedEvent로 telegram_enabled 동적 변경 (Refs #997)."""
        from ante.eventbus.events import ConfigChangedEvent

        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            telegram_enabled=True,
        )
        svc.subscribe()

        # telegram_enabled=false로 변경
        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.telegram_enabled",
                old_value='"true"',
                new_value='"false"',
                changed_by="test",
            )
        )
        assert svc._telegram_enabled is False

        # INFO 알림 발송 시도 — 차단됨
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="차단될 알림",
            )
        )
        assert len(adapter.sent_rich) == 0

        # 다시 true로 변경
        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.telegram_enabled",
                old_value='"false"',
                new_value='"true"',
                changed_by="test",
            )
        )
        assert svc._telegram_enabled is True

        # 이제 발송됨
        await eventbus.publish(
            NotificationEvent(
                level="info",
                title="발송될 알림",
            )
        )
        assert len(adapter.sent_rich) == 1

    async def test_min_level_config_change(self, adapter, eventbus):
        """ConfigChangedEvent로 notification.min_level을 동적 변경."""
        from ante.eventbus.events import ConfigChangedEvent

        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            min_level=NotificationLevel.INFO,
        )
        svc.subscribe()

        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.min_level",
                old_value='"info"',
                new_value='"error"',
                changed_by="test",
            )
        )
        assert svc._min_level == NotificationLevel.ERROR

        await eventbus.publish(NotificationEvent(level="warning", title="차단"))
        assert len(adapter.sent_rich) == 0

        await eventbus.publish(NotificationEvent(level="error", title="발송"))
        assert len(adapter.sent_rich) == 1

    async def test_invalid_min_level_config_change_ignored(self, adapter, eventbus):
        """유효하지 않은 notification.min_level 변경은 기존 값을 유지."""
        from ante.eventbus.events import ConfigChangedEvent

        svc = NotificationService(
            adapter=adapter,
            eventbus=eventbus,
            min_level=NotificationLevel.INFO,
        )
        svc.subscribe()

        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.min_level",
                old_value='"info"',
                new_value='"important"',
                changed_by="test",
            )
        )
        assert svc._min_level == NotificationLevel.INFO


# ── parse_quiet_hours ─────────────────────────────


class TestParseQuietHours:
    def test_valid_format(self):
        """정상 형식 파싱."""
        from ante.notification.service import parse_quiet_hours

        result = parse_quiet_hours("23:00-07:00")
        assert result == (time(23, 0), time(7, 0))

    def test_with_spaces(self):
        """공백 포함 형식 파싱."""
        from ante.notification.service import parse_quiet_hours

        result = parse_quiet_hours("23:00 - 07:00")
        assert result == (time(23, 0), time(7, 0))

    def test_invalid_format_returns_none(self):
        """잘못된 형식은 None 반환."""
        from ante.notification.service import parse_quiet_hours

        assert parse_quiet_hours("invalid") is None
        assert parse_quiet_hours("") is None
        assert parse_quiet_hours("25:00-07:00") is None

    def test_midnight_range(self):
        """자정 포함 범위."""
        from ante.notification.service import parse_quiet_hours

        result = parse_quiet_hours("00:00-06:00")
        assert result == (time(0, 0), time(6, 0))


# ── ConfigChangedEvent → quiet_hours 갱신 ─────────


class TestQuietHoursConfigChange:
    @pytest.fixture
    def adapter(self):
        return MockAdapter()

    @pytest.fixture
    def eventbus(self):
        return EventBus()

    @pytest.fixture
    def service(self, adapter, eventbus):
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        svc.subscribe()
        return svc

    async def test_config_change_updates_quiet_hours(self, service, eventbus):
        """ConfigChangedEvent로 quiet_hours 갱신."""
        from ante.eventbus.events import ConfigChangedEvent

        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.quiet_hours",
                old_value="",
                new_value='"23:00-07:00"',
                changed_by="test",
            )
        )
        assert service._quiet_start == time(23, 0)
        assert service._quiet_end == time(7, 0)

    async def test_config_change_clears_quiet_hours(self, service, eventbus):
        """빈 값으로 quiet_hours 비활성화."""
        from ante.eventbus.events import ConfigChangedEvent

        # 먼저 설정
        service._quiet_start = time(23, 0)
        service._quiet_end = time(7, 0)

        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.quiet_hours",
                old_value='"23:00-07:00"',
                new_value='""',
                changed_by="test",
            )
        )
        assert service._quiet_start is None
        assert service._quiet_end is None

    async def test_config_change_ignores_other_keys(self, service, eventbus):
        """다른 키 변경은 무시."""
        from ante.eventbus.events import ConfigChangedEvent

        service._quiet_start = time(23, 0)
        service._quiet_end = time(7, 0)

        await eventbus.publish(
            ConfigChangedEvent(
                category="system",
                key="system.log_level",
                old_value='"INFO"',
                new_value='"DEBUG"',
                changed_by="test",
            )
        )
        # 변경 없음
        assert service._quiet_start == time(23, 0)
        assert service._quiet_end == time(7, 0)

    async def test_config_change_invalid_format(self, service, eventbus):
        """잘못된 형식이면 quiet_hours 비활성화."""
        from ante.eventbus.events import ConfigChangedEvent

        service._quiet_start = time(23, 0)
        service._quiet_end = time(7, 0)

        await eventbus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.quiet_hours",
                old_value='"23:00-07:00"',
                new_value='"invalid"',
                changed_by="test",
            )
        )
        assert service._quiet_start is None
        assert service._quiet_end is None


# ── 기동 중 쌓기 · 해제 뒤 전송 · 정지 (#3109) ─────────


class GatedAdapter(NotificationAdapter):
    """보낸 제목을 기록한다. ``blocked`` 의 제목은 ``gate`` 가 열릴 때까지 막힌다."""

    def __init__(self, blocked: set[str] | None = None) -> None:
        self.blocked = blocked or set()
        self.gate = asyncio.Event()
        self.started: list[str] = []
        self.delivered: list[str] = []

    async def send(self, level: NotificationLevel, message: str) -> bool:
        return True

    async def send_rich(
        self,
        level: NotificationLevel,
        title: str,
        body: str,
        metadata: dict | None = None,
    ) -> bool:
        self.started.append(title)
        if title in self.blocked:
            await self.gate.wait()
        self.delivered.append(title)
        return True


def _event(title: str, level: str = "info") -> NotificationEvent:
    return NotificationEvent(level=level, title=title, message=f"{title} 본문")


async def _until(predicate, *, guard: float = 5.0) -> None:
    async def _poll() -> None:
        while not predicate():
            await asyncio.sleep(0)

    await asyncio.wait_for(_poll(), timeout=guard)


def _deferred(adapter: NotificationAdapter, **kwargs) -> tuple:
    bus = EventBus()
    svc = NotificationService(adapter=adapter, eventbus=bus, **kwargs)
    svc.subscribe(defer=True)
    return svc, bus


class TestDeferredDelivery:
    async def test_events_wait_until_release_then_go_in_publish_order(self):
        """쌓는 중의 알림은 CRITICAL을 포함해 해제 뒤 발행 순서대로 나간다."""
        adapter = GatedAdapter()
        svc, bus = _deferred(adapter)

        await bus.publish(_event("A"))
        await bus.publish(_event("K", level="critical"))
        await bus.publish(_event("B", level="error"))
        assert adapter.started == []

        svc.release()
        await _until(lambda: len(adapter.delivered) == 3)

        assert adapter.delivered == ["A", "K", "B"]

    async def test_non_critical_published_during_drain_goes_after_queue(self):
        """해제 뒤 큐를 비우는 중에 낸 CRITICAL이 아닌 알림은 큐 뒤에 붙는다."""
        adapter = GatedAdapter(blocked={"A"})
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))
        await bus.publish(_event("B"))

        svc.release()
        await _until(lambda: adapter.started == ["A"])
        await bus.publish(_event("C", level="error"))
        assert adapter.started == ["A"]

        adapter.gate.set()
        await _until(lambda: len(adapter.delivered) == 3)
        assert adapter.delivered == ["A", "B", "C"]

    async def test_published_while_last_item_sending_goes_after_it(self):
        """마지막 건을 보내는 중에 낸 알림은 그 뒤에 닿는다(보낸 뒤 꺼내기)."""
        adapter = GatedAdapter(blocked={"A"})
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))

        svc.release()
        await _until(lambda: adapter.started == ["A"])
        await bus.publish(_event("C"))
        assert adapter.started == ["A"]

        adapter.gate.set()
        await _until(lambda: len(adapter.delivered) == 2)
        assert adapter.delivered == ["A", "C"]

    async def test_critical_during_drain_is_sent_before_queue(self):
        """해제 뒤 큐를 비우는 중에 낸 CRITICAL은 큐를 기다리지 않고 바로 나간다."""
        adapter = GatedAdapter(blocked={"A"})
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))
        await bus.publish(_event("B"))

        svc.release()
        await _until(lambda: adapter.started == ["A"])
        await bus.publish(_event("K", level="critical"))
        assert adapter.delivered == ["K"]

        adapter.gate.set()
        await _until(lambda: len(adapter.delivered) == 3)
        assert adapter.delivered == ["K", "A", "B"]

    async def test_after_drain_sends_immediately(self):
        """큐가 비면 바로 보내는 평소 방식으로 돌아간다."""
        adapter = GatedAdapter()
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))
        svc.release()
        await _until(lambda: adapter.delivered == ["A"])

        await bus.publish(_event("B"))

        assert adapter.delivered == ["A", "B"]

    async def test_filters_and_dedup_apply_at_send_time(self):
        """최소 레벨·중복 억제는 쌓을 때가 아니라 보낼 때 평소의 경로로 판정한다."""
        from ante.eventbus.events import ConfigChangedEvent

        adapter = GatedAdapter()
        svc, bus = _deferred(adapter, min_level=NotificationLevel.ERROR)
        await bus.publish(_event("I"))
        await bus.publish(_event("W", level="warning"))
        await bus.publish(_event("D", level="error"))
        await bus.publish(_event("D", level="error"))
        await bus.publish(
            ConfigChangedEvent(
                category="notification",
                key="notification.min_level",
                old_value='"error"',
                new_value='"warning"',
                changed_by="test",
            )
        )

        svc.release()
        await _until(lambda: svc._drain_task is not None and svc._drain_task.done())

        assert adapter.delivered == ["W", "D"]

    async def test_one_failing_item_does_not_drop_the_rest(self, caplog):
        """한 건의 처리 실패가 나머지 큐를 버리지 않고, 실패는 로그로 남는다."""
        import logging

        adapter = GatedAdapter()
        svc, bus = _deferred(adapter)
        await bus.publish(_event("bad", level="bogus"))
        await bus.publish(_event("A"))

        with caplog.at_level(logging.ERROR, logger="ante.notification.service"):
            svc.release()
            await _until(lambda: svc._drain_task.done())

        assert adapter.delivered == ["A"]
        assert any("쌓인 알림 전송 실패" in r.message for r in caplog.records)

    async def test_stop_waits_for_drain(self):
        """정지는 큐를 다 비울 때까지 기다린다."""
        adapter = GatedAdapter(blocked={"A"})
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))
        await bus.publish(_event("B"))
        svc.release()
        await _until(lambda: adapter.started == ["A"])

        asyncio.get_running_loop().call_later(0.05, adapter.gate.set)
        await svc.stop(timeout=5.0)

        assert adapter.delivered == ["A", "B"]

    async def test_stop_returns_after_timeout_with_blocked_adapter(self, caplog):
        """막힌 어댑터에서 정지는 제한 시간 뒤 작업자를 취소하고 남은 건수를 남긴다."""
        import logging

        adapter = GatedAdapter(blocked={"A"})
        svc, bus = _deferred(adapter)
        await bus.publish(_event("A"))
        await bus.publish(_event("B"))
        svc.release()
        await _until(lambda: adapter.started == ["A"])

        loop = asyncio.get_running_loop()
        started = loop.time()
        with caplog.at_level(logging.WARNING, logger="ante.notification.service"):
            await asyncio.wait_for(svc.stop(timeout=0.05), timeout=2.0)
        elapsed = loop.time() - started

        assert 0.05 <= elapsed < 2.0
        assert svc._drain_task.cancelled()
        assert adapter.delivered == []
        assert any("2건" in r.message for r in caplog.records)

    def test_stop_timeout_defaults_to_five_seconds(self):
        """정지의 기본 제한 시간은 5초다."""
        param = inspect.signature(NotificationService.stop).parameters["timeout"]
        assert param.default == 5.0

    def test_adapter_property_returns_same_instance(self):
        """``adapter`` 는 서비스가 보내는 데 쓰는 바로 그 인스턴스다."""
        adapter = GatedAdapter()
        svc = NotificationService(adapter=adapter, eventbus=EventBus())
        assert svc.adapter is adapter
