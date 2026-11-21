"""계좌·멤버·회로차단기 상태 전이의 특성 테스트 (#2657).

가드가 있는 메서드(계좌 ``suspend``·``activate``·``delete``, 멤버
``suspend``·``reactivate``·``revoke``)마다 허용하는 이전 상태와 거부하는
이전 상태를 지금 동작 그대로 잠근다. 기대값은 모두 리터럴(상태 문자열,
예외 메시지 전체, 발행된 이벤트 타입 목록)이다. 이전 상태는 원시 SQL로
DB에 넣고, 계좌는 새 서비스를 초기화해 캐시가 DB에서 읽은 값을 보게 한다.

회로차단기는 ``_transition`` 을 부르는 네 자리(``state`` 의 타임아웃,
``record_success``, ``record_failure`` 의 시험 실패와 임계 도달)의 허용 경로와
지금 닿는 「전이 없음」 경로를 공개 API로만 몰아 상태와 발행 이벤트로 잠근다.

뒤쪽은 두 전이표가 리터럴로 적은 쌍과 같은지, 전이 함수가 3×3=9쌍에서 허용
쌍만 통과시키는지 본다(멤버는 enum·``str`` 현재 값과 표 밖 문자열까지).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

import ante.broker.circuit_breaker as circuit_module
from ante.account.errors import AccountAlreadySuspendedError, AccountDeletedError
from ante.account.models import ACCOUNT_STATUS_TRANSITIONS, Account, AccountStatus
from ante.account.service import AccountService
from ante.account.service import _transition_status as account_transition
from ante.broker.circuit_breaker import CircuitBreaker
from ante.broker.exceptions import CircuitOpenError
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
    AccountSuspendedEvent,
    CircuitBreakerEvent,
    MemberReactivatedEvent,
    MemberRevokedEvent,
    MemberSuspendedEvent,
    NotificationEvent,
)
from ante.member.errors import MemberStateConflictError
from ante.member.models import (
    MEMBER_STATUS_TRANSITIONS,
    Member,
    MemberStatus,
    MemberType,
)
from ante.member.service import MemberService
from ante.member.service import _transition_status as member_transition

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


# ── 회로차단기 ───────────────────────────────────────────────────


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    fake = _Clock()
    monkeypatch.setattr(
        circuit_module, "time", SimpleNamespace(monotonic=fake.monotonic)
    )
    return fake


@pytest.fixture
async def circuit_events(eventbus: EventBus) -> list[tuple[Any, ...]]:
    seen: list[tuple[Any, ...]] = []

    async def _on_circuit(event: CircuitBreakerEvent) -> None:
        seen.append(
            (
                "CircuitBreakerEvent",
                event.broker,
                event.old_state,
                event.new_state,
                event.failure_count,
                event.reason,
            )
        )

    async def _on_notification(event: NotificationEvent) -> None:
        seen.append(("NotificationEvent", event.level, event.title, event.message))

    eventbus.subscribe(CircuitBreakerEvent, _on_circuit)
    eventbus.subscribe(NotificationEvent, _on_notification)
    return seen


async def _drain() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def _breaker(eventbus: EventBus) -> CircuitBreaker:
    return CircuitBreaker(
        failure_threshold=3, recovery_timeout=60.0, eventbus=eventbus, name="cb-2657"
    )


async def _open_breaker(
    eventbus: EventBus, events: list[tuple[Any, ...]]
) -> CircuitBreaker:
    breaker = _breaker(eventbus)
    for _ in range(3):
        breaker.record_failure()
    await _drain()
    assert breaker.state == "open"
    events.clear()
    return breaker


async def _half_open_breaker(
    eventbus: EventBus, events: list[tuple[Any, ...]], clock: _Clock
) -> CircuitBreaker:
    breaker = await _open_breaker(eventbus, events)
    clock.now += 60.0
    assert breaker.state == "half_open"
    await _drain()
    events.clear()
    return breaker


async def test_circuit_closed_failures_below_threshold_stay_closed(
    eventbus, circuit_events, clock
):
    breaker = _breaker(eventbus)
    breaker.record_failure()
    breaker.record_failure()
    await _drain()
    assert breaker.state == "closed"
    assert breaker.failure_count == 2
    assert circuit_events == []


async def test_circuit_closed_threshold_reached_opens(eventbus, circuit_events, clock):
    breaker = _breaker(eventbus)
    for _ in range(3):
        breaker.record_failure()
    await _drain()
    assert breaker._state == "open"
    assert circuit_events == [
        ("CircuitBreakerEvent", "cb-2657", "closed", "open", 3, "연속 3회 실패"),
        (
            "NotificationEvent",
            "error",
            "서킷 브레이커 차단",
            "브로커 `cb-2657`\nclosed → *open* (연속 3회 실패)",
        ),
    ]


async def test_circuit_open_failure_again_stays_open(eventbus, circuit_events, clock):
    breaker = await _open_breaker(eventbus, circuit_events)
    breaker.record_failure()
    await _drain()
    assert breaker._state == "open"
    assert breaker.failure_count == 4
    assert circuit_events == []


async def test_circuit_open_before_timeout_stays_open_and_blocks(
    eventbus, circuit_events, clock
):
    breaker = await _open_breaker(eventbus, circuit_events)
    clock.now += 59.0
    assert breaker.state == "open"
    with pytest.raises(Exception) as exc_info:
        breaker.check()
    _assert_exact(
        exc_info,
        CircuitOpenError,
        "Circuit breaker OPEN — 3회 연속 실패, 60초 후 재시도",
    )
    await _drain()
    assert circuit_events == []


async def test_circuit_open_timeout_moves_to_half_open(eventbus, circuit_events, clock):
    breaker = await _open_breaker(eventbus, circuit_events)
    clock.now += 60.0
    assert breaker.state == "half_open"
    await _drain()
    assert breaker._state == "half_open"
    assert circuit_events == [
        (
            "CircuitBreakerEvent",
            "cb-2657",
            "open",
            "half_open",
            3,
            "recovery_timeout 경과",
        ),
    ]


async def test_circuit_half_open_state_read_stays_half_open(
    eventbus, circuit_events, clock
):
    breaker = await _half_open_breaker(eventbus, circuit_events, clock)
    clock.now += 600.0
    assert breaker.state == "half_open"
    breaker.check()
    await _drain()
    assert circuit_events == []


async def test_circuit_half_open_failure_reopens(eventbus, circuit_events, clock):
    breaker = await _half_open_breaker(eventbus, circuit_events, clock)
    breaker.record_failure()
    await _drain()
    assert breaker._state == "open"
    assert circuit_events == [
        (
            "CircuitBreakerEvent",
            "cb-2657",
            "half_open",
            "open",
            4,
            "HALF_OPEN 시험 실패",
        ),
        (
            "NotificationEvent",
            "error",
            "서킷 브레이커 차단",
            "브로커 `cb-2657`\nhalf_open → *open* (HALF_OPEN 시험 실패)",
        ),
    ]


async def test_circuit_half_open_success_closes(eventbus, circuit_events, clock):
    breaker = await _half_open_breaker(eventbus, circuit_events, clock)
    breaker.record_success()
    await _drain()
    assert breaker._state == "closed"
    assert breaker.failure_count == 0
    assert circuit_events == [
        ("CircuitBreakerEvent", "cb-2657", "half_open", "closed", 3, "API 호출 성공"),
        (
            "NotificationEvent",
            "info",
            "서킷 브레이커 복구",
            "브로커 `cb-2657`\nhalf_open → *closed* (API 호출 성공)",
        ),
    ]


async def test_circuit_open_success_closes_directly(eventbus, circuit_events, clock):
    breaker = await _open_breaker(eventbus, circuit_events)
    breaker.record_success()
    await _drain()
    assert breaker._state == "closed"
    assert breaker.failure_count == 0
    assert circuit_events == [
        ("CircuitBreakerEvent", "cb-2657", "open", "closed", 3, "API 호출 성공"),
        (
            "NotificationEvent",
            "info",
            "서킷 브레이커 복구",
            "브로커 `cb-2657`\nopen → *closed* (API 호출 성공)",
        ),
    ]


async def test_circuit_closed_success_does_not_transition(
    eventbus, circuit_events, clock
):
    breaker = _breaker(eventbus)
    breaker.record_failure()
    breaker.record_success()
    await _drain()
    assert breaker._state == "closed"
    assert breaker.failure_count == 0
    assert circuit_events == []


def test_circuit_without_eventbus_or_loop_still_transitions(clock):
    breaker = CircuitBreaker(failure_threshold=1, recovery_timeout=60.0, name="x")
    breaker.record_failure()
    assert breaker._state == "open"
    clock.now += 60.0
    assert breaker.state == "half_open"
    breaker.record_success()
    assert breaker._state == "closed"


# ── 전이표와 전이 함수 ────────────────────────────────────────────

ACCOUNT_ALLOWED_PAIRS = {
    ("active", "suspended"),
    ("active", "deleted"),
    ("suspended", "active"),
    ("suspended", "deleted"),
}

MEMBER_ALLOWED_PAIRS = {
    ("active", "suspended"),
    ("active", "revoked"),
    ("suspended", "active"),
    ("suspended", "revoked"),
}

ACCOUNT_ALL_PAIRS = [(c, t) for c in ACCOUNT_STATUSES for t in ACCOUNT_STATUSES]
MEMBER_ALL_PAIRS = [(c, t) for c in MEMBER_STATUSES for t in MEMBER_STATUSES]


def _pairs(table: dict[Any, set[Any]]) -> set[tuple[str, str]]:
    return {
        (str(current), str(target))
        for current, targets in table.items()
        for target in targets
    }


def test_account_transition_table_equals_the_four_literal_pairs():
    assert sorted(str(k) for k in ACCOUNT_STATUS_TRANSITIONS) == sorted(
        ACCOUNT_STATUSES
    )
    assert _pairs(ACCOUNT_STATUS_TRANSITIONS) == ACCOUNT_ALLOWED_PAIRS
    assert len(ACCOUNT_ALLOWED_PAIRS) == 4
    assert len(ACCOUNT_ALL_PAIRS) == 9


def test_member_transition_table_equals_the_four_literal_pairs():
    assert sorted(str(k) for k in MEMBER_STATUS_TRANSITIONS) == sorted(MEMBER_STATUSES)
    assert _pairs(MEMBER_STATUS_TRANSITIONS) == MEMBER_ALLOWED_PAIRS
    assert len(MEMBER_ALLOWED_PAIRS) == 4
    assert len(MEMBER_ALL_PAIRS) == 9


def _account_with(status: AccountStatus) -> Account:
    return Account(
        account_id="acct-1",
        name="",
        exchange="TEST",
        currency="KRW",
        status=status,
    )


@pytest.mark.parametrize(("current", "target"), ACCOUNT_ALL_PAIRS)
def test_account_transition_status_over_all_9_pairs(current, target):
    account = _account_with(AccountStatus(current))
    if (current, target) in ACCOUNT_ALLOWED_PAIRS:
        returned = account_transition(account, AccountStatus(target))
        assert returned == target
        assert type(returned) is AccountStatus
        assert account.status == target
        return
    with pytest.raises(Exception) as exc_info:
        account_transition(account, AccountStatus(target))
    _assert_exact(
        exc_info,
        ValueError,
        f"계좌 'acct-1' 상태 '{current}' 에서 '{target}' 으로 전이할 수 없습니다.",
    )
    assert account.status == current


def _member_with(status: str) -> Member:
    return Member(member_id="m-1", type="agent", role="default", status=status)


@pytest.mark.parametrize("as_enum", [True, False], ids=["enum", "str"])
@pytest.mark.parametrize(("current", "target"), MEMBER_ALL_PAIRS)
def test_member_transition_status_over_all_9_pairs(current, target, as_enum):
    member = _member_with(MemberStatus(current) if as_enum else current)
    if (current, target) in MEMBER_ALLOWED_PAIRS:
        returned = member_transition(member, MemberStatus(target), "act")
        assert returned == target
        assert type(returned) is MemberStatus
        assert member.status == target
        return
    with pytest.raises(Exception) as exc_info:
        member_transition(member, MemberStatus(target), "act")
    _assert_exact(
        exc_info,
        MemberStateConflictError,
        f"멤버 'm-1' 상태 '{current}' 에서 'act' 작업을 수행할 수 없습니다.",
    )
    assert exc_info.value.code == "MEMBER_STATE_CONFLICT"
    assert exc_info.value.current_status == current
    assert exc_info.value.requested_action == "act"
    assert member.status == current


@pytest.mark.parametrize("target", MEMBER_STATUSES)
def test_member_transition_status_rejects_unknown_current_string(target):
    member = _member_with("legacy")
    with pytest.raises(Exception) as exc_info:
        member_transition(member, MemberStatus(target), "act")
    _assert_exact(
        exc_info,
        MemberStateConflictError,
        "멤버 'm-1' 상태 'legacy' 에서 'act' 작업을 수행할 수 없습니다.",
    )
    assert exc_info.value.current_status == "legacy"
    assert member.status == "legacy"
