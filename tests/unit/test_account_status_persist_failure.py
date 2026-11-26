"""계좌 상태 UPDATE가 실패할 때 캐시와 DB가 어긋나지 않는지 검증한다 (#2667).

``activate``·``delete``는 실패하면(취소 포함) 캐시의 ``status``·``updated_at``을
호출 전 값으로 되돌리고 같은 예외를 다시 올린다. ``suspend``는 실패해도
정지를 유지하고 정지 이벤트와 실패 알림을 낸 뒤 오류를 올리며, 다시 보낸
정지가 DB 쓰기를 다시 시도한다 (#2858).
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
    AccountAlreadySuspendedError,
    AccountSuspendAllFailedError,
    AccountSuspendNotPersistedError,
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


_NOT_PERSISTED_MESSAGE = (
    "계좌 'main'의 정지는 적용됐지만 DB에 기록되지 않았습니다. "
    "재시작하면 활성으로 돌아옵니다. 정지를 다시 보내면 기록을 다시 시도합니다."
)
_FAILURE_NOTICE = (
    "계좌 `main` 정지(SUSPENDED)는 적용됐지만 DB에 기록되지 않았습니다.\n"
    "재시작하면 활성으로 돌아옵니다. 정지를 다시 보내 기록하세요.\n"
    "사유: 킬 스위치\n"
    "실행: `admin`"
)


async def _failed_suspend(
    service: AccountService, monkeypatch, account_id: str = "main"
) -> Account:
    await service.create(_make_account(account_id))
    _fail_status_update(monkeypatch, service)
    with pytest.raises(AccountSuspendNotPersistedError):
        await service.suspend(account_id, reason="킬 스위치", suspended_by="admin")
    monkeypatch.undo()
    return service._accounts[account_id]


@pytest.mark.asyncio
async def test_suspend_write_failure_keeps_suspended_stops_bots_and_raises(
    service, db, published, monkeypatch
):
    await service.create(_make_account())
    account = service._accounts["main"]
    _fail_status_update(monkeypatch, service)

    with pytest.raises(AccountSuspendNotPersistedError) as caught:
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    exc = caught.value
    assert exc.code == "EXECUTION_ERROR"
    assert isinstance(exc.__cause__, _WriteError)
    assert str(exc) == _NOT_PERSISTED_MESSAGE
    assert "디스크 오류" not in str(exc)
    assert account.status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "main"))[0] == AccountStatus.ACTIVE
    assert service.has_unpersisted_suspensions() is True
    assert [type(e) for e in published] == [AccountSuspendedEvent, NotificationEvent]
    event, notice = published
    assert (event.account_id, event.reason, event.suspended_by) == (
        "main",
        "킬 스위치",
        "admin",
    )
    assert notice.level == "critical"
    assert notice.category == "system"
    assert notice.message == _FAILURE_NOTICE


@pytest.mark.asyncio
async def test_resuspend_retries_write_and_then_reports_already_suspended(
    service, db, published, monkeypatch
):
    account = await _failed_suspend(service, monkeypatch)
    published.clear()

    await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    assert account.status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "main"))[0] == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False
    assert [type(e) for e in published] == [AccountSuspendedEvent, NotificationEvent]
    assert published[1].message == (
        "계좌 `main` 정지(SUSPENDED)\n사유: 킬 스위치\n실행: `admin`"
    )
    with pytest.raises(AccountAlreadySuspendedError):
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")


@pytest.mark.asyncio
async def test_resuspend_failing_again_raises_again(
    service, db, published, monkeypatch
):
    account = await _failed_suspend(service, monkeypatch)
    published.clear()
    _fail_status_update(monkeypatch, service)

    for _ in range(2):
        with pytest.raises(AccountSuspendNotPersistedError):
            await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    assert account.status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "main"))[0] == AccountStatus.ACTIVE
    assert service.has_unpersisted_suspensions() is True
    assert [type(e) for e in published] == [
        AccountSuspendedEvent,
        NotificationEvent,
        AccountSuspendedEvent,
        NotificationEvent,
    ]
    assert [e.message for e in published[1::2]] == [_FAILURE_NOTICE] * 2


def _cancel_status_update(monkeypatch, service: AccountService) -> None:
    real_execute = service._db.execute

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if _is_status_update(sql):
            raise asyncio.CancelledError
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)


@pytest.mark.asyncio
async def test_cancelled_suspend_keeps_mark_and_publishes_nothing(
    service, db, published, monkeypatch
):
    await service.create(_make_account())
    account = service._accounts["main"]
    _cancel_status_update(monkeypatch, service)

    with pytest.raises(asyncio.CancelledError):
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    assert account.status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "main"))[0] == AccountStatus.ACTIVE
    assert service.has_unpersisted_suspensions() is True
    assert published == []


@pytest.mark.asyncio
async def test_cancelled_retry_keeps_mark_and_publishes_nothing(
    service, db, published, monkeypatch
):
    await _failed_suspend(service, monkeypatch)
    published.clear()
    _cancel_status_update(monkeypatch, service)

    with pytest.raises(asyncio.CancelledError):
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")

    assert service.has_unpersisted_suspensions() is True
    assert published == []
    monkeypatch.undo()
    await service.suspend("main", reason="킬 스위치", suspended_by="admin")
    assert (await _db_status(db, "main"))[0] == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_overlapping_suspend_while_first_write_is_in_flight_is_already_suspended(
    service, db, published, monkeypatch
):
    await service.create(_make_account())
    real_execute = service._db.execute
    entered = asyncio.Event()
    release = asyncio.Event()

    async def execute(sql: str, params: tuple[Any, ...] = ()) -> None:
        if _is_status_update(sql):
            entered.set()
            await release.wait()
        await real_execute(sql, params)

    monkeypatch.setattr(service._db, "execute", execute)
    first = asyncio.create_task(
        service.suspend("main", reason="킬 스위치", suspended_by="admin")
    )
    await asyncio.wait_for(entered.wait(), timeout=5)
    try:
        assert service.has_unpersisted_suspensions() is False
        with pytest.raises(AccountAlreadySuspendedError):
            await service.suspend("main", reason="킬 스위치", suspended_by="admin")
    finally:
        release.set()
    await first
    assert (await _db_status(db, "main"))[0] == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False
    assert [type(e) for e in published] == [AccountSuspendedEvent, NotificationEvent]


@pytest.mark.asyncio
async def test_activate_clears_unpersisted_mark(service, db, published, monkeypatch):
    account = await _failed_suspend(service, monkeypatch)

    await service.activate("main", activated_by="admin")

    assert account.status == AccountStatus.ACTIVE
    assert service.has_unpersisted_suspensions() is False
    await service.suspend("main", reason="킬 스위치", suspended_by="admin")
    with pytest.raises(AccountAlreadySuspendedError):
        await service.suspend("main", reason="킬 스위치", suspended_by="admin")


@pytest.mark.asyncio
async def test_activate_failure_keeps_unpersisted_mark(
    service, db, published, monkeypatch
):
    account = await _failed_suspend(service, monkeypatch)
    _fail_status_update(monkeypatch, service)

    with pytest.raises(_WriteError):
        await service.activate("main", activated_by="admin")

    assert account.status == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is True
    monkeypatch.undo()
    await service.suspend("main", reason="킬 스위치", suspended_by="admin")
    assert (await _db_status(db, "main"))[0] == AccountStatus.SUSPENDED


@pytest.mark.asyncio
async def test_delete_clears_unpersisted_mark(service, db, published, monkeypatch):
    await _failed_suspend(service, monkeypatch)
    published.clear()

    await service.delete("main", deleted_by="admin")

    assert service.has_unpersisted_suspensions() is False
    assert (await _db_status(db, "main"))[0] == AccountStatus.DELETED
    assert published == []


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
    assert service._accounts["acct2"].status == AccountStatus.SUSPENDED
    assert (await _db_status(db, "acct2"))[0] == AccountStatus.ACTIVE
    assert suspended_ids == {"acct1", "acct2", "acct3"}
    notices = [e for e in published if isinstance(e, NotificationEvent)]
    assert [n.level for n in notices] == ["critical"] * 3
    assert sum("DB에 기록되지 않았습니다" in n.message for n in notices) == 1
    exc = caught.value
    assert exc.failed_account_ids == ("acct2",)
    assert exc.suspended_count == 2
    assert str(exc) == _SUSPEND_ALL_MESSAGE
    assert "디스크 오류" not in str(exc)


@pytest.mark.asyncio
async def test_suspend_all_retries_unpersisted_account(
    service, db, published, monkeypatch
):
    await _three_active(service)
    _fail_status_update(monkeypatch, service, only_account="acct2")
    with pytest.raises(AccountSuspendAllFailedError):
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")
    monkeypatch.undo()
    published.clear()

    results = await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert results == [
        {
            "account_id": account_id,
            "previous_status": "suspended",
            "status": "suspended",
            "changed": False,
        }
        for account_id in ("acct1", "acct2", "acct3")
    ]
    assert (await _db_status(db, "acct2"))[0] == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False
    assert [
        e.account_id for e in published if isinstance(e, AccountSuspendedEvent)
    ] == ["acct2"]


@pytest.mark.asyncio
async def test_suspend_all_retry_failing_again_is_suspend_all_failed(
    service, db, monkeypatch
):
    await _three_active(service)
    _fail_status_update(monkeypatch, service, only_account="acct2")
    with pytest.raises(AccountSuspendAllFailedError):
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    with pytest.raises(AccountSuspendAllFailedError) as caught:
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert caught.value.failed_account_ids == ("acct2",)
    assert caught.value.suspended_count == 0
    assert (await _db_status(db, "acct2"))[0] == AccountStatus.ACTIVE
    assert service.has_unpersisted_suspensions() is True


@pytest.mark.asyncio
async def test_suspend_all_does_not_trap_cancellation(service, db, monkeypatch):
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
    assert service._accounts["acct3"].status == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is True
    assert (await _db_status(db, "acct3"))[0] == AccountStatus.ACTIVE
    monkeypatch.undo()

    results = await service.suspend_all(reason="킬 스위치", suspended_by="admin")

    assert results == [
        {
            "account_id": account_id,
            "previous_status": "suspended",
            "status": "suspended",
            "changed": False,
        }
        for account_id in ("acct1", "acct2", "acct3")
    ]
    for account_id in ("acct2", "acct3"):
        assert (await _db_status(db, account_id))[0] == AccountStatus.SUSPENDED
    assert service.has_unpersisted_suspensions() is False


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


async def _dispatch(
    server: IPCServer, command: str, args: dict[str, Any] | None = None
) -> dict[str, Any]:
    await server.start()
    try:
        return await server._dispatch(
            {
                "id": "1",
                "command": command,
                "args": args or {"reason": "r"},
                "actor": "ops",
            }
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


@pytest.mark.asyncio
async def test_account_suspend_write_failure_is_execution_error_envelope(
    service, monkeypatch
):
    await service.create(_make_account())
    _fail_status_update(monkeypatch, service)
    audit_log = AsyncMock(return_value=None)

    response = await _dispatch(
        _kill_switch_server(service, audit_log),
        "account.suspend",
        {"account_id": "main", "reason": "킬 스위치"},
    )

    assert response == {
        "id": "1",
        "status": "error",
        "error": {"code": "EXECUTION_ERROR", "message": _NOT_PERSISTED_MESSAGE},
    }


@pytest.mark.asyncio
async def test_system_halt_resend_after_partial_failure_succeeds(service, monkeypatch):
    await _three_active(service)
    _fail_status_update(monkeypatch, service, only_account="acct2")
    with pytest.raises(AccountSuspendAllFailedError):
        await service.suspend_all(reason="킬 스위치", suspended_by="admin")
    monkeypatch.undo()
    audit_log = AsyncMock(return_value=None)

    response = await _dispatch(_kill_switch_server(service, audit_log), "system.halt")

    assert response["status"] == "ok"
    assert response["result"]["accounts_changed"] == 0
    assert {a["account_id"] for a in response["result"]["accounts"]} == {
        "acct1",
        "acct2",
        "acct3",
    }
    assert service.has_unpersisted_suspensions() is False
