"""ApprovalService.list_invalid_type_requests / cancel_invalid_type_request (#1472).

#1469 (write path 가드) + #1470 (approve guard) 가 invalid-type approval row 의
신규 생성과 silent approve 를 차단했으므로 신규 invalid row 는 더 이상 만들어지지
않는다. 본 모듈은 그 이전에 생성된 legacy invalid row 에 대한
administrative cleanup API 의 invariant 를 검증한다:

- ``list_invalid_type_requests`` 는 ``_VALID_APPROVAL_TYPES`` 에 없는 ``type``
  의 row 만 반환하며, 정상 type row 는 절대 결과에 포함되지 않는다.
- ``status`` 필터가 정상 동작한다 (예: ``pending`` 만 조회).
- ``cancel_invalid_type_request`` 는 정상 type row 를 거부한다.
- 종결 상태(approved/rejected/cancelled/expired) row 를 거부한다.
- 처리 가능 상태(pending/on_hold/execution_failed) 의 invalid row 는 status
  → ``cancelled`` 로 전이되고 history 에 ``cancelled_invalid_type`` 액션이
  append 된다.
- 기본값 ``suppress_notification=True`` 에서는
  ``ApprovalResolvedEvent`` / ``NotificationEvent`` 가 발행되지 않는다.
- ``suppress_notification=False`` 에서는 일반 ``cancel()`` 과 동일하게
  ``ApprovalResolvedEvent`` 가 1회 발행된다.
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

# ── 헬퍼 ─────────────────────────────────────────────────────────


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
        if event.category == "approval":
            self.resolved_notifications.append(event)


async def _seed_row(
    db: Database,
    *,
    approval_id: str,
    approval_type: str,
    status: str = ApprovalStatus.PENDING,
    requester: str = "agent-x",
    created_at: str = "2026-04-01T00:00:00+00:00",
) -> None:
    """raw INSERT 로 임의 type/status 의 approval row 를 시드한다.

    Service.create 가 invalid type 을 거부하므로 legacy 상태 재현은 직접 INSERT 한다.
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
            status,
            requester,
            f"row {approval_id}",
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
            "",
            "",
        ),
    )


# ── 픽스처 ───────────────────────────────────────────────────────


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


# ── list_invalid_type_requests ───────────────────────────────────


class TestListInvalidTypeRequests:
    """invalid 만 식별 / 정상 type row 제외."""

    async def test_returns_only_invalid_type_rows(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """invalid type row 는 노출되고 정상 type row 는 제외된다."""
        await _seed_row(
            db,
            approval_id="invalid-1",
            approval_type="oracle_invalid_type",
        )
        # 정상 type 두 종류
        await _seed_row(
            db,
            approval_id="valid-1",
            approval_type=ApprovalType.STRATEGY_ADOPT.value,
        )
        await _seed_row(
            db,
            approval_id="valid-2",
            approval_type=ApprovalType.BOT_STOP.value,
        )

        result = await service.list_invalid_type_requests()
        ids = sorted(r.id for r in result)
        assert ids == ["invalid-1"]
        assert all(r.type not in {t.value for t in ApprovalType} for r in result), (
            "정상 type row 가 결과에 포함됨 — invariant 위반"
        )

    async def test_includes_all_statuses_when_status_none(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """status 미지정 시 모든 상태의 invalid row 를 반환."""
        await _seed_row(
            db,
            approval_id="inv-pending",
            approval_type="legacy_type_a",
            status=ApprovalStatus.PENDING,
        )
        await _seed_row(
            db,
            approval_id="inv-cancelled",
            approval_type="legacy_type_b",
            status=ApprovalStatus.CANCELLED,
        )

        result = await service.list_invalid_type_requests()
        ids = sorted(r.id for r in result)
        assert ids == ["inv-cancelled", "inv-pending"]

    async def test_status_filter_applied(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """status 지정 시 그 상태의 invalid row 만 반환."""
        await _seed_row(
            db,
            approval_id="inv-pending",
            approval_type="legacy_type",
            status=ApprovalStatus.PENDING,
        )
        await _seed_row(
            db,
            approval_id="inv-cancelled",
            approval_type="legacy_type",
            status=ApprovalStatus.CANCELLED,
        )

        result = await service.list_invalid_type_requests(status=ApprovalStatus.PENDING)
        assert [r.id for r in result] == ["inv-pending"]

    async def test_empty_when_only_valid_rows(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """정상 type row 만 있으면 결과는 빈 리스트."""
        await _seed_row(
            db,
            approval_id="valid-1",
            approval_type=ApprovalType.STRATEGY_ADOPT.value,
        )
        result = await service.list_invalid_type_requests()
        assert result == []


# ── cancel_invalid_type_request 거부 케이스 ───────────────────────


class TestCancelInvalidTypeRequestRejection:
    """정상 type 거부 / 종결 상태 거부 / 미존재 거부."""

    async def test_rejects_valid_type_row(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """정상 type row 는 ``ValueError`` 로 거부 — invariant 보호."""
        await _seed_row(
            db,
            approval_id="valid-1",
            approval_type=ApprovalType.STRATEGY_ADOPT.value,
        )

        with pytest.raises(ValueError, match="not an invalid-type request"):
            await service.cancel_invalid_type_request("valid-1", resolved_by="admin-1")

        # row 는 PENDING 그대로
        row = await db.fetch_one(
            "SELECT status, resolved_by FROM approvals WHERE id = ?",
            ("valid-1",),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.PENDING
        assert row["resolved_by"] == ""

    @pytest.mark.parametrize(
        "terminal_status",
        [
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.CANCELLED,
            ApprovalStatus.EXPIRED,
        ],
    )
    async def test_rejects_terminal_status_row(
        self,
        service: ApprovalService,
        db: Database,
        terminal_status: str,
    ) -> None:
        """이미 종결된 invalid row 는 cancel-invalid 로 덮어쓰지 못한다."""
        await _seed_row(
            db,
            approval_id="inv-term",
            approval_type="oracle_invalid_type",
            status=terminal_status,
        )

        with pytest.raises(ValueError, match="cancel-invalid 가능"):
            await service.cancel_invalid_type_request("inv-term", resolved_by="admin-1")

        row = await db.fetch_one(
            "SELECT status FROM approvals WHERE id = ?", ("inv-term",)
        )
        assert row is not None
        assert row["status"] == terminal_status

    async def test_rejects_nonexistent_row(
        self,
        service: ApprovalService,
    ) -> None:
        """미존재 id 는 ``ApprovalNotFoundError`` (code=APPROVAL_NOT_FOUND).

        #1798 Group A sweep: 이전 ``ValueError`` 에서 typed
        ``ApprovalNotFoundError`` 로 전환되어 IPC envelope 이 안정
        코드 ``APPROVAL_NOT_FOUND`` 를 surface 한다. type/status 검증의
        ``ValueError`` 는 그대로 유지된다 (sibling tests 회귀 없음).
        """
        from ante.approval.errors import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError, match="찾을 수 없음") as excinfo:
            await service.cancel_invalid_type_request(
                "no-such-id", resolved_by="admin-1"
            )
        assert getattr(excinfo.value, "code", None) == "APPROVAL_NOT_FOUND"


# ── cancel_invalid_type_request 성공 케이스 ───────────────────────


class TestCancelInvalidTypeRequestSuccess:
    """정상 처리 + history append + status 전이."""

    @pytest.mark.parametrize(
        "start_status",
        [
            ApprovalStatus.PENDING,
            ApprovalStatus.ON_HOLD,
            ApprovalStatus.EXECUTION_FAILED,
        ],
    )
    async def test_cancels_processable_invalid_row(
        self,
        service: ApprovalService,
        db: Database,
        start_status: str,
    ) -> None:
        """pending/on_hold/execution_failed invalid row 가 cancelled 로 전이."""
        await _seed_row(
            db,
            approval_id="inv-1",
            approval_type="oracle_invalid_type",
            status=start_status,
        )

        result = await service.cancel_invalid_type_request(
            "inv-1", resolved_by="admin-1"
        )
        assert result.status == ApprovalStatus.CANCELLED
        assert result.resolved_by == "admin-1"
        assert result.resolved_at != ""

        row = await db.fetch_one(
            "SELECT status, resolved_by, resolved_at, history FROM approvals "
            "WHERE id = ?",
            ("inv-1",),
        )
        assert row is not None
        assert row["status"] == ApprovalStatus.CANCELLED
        assert row["resolved_by"] == "admin-1"
        assert row["resolved_at"] != ""

        history = json.loads(row["history"])
        actions = [entry["action"] for entry in history]
        assert actions[-1] == "cancelled_invalid_type"
        last_entry = history[-1]
        assert last_entry["actor"] == "admin-1"
        assert last_entry["detail"] == "legacy invalid type cleanup"

    async def test_custom_detail_recorded_in_history(
        self,
        service: ApprovalService,
        db: Database,
    ) -> None:
        """custom detail 인자가 history 에 그대로 기록된다."""
        await _seed_row(
            db,
            approval_id="inv-1",
            approval_type="oracle_invalid_type",
        )
        await service.cancel_invalid_type_request(
            "inv-1",
            resolved_by="admin-1",
            detail="rfp-2026-04 cleanup batch",
        )

        row = await db.fetch_one(
            "SELECT history FROM approvals WHERE id = ?", ("inv-1",)
        )
        assert row is not None
        history = json.loads(row["history"])
        assert history[-1]["detail"] == "rfp-2026-04 cleanup batch"


# ── suppress_notification 분기 ───────────────────────────────────


class TestCancelInvalidTypeSuppressNotification:
    """suppress_notification True(default)/False 양쪽 분기 검증."""

    async def test_default_suppresses_event_and_notification(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """기본값(True) 에서는 ApprovalResolvedEvent / NotificationEvent 발행 없음."""
        await _seed_row(
            db,
            approval_id="inv-1",
            approval_type="oracle_invalid_type",
        )

        await service.cancel_invalid_type_request("inv-1", resolved_by="admin-1")

        assert collector.resolved == []
        assert collector.resolved_notifications == []

    async def test_suppress_false_publishes_resolved_event(
        self,
        service: ApprovalService,
        db: Database,
        collector: _EventCollector,
    ) -> None:
        """suppress_notification=False 에서는 ApprovalResolvedEvent 1회 발행."""
        await _seed_row(
            db,
            approval_id="inv-2",
            approval_type="oracle_invalid_type",
        )

        await service.cancel_invalid_type_request(
            "inv-2",
            resolved_by="admin-1",
            suppress_notification=False,
        )

        assert len(collector.resolved) == 1
        event = collector.resolved[0]
        assert event.approval_id == "inv-2"
        assert event.approval_type == "oracle_invalid_type"
        assert event.resolution == ApprovalStatus.CANCELLED
        assert event.resolved_by == "admin-1"

        # 결재 처리 완료 notification 도 1회 발행
        completion = [
            n for n in collector.resolved_notifications if n.title == "결재 처리 완료"
        ]
        assert len(completion) == 1
