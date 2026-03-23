"""RecoveryKeyManager 인증 실패 시 NotificationEvent 발행 테스트 (#807)."""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import MemberAuthFailedEvent, NotificationEvent
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


class TestRecoveryAuthFailedNotification:
    """RecoveryKeyManager._publish_auth_failed 시 NotificationEvent 발행 검증."""

    async def test_notification_on_invalid_recovery_key(self, service, eventbus):
        """잘못된 recovery key로 리셋 시도 시 NotificationEvent 발행."""
        notifications: list[NotificationEvent] = []
        auth_failed: list[MemberAuthFailedEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))
        eventbus.subscribe(MemberAuthFailedEvent, lambda e: auth_failed.append(e))

        _, _token, _ = await service.bootstrap_master("owner", "pass123")

        with pytest.raises(PermissionError):
            await service.reset_password("owner", "wrong-key", "newpass")

        # MemberAuthFailedEvent 발행 확인
        assert len(auth_failed) == 1
        assert auth_failed[0].member_id == "owner"
        assert "recovery key" in auth_failed[0].reason

        # NotificationEvent 발행 확인
        member_notifications = [e for e in notifications if e.category == "member"]
        assert len(member_notifications) == 1
        evt = member_notifications[0]
        assert evt.level == "warning"
        assert evt.title == "인증 실패"
        assert "`owner`" in evt.message
        assert "recovery key" in evt.message

    async def test_no_auth_failed_notification_on_valid_recovery_key(
        self, service, eventbus
    ):
        """올바른 recovery key로 리셋 시 인증 실패 알림이 발행되지 않아야 한다."""
        notifications: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))

        _, _token, recovery_key = await service.bootstrap_master("owner", "pass123")
        await service.reset_password("owner", recovery_key, "newpass")

        auth_fail_notifications = [
            e
            for e in notifications
            if e.category == "member" and "인증 실패" in e.title
        ]
        assert len(auth_fail_notifications) == 0
