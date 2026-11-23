"""계좌·멤버·회로차단기 상태 전이의 특성 테스트 (#2657).

가드가 있는 메서드(계좌 ``suspend``·``activate``·``delete``, 멤버
``suspend``·``reactivate``·``revoke``)마다 허용하는 이전 상태와 거부하는
이전 상태를 지금 동작 그대로 잠근다. 기대값은 모두 리터럴(상태 문자열,
예외 메시지 전체, 발행된 이벤트 타입 목록)이다. 이전 상태는 원시 SQL로
DB에 넣고, 계좌는 새 서비스를 초기화해 캐시가 DB에서 읽은 값을 보게 한다.

회로차단기는 ``_transition`` 을 부르는 네 자리(``state`` 의 타임아웃,
``record_success``, ``record_failure`` 의 시험 실패와 임계 도달)의 허용 경로와
지금 닿는 「전이 없음」 경로를 공개 API로만 몰아 상태와 발행 이벤트로 잠근다.

뒤쪽은 세 전이표가 리터럴로 적은 쌍과 같은지, 전이 함수(회로차단기는
``_transition``)가 3×3=9쌍에서 허용 쌍만 통과시키는지 본다(멤버는 enum·
``str`` 현재 값과 표 밖 문자열까지). ``TradeStatus``·``QuarterStatus`` 의 빈
전이표는 표 전체를 리터럴과 비교한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ante.account.errors import AccountAlreadySuspendedError, AccountDeletedError
from ante.account.models import ACCOUNT_STATUS_TRANSITIONS, Account, AccountStatus
from ante.account.service import AccountService
from ante.account.service import _transition_status as account_transition
from ante.broker.circuit_breaker import (
    CIRCUIT_STATE_TRANSITIONS,
    CircuitBreaker,
    CircuitState,
)
from ante.broker.exceptions import APIError, CircuitOpenError
from ante.broker.kis import KISDomesticAdapter
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
from ante.feed.pipeline.dart_collector import QUARTER_STATUS_TRANSITIONS
from ante.member.errors import MemberStateConflictError
from ante.member.models import (
    MEMBER_STATUS_TRANSITIONS,
    Member,
    MemberStatus,
    MemberType,
)
from ante.member.service import MemberService
from ante.member.service import _transition_status as member_transition
from ante.trade.models import TRADE_STATUS_TRANSITIONS

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
        MemberStateConflictError,
        "멤버 'agent-2657' 상태 'revoked' 에서 'revoke' 작업을 수행할 수 없습니다.",
    )
    assert exc_info.value.current_status == "revoked"
    assert exc_info.value.requested_action == "revoke"
    assert exc_info.value.code == "MEMBER_STATE_CONFLICT"
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


@pytest.fixture
def clock(manual_clock: Any) -> Any:
    return manual_clock


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
    eventbus: EventBus, events: list[tuple[Any, ...]], clock: Any
) -> CircuitBreaker:
    breaker = await _open_breaker(eventbus, events)
    clock.advance(60.0)
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
    clock.advance(59.0)
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
    clock.advance(60.0)
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
    clock.advance(600.0)
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


async def test_circuit_open_success_is_ignored(eventbus, circuit_events, clock):
    breaker = await _open_breaker(eventbus, circuit_events)
    last_failure_time = breaker._last_failure_time
    breaker.record_success()
    await _drain()
    assert breaker._state == "open"
    assert breaker.failure_count == 3
    assert breaker._last_failure_time == last_failure_time
    assert circuit_events == []
    with pytest.raises(Exception) as exc_info:
        breaker.check()
    _assert_exact(
        exc_info,
        CircuitOpenError,
        "Circuit breaker OPEN — 3회 연속 실패, 60초 후 재시도",
    )


async def test_circuit_open_success_ignored_then_half_open_success_closes(
    eventbus, circuit_events, clock
):
    breaker = await _open_breaker(eventbus, circuit_events)
    breaker.record_success()
    clock.advance(60.0)
    assert breaker.state == "half_open"
    breaker.record_success()
    await _drain()
    assert breaker._state == "closed"
    assert breaker.failure_count == 0
    assert circuit_events == [
        (
            "CircuitBreakerEvent",
            "cb-2657",
            "open",
            "half_open",
            3,
            "recovery_timeout 경과",
        ),
        ("CircuitBreakerEvent", "cb-2657", "half_open", "closed", 3, "API 호출 성공"),
        (
            "NotificationEvent",
            "info",
            "서킷 브레이커 복구",
            "브로커 `cb-2657`\nhalf_open → *closed* (API 호출 성공)",
        ),
    ]


async def test_circuit_open_success_after_timeout_without_check_does_not_close(
    eventbus, circuit_events, clock
):
    breaker = await _open_breaker(eventbus, circuit_events)
    clock.advance(60.0)
    breaker.record_success()
    await _drain()
    assert breaker._state == "open"
    assert breaker.failure_count == 3
    assert circuit_events == []


def _adapter_with(breaker: CircuitBreaker, monkeypatch: pytest.MonkeyPatch) -> Any:
    adapter = KISDomesticAdapter(
        config={
            "app_key": "test-key",
            "app_secret": "test-secret",
            "account_no": "1234567890",
            "is_paper": True,
        }
    )

    async def _no_wait(*args: Any) -> None:
        return None

    monkeypatch.setattr(adapter, "_circuit_breaker", breaker)
    monkeypatch.setattr(adapter, "_ensure_authenticated", _no_wait)
    monkeypatch.setattr(adapter, "_rate_limit_wait", _no_wait)
    monkeypatch.setattr(adapter._retry_handler, "wait_and_log", _no_wait)
    return adapter


def _fail_then_succeed(adapter: Any, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    attempts: list[str] = []

    async def _send_http(*args: Any) -> tuple[dict[str, Any], str]:
        attempts.append("send")
        if len(attempts) == 1:
            raise APIError("server busy", retryable=True, status_code=503)
        return {"rt_cd": "0"}, ""

    monkeypatch.setattr(adapter, "_send_http", _send_http)
    return attempts


_QUERY_URL = "https://example.invalid/uapi/domestic-stock/v1/quotations/inquire-price"


async def test_circuit_retry_success_after_opening_keeps_breaker_open(
    eventbus, circuit_events, clock, monkeypatch
):
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout=60.0, eventbus=eventbus, name="kis"
    )
    adapter = _adapter_with(breaker, monkeypatch)
    attempts = _fail_then_succeed(adapter, monkeypatch)
    result = await adapter._request_with_cont("GET", _QUERY_URL, "FHKST01010100")
    await _drain()
    assert result == ({"rt_cd": "0"}, "")
    assert attempts == ["send", "send"]
    assert breaker._state == "open"
    assert breaker.failure_count == 1
    assert [event[:4] for event in circuit_events] == [
        ("CircuitBreakerEvent", "kis", "closed", "open"),
        (
            "NotificationEvent",
            "error",
            "서킷 브레이커 차단",
            "브로커 `kis`\nclosed → *open* (연속 1회 실패)",
        ),
    ]
    with pytest.raises(CircuitOpenError):
        await adapter._request_with_cont("GET", _QUERY_URL, "FHKST01010100")
    assert attempts == ["send", "send"]


async def test_circuit_half_open_trial_retry_success_keeps_breaker_open(
    eventbus, circuit_events, clock, monkeypatch
):
    breaker = CircuitBreaker(
        failure_threshold=1, recovery_timeout=60.0, eventbus=eventbus, name="kis"
    )
    breaker.record_failure()
    await _drain()
    circuit_events.clear()
    clock.advance(60.0)
    adapter = _adapter_with(breaker, monkeypatch)
    attempts = _fail_then_succeed(adapter, monkeypatch)
    result = await adapter._request_with_cont("GET", _QUERY_URL, "FHKST01010100")
    await _drain()
    assert result == ({"rt_cd": "0"}, "")
    assert attempts == ["send", "send"]
    assert breaker._state == "open"
    assert [event[:4] for event in circuit_events] == [
        ("CircuitBreakerEvent", "kis", "open", "half_open"),
        ("CircuitBreakerEvent", "kis", "half_open", "open"),
        (
            "NotificationEvent",
            "error",
            "서킷 브레이커 차단",
            "브로커 `kis`\nhalf_open → *open* (HALF_OPEN 시험 실패)",
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
    clock.advance(60.0)
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


CIRCUIT_STATES = ("closed", "open", "half_open")

CIRCUIT_ALLOWED_PAIRS = {
    ("closed", "open"),
    ("open", "half_open"),
    ("half_open", "open"),
    ("half_open", "closed"),
}

CIRCUIT_ALL_PAIRS = [(c, t) for c in CIRCUIT_STATES for t in CIRCUIT_STATES]


def test_circuit_transition_table_equals_the_four_literal_pairs():
    assert sorted(str(k) for k in CIRCUIT_STATE_TRANSITIONS) == sorted(CIRCUIT_STATES)
    assert _pairs(CIRCUIT_STATE_TRANSITIONS) == CIRCUIT_ALLOWED_PAIRS
    assert len(CIRCUIT_ALLOWED_PAIRS) == 4
    assert len(CIRCUIT_ALL_PAIRS) == 9


_CIRCUIT_ALLOWED_EVENTS = {
    "open": "서킷 브레이커 차단",
    "closed": "서킷 브레이커 복구",
    "half_open": None,
}


@pytest.mark.parametrize(("current", "target"), CIRCUIT_ALL_PAIRS)
async def test_circuit_transition_over_all_9_pairs(
    eventbus, circuit_events, current, target
):
    breaker = _breaker(eventbus)
    breaker._state = CircuitState(current)
    if (current, target) in CIRCUIT_ALLOWED_PAIRS:
        assert breaker._transition(CircuitState(target), "pair") is None
        await _drain()
        assert breaker._state == target
        kinds = [event[0] for event in circuit_events]
        title = _CIRCUIT_ALLOWED_EVENTS[target]
        if title is None:
            assert kinds == ["CircuitBreakerEvent"]
        else:
            assert kinds == ["CircuitBreakerEvent", "NotificationEvent"]
            assert circuit_events[1][2] == title
        assert circuit_events[0] == (
            "CircuitBreakerEvent",
            "cb-2657",
            current,
            target,
            0,
            "pair",
        )
        return
    with pytest.raises(Exception) as exc_info:
        breaker._transition(CircuitState(target), "pair")
    _assert_exact(
        exc_info,
        ValueError,
        f"CircuitBreaker[cb-2657] {current} → {target} 전이는 허용되지 않습니다.",
    )
    await _drain()
    assert breaker._state == current
    assert circuit_events == []


def test_trade_status_transition_table_is_empty_for_every_member():
    assert {str(k): v for k, v in TRADE_STATUS_TRANSITIONS.items()} == {
        "filled": set(),
        "cancelled": set(),
        "rejected": set(),
        "failed": set(),
        "adjusted": set(),
        "modified": set(),
    }


def test_quarter_status_transition_table_is_empty_for_every_member():
    assert {k.value: v for k, v in QUARTER_STATUS_TRANSITIONS.items()} == {
        "ok": set(),
        "halt": set(),
        "skip_empty": set(),
    }
