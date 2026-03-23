"""패스워드 변경/리셋 시 텔레그램 알림 발행 테스트 (GAP-035, #773)."""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import NotificationEvent
from ante.member.service import MemberService


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    yield db
    await db.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = MemberService(db, eventbus)
    await svc.initialize()
    return svc


class TestChangePasswordNotification:
    """change_password 성공 시 NotificationEvent 발행 검증."""

    async def test_notification_published_on_change_password(self, service, eventbus):
        """패스워드 변경 성공 시 warning 레벨 NotificationEvent가 발행되어야 한다."""
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        _, _token, _ = await service.bootstrap_master("owner", "pass123")
        await service.change_password("owner", "pass123", "newpass")

        security_events = [
            e for e in captured if e.category == "security" and "변경" in e.title
        ]
        assert len(security_events) == 1
        evt = security_events[0]
        assert evt.level == "warning"
        assert evt.title == "패스워드 변경"
        assert "`owner`" in evt.message
        assert "세션이 무효화" in evt.message
        assert "토큰을 재발급" in evt.message

    async def test_no_notification_on_wrong_password(self, service, eventbus):
        """잘못된 패스워드로 변경 시도 시 변경 알림이 발행되지 않아야 한다."""
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        _, _token, _ = await service.bootstrap_master("owner", "pass123")

        with pytest.raises(PermissionError):
            await service.change_password("owner", "wrong", "newpass")

        change_events = [
            e for e in captured if e.category == "security" and "변경" in e.title
        ]
        assert len(change_events) == 0


class TestResetPasswordNotification:
    """reset_password 성공 시 NotificationEvent 발행 검증."""

    async def test_notification_published_on_reset_password(self, service, eventbus):
        """패스워드 리셋 성공 시 warning 레벨 NotificationEvent가 발행되어야 한다."""
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        _, _token, recovery_key = await service.bootstrap_master("owner", "pass123")
        await service.reset_password("owner", recovery_key, "resetpass")

        security_events = [
            e for e in captured if e.category == "security" and "리셋" in e.title
        ]
        assert len(security_events) == 1
        evt = security_events[0]
        assert evt.level == "warning"
        assert evt.title == "패스워드 리셋"
        assert "`owner`" in evt.message
        assert "recovery key로 리셋" in evt.message
        assert "세션이 무효화" in evt.message
        assert "recovery key를 재발급" in evt.message

    async def test_no_notification_on_wrong_recovery_key(self, service, eventbus):
        """잘못된 recovery key로 리셋 시도 시 리셋 알림이 발행되지 않아야 한다."""
        captured: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: captured.append(e))

        _, _token, _ = await service.bootstrap_master("owner", "pass123")

        with pytest.raises(PermissionError):
            await service.reset_password("owner", "wrong-key", "resetpass")

        reset_events = [
            e for e in captured if e.category == "security" and "리셋" in e.title
        ]
        assert len(reset_events) == 0
