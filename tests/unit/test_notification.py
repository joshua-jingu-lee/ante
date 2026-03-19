"""Notification 모듈 단위 테스트."""

from datetime import time

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotErrorEvent,
    NotificationEvent,
    OrderFilledEvent,
    TradingStateChangedEvent,
)
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
    """테스트용 Mock 어댑터."""

    def __init__(self) -> None:
        self.sent: list[tuple[NotificationLevel, str]] = []
        self.sent_rich: list[dict] = []

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

    async def test_bot_error_event(self, service, eventbus, adapter):
        """BotErrorEvent → send 호출."""
        await eventbus.publish(
            BotErrorEvent(
                bot_id="bot1",
                error_message="Connection timeout",
            )
        )
        assert len(adapter.sent) == 1
        assert "봇 에러" in adapter.sent[0][1]
        assert "bot1" in adapter.sent[0][1]
        assert adapter.sent[0][0] == NotificationLevel.ERROR

    async def test_order_filled_event(self, service, eventbus, adapter):
        """OrderFilledEvent → 체결 알림."""
        await eventbus.publish(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=100.0,
                price=72000.0,
                order_type="market",
            )
        )
        assert len(adapter.sent) == 1
        assert "체결" in adapter.sent[0][1]
        assert "005930" in adapter.sent[0][1]

    async def test_trading_state_changed(self, service, eventbus, adapter):
        """TradingStateChangedEvent → CRITICAL 알림."""
        await eventbus.publish(
            TradingStateChangedEvent(
                old_state="active",
                new_state="halted",
                reason="일일 손실 한도 초과",
                changed_by="rule_engine",
            )
        )
        assert len(adapter.sent) == 1
        assert adapter.sent[0][0] == NotificationLevel.CRITICAL

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
        """buttons 필드가 NotificationEvent에 설정 가능."""
        buttons = [
            [
                {"text": "승인", "callback_data": "approve:1"},
                {"text": "거절", "callback_data": "reject:1"},
            ]
        ]
        event = NotificationEvent(
            level="info",
            title="결재 요청",
            message="봇 등록 결재",
            category="approval",
            buttons=buttons,
        )
        assert event.buttons == buttons
        assert event.category == "approval"
