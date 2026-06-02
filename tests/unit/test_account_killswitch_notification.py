"""킬 스위치 NotificationEvent 발행 테스트 (#2131).

`notification.md` 트리거 표는 "거래 상태 변경(킬 스위치)"의 담당을
AccountService·레벨 CRITICAL·category system 으로 명시한다. AccountService.suspend
는 도메인 이벤트(`AccountSuspendedEvent`)와 함께 CRITICAL `NotificationEvent` 를,
activate 는 `AccountActivatedEvent` 와 함께 INFO `NotificationEvent` 를 직접
발행해야 한다 (#2151 approval `_publish_created`·#2150 member `suspend` 동형).
"""

import pytest
import pytest_asyncio

from ante.account.errors import AccountAlreadySuspendedError
from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
    AccountSuspendedEvent,
    NotificationEvent,
)


@pytest_asyncio.fixture
async def db(tmp_path):
    """테스트용 인메모리 DB."""
    db_path = str(tmp_path / "test_account_killswitch.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    """테스트용 EventBus."""
    return EventBus()


@pytest_asyncio.fixture
async def service(db, eventbus):
    """초기화된 AccountService."""
    svc = AccountService(db, eventbus)
    await svc.initialize()
    return svc


def _make_account(
    account_id: str = "main",
    name: str = "테스트",
    exchange: str = "TEST",
    currency: str = "KRW",
    broker_type: str = "test",
    **kwargs,
) -> Account:
    """테스트용 Account 생성 헬퍼."""
    if "credentials" not in kwargs:
        kwargs["credentials"] = {"app_key": "test", "app_secret": "test"}
    return Account(
        account_id=account_id,
        name=name,
        exchange=exchange,
        currency=currency,
        broker_type=broker_type,
        **kwargs,
    )


def _capture(eventbus):
    """모든 이벤트를 종류별 리스트로 캡처한다."""
    suspended: list[AccountSuspendedEvent] = []
    activated: list[AccountActivatedEvent] = []
    notifications: list[NotificationEvent] = []

    async def on_suspended(event: AccountSuspendedEvent) -> None:
        suspended.append(event)

    async def on_activated(event: AccountActivatedEvent) -> None:
        activated.append(event)

    async def on_notification(event: NotificationEvent) -> None:
        notifications.append(event)

    eventbus.subscribe(AccountSuspendedEvent, on_suspended)
    eventbus.subscribe(AccountActivatedEvent, on_activated)
    eventbus.subscribe(NotificationEvent, on_notification)
    return suspended, activated, notifications


@pytest.mark.asyncio
async def test_suspend_publishes_domain_event_and_critical_notification(
    service, eventbus
):
    """suspend()는 AccountSuspendedEvent AND CRITICAL NotificationEvent 둘 다 발행."""
    await service.create(_make_account())
    suspended, _activated, notifications = _capture(eventbus)

    await service.suspend("main", reason="위험 감지", suspended_by="rule-engine")

    # 도메인 이벤트 1회
    assert len(suspended) == 1
    assert suspended[0].account_id == "main"
    assert suspended[0].reason == "위험 감지"
    assert suspended[0].suspended_by == "rule-engine"

    # CRITICAL 알림 1회
    assert len(notifications) == 1
    note = notifications[0]
    assert note.level == "critical"
    assert note.category == "system"
    # account_id·reason·suspended_by 가 메시지에 포함
    assert "main" in note.message
    assert "위험 감지" in note.message
    assert "rule-engine" in note.message
    assert note.title


@pytest.mark.asyncio
async def test_activate_publishes_domain_event_and_info_notification(service, eventbus):
    """activate()는 AccountActivatedEvent AND INFO NotificationEvent 둘 다 발행."""
    await service.create(_make_account())
    await service.suspend("main", reason="테스트", suspended_by="system")

    _suspended, activated, notifications = _capture(eventbus)

    await service.activate("main", activated_by="admin")

    # 도메인 이벤트 1회
    assert len(activated) == 1
    assert activated[0].account_id == "main"
    assert activated[0].activated_by == "admin"

    # INFO 알림 1회 (CRITICAL 승격 금지)
    assert len(notifications) == 1
    note = notifications[0]
    assert note.level == "info"
    assert note.category == "system"
    assert "main" in note.message
    assert "admin" in note.message
    assert note.title


@pytest.mark.asyncio
async def test_suspend_all_publishes_one_critical_per_account(service, eventbus):
    """suspend_all(2 ACTIVE 계좌)은 계좌별 CRITICAL NotificationEvent 를 발행한다."""
    await service.create(_make_account(account_id="acc1"))
    await service.create(_make_account(account_id="acc2"))

    _suspended, _activated, notifications = _capture(eventbus)

    await service.suspend_all(reason="시스템 긴급 정지", suspended_by="system")

    assert len(notifications) == 2
    assert all(n.level == "critical" for n in notifications)
    assert all(n.category == "system" for n in notifications)
    # 두 계좌 각각에 대해 정확히 하나의 CRITICAL 알림이 발행되어야 한다.
    assert any("acc1" in n.message for n in notifications)
    assert any("acc2" in n.message for n in notifications)


@pytest.mark.asyncio
async def test_suspend_already_suspended_raises_and_publishes_nothing(
    service, eventbus
):
    """이미 SUSPENDED면 raise하고 도메인/알림 이벤트 미발행 (기존 invariant)."""
    await service.create(_make_account())
    await service.suspend("main", reason="첫 정지", suspended_by="system")

    suspended, _activated, notifications = _capture(eventbus)

    with pytest.raises(AccountAlreadySuspendedError):
        await service.suspend("main", reason="중복", suspended_by="system")

    assert suspended == []
    assert notifications == []
    # 상태는 SUSPENDED 그대로
    account = await service.get("main")
    assert account.status == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_activate_already_active_publishes_nothing(service, eventbus):
    """이미 ACTIVE면 early-return — 도메인/알림 이벤트를 발행하지 않는다."""
    await service.create(_make_account())

    _suspended, activated, notifications = _capture(eventbus)

    await service.activate("main", activated_by="admin")

    assert activated == []
    assert notifications == []
