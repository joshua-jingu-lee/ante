"""계좌·멤버 상태 전이의 특성 테스트 (#2657).

가드가 있는 메서드(계좌 ``suspend``·``activate``·``delete``, 멤버
``suspend``·``reactivate``·``revoke``)마다 허용하는 이전 상태와 거부하는
이전 상태를 지금 동작 그대로 잠근다. 기대값은 모두 리터럴(상태 문자열,
예외 메시지 전체, 발행된 이벤트 타입 목록)이다. 이전 상태는 원시 SQL로
DB에 넣고, 계좌는 새 서비스를 초기화해 캐시가 DB에서 읽은 값을 보게 한다.
"""

from __future__ import annotations

from typing import Any

import pytest

from ante.account.errors import AccountAlreadySuspendedError, AccountDeletedError
from ante.account.models import Account
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
    AccountSuspendedEvent,
    MemberReactivatedEvent,
    MemberRevokedEvent,
    MemberSuspendedEvent,
    NotificationEvent,
)
from ante.member.errors import MemberStateConflictError
from ante.member.models import MemberType
from ante.member.service import MemberService

ACCOUNT_STATUSES = ("active", "suspended", "deleted")
MEMBER_STATUSES = ("active", "suspended", "revoked")

ACCOUNT_ID = "acct-2657"
MASTER_ID = "owner"
TARGET_ID = "agent-2657"


def _assert_exact(exc_info: pytest.ExceptionInfo[Any], cls: type, message: str):
    assert type(exc_info.value) is cls
    assert str(exc_info.value) == message


# ── 공용 픽스처 ──────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "state-2657.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def published(eventbus: EventBus) -> list[str]:
    seen: list[str] = []

    async def _record(event: Any) -> None:
        seen.append(type(event).__name__)

    for event_type in (
        AccountSuspendedEvent,
        AccountActivatedEvent,
        MemberSuspendedEvent,
        MemberReactivatedEvent,
        MemberRevokedEvent,
        NotificationEvent,
    ):
        eventbus.subscribe(event_type, _record)
    return seen


# ── 계좌 ─────────────────────────────────────────────────────────


async def _account_service_in(db: Database, eventbus: EventBus, status: str) -> Any:
    """계좌 하나를 만들고 원시 SQL로 상태를 바꾼 뒤 새 서비스로 다시 읽는다."""
    seed = AccountService(db, EventBus())
    await seed.initialize()
    await seed.create(
        Account(
            account_id=ACCOUNT_ID,
            name="특성 테스트",
            exchange="TEST",
            currency="KRW",
            broker_type="test",
            credentials={"app_key": "test", "app_secret": "test"},
        )
    )
    await db.execute(
        "UPDATE accounts SET status = ?, updated_at = ? WHERE account_id = ?",
        (status, "2026-01-01T00:00:00+00:00", ACCOUNT_ID),
    )
    service = AccountService(db, eventbus)
    await service.initialize()
    return service


async def _account_row(db: Database) -> dict[str, Any]:
    row = await db.fetch_one(
        "SELECT status, updated_at FROM accounts WHERE account_id = ?",
        (ACCOUNT_ID,),
    )
    assert row is not None
    return {"status": row["status"], "updated_at": row["updated_at"]}


@pytest.mark.parametrize("prev", ["active", "suspended"])
async def test_account_previous_status_is_loaded_into_cache(db, eventbus, prev):
    service = await _account_service_in(db, eventbus, prev)
    assert service._accounts[ACCOUNT_ID].status == prev


async def test_account_deleted_is_read_from_db_not_cache(db, eventbus):
    service = await _account_service_in(db, eventbus, "deleted")
    assert ACCOUNT_ID not in service._accounts
    account = await service.get(ACCOUNT_ID)
    assert account.status == "deleted"


@pytest.mark.parametrize(
    ("prev", "cls", "message"),
    [
        (
            "deleted",
            AccountDeletedError,
            "삭제된 계좌 'acct-2657'는 정지할 수 없습니다.",
        ),
        (
            "suspended",
            AccountAlreadySuspendedError,
            "이미 정지된 계좌입니다: 'acct-2657'",
        ),
    ],
)
async def test_account_suspend_rejects(db, eventbus, published, prev, cls, message):
    service = await _account_service_in(db, eventbus, prev)
    with pytest.raises(Exception) as exc_info:
        await service.suspend(ACCOUNT_ID, reason="r", suspended_by="tester")
    _assert_exact(exc_info, cls, message)
    assert await _account_row(db) == {
        "status": prev,
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    assert published == []


async def test_account_activate_rejects_deleted(db, eventbus, published):
    service = await _account_service_in(db, eventbus, "deleted")
    with pytest.raises(Exception) as exc_info:
        await service.activate(ACCOUNT_ID, activated_by="tester")
    _assert_exact(
        exc_info,
        AccountDeletedError,
        "삭제된 계좌 'acct-2657'는 활성화할 수 없습니다.",
    )
    assert await _account_row(db) == {
        "status": "deleted",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    assert published == []


async def test_account_delete_rejects_deleted(db, eventbus, published):
    service = await _account_service_in(db, eventbus, "deleted")
    assert service._runtime_started is False
    with pytest.raises(Exception) as exc_info:
        await service.delete(ACCOUNT_ID, deleted_by="tester")
    _assert_exact(exc_info, AccountDeletedError, "이미 삭제된 계좌입니다: 'acct-2657'")
    assert await _account_row(db) == {
        "status": "deleted",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    assert published == []


async def test_account_activate_on_active_is_a_noop(db, eventbus, published):
    service = await _account_service_in(db, eventbus, "active")
    assert await service.activate(ACCOUNT_ID, activated_by="tester") is None
    assert service._accounts[ACCOUNT_ID].status == "active"
    assert await _account_row(db) == {
        "status": "active",
        "updated_at": "2026-01-01T00:00:00+00:00",
    }
    assert published == []


async def test_account_suspend_allows_active(db, eventbus, published):
    service = await _account_service_in(db, eventbus, "active")
    cached = service._accounts[ACCOUNT_ID]
    assert await service.suspend(ACCOUNT_ID, reason="r", suspended_by="t") is None
    assert service._accounts[ACCOUNT_ID] is cached
    assert cached.status == "suspended"
    row = await _account_row(db)
    assert row["status"] == "suspended"
    assert row["updated_at"] != "2026-01-01T00:00:00+00:00"
    assert published == ["AccountSuspendedEvent", "NotificationEvent"]


async def test_account_activate_allows_suspended(db, eventbus, published):
    service = await _account_service_in(db, eventbus, "suspended")
    cached = service._accounts[ACCOUNT_ID]
    assert await service.activate(ACCOUNT_ID, activated_by="tester") is None
    assert service._accounts[ACCOUNT_ID] is cached
    assert cached.status == "active"
    row = await _account_row(db)
    assert row["status"] == "active"
    assert row["updated_at"] != "2026-01-01T00:00:00+00:00"
    assert published == ["AccountActivatedEvent", "NotificationEvent"]


@pytest.mark.parametrize(
    ("prev", "events"),
    [("active", ["AccountSuspendedEvent"]), ("suspended", [])],
)
async def test_account_delete_allows(db, eventbus, published, prev, events):
    service = await _account_service_in(db, eventbus, prev)
    assert service._runtime_started is False
    cached = service._accounts[ACCOUNT_ID]
    assert await service.delete(ACCOUNT_ID, deleted_by="tester") is None
    assert ACCOUNT_ID not in service._accounts
    assert cached.status == "deleted"
    row = await _account_row(db)
    assert row["status"] == "deleted"
    assert row["updated_at"] != "2026-01-01T00:00:00+00:00"
    assert published == events


# ── 멤버 ─────────────────────────────────────────────────────────


async def _member_service_in(db: Database, eventbus: EventBus, status: str) -> Any:
    """master와 master가 아닌 대상 멤버를 만들고 대상의 상태를 원시 SQL로 바꾼다."""
    service = MemberService(db, eventbus)
    await service.initialize()
    await service.bootstrap_master(MASTER_ID, "pass123")
    await service.register(TARGET_ID, MemberType.AGENT, registered_by=MASTER_ID)
    await db.execute(
        "UPDATE members SET status = ? WHERE member_id = ?",
        (status, TARGET_ID),
    )
    return service


async def _member_status(db: Database) -> str:
    row = await db.fetch_one(
        "SELECT status FROM members WHERE member_id = ?",
        (TARGET_ID,),
    )
    assert row is not None
    return str(row["status"])


async def test_member_previous_status_is_read_from_db_as_plain_str(db, eventbus):
    service = await _member_service_in(db, eventbus, "suspended")
    member = await service.get(TARGET_ID)
    assert member is not None
    assert type(member.status) is str
    assert member.status == "suspended"


@pytest.mark.parametrize("prev", ["suspended", "revoked"])
async def test_member_suspend_rejects(db, eventbus, published, prev):
    service = await _member_service_in(db, eventbus, prev)
    published.clear()
    with pytest.raises(Exception) as exc_info:
        await service.suspend(TARGET_ID, suspended_by=MASTER_ID)
    _assert_exact(
        exc_info,
        MemberStateConflictError,
        f"멤버 'agent-2657' 상태 '{prev}' 에서 'suspend' 작업을 수행할 수 없습니다.",
    )
    assert exc_info.value.current_status == prev
    assert exc_info.value.requested_action == "suspend"
    assert await _member_status(db) == prev
    assert published == []


@pytest.mark.parametrize("prev", ["active", "revoked"])
async def test_member_reactivate_rejects(db, eventbus, published, prev):
    service = await _member_service_in(db, eventbus, prev)
    published.clear()
    with pytest.raises(Exception) as exc_info:
        await service.reactivate(TARGET_ID, reactivated_by=MASTER_ID)
    _assert_exact(
        exc_info,
        MemberStateConflictError,
        f"멤버 'agent-2657' 상태 '{prev}' 에서 'reactivate' 작업을 수행할 수 없습니다.",
    )
    assert exc_info.value.current_status == prev
    assert exc_info.value.requested_action == "reactivate"
    assert await _member_status(db) == prev
    assert published == []


async def test_member_revoke_rejects_revoked(db, eventbus, published):
    service = await _member_service_in(db, eventbus, "revoked")
    published.clear()
    with pytest.raises(Exception) as exc_info:
        await service.revoke(TARGET_ID, revoked_by=MASTER_ID)
    _assert_exact(
        exc_info,
        PermissionError,
        "revoke은(는) active, suspended 상태에서만 가능합니다 (현재: revoked)",
    )
    assert await _member_status(db) == "revoked"
    assert published == []


async def test_member_suspend_allows_active(db, eventbus, published):
    service = await _member_service_in(db, eventbus, "active")
    published.clear()
    member = await service.suspend(TARGET_ID, suspended_by=MASTER_ID)
    assert member.member_id == TARGET_ID
    assert member.status == "suspended"
    assert member.suspended_at != ""
    assert await _member_status(db) == "suspended"
    assert published == ["MemberSuspendedEvent", "NotificationEvent"]


async def test_member_reactivate_allows_suspended(db, eventbus, published):
    service = await _member_service_in(db, eventbus, "suspended")
    published.clear()
    member = await service.reactivate(TARGET_ID, reactivated_by=MASTER_ID)
    assert member.member_id == TARGET_ID
    assert member.status == "active"
    assert await _member_status(db) == "active"
    assert published == ["MemberReactivatedEvent"]


@pytest.mark.parametrize("prev", ["active", "suspended"])
async def test_member_revoke_allows(db, eventbus, published, prev):
    service = await _member_service_in(db, eventbus, prev)
    published.clear()
    member = await service.revoke(TARGET_ID, revoked_by=MASTER_ID)
    assert member.member_id == TARGET_ID
    assert member.status == "revoked"
    assert member.token_hash == ""
    assert member.revoked_at != ""
    assert await _member_status(db) == "revoked"
    assert published == ["MemberRevokedEvent", "NotificationEvent"]
