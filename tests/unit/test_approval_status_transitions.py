"""결재 상태 전이의 특성 테스트 (#2654).

메서드마다 허용하는 이전 상태와 거부하는 이전 상태, 가드가 없는 경로
(create·_execute_approved·expire_stale)를 지금 동작 그대로 잠근다.
기대값은 모두 리터럴(상태 문자열, 예외 메시지 전체, history의 action
목록)이고, 이전 상태는 원시 SQL로 DB에 넣어 서비스가 DB에서 읽은
``str`` 형태로 보게 한다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ante.approval.auto_approve import AutoApproveConfig, AutoApproveEvaluator
from ante.approval.errors import ApprovalStatusConflictError
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalResolvedEvent

ALL_STATUSES = (
    "pending",
    "approved",
    "execution_failed",
    "rejected",
    "on_hold",
    "expired",
    "cancelled",
)

REQUESTER = "agent-a"
LEGACY_TYPE = "legacy_removed_type"


def _others(*allowed: str) -> list[str]:
    return [s for s in ALL_STATUSES if s not in allowed]


# ── 픽스처 ───────────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "approval-2654.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def resolved(eventbus: EventBus) -> list[str]:
    seen: list[str] = []

    async def _on_resolved(event: ApprovalResolvedEvent) -> None:
        seen.append(str(event.resolution))

    eventbus.subscribe(ApprovalResolvedEvent, _on_resolved)
    return seen


async def _noop_executor(params: dict) -> None:
    return None


async def _failing_executor(params: dict) -> None:
    raise RuntimeError("executor boom")


async def _make_service(
    db: Database,
    eventbus: EventBus,
    executors: dict | None = None,
    auto_approve_evaluator: AutoApproveEvaluator | None = None,
) -> ApprovalService:
    svc = ApprovalService(
        db=db,
        eventbus=eventbus,
        executors=executors,
        auto_approve_evaluator=auto_approve_evaluator,
    )
    await svc.initialize()
    return svc


@pytest.fixture
async def service(db: Database, eventbus: EventBus) -> ApprovalService:
    return await _make_service(db, eventbus, {"strategy_adopt": _noop_executor})


async def _set_status(db: Database, approval_id: str, status: str) -> None:
    await db.execute(
        "UPDATE approvals SET status = ? WHERE id = ?",
        (status, approval_id),
    )


async def _request_in(service: ApprovalService, db: Database, status: str) -> str:
    """정상 요청 하나를 만들고 원시 SQL로 상태만 바꾼다."""
    req = await service.create(
        type="strategy_adopt",
        requester=REQUESTER,
        title="특성 테스트",
        params={"strategy_id": "s1"},
    )
    await _set_status(db, req.id, status)
    return req.id


async def _invalid_type_request_in(db: Database, status: str) -> str:
    approval_id = f"legacy-{status}"
    await db.execute(
        """INSERT INTO approvals
           (id, type, status, requester, title, body, params,
            reviews, history, reference_id, expires_at, created_at,
            resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval_id,
            LEGACY_TYPE,
            status,
            REQUESTER,
            "legacy row",
            "",
            json.dumps({}),
            json.dumps([]),
            json.dumps(
                [
                    {
                        "action": "created",
                        "actor": REQUESTER,
                        "at": "2026-04-01T00:00:00+00:00",
                        "detail": "",
                    }
                ]
            ),
            "",
            "",
            "2026-04-01T00:00:00+00:00",
            "",
            "",
        ),
    )
    return approval_id


async def _stored_status(service: ApprovalService, approval_id: str) -> Any:
    stored = await service.get(approval_id)
    assert stored is not None
    return stored.status


async def _stored_actions(service: ApprovalService, approval_id: str) -> list[str]:
    stored = await service.get(approval_id)
    assert stored is not None
    return [entry["action"] for entry in stored.history]


def _assert_exact(exc_info: pytest.ExceptionInfo[Any], cls: type, message: str):
    assert type(exc_info.value) is cls
    assert str(exc_info.value) == message


# ── 이전 상태가 DB에서 읽은 str ───────────────────────────────────


async def test_previous_status_is_read_from_db_as_plain_str(service, db):
    approval_id = await _request_in(service, db, "on_hold")
    stored = await service.get(approval_id)
    assert stored is not None
    assert type(stored.status) is str
    assert stored.status == "on_hold"

    resumed = await service.resume(approval_id)
    assert resumed.status == "pending"
    assert await _stored_status(service, approval_id) == "pending"


# ── 거부 경로 ────────────────────────────────────────────────────


@pytest.mark.parametrize("prev", _others("pending", "execution_failed"))
async def test_approve_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.approve(approval_id)
    _assert_exact(
        exc_info,
        ApprovalStatusConflictError,
        f"결재 '{approval_id}' 상태 '{prev}' 에서 'approve' 작업을 수행할 수 없습니다.",
    )
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("pending", "execution_failed"))
async def test_reject_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.reject(approval_id)
    _assert_exact(
        exc_info,
        ApprovalStatusConflictError,
        f"결재 '{approval_id}' 상태 '{prev}' 에서 'reject' 작업을 수행할 수 없습니다.",
    )
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("rejected"))
async def test_reopen_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.reopen(approval_id, requester=REQUESTER)
    _assert_exact(
        exc_info, ValueError, f"rejected 상태에서만 reopen 가능 (현재: {prev})"
    )
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("pending", "on_hold", "execution_failed"))
async def test_cancel_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.cancel(approval_id, requester=REQUESTER)
    _assert_exact(
        exc_info,
        ValueError,
        f"pending/on_hold/execution_failed 상태에서만 철회 가능 (현재: {prev})",
    )
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("pending", "execution_failed"))
async def test_hold_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.hold(approval_id)
    _assert_exact(
        exc_info,
        ValueError,
        f"pending/execution_failed 상태에서만 보류 가능 (현재: {prev})",
    )
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("on_hold"))
async def test_resume_rejects(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.resume(approval_id)
    _assert_exact(exc_info, ValueError, f"on_hold 상태에서만 재개 가능 (현재: {prev})")
    assert await _stored_status(service, approval_id) == prev


@pytest.mark.parametrize("prev", _others("pending", "on_hold", "execution_failed"))
async def test_cancel_invalid_type_request_rejects(service, db, prev):
    approval_id = await _invalid_type_request_in(db, prev)
    with pytest.raises(ValueError) as exc_info:
        await service.cancel_invalid_type_request(approval_id, resolved_by="admin")
    _assert_exact(
        exc_info,
        ValueError,
        "pending/on_hold/execution_failed 상태에서만 cancel-invalid 가능"
        f" (현재: {prev})",
    )
    assert await _stored_status(service, approval_id) == prev


# ── 허용 경로 ────────────────────────────────────────────────────


@pytest.mark.parametrize("prev", ["pending", "execution_failed"])
async def test_approve_allows(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    result = await service.approve(approval_id)
    assert result.status == "approved"
    assert await _stored_status(service, approval_id) == "approved"


@pytest.mark.parametrize("prev", ["pending", "execution_failed"])
async def test_reject_allows(service, db, resolved, prev):
    approval_id = await _request_in(service, db, prev)
    result = await service.reject(approval_id, reject_reason="사유")
    assert result.status == "rejected"
    assert await _stored_status(service, approval_id) == "rejected"
    assert resolved == ["rejected"]


async def test_reopen_allows(service, db):
    approval_id = await _request_in(service, db, "rejected")
    result = await service.reopen(approval_id, requester=REQUESTER)
    assert result.status == "pending"
    assert await _stored_status(service, approval_id) == "pending"


@pytest.mark.parametrize("prev", ["pending", "on_hold", "execution_failed"])
async def test_cancel_allows(service, db, resolved, prev):
    approval_id = await _request_in(service, db, prev)
    result = await service.cancel(approval_id, requester=REQUESTER)
    assert result.status == "cancelled"
    assert await _stored_status(service, approval_id) == "cancelled"
    assert resolved == ["cancelled"]


@pytest.mark.parametrize("prev", ["pending", "execution_failed"])
async def test_hold_allows(service, db, prev):
    approval_id = await _request_in(service, db, prev)
    result = await service.hold(approval_id)
    assert result.status == "on_hold"
    assert await _stored_status(service, approval_id) == "on_hold"


async def test_resume_allows(service, db):
    approval_id = await _request_in(service, db, "on_hold")
    result = await service.resume(approval_id)
    assert result.status == "pending"
    assert await _stored_status(service, approval_id) == "pending"


@pytest.mark.parametrize("prev", ["pending", "on_hold", "execution_failed"])
async def test_cancel_invalid_type_request_allows(service, db, resolved, prev):
    approval_id = await _invalid_type_request_in(db, prev)
    result = await service.cancel_invalid_type_request(
        approval_id, resolved_by="admin", suppress_notification=False
    )
    assert result.status == "cancelled"
    assert await _stored_status(service, approval_id) == "cancelled"
    assert resolved == ["cancelled"]


# ── 가드가 없는 경로 ──────────────────────────────────────────────


async def test_create_without_auto_approve_stores_pending(service):
    result = await service.create(
        type="strategy_adopt",
        requester=REQUESTER,
        title="일반 요청",
        params={"strategy_id": "s1"},
    )
    assert result.status == "pending"
    assert await _stored_status(service, result.id) == "pending"
    assert await _stored_actions(service, result.id) == ["created"]


def _auto_approve_bot_stop() -> AutoApproveEvaluator:
    return AutoApproveEvaluator(config=AutoApproveConfig(enabled=True, bot_stop=True))


async def test_create_auto_approved_with_succeeding_executor(db, eventbus, resolved):
    svc = await _make_service(
        db, eventbus, {"bot_stop": _noop_executor}, _auto_approve_bot_stop()
    )
    result = await svc.create(
        type="bot_stop",
        requester=REQUESTER,
        title="전결",
        params={"bot_id": "bot-1"},
    )
    assert result.status == "approved"
    assert await _stored_status(svc, result.id) == "approved"
    assert await _stored_actions(svc, result.id) == [
        "created",
        "approved",
        "executed",
    ]
    assert resolved == ["approved"]


async def test_create_auto_approved_with_failing_executor(db, eventbus, resolved):
    svc = await _make_service(
        db, eventbus, {"bot_stop": _failing_executor}, _auto_approve_bot_stop()
    )
    result = await svc.create(
        type="bot_stop",
        requester=REQUESTER,
        title="전결 실패",
        params={"bot_id": "bot-1"},
    )
    assert result.status == "execution_failed"
    assert await _stored_status(svc, result.id) == "execution_failed"
    assert await _stored_actions(svc, result.id) == [
        "created",
        "approved",
        "execution_failed",
    ]
    assert resolved == ["execution_failed"]


async def test_execute_approved_failure_marks_execution_failed(db, eventbus, resolved):
    svc = await _make_service(db, eventbus, {"strategy_adopt": _failing_executor})
    approval_id = await _request_in(svc, db, "pending")
    result = await svc.approve(approval_id)
    assert result.status == "execution_failed"
    assert await _stored_status(svc, approval_id) == "execution_failed"
    assert await _stored_actions(svc, approval_id) == [
        "created",
        "approved",
        "execution_failed",
    ]
    assert resolved == ["execution_failed"]


async def test_execute_approved_without_executor_marks_execution_failed(
    db, eventbus, resolved
):
    svc = await _make_service(db, eventbus, {})
    approval_id = await _request_in(svc, db, "pending")
    result = await svc.approve(approval_id)
    assert result.status == "execution_failed"
    assert await _stored_status(svc, approval_id) == "execution_failed"
    assert await _stored_actions(svc, approval_id) == [
        "created",
        "approved",
        "no_executor",
    ]
    assert resolved == ["execution_failed"]


async def _set_expired_deadline(db: Database, approval_id: str) -> None:
    await db.execute(
        "UPDATE approvals SET expires_at = ? WHERE id = ?",
        ("2000-01-01T00:00:00+00:00", approval_id),
    )


async def test_expire_stale_expires_past_pending(service, db, resolved):
    approval_id = await _request_in(service, db, "pending")
    await _set_expired_deadline(db, approval_id)
    assert await service.expire_stale() == 1
    assert await _stored_status(service, approval_id) == "expired"
    assert resolved == ["expired"]


@pytest.mark.parametrize("prev", _others("pending"))
async def test_expire_stale_skips_non_pending(service, db, resolved, prev):
    approval_id = await _request_in(service, db, prev)
    await _set_expired_deadline(db, approval_id)
    assert await service.expire_stale() == 0
    assert await _stored_status(service, approval_id) == prev
    assert resolved == []
