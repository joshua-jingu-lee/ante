"""Legacy invalid approval type cleanup 테스트 (#1472).

운영자가 ``ApprovalType`` SSOT 에 없는 legacy invalid approval row 를 식별
(``list_invalid_type_approvals``) 하고, 강제 cancel 처리
(``force_cancel_invalid_type``) 하는 경로를 검증한다.

검증 대상:

- ``list_invalid_type_approvals``
  - invalid type row 만 반환한다.
  - valid type row 는 반환하지 않는다.
  - ``created_at`` 오름차순 정렬을 보존한다.
  - 종결/미종결 row 모두 audit 목적으로 포함된다.
- ``force_cancel_invalid_type``
  - invalid type pending row → CANCELLED 전이 + ``force_cancelled`` history.
  - ``ApprovalResolvedEvent`` 와 결재 처리 완료 notification 발행.
  - valid type row 는 ``ValueError`` 로 거부 (운영 도구가 정상 row 를 강제
    종결 시키지 못함).
  - 이미 종결된 row 는 ``ValueError`` 로 거부 (audit trail 보존).
  - 존재하지 않는 ID 는 ``ValueError`` 로 거부.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from ante.approval.models import ApprovalRequest, ApprovalStatus, ApprovalType
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalResolvedEvent, NotificationEvent

# ── 헬퍼 ──────────────────────────────────────────────────────────


class _EventCollector:
    """``ApprovalResolvedEvent`` 와 approval-category notification 캡처."""

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


async def _seed_invalid_row(
    db: Database,
    *,
    approval_id: str,
    approval_type: str = "oracle_invalid_type",
    requester: str = "agent-oracle",
    status: str = ApprovalStatus.PENDING,
    created_at: str = "2026-05-10T22:08:18+00:00",
    resolved_at: str = "",
    resolved_by: str = "",
    title: str = "legacy invalid type row",
) -> None:
    """invalid approval type row 를 raw INSERT 로 시드한다."""
    await db.execute(
        """INSERT INTO approvals
           (id, type, status, requester, title, body, params,
            reviews, history, reference_id, expires_at, created_at,
            resolved_at, resolved_by)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            approval_id,
            approval_type,
            status,
            requester,
            title,
            "",
            json.dumps({}),
            json.dumps([]),
            json.dumps(
                [
                    {
                        "action": "created",
                        "actor": requester,
                        "at": created_at,
                        "detail": "",
                    }
                ]
            ),
            "",
            "",
            created_at,
            resolved_at,
            resolved_by,
        ),
    )


# ── 픽스처 ────────────────────────────────────────────────────────


@pytest.fixture
async def db(tmp_path: Any) -> Database:
    database = Database(str(tmp_path / "approval-1472.db"))
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


# ── list_invalid_type_approvals ───────────────────────────────────


class TestListInvalidTypeApprovals:
    """invalid type row 식별 (read-only)."""

    async def test_empty_db_returns_empty_list(self, service: ApprovalService) -> None:
        """row 가 없으면 빈 list 반환."""
        result = await service.list_invalid_type_approvals()
        assert result == []

    async def test_only_valid_rows_returns_empty_list(
        self, service: ApprovalService
    ) -> None:
        """valid type row 만 있으면 빈 list 반환."""
        await service.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="happy path",
            params={"strategy_id": "s-1", "report_id": "r-1"},
        )
        result = await service.list_invalid_type_approvals()
        assert result == []

    async def test_invalid_row_identified(
        self, service: ApprovalService, db: Database
    ) -> None:
        """invalid type row 1건 → 1건 반환."""
        await _seed_invalid_row(db, approval_id="legacy-1")

        result = await service.list_invalid_type_approvals()
        assert len(result) == 1
        assert result[0].id == "legacy-1"
        assert result[0].type == "oracle_invalid_type"
        assert result[0].status == ApprovalStatus.PENDING

    async def test_invalid_row_mixed_with_valid_filters_correctly(
        self, service: ApprovalService, db: Database
    ) -> None:
        """valid + invalid 가 섞여있어도 invalid 만 반환."""
        # valid row 1건
        await service.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="valid",
            params={"strategy_id": "s-1", "report_id": "r-1"},
        )
        # invalid row 2건
        await _seed_invalid_row(
            db,
            approval_id="legacy-A",
            approval_type="oracle_invalid_type",
            created_at="2026-05-10T22:08:18+00:00",
        )
        await _seed_invalid_row(
            db,
            approval_id="legacy-B",
            approval_type="bogus_type_2",
            created_at="2026-05-11T01:00:00+00:00",
        )

        result = await service.list_invalid_type_approvals()
        ids = {r.id for r in result}
        assert ids == {"legacy-A", "legacy-B"}
        types = {r.type for r in result}
        assert "strategy_adopt" not in types

    async def test_order_by_created_at_ascending(
        self, service: ApprovalService, db: Database
    ) -> None:
        """created_at 오름차순 정렬: 가장 오래된 row 가 먼저."""
        await _seed_invalid_row(
            db,
            approval_id="newer",
            created_at="2026-05-12T00:00:00+00:00",
        )
        await _seed_invalid_row(
            db,
            approval_id="older",
            created_at="2026-05-10T00:00:00+00:00",
        )
        await _seed_invalid_row(
            db,
            approval_id="middle",
            created_at="2026-05-11T00:00:00+00:00",
        )

        result = await service.list_invalid_type_approvals()
        assert [r.id for r in result] == ["older", "middle", "newer"]

    async def test_resolved_invalid_row_also_returned(
        self, service: ApprovalService, db: Database
    ) -> None:
        """audit 목적 — 이미 종결된 invalid row 도 반환된다."""
        await _seed_invalid_row(
            db,
            approval_id="resolved-invalid",
            status=ApprovalStatus.REJECTED,
            resolved_at="2026-05-11T00:00:00+00:00",
            resolved_by="user-master",
        )

        result = await service.list_invalid_type_approvals()
        ids = [r.id for r in result]
        assert "resolved-invalid" in ids

    async def test_all_valid_enum_members_excluded(
        self, service: ApprovalService
    ) -> None:
        """``ApprovalType`` 의 모든 멤버는 invalid 목록에 포함되지 않는다."""
        for t in ApprovalType:
            # account-scoped 타입은 account_id 가 필요
            params: dict = {"account_id": "acct-test"}
            if t in (ApprovalType.STRATEGY_ADOPT, ApprovalType.STRATEGY_RETIRE):
                params = {"strategy_id": "s", "report_id": "r"}
            await service.create(
                type=t,
                requester="agent",
                title=f"valid-{t.value}",
                params=params,
            )

        result = await service.list_invalid_type_approvals()
        assert result == []


# ── force_cancel_invalid_type ─────────────────────────────────────


class TestForceCancelInvalidType:
    """invalid pending row 강제 cancel."""

    async def test_pending_invalid_row_cancelled(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """invalid pending row → CANCELLED + ``force_cancelled`` history."""
        await _seed_invalid_row(db, approval_id="legacy-1")

        result = await service.force_cancel_invalid_type(
            id="legacy-1",
            actor="user-master",
            reason="legacy cleanup",
        )

        assert result.status == ApprovalStatus.CANCELLED
        assert result.resolved_by == "user-master"
        assert result.resolved_at != ""

        # DB 검증
        row = await db.fetch_one(
            "SELECT status, resolved_at, resolved_by, history FROM approvals "
            "WHERE id = ?",
            ("legacy-1",),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.CANCELLED
        assert row["resolved_by"] == "user-master"
        assert row["resolved_at"] != ""
        history = json.loads(row["history"])
        actions = [entry["action"] for entry in history]
        assert "force_cancelled" in actions
        # 일반 cancelled 와 구별되어야 함 — 운영 강제 정리 표시.
        assert "cancelled" not in actions
        force = next(e for e in history if e["action"] == "force_cancelled")
        assert force["actor"] == "user-master"
        assert force["detail"] == "legacy cleanup"

    async def test_default_reason_when_omitted(
        self, service: ApprovalService, db: Database
    ) -> None:
        """reason 미지정 시 기본 detail 메시지 사용."""
        await _seed_invalid_row(db, approval_id="legacy-1")

        await service.force_cancel_invalid_type(id="legacy-1", actor="ops")

        row = await db.fetch_one(
            "SELECT history FROM approvals WHERE id = ?", ("legacy-1",)
        )
        assert row is not None
        history = json.loads(row["history"])
        force = next(e for e in history if e["action"] == "force_cancelled")
        assert force["detail"] == "legacy invalid approval type cleanup"

    async def test_publishes_resolved_event(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """``ApprovalResolvedEvent`` 가 ``cancelled`` resolution 으로 발행."""
        await _seed_invalid_row(db, approval_id="legacy-1")

        await service.force_cancel_invalid_type(id="legacy-1", actor="ops")

        assert len(collector.resolved) == 1
        ev = collector.resolved[0]
        assert ev.approval_id == "legacy-1"
        assert ev.resolution == ApprovalStatus.CANCELLED
        assert ev.resolved_by == "ops"

    async def test_publishes_resolved_notification(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """결재 처리 완료 notification 발행."""
        await _seed_invalid_row(db, approval_id="legacy-1")

        await service.force_cancel_invalid_type(id="legacy-1", actor="ops")

        assert len(collector.resolved_notifications) == 1
        notif = collector.resolved_notifications[0]
        assert "cancelled" in notif.message
        assert "legacy-1" in notif.message

    async def test_valid_type_row_rejected(
        self, service: ApprovalService, collector: _EventCollector
    ) -> None:
        """valid type row 는 force-cancel 거부 — 운영 도구가 정상 row 침범 금지."""
        req = await service.create(
            type=ApprovalType.STRATEGY_ADOPT,
            requester="agent-01",
            title="valid",
            params={"strategy_id": "s-1", "report_id": "r-1"},
        )

        with pytest.raises(ValueError, match="invalid type row 전용"):
            await service.force_cancel_invalid_type(
                id=req.id, actor="ops", reason="oops"
            )

        # 상태는 PENDING 유지, event 미발행
        assert collector.resolved == []
        assert collector.resolved_notifications == []

    async def test_already_resolved_invalid_row_rejected(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """이미 종결된 invalid row 는 거부 — audit trail 보존."""
        await _seed_invalid_row(
            db,
            approval_id="resolved-invalid",
            status=ApprovalStatus.REJECTED,
            resolved_at="2026-05-11T00:00:00+00:00",
            resolved_by="user-master",
        )

        with pytest.raises(ValueError, match="이미 종결된"):
            await service.force_cancel_invalid_type(id="resolved-invalid", actor="ops")

        # DB row 변경 없음
        row = await db.fetch_one(
            "SELECT status, resolved_by FROM approvals WHERE id = ?",
            ("resolved-invalid",),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.REJECTED
        assert row["resolved_by"] == "user-master"
        # 새 event 미발행
        assert collector.resolved == []

    async def test_nonexistent_id_rejected(self, service: ApprovalService) -> None:
        """존재하지 않는 ID 는 거부."""
        with pytest.raises(ValueError, match="찾을 수 없음"):
            await service.force_cancel_invalid_type(id="does-not-exist", actor="ops")

    async def test_force_cancel_does_not_revive_approve_path(
        self, service: ApprovalService, db: Database
    ) -> None:
        """force-cancel 한 row 는 이후 approve 시도해도 invalid 가드가 유지된다.

        force_cancel 은 status 만 바꾸고 ``type`` 컬럼은 invalid 그대로
        둔다. 따라서 ``approve()`` 의 enum 가드(#1470) 가 여전히 ValueError
        를 던져 audit trail 의 invariant 가 깨지지 않는다.
        """
        await _seed_invalid_row(db, approval_id="legacy-1")
        await service.force_cancel_invalid_type(id="legacy-1", actor="ops")

        # 이미 cancelled 이므로 approve 시도가 invalid type 으로 차단되어야 함.
        with pytest.raises(ValueError, match="invalid approval type"):
            await service.approve("legacy-1", resolved_by="user-master")


# ── _execute_approved defense-in-depth 회귀 ───────────────────────


class TestForceCancelDoesNotBypassApproveGuard:
    """force-cancel 이 #1470 의 invariant 를 우회하지 않음을 회귀로 확인."""

    async def test_force_cancel_pending_invalid_then_approve_blocked(
        self, service: ApprovalService, db: Database
    ) -> None:
        """force-cancel 한 invalid row 의 ``_execute_approved`` 직접 호출도
        enum 가드로 차단된다."""
        await _seed_invalid_row(db, approval_id="legacy-1")
        await service.force_cancel_invalid_type(id="legacy-1", actor="ops")

        bogus_request = ApprovalRequest(
            id="legacy-1",
            type="oracle_invalid_type",
            status=ApprovalStatus.APPROVED,
            requester="agent",
            title="bogus",
        )
        with pytest.raises(ValueError, match="invalid approval type"):
            await service._execute_approved(bogus_request, actor="ops")
