"""계좌 상태 UPDATE가 실패할 때 캐시와 DB가 어긋나지 않는지 검증한다 (#2667).

``activate``·``delete``는 실패하면(취소 포함) 캐시의 ``status``·``updated_at``을
호출 전 값으로 되돌리고 같은 예외를 다시 올린다. ``suspend``의 실패 정책은
유지관리자 결정 대기라 지금의 동작(메모리만 정지로 남는다)을 그대로 잠근다.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio

from ante.account.errors import (
    AccountActivateAllFailedError,
    AccountSuspendAllFailedError,
)
from ante.account.models import Account, AccountStatus
from ante.account.service import AccountService
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
    AccountSuspendedEvent,
    NotificationEvent,
)
from ante.ipc.registry import CommandRegistry, register_all_handlers
from ante.ipc.server import IPCServer


class _WriteError(RuntimeError):
    pass


@pytest_asyncio.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "account_persist_failure.db"))
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


@pytest.fixture
def published(eventbus) -> list[Any]:
    events: list[Any] = []

    async def record(event: Any) -> None:
        events.append(event)

    for event_type in (AccountActivatedEvent, AccountSuspendedEvent, NotificationEvent):
        eventbus.subscribe(event_type, record)
    return events


def _make_account(account_id: str = "main") -> Account:
    return Account(
        account_id=account_id,
        name="테스트",
        exchange="TEST",
        currency="KRW",
        broker_type="test",
        credentials={"app_key": "test", "app_secret": "test"},
    )


def _is_status_update(sql: str) -> bool:
    return "SET status" in " ".join(sql.split())


def _fail_status_update(
    monkeypatch, service: AccountService, only_account: str | None = None
) -> None:
    real_execute = service._db.execute

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if _is_status_update(sql) and only_account in (None, params[-1]):
            raise _WriteError("디스크 오류")
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)


async def _db_status(db: Database, account_id: str) -> tuple[str, str]:
    row = await db.fetch_one(
        "SELECT status, updated_at FROM accounts WHERE account_id = ?", (account_id,)
    )
    assert row is not None
    return row["status"], row["updated_at"]


async def _suspended(service: AccountService, account_id: str = "main") -> Account:
    await service.create(_make_account(account_id))
    await service.suspend(account_id, reason="준비", suspended_by="test")
    return service._accounts[account_id]


@pytest.mark.asyncio
async def test_activate_failure_restores_cache_and_publishes_nothing(
    service, db, published, monkeypatch
):
    account = await _suspended(service)
    before_updated_at = account.updated_at
    before_row = await _db_status(db, "main")
    published.clear()
    _fail_status_update(monkeypatch, service)

    with pytest.raises(_WriteError):
        await service.activate("main", activated_by="admin")

    assert service._accounts["main"] is account
    assert account.status == AccountStatus.SUSPENDED
    assert account.updated_at == before_updated_at
    assert await _db_status(db, "main") == before_row
    assert published == []

    monkeypatch.undo()
    await service.activate("main", activated_by="admin")
    assert account.status == AccountStatus.ACTIVE
    assert (await _db_status(db, "main"))[0] == AccountStatus.ACTIVE
    assert [type(e) for e in published] == [AccountActivatedEvent, NotificationEvent]


@pytest.mark.asyncio
async def test_activate_cancelled_mid_write_restores_cache_and_db_rolls_back(
    service, db, published, monkeypatch
):
    account = await _suspended(service)
    before_updated_at = account.updated_at
    before_row = await _db_status(db, "main")
    published.clear()

    writer = db._get_writer()
    real_commit = writer.commit
    entered = asyncio.Event()

    async def blocked_commit() -> None:
        entered.set()
        await asyncio.Event().wait()
        await real_commit()

    monkeypatch.setattr(writer, "commit", blocked_commit)
    task = asyncio.create_task(service.activate("main", activated_by="admin"))
    await asyncio.wait_for(entered.wait(), timeout=5)
    status_during_write = account.status
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert status_during_write == AccountStatus.ACTIVE
    assert account.status == AccountStatus.SUSPENDED
    assert account.updated_at == before_updated_at
    assert await _db_status(db, "main") == before_row
    assert published == []


@pytest.mark.asyncio
async def test_delete_failure_restores_cache_and_publishes_nothing(
    service, db, published, monkeypatch
):
    await service.create(_make_account())
    account = service._accounts["main"]
    before_updated_at = account.updated_at
    before_row = await _db_status(db, "main")
    _fail_status_update(monkeypatch, service)

    with pytest.raises(_WriteError):
        await service.delete("main", deleted_by="admin")

    assert service._accounts["main"] is account
    assert account.status == AccountStatus.ACTIVE
    assert account.updated_at == before_updated_at
    assert await _db_status(db, "main") == before_row
    assert published == []

    monkeypatch.undo()
    await service.delete("main", deleted_by="admin")
    assert "main" not in service._accounts
    assert (await _db_status(db, "main"))[0] == AccountStatus.DELETED
    assert [type(e) for e in published] == [AccountSuspendedEvent]


@pytest.mark.asyncio
async def test_delete_publishes_suspended_event_after_db_write_and_cache_removal(
    service, db, eventbus
):
    await service.create(_make_account())
    seen: list[tuple[bool, str]] = []

    async def on_suspended(event: AccountSuspendedEvent) -> None:
        seen.append(("main" in service._accounts, (await _db_status(db, "main"))[0]))

    eventbus.subscribe(AccountSuspendedEvent, on_suspended)
    await service.delete("main", deleted_by="admin")

    assert seen == [(False, AccountStatus.DELETED)]


@pytest.mark.asyncio
async def test_activate_all_stops_at_failed_account_with_cache_matching_db(
    service, db, monkeypatch
):
    first = await _suspended(service, "acct1")
    second = await _suspended(service, "acct2")
    _fail_status_update(monkeypatch, service, only_account="acct2")

    with pytest.raises(AccountActivateAllFailedError) as caught:
        await service.activate_all(activated_by="admin")

    exc = caught.value
    assert isinstance(exc.__cause__, _WriteError)
    assert exc.failed_account_id == "acct2"
    assert exc.activated_count == 1
    assert str(exc) == _ACTIVATE_ALL_MESSAGE
    assert "디스크 오류" not in str(exc)
    assert first.status == AccountStatus.ACTIVE
    assert (await _db_status(db, "acct1"))[0] == AccountStatus.ACTIVE
    assert second.status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "acct2"))[0] == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_overlapping_activate_returns_early_while_first_write_is_in_flight(
    service, published, monkeypatch
):
    account = await _suspended(service)
    published.clear()
    real_execute = service._db.execute
    entered = asyncio.Event()
    release = asyncio.Event()
    status_updates = 0

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        nonlocal status_updates
        if _is_status_update(sql):
            status_updates += 1
            entered.set()
            await release.wait()
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)
    first = asyncio.create_task(service.activate("main", activated_by="admin"))
    await asyncio.wait_for(entered.wait(), timeout=5)

    try:
        await asyncio.wait_for(
            service.activate("main", activated_by="admin"), timeout=1
        )
        assert status_updates == 1
        assert published == []
    finally:
        release.set()
    await first
    assert account.status == AccountStatus.ACTIVE
    assert [type(e) for e in published] == [AccountActivatedEvent, NotificationEvent]


# 알려진 한계: 같은 계좌의 활성화 둘이 겹쳤을 때 첫째가 실패해 되돌리면, 이미
# 돌아간 둘째의 호출자는 성공으로 안다. 결과는 정지 쪽(fail-closed)이고 #2667은
# 이것을 바꾸지 않는다.


@pytest.mark.asyncio
async def test_suspend_failure_keeps_memory_suspended_pending_maintainer_decision(
    service, db, published, monkeypatch
):
    await service.create(_make_account())
    account = service._accounts["main"]
    _fail_status_update(monkeypatch, service)

    with pytest.raises(_WriteError):
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    reason = (
        "suspend 실패 정책은 유지관리자 결정 대기(#2667): 결정 전까지 "
        "메모리는 정지로 남고 DB는 활성이며 이벤트는 나가지 않는다"
    )
    assert account.status == AccountStatus.SUSPENDED, reason
    assert (await _db_status(db, "main"))[0] == AccountStatus.ACTIVE, reason
    assert published == [], reason


_SUSPEND_ALL_MESSAGE = (
    "전체 계좌 정지가 1개 계좌에서 실패했습니다: acct2. "
    "이번 요청으로 정지된 계좌는 2개입니다."
)
_ACTIVATE_ALL_MESSAGE = (
    "전체 계좌 활성화가 계좌 'acct2'에서 실패해 멈췄습니다. "
    "그 전에 활성화된 계좌는 1개이고, 뒤의 계좌는 시도하지 않았습니다."
)


async def _three_active(service: AccountService) -> None:
    for account_id in ("acct1", "acct2", "acct3"):
        await service.create(_make_account(account_id))


def _record_suspend_attempts(monkeypatch, service: AccountService) -> list[str]:
    attempted: list[str] = []
    real_suspend = service.suspend

    async def suspend(account_id: str, reason: str, suspended_by: str) -> None:
        attempted.append(account_id)
        await real_suspend(account_id, reason, suspended_by)

    monkeypatch.setattr(service, "suspend", suspend)
    return attempted


@pytest.mark.asyncio
async def test_suspend_all_tries_every_account_and_reports_failed_one(
    service, db, published, monkeypatch
):
    await _three_active(service)
    published.clear()
    _fail_status_update(monkeypatch, service, only_account="acct2")
    attempted = _record_suspend_attempts(monkeypatch, service)

    with pytest.raises(AccountSuspendAllFailedError) as caught:
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert attempted == ["acct1", "acct2", "acct3"]
    for account_id in ("acct1", "acct3"):
        assert service._accounts[account_id].status == AccountStatus.SUSPENDED
        assert (await _db_status(db, account_id))[0] == AccountStatus.SUSPENDED
    suspended_ids = {
        e.account_id for e in published if isinstance(e, AccountSuspendedEvent)
    }
    assert suspended_ids == {"acct1", "acct3"}
    assert sum(isinstance(e, NotificationEvent) for e in published) == 2
    exc = caught.value
    assert exc.failed_account_ids == ("acct2",)
    assert exc.suspended_count == 2
    assert str(exc) == _SUSPEND_ALL_MESSAGE
    assert "디스크 오류" not in str(exc)


@pytest.mark.asyncio
async def test_suspend_all_does_not_trap_cancellation(service, monkeypatch):
    await _three_active(service)
    real_execute = service._db.execute

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if _is_status_update(sql) and params[-1] == "acct2":
            raise asyncio.CancelledError
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)
    attempted = _record_suspend_attempts(monkeypatch, service)

    with pytest.raises(asyncio.CancelledError):
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert attempted == ["acct1", "acct2"]
    assert service._accounts["acct3"].status == AccountStatus.ACTIVE


def _kill_switch_server(service: AccountService, audit_log: AsyncMock) -> IPCServer:
    cmd_registry = CommandRegistry()
    register_all_handlers(cmd_registry)
    audit_logger = MagicMock()
    audit_logger.log = audit_log
    svc_registry = ServiceRegistry(
        account=service,
        bot_manager=MagicMock(),
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
        audit_logger=audit_logger,
    )
    socket_dir = tempfile.mkdtemp(prefix="ipc-2924", dir="/tmp")
    return IPCServer(str(Path(socket_dir) / "t.sock"), svc_registry, cmd_registry)


async def _dispatch(server: IPCServer, command: str) -> dict[str, Any]:
    await server.start()
    try:
        return await server._dispatch(
            {"id": "1", "command": command, "args": {"reason": "r"}, "actor": "ops"}
        )
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_system_halt_partial_failure_is_error_envelope_with_audit(
    service, monkeypatch
):
    await _three_active(service)
    _fail_status_update(monkeypatch, service, only_account="acct2")
    audit_log = AsyncMock(return_value=None)

    response = await _dispatch(_kill_switch_server(service, audit_log), "system.halt")

    assert response == {
        "id": "1",
        "status": "error",
        "error": {
            "code": "ACCOUNT_SUSPEND_ALL_FAILED",
            "message": _SUSPEND_ALL_MESSAGE,
        },
    }
    audit_log.assert_awaited_once_with(
        member_id="ops",
        action="system.halt",
        resource="system:kill_switch",
        detail="failed=acct2; changed=2; reason=r",
        ip="",
    )


@pytest.mark.asyncio
async def test_system_clear_halt_partial_failure_is_error_envelope_with_audit(
    service, monkeypatch
):
    await _suspended(service, "acct1")
    await _suspended(service, "acct2")
    await _suspended(service, "acct3")
    _fail_status_update(monkeypatch, service, only_account="acct2")
    audit_log = AsyncMock(return_value=None)

    response = await _dispatch(
        _kill_switch_server(service, audit_log), "system.clear_halt"
    )

    assert response == {
        "id": "1",
        "status": "error",
        "error": {
            "code": "ACCOUNT_ACTIVATE_ALL_FAILED",
            "message": _ACTIVATE_ALL_MESSAGE,
        },
    }
    audit_log.assert_awaited_once_with(
        member_id="ops",
        action="system.clear_halt",
        resource="system:kill_switch",
        detail="failed=acct2; changed=1; reason=r",
        ip="",
    )
    assert service._accounts["acct3"].status == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_system_halt_audit_failure_does_not_mask_partial_failure(
    service, monkeypatch
):
    await _three_active(service)
    _fail_status_update(monkeypatch, service, only_account="acct2")
    audit_log = AsyncMock(side_effect=RuntimeError("감사 저장 실패"))

    response = await _dispatch(_kill_switch_server(service, audit_log), "system.halt")

    assert response["status"] == "error"
    assert response["error"] == {
        "code": "ACCOUNT_SUSPEND_ALL_FAILED",
        "message": _SUSPEND_ALL_MESSAGE,
    }
    audit_log.assert_awaited_once()
