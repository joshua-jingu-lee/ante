"""전체 정지가 어느 정지 이벤트 구독자보다 먼저 모든 활성 계좌를 막는지 잠근다 (#3077).

정지 이벤트의 구독자가 막혀 있는 동안(예: 앞 계좌 봇의 주문 취소가 브로커
응답을 기다리는 동안) 뒤 계좌의 메모리 상태가 이미 SUSPENDED이고, 그 계좌의
매수가 규칙 엔진의 계좌 상태 검사에서 ``account_suspended`` 로 거부되어야 한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
import pytest_asyncio

from ante.account.errors import (
    AccountAlreadySuspendedError,
    AccountSuspendNotPersistedError,
)
from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountSuspendedEvent,
    NotificationEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import RuleEngine
from tests.unit._readiness_gate_helpers import ready_registry
from tests.unit._rule_engine_helpers import StubTreasury

_KILL_SWITCH_TITLE = "거래 상태 변경 (킬 스위치)"


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "suspend_all_blocks_first.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest_asyncio.fixture
async def service(db, eventbus):
    svc = AccountService(db, eventbus)
    await svc.initialize()
    return svc


def _make_account(account_id: str) -> Account:
    return Account(
        account_id=account_id,
        name="테스트",
        exchange="TEST",
        currency="KRW",
        broker_type="test",
        credentials={"app_key": "test", "app_secret": "test"},
    )


async def _db_status(db: Database, account_id: str) -> str:
    row = await db.fetch_one(
        "SELECT status FROM accounts WHERE account_id = ?", (account_id,)
    )
    assert row is not None
    return row["status"]


def _buy(account_id: str) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=account_id,
        bot_id="bot-b",
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=1.0,
        order_type="limit",
        price=50000.0,
    )


async def _rule_engine(
    service: AccountService, account_id: str
) -> tuple[RuleEngine, list[OrderRejectedEvent], list[OrderValidatedEvent]]:
    bus = EventBus()
    rejected: list[OrderRejectedEvent] = []
    validated: list[OrderValidatedEvent] = []
    bus.subscribe(OrderRejectedEvent, rejected.append)
    bus.subscribe(OrderValidatedEvent, validated.append)
    account = await service.get(account_id)
    engine = RuleEngine(
        eventbus=bus,
        account_id=account_id,
        account_service=service,
        treasury=StubTreasury(),
        account=account,
        runtime_readiness=ready_registry(
            account_id,
            broker_type=account.broker_type,
            trading_mode=account.trading_mode,
        ),
    )
    return engine, rejected, validated


@pytest.mark.asyncio
async def test_every_active_account_is_suspended_before_any_subscriber_returns(
    service, db, eventbus
):
    for account_id in ("acct-a", "acct-b"):
        await service.create(_make_account(account_id))
    engine, rejected, validated = await _rule_engine(service, "acct-b")

    entered = asyncio.Event()
    release = asyncio.Event()
    snapshots: list[dict[str, AccountStatus]] = []
    event_order: list[str] = []
    notices: list[NotificationEvent] = []

    async def blocking_subscriber(event: AccountSuspendedEvent) -> None:
        event_order.append(event.account_id)
        snapshots.append(
            {
                account_id: service._accounts[account_id].status
                for account_id in ("acct-a", "acct-b")
            }
        )
        if not entered.is_set():
            entered.set()
            await release.wait()

    async def record_notice(event: NotificationEvent) -> None:
        notices.append(event)

    eventbus.subscribe(AccountSuspendedEvent, blocking_subscriber)
    eventbus.subscribe(NotificationEvent, record_notice)

    task = asyncio.create_task(
        service.suspend_all(reason="킬 스위치", suspended_by="admin")
    )
    entered_wait = asyncio.create_task(entered.wait())
    await asyncio.wait(
        {task, entered_wait}, timeout=5, return_when=asyncio.FIRST_COMPLETED
    )
    entered_wait.cancel()
    assert entered.is_set(), "정지 이벤트 구독자에 들어오지 않았다"

    assert service._accounts["acct-a"].status == AccountStatus.SUSPENDED
    assert service._accounts["acct-b"].status == AccountStatus.SUSPENDED
    assert not task.done()
    await engine._on_order_request(_buy("acct-b"))
    assert [e.reason for e in rejected] == ["account_suspended"]
    assert validated == []

    release.set()
    results = await task

    assert results == [
        {
            "account_id": account_id,
            "previous_status": "active",
            "status": "suspended",
            "changed": True,
        }
        for account_id in ("acct-a", "acct-b")
    ]
    assert event_order == ["acct-a", "acct-b"]
    assert (
        snapshots
        == [{"acct-a": AccountStatus.SUSPENDED, "acct-b": AccountStatus.SUSPENDED}] * 2
    )
    kill_switch = [n for n in notices if n.title == _KILL_SWITCH_TITLE]
    assert [n.level for n in kill_switch] == ["critical", "critical"]
    for account_id in ("acct-a", "acct-b"):
        assert await _db_status(db, account_id) == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False


def _fail_status_update_for(
    monkeypatch, service: AccountService, account_id: str
) -> None:
    real_execute = service._db.execute

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if "SET status" in " ".join(sql.split()) and params[-1] == account_id:
            raise RuntimeError("디스크 오류")
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)


@pytest.mark.asyncio
async def test_mixed_accounts_report_pre_call_status_and_retry_only_unpersisted(
    service, db, eventbus, monkeypatch
):
    for account_id in ("active", "persisted", "unpersisted", "deleted"):
        await service.create(_make_account(account_id))
    await service.delete("deleted", deleted_by="admin")
    await service.suspend("persisted", reason="준비", suspended_by="admin")
    _fail_status_update_for(monkeypatch, service, "unpersisted")
    with pytest.raises(AccountSuspendNotPersistedError):
        await service.suspend("unpersisted", reason="준비", suspended_by="admin")
    monkeypatch.undo()

    suspended_events: list[str] = []

    async def record(event: AccountSuspendedEvent) -> None:
        suspended_events.append(event.account_id)

    eventbus.subscribe(AccountSuspendedEvent, record)
    real_suspend = service.suspend
    raised: list[BaseException] = []

    async def suspend(account_id: str, reason: str, suspended_by: str) -> None:
        try:
            await real_suspend(account_id, reason, suspended_by)
        except AccountAlreadySuspendedError as exc:
            raised.append(exc)
            raise

    monkeypatch.setattr(service, "suspend", suspend)

    results = await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert [(r["account_id"], r["previous_status"], r["changed"]) for r in results] == [
        ("active", "active", True),
        ("persisted", "suspended", False),
        ("unpersisted", "suspended", False),
    ]
    assert all(r["status"] == "suspended" for r in results)
    assert suspended_events == ["active", "unpersisted"]
    assert raised == []
    for account_id in ("active", "persisted", "unpersisted"):
        assert await _db_status(db, account_id) == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False


def _record_suspend_calls(monkeypatch, service: AccountService) -> list[str]:
    called: list[str] = []
    real_suspend = service.suspend

    async def suspend(account_id: str, reason: str, suspended_by: str) -> None:
        called.append(account_id)
        await real_suspend(account_id, reason, suspended_by)

    monkeypatch.setattr(service, "suspend", suspend)
    return called


def _assert_changed_rows_were_suspended(
    results: list[dict[str, Any]], called: list[str], events: list[str]
) -> None:
    changed = {r["account_id"] for r in results if r["changed"]}
    assert changed <= set(called)
    assert changed <= set(events)


@pytest.mark.asyncio
async def test_activation_in_flight_does_not_drop_the_kill_switch_write(
    service, db, eventbus, monkeypatch
):
    for account_id in ("aaa", "bbb"):
        await service.create(_make_account(account_id))
    await service.suspend("bbb", reason="준비", suspended_by="admin")

    real_execute = service._db.execute
    activate_writing = asyncio.Event()
    activate_release = asyncio.Event()

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if (
            "SET status" in " ".join(sql.split())
            and params[0] == AccountStatus.ACTIVE
            and params[-1] == "bbb"
        ):
            activate_writing.set()
            await activate_release.wait()
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)
    called = _record_suspend_calls(monkeypatch, service)

    sub_entered = asyncio.Event()
    sub_release = asyncio.Event()
    events: list[str] = []

    async def blocking_subscriber(event: AccountSuspendedEvent) -> None:
        events.append(event.account_id)
        if event.account_id == "aaa":
            sub_entered.set()
            await sub_release.wait()

    eventbus.subscribe(AccountSuspendedEvent, blocking_subscriber)

    activating = asyncio.create_task(service.activate("bbb", activated_by="admin"))
    await asyncio.wait_for(activate_writing.wait(), timeout=5)
    halting = asyncio.create_task(
        service.suspend_all(reason="킬 스위치", suspended_by="admin")
    )
    await asyncio.wait_for(sub_entered.wait(), timeout=5)
    activate_release.set()
    await asyncio.wait_for(activating, timeout=5)
    assert service._accounts["bbb"].status == AccountStatus.SUSPENDED
    sub_release.set()
    results = await asyncio.wait_for(halting, timeout=5)

    assert [(r["account_id"], r["previous_status"], r["changed"]) for r in results] == [
        ("aaa", "active", True),
        ("bbb", "active", True),
    ]
    assert called == ["aaa", "bbb"]
    assert events == ["aaa", "bbb"]
    assert await _db_status(db, "bbb") == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False
    _assert_changed_rows_were_suspended(results, called, events)


@pytest.mark.parametrize("overlap", ["activate", "suspend", "delete"])
@pytest.mark.asyncio
async def test_changed_rows_were_suspended_in_this_call_under_overlaps(
    service, db, eventbus, monkeypatch, overlap
):
    for account_id in ("aaa", "bbb"):
        await service.create(_make_account(account_id))
    called = _record_suspend_calls(monkeypatch, service)
    events: list[str] = []
    done_overlap = False

    async def overlapping_subscriber(event: AccountSuspendedEvent) -> None:
        nonlocal done_overlap
        events.append(event.account_id)
        if event.account_id != "aaa" or done_overlap:
            return
        done_overlap = True
        if overlap == "activate":
            await service.activate("bbb", activated_by="admin")
        elif overlap == "suspend":
            await service.suspend("bbb", reason="개별", suspended_by="admin")
        else:
            await service.delete("bbb", deleted_by="admin")

    eventbus.subscribe(AccountSuspendedEvent, overlapping_subscriber)

    results = await asyncio.wait_for(
        service.suspend_all(reason="킬 스위치", suspended_by="admin"), timeout=5
    )

    _assert_changed_rows_were_suspended(results, called, events)
    if overlap == "delete":
        assert [r["account_id"] for r in results] == ["aaa"]
        assert await _db_status(db, "bbb") == AccountStatus.DELETED
    else:
        assert [r["account_id"] for r in results] == ["aaa", "bbb"]
        assert service._accounts["bbb"].status == AccountStatus.SUSPENDED
        assert await _db_status(db, "bbb") == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False
