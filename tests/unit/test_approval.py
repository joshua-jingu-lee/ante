"""Approval 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ante.approval.models import (
    ApprovalRequest,
    ApprovalStatus,
    ApprovalType,
    ApprovalValidationError,
    ValidationResult,
)
from ante.approval.service import ApprovalService
from ante.core.database import Database
from ante.eventbus.bus import EventBus
from ante.eventbus.events import ApprovalCreatedEvent, ApprovalResolvedEvent

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    """테스트용 SQLite DB."""
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    return db


@pytest.fixture
async def eventbus():
    return EventBus()


@pytest.fixture
async def service(db, eventbus):
    svc = ApprovalService(db=db, eventbus=eventbus)
    await svc.initialize()
    return svc


# ── Models ───────────────────────────────────────────


class TestModels:
    def test_approval_status_values(self):
        """ApprovalStatus 값."""
        assert ApprovalStatus.PENDING == "pending"
        assert ApprovalStatus.APPROVED == "approved"
        assert ApprovalStatus.REJECTED == "rejected"
        assert ApprovalStatus.ON_HOLD == "on_hold"
        assert ApprovalStatus.EXPIRED == "expired"
        assert ApprovalStatus.CANCELLED == "cancelled"

    def test_approval_type_values(self):
        """ApprovalType 값."""
        assert ApprovalType.STRATEGY_ADOPT == "strategy_adopt"
        assert ApprovalType.BUDGET_CHANGE == "budget_change"
        assert ApprovalType.BOT_CREATE == "bot_create"
        assert ApprovalType.BOT_STOP == "bot_stop"
        assert ApprovalType.RULE_CHANGE == "rule_change"

    def test_approval_request_defaults(self):
        """ApprovalRequest 기본값."""
        req = ApprovalRequest(
            id="test-id",
            type="budget_change",
            status="pending",
            requester="agent",
            title="테스트 요청",
        )
        assert req.body == ""
        assert req.params == {}
        assert req.reviews == []
        assert req.history == []
        assert req.reference_id == ""
        assert req.expires_at == ""


# ── ApprovalService: 생성 및 조회 (US-1) ────────────


class TestCreate:
    async def test_create_request(self, service):
        """결재 요청 생성."""
        req = await service.create(
            type="budget_change",
            requester="agent:strategy-dev",
            title="예산 증액 요청",
            body="수익률 15%, 비중 확대 요청",
            params={"bot_id": "bot-1", "amount": 25000000},
        )

        assert req.id
        assert req.type == "budget_change"
        assert req.status == "pending"
        assert req.requester == "agent:strategy-dev"
        assert req.title == "예산 증액 요청"
        assert req.body == "수익률 15%, 비중 확대 요청"
        assert req.params == {"bot_id": "bot-1", "amount": 25000000}
        assert len(req.history) == 1
        assert req.history[0]["action"] == "created"

    async def test_create_with_reference(self, service):
        """참조 ID가 있는 결재 요청."""
        req = await service.create(
            type="strategy_adopt",
            requester="agent",
            title="전략 채택 요청",
            reference_id="report-123",
        )
        assert req.reference_id == "report-123"

    async def test_create_with_expires(self, service):
        """만료 시간이 있는 결재 요청."""
        future = (datetime.now(UTC) + timedelta(hours=72)).isoformat()
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="테스트",
            expires_at=future,
        )
        assert req.expires_at == future

    async def test_create_publishes_event(self, service, eventbus):
        """생성 시 ApprovalCreatedEvent 발행."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalCreatedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalCreatedEvent, handler)

        await service.create(
            type="bot_create",
            requester="agent",
            title="봇 생성 요청",
        )

        assert len(received) == 1
        assert received[0].approval_type == "bot_create"
        assert received[0].requester == "agent"

    async def test_get_request(self, service):
        """단건 조회."""
        created = await service.create(
            type="budget_change",
            requester="agent",
            title="테스트",
        )

        fetched = await service.get(created.id)
        assert fetched is not None
        assert fetched.id == created.id
        assert fetched.type == "budget_change"

    async def test_get_nonexistent(self, service):
        """존재하지 않는 요청 조회 시 None."""
        assert await service.get("nonexistent") is None

    async def test_list_all(self, service):
        """전체 목록 조회."""
        await service.create(type="budget_change", requester="agent", title="요청 1")
        await service.create(type="bot_create", requester="agent", title="요청 2")
        await service.create(type="bot_stop", requester="agent", title="요청 3")

        all_requests = await service.list()
        assert len(all_requests) == 3

    async def test_list_filter_status(self, service):
        """상태 필터 조회."""
        req = await service.create(
            type="budget_change", requester="agent", title="요청 1"
        )
        await service.create(type="bot_create", requester="agent", title="요청 2")
        await service.approve(req.id)

        pending = await service.list(status="pending")
        assert len(pending) == 1

        approved = await service.list(status="approved")
        assert len(approved) == 1

    async def test_list_filter_type(self, service):
        """유형 필터 조회."""
        await service.create(type="budget_change", requester="agent", title="요청 1")
        await service.create(type="bot_create", requester="agent", title="요청 2")

        budget = await service.list(type="budget_change")
        assert len(budget) == 1
        assert budget[0].type == "budget_change"

    async def test_list_pagination(self, service):
        """페이지네이션."""
        for i in range(5):
            await service.create(
                type="budget_change", requester="agent", title=f"요청 {i}"
            )

        page1 = await service.list(limit=2, offset=0)
        page2 = await service.list(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2


# ── 승인·거절·보류 (US-2) ────────────────────────────


class TestResolve:
    async def test_approve(self, service):
        """결재 승인."""
        req = await service.create(
            type="budget_change", requester="agent", title="승인 테스트"
        )
        approved = await service.approve(req.id)

        assert approved.status == "approved"
        assert approved.resolved_by == "user"
        assert approved.resolved_at != ""
        assert any(h["action"] == "approved" for h in approved.history)

    async def test_approve_executes_handler(self, db, eventbus):
        """승인 시 executor 실행."""
        executed = []

        async def mock_executor(params: dict) -> None:
            executed.append(params)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": mock_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="실행 테스트",
            params={"bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)

        assert len(executed) == 1
        assert executed[0]["bot_id"] == "bot-1"

    async def test_approve_publishes_event(self, service, eventbus):
        """승인 시 ApprovalResolvedEvent 발행."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalResolvedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, handler)

        req = await service.create(
            type="budget_change", requester="agent", title="이벤트 테스트"
        )
        await service.approve(req.id)

        assert len(received) == 1
        assert received[0].resolution == "approved"

    async def test_approve_non_pending_fails(self, service):
        """pending이 아닌 상태에서 승인 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent", title="테스트"
        )
        await service.approve(req.id)

        with pytest.raises(ValueError, match="pending 상태에서만 승인 가능"):
            await service.approve(req.id)

    async def test_reject(self, service):
        """결재 거절."""
        req = await service.create(
            type="budget_change", requester="agent", title="거절 테스트"
        )
        rejected = await service.reject(req.id, reject_reason="리스크 과다")

        assert rejected.status == "rejected"
        assert rejected.reject_reason == "리스크 과다"
        assert any(h["action"] == "rejected" for h in rejected.history)

    async def test_reject_non_pending_fails(self, service):
        """pending이 아닌 상태에서 거절 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent", title="테스트"
        )
        await service.reject(req.id)

        with pytest.raises(ValueError, match="pending 상태에서만 거절 가능"):
            await service.reject(req.id)

    async def test_hold_and_resume(self, service):
        """보류 및 재개."""
        req = await service.create(
            type="budget_change", requester="agent", title="보류 테스트"
        )

        held = await service.hold(req.id)
        assert held.status == "on_hold"
        assert any(h["action"] == "held" for h in held.history)

        resumed = await service.resume(req.id)
        assert resumed.status == "pending"
        assert any(h["action"] == "resumed" for h in resumed.history)

    async def test_hold_non_pending_fails(self, service):
        """pending이 아닌 상태에서 보류 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent", title="테스트"
        )
        await service.approve(req.id)

        with pytest.raises(ValueError, match="pending 상태에서만 보류 가능"):
            await service.hold(req.id)

    async def test_resume_non_hold_fails(self, service):
        """on_hold가 아닌 상태에서 재개 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent", title="테스트"
        )

        with pytest.raises(ValueError, match="on_hold 상태에서만 재개 가능"):
            await service.resume(req.id)


# ── 철회 (US-3) ──────────────────────────────────────


class TestCancel:
    async def test_cancel_pending(self, service):
        """pending 상태에서 철회."""
        req = await service.create(
            type="budget_change", requester="agent:dev", title="철회 테스트"
        )
        cancelled = await service.cancel(req.id, requester="agent:dev")

        assert cancelled.status == "cancelled"
        assert any(h["action"] == "cancelled" for h in cancelled.history)

    async def test_cancel_on_hold(self, service):
        """on_hold 상태에서 철회."""
        req = await service.create(
            type="budget_change", requester="agent:dev", title="보류 후 철회"
        )
        await service.hold(req.id)
        cancelled = await service.cancel(req.id, requester="agent:dev")

        assert cancelled.status == "cancelled"

    async def test_cancel_wrong_requester_fails(self, service):
        """본인이 아닌 요청자가 철회 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent:dev", title="테스트"
        )

        with pytest.raises(ValueError, match="본인 요청만 철회 가능"):
            await service.cancel(req.id, requester="agent:other")

    async def test_cancel_approved_fails(self, service):
        """이미 승인된 요청 철회 시 에러."""
        req = await service.create(
            type="budget_change", requester="agent:dev", title="테스트"
        )
        await service.approve(req.id)

        with pytest.raises(ValueError, match="pending/on_hold 상태에서만 철회 가능"):
            await service.cancel(req.id, requester="agent:dev")

    async def test_cancel_publishes_event(self, service, eventbus):
        """철회 시 ApprovalResolvedEvent 발행."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalResolvedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, handler)

        req = await service.create(
            type="budget_change", requester="agent:dev", title="이벤트 테스트"
        )
        await service.cancel(req.id, requester="agent:dev")

        assert len(received) == 1
        assert received[0].resolution == "cancelled"


# ── 사전 검증 (US-4) ────────────────────────────────


class TestReview:
    async def test_add_review(self, service):
        """검토 의견 추가."""
        req = await service.create(
            type="budget_change", requester="agent", title="검토 테스트"
        )

        reviewed = await service.add_review(
            id=req.id,
            reviewer="treasury",
            result="pass",
            detail="가용 잔액 충분",
        )

        assert len(reviewed.reviews) == 1
        assert reviewed.reviews[0]["reviewer"] == "treasury"
        assert reviewed.reviews[0]["result"] == "pass"
        assert reviewed.reviews[0]["detail"] == "가용 잔액 충분"
        assert any(h["action"] == "review_added" for h in reviewed.history)

    async def test_multiple_reviews(self, service):
        """복수 검토 의견."""
        req = await service.create(
            type="budget_change", requester="agent", title="복수 검토"
        )

        await service.add_review(req.id, "treasury", "pass", "잔액 충분")
        reviewed = await service.add_review(
            req.id, "agent:risk-analyst", "warn", "변동성 주의"
        )

        assert len(reviewed.reviews) == 2

    async def test_review_nonexistent_fails(self, service):
        """존재하지 않는 요청에 검토 시 에러."""
        with pytest.raises(ValueError, match="결재 요청을 찾을 수 없음"):
            await service.add_review("nonexistent", "treasury", "pass")


# ── 감사 이력 (US-5) ────────────────────────────────


class TestHistory:
    async def test_full_lifecycle_history(self, service):
        """전체 생명주기 이력 추적."""
        req = await service.create(
            type="budget_change", requester="agent:dev", title="이력 테스트"
        )
        await service.add_review(req.id, "treasury", "pass", "잔액 충분")
        await service.hold(req.id)
        await service.resume(req.id)
        result = await service.approve(req.id)

        actions = [h["action"] for h in result.history]
        assert actions == [
            "created",
            "review_added",
            "held",
            "resumed",
            "approved",
        ]

    async def test_history_persisted(self, service):
        """이력이 DB에 영속화."""
        req = await service.create(
            type="budget_change", requester="agent", title="영속화 테스트"
        )
        await service.approve(req.id)

        fetched = await service.get(req.id)
        assert fetched is not None
        assert len(fetched.history) == 2
        assert fetched.history[0]["action"] == "created"
        assert fetched.history[1]["action"] == "approved"


# ── 만료 처리 (US-6) ────────────────────────────────


class TestExpire:
    async def test_expire_stale(self, service):
        """만료 기한이 지난 요청 일괄 처리."""
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await service.create(
            type="budget_change",
            requester="agent",
            title="만료 테스트",
            expires_at=past,
        )

        count = await service.expire_stale()
        assert count == 1

        requests = await service.list(status="expired")
        assert len(requests) == 1
        assert any(h["action"] == "expired" for h in requests[0].history)

    async def test_expire_skips_non_pending(self, service):
        """pending이 아닌 요청은 만료 처리 안 함."""
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="이미 승인됨",
            expires_at=past,
        )
        await service.approve(req.id)

        count = await service.expire_stale()
        assert count == 0

    async def test_expire_skips_no_expiry(self, service):
        """만료 기한이 없는 요청은 만료 처리 안 함."""
        await service.create(type="budget_change", requester="agent", title="무기한")

        count = await service.expire_stale()
        assert count == 0

    async def test_expire_skips_future(self, service):
        """만료 기한이 아직 안 된 요청은 만료 처리 안 함."""
        future = (datetime.now(UTC) + timedelta(hours=72)).isoformat()
        await service.create(
            type="budget_change",
            requester="agent",
            title="아직 유효",
            expires_at=future,
        )

        count = await service.expire_stale()
        assert count == 0


# ── 이벤트 모델 (US-7) ──────────────────────────────


class TestEvents:
    def test_approval_created_event(self):
        """ApprovalCreatedEvent 기본값."""
        event = ApprovalCreatedEvent(
            approval_id="test-id",
            approval_type="budget_change",
            requester="agent",
            title="테스트",
        )
        assert event.approval_id == "test-id"
        assert event.event_id is not None
        assert event.timestamp is not None

    def test_approval_resolved_event(self):
        """ApprovalResolvedEvent 기본값."""
        event = ApprovalResolvedEvent(
            approval_id="test-id",
            approval_type="budget_change",
            resolution="approved",
            resolved_by="user",
        )
        assert event.resolution == "approved"
        assert event.event_id is not None


# ── 사전 검증 Validator (US-8) ────────────────────────


class TestValidator:
    """사전 검증(validator) 단위 테스트."""

    async def test_fail_blocks_creation(self, db, eventbus):
        """fail 등급 검증 결과 시 요청 생성이 차단된다."""

        def fail_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("fail", "봇이 running 상태", "system:bot_manager")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"bot_delete": fail_validator},
        )
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="봇이 running 상태"):
            await svc.create(
                type="bot_delete",
                requester="agent",
                title="봇 삭제 요청",
                params={"bot_id": "bot-1"},
            )

        # DB에 요청이 생성되지 않았는지 확인
        all_requests = await svc.list()
        assert len(all_requests) == 0

    async def test_warn_attaches_review(self, db, eventbus):
        """warn 등급 검증 결과 시 요청은 생성되고 reviews에 경고가 첨부된다."""

        def warn_validator(params: dict) -> list[ValidationResult]:
            return [
                ValidationResult(
                    "warn",
                    "미할당 잔액 부족",
                    "system:treasury",
                )
            ]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"budget_change": warn_validator},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="예산 증액",
            params={"bot_id": "bot-1", "amount": 50000000, "current": 10000000},
        )

        assert req.status == "pending"
        assert len(req.reviews) == 1
        assert req.reviews[0]["result"] == "warn"
        assert req.reviews[0]["reviewer"] == "system:treasury"
        assert "미할당 잔액 부족" in req.reviews[0]["detail"]

    async def test_pass_creates_normally(self, db, eventbus):
        """pass 등급 검증 결과 시 요청이 정상 생성된다."""

        def pass_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("pass", "", "system:bot_manager")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"bot_delete": pass_validator},
        )
        await svc.initialize()

        req = await svc.create(
            type="bot_delete",
            requester="agent",
            title="봇 삭제",
            params={"bot_id": "bot-1"},
        )

        assert req.status == "pending"
        assert len(req.reviews) == 0

    async def test_no_validator_creates_normally(self, service):
        """validator가 등록되지 않은 유형은 정상 생성된다."""
        req = await service.create(
            type="rule_change",
            requester="agent",
            title="규칙 변경",
            params={"bot_id": "bot-1", "rules": {}},
        )
        assert req.status == "pending"

    async def test_multiple_results_first_fail_blocks(self, db, eventbus):
        """복수 검증 결과 중 첫 번째 fail이 생성을 차단한다."""

        def multi_validator(params: dict) -> list[ValidationResult]:
            return [
                ValidationResult("fail", "봇이 running 상태", "system:bot_manager"),
                ValidationResult("fail", "보유 포지션 존재", "system:trade"),
            ]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"bot_delete": multi_validator},
        )
        await svc.initialize()

        with pytest.raises(ApprovalValidationError, match="봇이 running 상태"):
            await svc.create(
                type="bot_delete",
                requester="agent",
                title="봇 삭제",
                params={"bot_id": "bot-1"},
            )

    async def test_warn_persisted_to_db(self, db, eventbus):
        """warn reviews가 DB에 영속화된다."""

        def warn_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("warn", "잔액 주의", "system:treasury")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"budget_change": warn_validator},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="예산 변경",
            params={"bot_id": "bot-1", "amount": 20000000, "current": 10000000},
        )

        fetched = await svc.get(req.id)
        assert fetched is not None
        assert len(fetched.reviews) == 1
        assert fetched.reviews[0]["result"] == "warn"

    async def test_warn_with_reviewed_at(self, db, eventbus):
        """warn review에 reviewed_at 시각이 포함된다."""

        def warn_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("warn", "잔액 부족", "system:treasury")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"budget_change": warn_validator},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="예산 변경",
            params={"bot_id": "bot-1", "amount": 20000000},
        )

        assert "reviewed_at" in req.reviews[0]
        assert req.reviews[0]["reviewed_at"] != ""


# ── 모델 추가분 (US-9) ──────────────────────────────


class TestValidationModels:
    def test_validation_result_frozen(self):
        """ValidationResult는 불변이다."""
        result = ValidationResult("fail", "테스트", "system:test")
        with pytest.raises(AttributeError):
            result.grade = "pass"  # type: ignore[misc]

    def test_approval_validation_error(self):
        """ApprovalValidationError에 detail 속성이 있다."""
        error = ApprovalValidationError("검증 실패")
        assert error.detail == "검증 실패"
        assert str(error) == "검증 실패"

    def test_approval_type_new_values(self):
        """새로 추가된 ApprovalType 값."""
        assert ApprovalType.STRATEGY_RETIRE == "strategy_retire"
        assert ApprovalType.BOT_ASSIGN_STRATEGY == "bot_assign_strategy"
        assert ApprovalType.BOT_CHANGE_STRATEGY == "bot_change_strategy"
        assert ApprovalType.BOT_RESUME == "bot_resume"
        assert ApprovalType.BOT_DELETE == "bot_delete"
