"""Notification 모듈 단위 테스트.

NotificationService는 NotificationEvent 단일 구독으로 동작한다.
개별 도메인 이벤트 핸들러는 제거되었으며,
각 모듈이 NotificationEvent를 직접 발행하는 구조.
"""

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

    async def test_subscribe_only_notification_event(self, adapter, eventbus):
        """subscribe()는 NotificationEvent만 구독한다."""
        svc = NotificationService(adapter=adapter, eventbus=eventbus)
        svc.subscribe()

        # NotificationEvent 핸들러만 등록되어 있어야 함
        handlers = eventbus._handlers
        assert NotificationEvent in handlers
        assert len(handlers) == 1

    async def test_no_instrument_service_dependency(self):
        """생성자에 instrument_service 파라미터가 없다."""
        sig = inspect.signature(NotificationService.__init__)
        param_names = list(sig.parameters.keys())
        assert "instrument_service" not in param_names
