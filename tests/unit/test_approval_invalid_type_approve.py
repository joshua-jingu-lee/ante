"""Approval invalid type approve 차단 + executor 미등록 처리 테스트 (#1470).

#1469 가 write path 의 invalid type 을 차단했지만, 이전에 DB 에 저장된
legacy invalid pending row 의 approve 전이는 여전히 ``_execute_approved``
가 silent no-op 으로 처리할 수 있다. 본 모듈은 다음을 검증한다:

- ``approve()`` 진입부에서 invalid approval type 의 PENDING → APPROVED
  전이가 ``ValueError`` 로 차단된다.
- 차단 시 DB row.status 는 PENDING 그대로이고, ``ApprovalResolvedEvent``
  와 결재 처리 완료 notification 은 발행되지 않는다.
- executor 가 등록되지 않은 valid type 은 approve 시 silent success 가
  아닌 ``EXECUTION_FAILED`` 로 마무리되며 history 에 ``no_executor``
  entry 가 기록된다.
- auto_approve 경로(``create()`` 내부 ``_execute_approved``)에서도
  invalid type 은 ``ValueError`` 로 차단된다 (defense-in-depth).
- 정상 valid type + 등록된 executor 의 회귀가 보존된다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ante.approval.models import ApprovalStatus, ApprovalType
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalResolvedEvent, NotificationEvent

# ── 헬퍼 ──────────────────────────────────────────────────────────


class _EventCollector:
    """ApprovalResolvedEvent 와 approval-category NotificationEvent 캡처."""

    def __init__(self) -> None:
        self.resolved: list[ApprovalResolvedEvent] = []
        self.resolved_notifications: list[NotificationEvent] = []

    def attach(self, eventbus: EventBus) -> None:
        eventbus.subscribe(ApprovalResolvedEvent, self._on_resolved)
        eventbus.subscribe(NotificationEvent, self._on_notification)

    async def _on_resolved(self, event: ApprovalResolvedEvent) -> None:
        self.resolved.append(event)

    async def _on_notification(self, event: NotificationEvent) -> None:
        if event.category == "approval" and event.title == "결재 처리 완료":
            self.resolved_notifications.append(event)


async def _seed_invalid_pending_row(
    db: Database,
    *,
    approval_id: str = "legacy-invalid-1",
    approval_type: str = "oracle_invalid_type",
    requester: str = "agent-oracle",
) -> None:
    """raw INSERT 로 invalid type 의 pending approval row 를 시드한다.

    Service.create 는 #1469 enum 가드로 invalid 를 거부하므로, legacy
    상태 재현을 위해 DB 에 직접 row 를 INSERT 한다.
    """
    await db.execute(
        """INSERT INTO approvals
           (id, type, status, requester, title, body, params,
            reviews, history, reference_id, expires_at, created_at,
            resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval_id,
            approval_type,
            ApprovalStatus.PENDING,
            requester,
            "legacy invalid type row",
            "",
            json.dumps({}),
            json.dumps([]),
            json.dumps(
                [
                    {
                        "action": "created",
                        "actor": requester,
                        "at": "2026-05-10T22:08:18+00:00",
                        "detail": "",
                    }
                ]
            ),
            "",
            "",
            "2026-05-10T22:08:18+00:00",
            "",
            "",
        ),
    )


# ── 픽스처 ────────────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path: Any) -> Database:
    """테스트용 SQLite DB."""
    database = Database(str(tmp_path / "approval-1470.db"))
    await database.connect()
    return database


@pytest.fixture
async def eventbus() -> EventBus:
    return EventBus()


@pytest.fixture
async def collector(eventbus: EventBus) -> _EventCollector:
    c = _EventCollector()
    c.attach(eventbus)
    return c


@pytest.fixture
async def service(db: Database, eventbus: EventBus) -> ApprovalService:
    svc = ApprovalService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


# ── invalid type approve 차단 ─────────────────────────────────────


class TestApproveInvalidTypeBlocked:
    """legacy invalid approval type pending row 의 approve 전이 차단."""

    async def test_invalid_type_pending_row_approve_raises_value_error(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """invalid type pending row → approve 시 ``ValueError``."""
        await _seed_invalid_pending_row(db)

        with pytest.raises(ValueError, match="invalid approval type"):
            await service.approve("legacy-invalid-1", resolved_by="user-master")

    async def test_invalid_type_row_status_remains_pending(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """차단된 invalid row 는 status/history 가 PENDING 그대로 유지된다."""
        await _seed_invalid_pending_row(db)

        with pytest.raises(ValueError):
            await service.approve("legacy-invalid-1", resolved_by="user-master")

        row = await db.fetch_one(
            "SELECT status, history, resolved_at, resolved_by FROM approvals "
            "WHERE id = ?",
            ("legacy-invalid-1",),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.PENDING
        assert row["resolved_at"] == ""
        assert row["resolved_by"] == ""
        history = json.loads(row["history"])
        actions = [entry["action"] for entry in history]
        assert "approved" not in actions
        assert "executed" not in actions
        assert "no_executor" not in actions

    async def test_invalid_type_approve_publishes_no_resolved_event(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """차단된 approve 는 ``ApprovalResolvedEvent`` 를 발행하지 않는다."""
        await _seed_invalid_pending_row(db)

        with pytest.raises(ValueError):
            await service.approve("legacy-invalid-1", resolved_by="user-master")

        assert collector.resolved == []

    async def test_invalid_type_approve_publishes_no_notification(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """차단된 approve 는 결재 처리 완료 notification 을 발행하지 않는다."""
        await _seed_invalid_pending_row(db)

        with pytest.raises(ValueError):
            await service.approve("legacy-invalid-1", resolved_by="user-master")

        assert collector.resolved_notifications == []


# ── executor 미등록 (valid type) 처리 ──────────────────────────────


class TestApproveValidTypeMissingExecutor:
    """enum 은 valid 하지만 executor 가 등록되지 않은 경우."""

    async def test_missing_executor_marks_execution_failed(
        self,
        service: ApprovalService,
        collector: _EventCollector,
    ) -> None:
        """executor 미등록 → status=EXECUTION_FAILED + no_executor history."""
        req = await service.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="strategy adopt without executor",
            params={"strategy_id": "strat-1", "report_id": "rpt-1"},
        )

        await service.approve(req.id, resolved_by="user-master")

        # 메모리 상의 request 와 DB 양쪽 모두 EXECUTION_FAILED 로 마감되어야 한다.
        row = await service._db.fetch_one(
            "SELECT status, history FROM approvals WHERE id = ?",
            (req.id,),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.EXECUTION_FAILED
        history = json.loads(row["history"])
        actions = [entry["action"] for entry in history]
        assert "approved" in actions
        assert "no_executor" in actions
        no_exec = next(e for e in history if e["action"] == "no_executor")
        assert no_exec["actor"] == "user-master"
        assert "strategy_adopt" in no_exec["detail"]

    async def test_missing_executor_publishes_resolved_event_with_failed_status(
        self,
        service: ApprovalService,
        collector: _EventCollector,
    ) -> None:
        """executor 미등록 시 ``ApprovalResolvedEvent.resolution`` 이
        ``execution_failed`` 로 발행되어 silent success 가 차단된다."""
        req = await service.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="missing executor",
            params={"strategy_id": "strat-1", "report_id": "rpt-1"},
        )

        await service.approve(req.id, resolved_by="user-master")

        assert len(collector.resolved) == 1
        resolved = collector.resolved[0]
        assert resolved.approval_id == req.id
        assert resolved.resolution == ApprovalStatus.EXECUTION_FAILED
        # notification 은 발행되지만 결과 status 는 execution_failed 로 표기됨.
        assert len(collector.resolved_notifications) == 1
        assert "execution_failed" in collector.resolved_notifications[0].message


# ── auto_approve 경로 enum 검증 ────────────────────────────────────


class TestAutoApproveEnumDefenseInDepth:
    """``_execute_approved`` 진입부의 enum 검증이 auto_approve 경로도 보호."""

    async def test_execute_approved_rejects_invalid_type_directly(
        self,
        service: ApprovalService,
    ) -> None:
        """``_execute_approved`` 를 직접 호출 시 invalid type → ``ValueError``.

        auto_approve 는 ``create()`` 내부에서 ``_execute_approved`` 를 직접
        호출하므로, ``approve()`` 의 가드를 우회할 수 있는 경로다. 따라서
        ``_execute_approved`` 자체에 enum 검증이 있어야 한다.
        """
        from ante.approval.models import ApprovalRequest

        bogus = ApprovalRequest(
            id="bogus-1",
            type="oracle_invalid_type",
            status=ApprovalStatus.APPROVED,
            requester="agent",
            title="bogus",
        )

        with pytest.raises(ValueError, match="invalid approval type"):
            await service._execute_approved(bogus, actor="system:auto_approve")


# ── 정상 lifecycle 회귀 ────────────────────────────────────────────


class TestApproveValidTypeWithExecutorRegression:
    """정상 valid type + 등록된 executor 의 회귀가 보존되는지 확인."""

    async def test_approve_with_executor_marks_executed(
        self,
        db: Database,
        eventbus: EventBus,
    ) -> None:
        executed_calls: list[dict] = []

        async def _executor(params: dict) -> None:
            executed_calls.append(params)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={ApprovalType.STRATEGY_ADOPT.value: _executor},
        )
        await svc.initialize()

        collector = _EventCollector()
        collector.attach(eventbus)

        req = await svc.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="happy path",
            params={"strategy_id": "strat-1", "report_id": "rpt-1"},
        )

        result = await svc.approve(req.id, resolved_by="user-master")

        assert result.status == ApprovalStatus.APPROVED
        assert executed_calls == [{"strategy_id": "strat-1", "report_id": "rpt-1"}]

        row = await db.fetch_one(
            "SELECT status, history FROM approvals WHERE id = ?",
            (req.id,),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.APPROVED
        history = json.loads(row["history"])
        actions = [entry["action"] for entry in history]
        assert "approved" in actions
        assert "executed" in actions
        assert "no_executor" not in actions
        assert "execution_failed" not in actions

        assert len(collector.resolved) == 1
        assert collector.resolved[0].resolution == ApprovalStatus.APPROVED
