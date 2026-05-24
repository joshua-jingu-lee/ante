"""Approval 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ante.account.models import Account, TradingMode
from ante.approval.auto_approve import AutoApproveConfig, AutoApproveEvaluator
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
from ante.eventbus.events import (
    ApprovalCreatedEvent,
    ApprovalResolvedEvent,
)

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
    """기본 ApprovalService.

    Refs #1418 → #1470 SPLIT-B: executor 미등록 valid type 의 approve 가
    silent success 가 아닌 ``EXECUTION_FAILED`` 로 마감되도록 강화되었기
    때문에, 기존 lifecycle 회귀 테스트들이 의도한 ``approved`` 종료 상태를
    유지하려면 valid type 별로 no-op executor 가 등록되어 있어야 한다.
    본 픽스처는 ``ApprovalType`` 의 모든 멤버에 대해 no-op executor 를
    등록한다 (silent no-op 회귀 가드 본 이슈의 검증은 새 테스트 모듈
    ``test_approval_invalid_type_approve.py`` 에서 다룬다).
    """

    async def _noop_executor(params: dict) -> None:
        return None

    executors = {t.value: _noop_executor for t in ApprovalType}
    svc = ApprovalService(db=db, eventbus=eventbus, executors=executors)
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
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )

        assert req.id
        assert req.type == "budget_change"
        assert req.status == "pending"
        assert req.requester == "agent:strategy-dev"
        assert req.title == "예산 증액 요청"
        assert req.body == "수익률 15%, 비중 확대 요청"
        assert req.params == {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 25000000,
        }
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
            params={"account_id": "acc-test"},
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
            params={"account_id": "acc-test"},
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
            params={"account_id": "acc-test"},
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
        await service.create(
            type="budget_change",
            requester="agent",
            title="요청 1",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="bot_create",
            requester="agent",
            title="요청 2",
            params={"account_id": "acc-test"},
        )
        await service.create(type="bot_stop", requester="agent", title="요청 3")

        all_requests = await service.list_approvals()
        assert len(all_requests) == 3

    async def test_list_filter_status(self, service):
        """상태 필터 조회."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="요청 1",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="bot_create",
            requester="agent",
            title="요청 2",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        pending = await service.list_approvals(status="pending")
        assert len(pending) == 1

        approved = await service.list_approvals(status="approved")
        assert len(approved) == 1

    async def test_list_filter_type(self, service):
        """유형 필터 조회."""
        await service.create(
            type="budget_change",
            requester="agent",
            title="요청 1",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="bot_create",
            requester="agent",
            title="요청 2",
            params={"account_id": "acc-test"},
        )

        budget = await service.list_approvals(type="budget_change")
        assert len(budget) == 1
        assert budget[0].type == "budget_change"

    async def test_list_pagination(self, service):
        """페이지네이션."""
        for i in range(5):
            await service.create(
                type="budget_change",
                requester="agent",
                title=f"요청 {i}",
                params={"account_id": "acc-test"},
            )

        page1 = await service.list_approvals(limit=2, offset=0)
        page2 = await service.list_approvals(limit=2, offset=2)
        assert len(page1) == 2
        assert len(page2) == 2


# ── 승인·거절·보류 (US-2) ────────────────────────────


class TestResolve:
    async def test_approve(self, service):
        """결재 승인."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="승인 테스트",
            params={"account_id": "acc-test"},
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
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
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
            type="budget_change",
            requester="agent",
            title="이벤트 테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        assert len(received) == 1
        assert received[0].resolution == "approved"

    async def test_approve_non_pending_fails(self, service):
        """pending이 아닌 상태에서 승인 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        with pytest.raises(
            ValueError, match="pending/execution_failed 상태에서만 승인 가능"
        ):
            await service.approve(req.id)

    async def test_reject(self, service):
        """결재 거절."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="거절 테스트",
            params={"account_id": "acc-test"},
        )
        rejected = await service.reject(req.id, reject_reason="리스크 과다")

        assert rejected.status == "rejected"
        assert rejected.reject_reason == "리스크 과다"
        assert any(h["action"] == "rejected" for h in rejected.history)

    async def test_reject_non_pending_fails(self, service):
        """pending이 아닌 상태에서 거절 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="테스트",
            params={"account_id": "acc-test"},
        )
        await service.reject(req.id)

        with pytest.raises(
            ValueError, match="pending/execution_failed 상태에서만 거절 가능"
        ):
            await service.reject(req.id)

    async def test_hold_and_resume(self, service):
        """보류 및 재개."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="보류 테스트",
            params={"account_id": "acc-test"},
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
            type="budget_change",
            requester="agent",
            title="테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        with pytest.raises(
            ValueError, match="pending/execution_failed 상태에서만 보류 가능"
        ):
            await service.hold(req.id)

    async def test_resume_non_hold_fails(self, service):
        """on_hold가 아닌 상태에서 재개 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="테스트",
            params={"account_id": "acc-test"},
        )

        with pytest.raises(ValueError, match="on_hold 상태에서만 재개 가능"):
            await service.resume(req.id)


# ── 철회 (US-3) ──────────────────────────────────────


class TestCancel:
    async def test_cancel_pending(self, service):
        """pending 상태에서 철회."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="철회 테스트",
            params={"account_id": "acc-test"},
        )
        cancelled = await service.cancel(req.id, requester="agent:dev")

        assert cancelled.status == "cancelled"
        assert any(h["action"] == "cancelled" for h in cancelled.history)

    async def test_cancel_on_hold(self, service):
        """on_hold 상태에서 철회."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="보류 후 철회",
            params={"account_id": "acc-test"},
        )
        await service.hold(req.id)
        cancelled = await service.cancel(req.id, requester="agent:dev")

        assert cancelled.status == "cancelled"

    async def test_cancel_wrong_requester_fails(self, service):
        """본인이 아닌 요청자가 철회 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="테스트",
            params={"account_id": "acc-test"},
        )

        with pytest.raises(ValueError, match="본인 요청만 철회 가능"):
            await service.cancel(req.id, requester="agent:other")

    async def test_cancel_approved_fails(self, service):
        """이미 승인된 요청 철회 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        with pytest.raises(
            ValueError, match="pending/on_hold/execution_failed 상태에서만 철회 가능"
        ):
            await service.cancel(req.id, requester="agent:dev")

    async def test_cancel_publishes_event(self, service, eventbus):
        """철회 시 ApprovalResolvedEvent 발행."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalResolvedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, handler)

        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="이벤트 테스트",
            params={"account_id": "acc-test"},
        )
        await service.cancel(req.id, requester="agent:dev")

        assert len(received) == 1
        assert received[0].resolution == "cancelled"


# ── 사전 검증 (US-4) ────────────────────────────────


class TestReview:
    async def test_add_review(self, service):
        """검토 의견 추가."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="검토 테스트",
            params={"account_id": "acc-test"},
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
            type="budget_change",
            requester="agent",
            title="복수 검토",
            params={"account_id": "acc-test"},
        )

        await service.add_review(req.id, "treasury", "pass", "잔액 충분")
        reviewed = await service.add_review(
            req.id, "agent:risk-analyst", "warn", "변동성 주의"
        )

        assert len(reviewed.reviews) == 2

    async def test_review_nonexistent_fails(self, service):
        """존재하지 않는 요청에 검토 시 ``ApprovalNotFoundError`` (#1811)."""
        from ante.approval.errors import ApprovalNotFoundError

        with pytest.raises(ApprovalNotFoundError) as excinfo:
            await service.add_review("nonexistent", "treasury", "pass")
        assert getattr(excinfo.value, "code", None) == "APPROVAL_NOT_FOUND"
        assert "결재 요청을 찾을 수 없음" in str(excinfo.value)


# ── 감사 이력 (US-5) ────────────────────────────────


class TestHistory:
    async def test_full_lifecycle_history(self, service):
        """전체 생명주기 이력 추적."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="이력 테스트",
            params={"account_id": "acc-test"},
        )
        await service.add_review(req.id, "treasury", "pass", "잔액 충분")
        await service.hold(req.id)
        await service.resume(req.id)
        result = await service.approve(req.id)

        actions = [h["action"] for h in result.history]
        # Refs #1470: service 픽스처에 no-op executor 가 등록되어 approve
        # 직후 ``executed`` history 가 자동 추가된다.
        assert actions == [
            "created",
            "review_added",
            "held",
            "resumed",
            "approved",
            "executed",
        ]

    async def test_history_persisted(self, service):
        """이력이 DB에 영속화."""
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="영속화 테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        fetched = await service.get(req.id)
        assert fetched is not None
        # Refs #1470: ``executed`` history 가 approve 직후 추가된다.
        assert len(fetched.history) == 3
        assert fetched.history[0]["action"] == "created"
        assert fetched.history[1]["action"] == "approved"
        assert fetched.history[2]["action"] == "executed"


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
            params={"account_id": "acc-test"},
        )

        count = await service.expire_stale()
        assert count == 1

        requests = await service.list_approvals(status="expired")
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
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        count = await service.expire_stale()
        assert count == 0

    async def test_expire_skips_no_expiry(self, service):
        """만료 기한이 없는 요청은 만료 처리 안 함."""
        await service.create(
            type="budget_change",
            requester="agent",
            title="무기한",
            params={"account_id": "acc-test"},
        )

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
            params={"account_id": "acc-test"},
        )

        count = await service.expire_stale()
        assert count == 0

    async def test_expire_event_published(self, service, eventbus):
        """만료 처리 시 건별 ApprovalResolvedEvent가 발행된다."""
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await service.create(
            type="budget_change",
            requester="agent",
            title="만료 이벤트 테스트",
            expires_at=past,
            params={"account_id": "acc-test"},
        )

        received: list[ApprovalResolvedEvent] = []

        async def _handler(event: ApprovalResolvedEvent) -> None:
            received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, _handler)

        count = await service.expire_stale()
        assert count == 1
        assert len(received) == 1
        assert received[0].resolution == ApprovalStatus.EXPIRED
        assert received[0].resolved_by == "system"


# ── 만료 스케줄러 (US-8) ──────────────────────────────


class TestExpireLoop:
    @staticmethod
    async def _expire_loop(approval_service, interval: float = 300.0):
        """main._approval_expire_loop과 동일한 로직 (테스트용 복제)."""
        import asyncio

        while True:
            await asyncio.sleep(interval)
            try:
                expired = await approval_service.expire_stale()
                if expired:
                    pass  # 로깅 생략
            except asyncio.CancelledError:
                raise
            except Exception:
                pass  # 로깅 생략

    async def test_expire_loop_calls_expire_stale(self):
        """만료 스케줄러가 주기적으로 expire_stale()을 호출한다."""
        import asyncio

        call_count = 0

        class FakeApprovalService:
            async def expire_stale(self) -> int:
                nonlocal call_count
                call_count += 1
                return call_count

        fake_service = FakeApprovalService()
        task = asyncio.create_task(
            self._expire_loop(fake_service, interval=0.01),
            name="test-expire-loop",
        )

        # 짧은 interval로 최소 2회 호출될 때까지 대기
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        assert call_count >= 2

    async def test_expire_loop_survives_error(self):
        """expire_stale()이 예외를 던져도 루프가 계속된다."""
        import asyncio

        call_count = 0

        class FlakyApprovalService:
            async def expire_stale(self) -> int:
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    msg = "일시적 DB 오류"
                    raise RuntimeError(msg)
                return 0

        fake_service = FlakyApprovalService()
        task = asyncio.create_task(
            self._expire_loop(fake_service, interval=0.01),
            name="test-expire-loop-error",
        )

        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

        # 첫 번째에서 예외가 발생해도 두 번째 이후 호출이 이루어져야 한다
        assert call_count >= 2


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
        all_requests = await svc.list_approvals()
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
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 50000000,
                "current": 10000000,
            },
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
            params={"account_id": "acc-test", "bot_id": "bot-1", "rules": {}},
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
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 20000000,
                "current": 10000000,
            },
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
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 20000000},
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


class TestExecutionFailed:
    async def test_executor_failure_transitions_to_execution_failed(self, db, eventbus):
        """executor 실패 시 execution_failed 상태로 전환."""

        async def failing_executor(params: dict) -> None:
            msg = "잔액 부족"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="실행 실패 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        result = await svc.approve(req.id)

        assert result.status == "execution_failed"
        assert any(h["action"] == "execution_failed" for h in result.history)
        # 에러 메시지가 history에 기록
        failed_entry = next(
            h for h in result.history if h["action"] == "execution_failed"
        )
        assert "잔액 부족" in failed_entry["detail"]

    async def test_execution_failed_persisted_in_db(self, db, eventbus):
        """execution_failed 상태가 DB에 영속화."""

        async def failing_executor(params: dict) -> None:
            msg = "봇 미존재"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"bot_stop": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="bot_stop",
            requester="agent",
            title="영속화 테스트",
            params={"bot_id": "bot-1"},
        )
        await svc.approve(req.id)

        fetched = await svc.get(req.id)
        assert fetched is not None
        assert fetched.status == "execution_failed"
        assert any(h["action"] == "execution_failed" for h in fetched.history)

    async def test_reapprove_after_execution_failed(self, db, eventbus):
        """execution_failed 상태에서 재승인 → executor 재실행."""
        call_count = 0

        async def flaky_executor(params: dict) -> None:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                msg = "일시적 오류"
                raise RuntimeError(msg)
            # 두 번째 호출은 성공

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": flaky_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="재승인 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 10000000},
        )
        failed = await svc.approve(req.id)
        assert failed.status == "execution_failed"

        # 재승인
        success = await svc.approve(req.id)
        assert success.status == "approved"
        assert call_count == 2
        assert any(h["action"] == "executed" for h in success.history)

    async def test_reject_after_execution_failed(self, db, eventbus):
        """execution_failed 상태에서 거절 가능."""

        async def failing_executor(params: dict) -> None:
            msg = "실패"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="거절 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)
        rejected = await svc.reject(req.id, reject_reason="원인 해소 불가")

        assert rejected.status == "rejected"
        assert rejected.reject_reason == "원인 해소 불가"

    async def test_hold_after_execution_failed(self, db, eventbus):
        """execution_failed 상태에서 보류 가능."""

        async def failing_executor(params: dict) -> None:
            msg = "실패"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="보류 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)
        held = await svc.hold(req.id)

        assert held.status == "on_hold"

    async def test_cancel_after_execution_failed(self, db, eventbus):
        """execution_failed 상태에서 철회 가능."""

        async def failing_executor(params: dict) -> None:
            msg = "실패"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent:dev",
            title="철회 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)
        cancelled = await svc.cancel(req.id, requester="agent:dev")

        assert cancelled.status == "cancelled"

    async def test_execution_failed_publishes_event(self, db, eventbus):
        """executor 실패 시 ApprovalResolvedEvent에 execution_failed resolution."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalResolvedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalResolvedEvent, handler)

        async def failing_executor(params: dict) -> None:
            msg = "실패"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="이벤트 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)

        assert len(received) == 1
        assert received[0].resolution == "execution_failed"

    async def test_list_filter_execution_failed(self, db, eventbus):
        """execution_failed 상태 필터 조회."""

        async def failing_executor(params: dict) -> None:
            msg = "실패"
            raise RuntimeError(msg)

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            executors={"budget_change": failing_executor},
        )
        await svc.initialize()

        req = await svc.create(
            type="budget_change",
            requester="agent",
            title="필터 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await svc.approve(req.id)

        failed_list = await svc.list_approvals(status="execution_failed")
        assert len(failed_list) == 1
        assert failed_list[0].status == "execution_failed"


# ── 재상신 Reopen (US-10) ────────────────────────────


class TestReopen:
    async def test_reopen_rejected_to_pending(self, service):
        """거절된 요청을 재상신하면 pending 상태로 전환된다."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="재상신 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await service.reject(req.id, reject_reason="금액 과다")

        reopened = await service.reopen(
            id=req.id,
            requester="agent:dev",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 15000000,
            },
        )

        assert reopened.status == "pending"
        assert reopened.params == {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 15000000,
        }
        assert reopened.reject_reason == ""
        assert any(h["action"] == "reopened" for h in reopened.history)

    async def test_reopen_updates_body(self, service):
        """재상신 시 body를 갱신할 수 있다."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="body 갱신",
            body="원본 사유",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await service.reject(req.id)

        reopened = await service.reopen(
            id=req.id,
            requester="agent:dev",
            body="수정된 사유",
        )

        assert reopened.body == "수정된 사유"
        # params는 기존 값 유지
        assert reopened.params == {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 25000000,
        }

    async def test_reopen_keeps_existing_when_none(self, service):
        """body/params를 None으로 전달하면 기존 값이 유지된다."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="유지 테스트",
            body="원본 본문",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 20000000},
        )
        await service.reject(req.id)

        reopened = await service.reopen(id=req.id, requester="agent:dev")

        assert reopened.body == "원본 본문"
        assert reopened.params == {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 20000000,
        }

    async def test_reopen_non_rejected_fails(self, service):
        """rejected가 아닌 상태에서 reopen 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="상태 에러",
            params={"account_id": "acc-test"},
        )

        with pytest.raises(ValueError, match="rejected 상태에서만 reopen 가능"):
            await service.reopen(id=req.id, requester="agent:dev")

    async def test_reopen_wrong_requester_fails(self, service):
        """본인이 아닌 요청자가 reopen 시 에러."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="권한 에러",
            params={"account_id": "acc-test"},
        )
        await service.reject(req.id)

        with pytest.raises(ValueError, match="본인 요청만 reopen 가능"):
            await service.reopen(id=req.id, requester="agent:other")

    async def test_reopen_nonexistent_fails(self, service):
        """존재하지 않는 요청 reopen 시 에러."""
        with pytest.raises(ValueError, match="결재 요청을 찾을 수 없음"):
            await service.reopen(id="nonexistent", requester="agent:dev")

    async def test_reopen_reruns_validator_fail(self, db, eventbus):
        """reopen 시 validator가 재실행되고, fail이면 차단된다."""

        def fail_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("fail", "잔액 부족", "system:treasury")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"budget_change": fail_validator},
        )
        await svc.initialize()

        # validator 없이 생성 (직접 DB에 rejected 상태 만들기)
        svc_no_validator = ApprovalService(db=db, eventbus=eventbus)
        await svc_no_validator.initialize()
        req = await svc_no_validator.create(
            type="budget_change",
            requester="agent:dev",
            title="검증 실패 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 50000000},
        )
        await svc_no_validator.reject(req.id)

        with pytest.raises(ApprovalValidationError, match="잔액 부족"):
            await svc.reopen(
                id=req.id,
                requester="agent:dev",
                params={
                    "account_id": "acc-test",
                    "bot_id": "bot-1",
                    "amount": 50000000,
                },
            )

        # 상태가 여전히 rejected인지 확인
        fetched = await svc.get(req.id)
        assert fetched is not None
        assert fetched.status == "rejected"

    async def test_reopen_reruns_validator_warn(self, db, eventbus):
        """reopen 시 validator warn이면 reviews에 첨부되고 pending 전환."""

        def warn_validator(params: dict) -> list[ValidationResult]:
            return [ValidationResult("warn", "잔액 주의", "system:treasury")]

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            validators={"budget_change": warn_validator},
        )
        await svc.initialize()

        # validator 없이 생성
        svc_no_validator = ApprovalService(db=db, eventbus=eventbus)
        req = await svc_no_validator.create(
            type="budget_change",
            requester="agent:dev",
            title="warn 테스트",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 30000000},
        )
        await svc_no_validator.reject(req.id)

        reopened = await svc.reopen(
            id=req.id,
            requester="agent:dev",
        )

        assert reopened.status == "pending"
        assert any(r["result"] == "warn" for r in reopened.reviews)

    async def test_reopen_publishes_created_event(self, service, eventbus):
        """reopen 시 ApprovalCreatedEvent가 재발행된다."""
        received = []

        async def handler(event: object) -> None:
            if isinstance(event, ApprovalCreatedEvent):
                received.append(event)

        eventbus.subscribe(ApprovalCreatedEvent, handler)

        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="이벤트 테스트",
            params={"account_id": "acc-test"},
        )
        created_event_count = len(received)

        await service.reject(req.id)
        await service.reopen(id=req.id, requester="agent:dev")

        # 생성 시 1건 + reopen 시 1건
        assert len(received) == created_event_count + 1
        assert received[-1].approval_id == req.id

    async def test_reopen_history_detail(self, service):
        """reopen history에 수정 내용이 기록된다."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="이력 테스트",
            body="원본",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await service.reject(req.id)

        reopened = await service.reopen(
            id=req.id,
            requester="agent:dev",
            body="수정본",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 15000000,
            },
        )

        reopened_entry = next(h for h in reopened.history if h["action"] == "reopened")
        assert "body 수정" in reopened_entry["detail"]
        assert "params 수정" in reopened_entry["detail"]

    async def test_reopen_persisted_to_db(self, service):
        """reopen 결과가 DB에 영속화된다."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="영속화 테스트",
            body="원본",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await service.reject(req.id)
        await service.reopen(
            id=req.id,
            requester="agent:dev",
            body="수정본",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 15000000,
            },
        )

        fetched = await service.get(req.id)
        assert fetched is not None
        assert fetched.status == "pending"
        assert fetched.body == "수정본"
        assert fetched.params == {
            "account_id": "acc-test",
            "bot_id": "bot-1",
            "amount": 15000000,
        }
        assert fetched.reject_reason == ""
        assert fetched.resolved_at == ""
        assert fetched.resolved_by == ""
        assert any(h["action"] == "reopened" for h in fetched.history)

    async def test_reopen_then_approve(self, service):
        """reopen 후 승인까지의 전체 흐름."""
        req = await service.create(
            type="budget_change",
            requester="agent:dev",
            title="전체 흐름",
            params={"account_id": "acc-test", "bot_id": "bot-1", "amount": 25000000},
        )
        await service.reject(req.id, reject_reason="금액 과다")
        await service.reopen(
            id=req.id,
            requester="agent:dev",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 15000000,
            },
        )
        approved = await service.approve(req.id)

        assert approved.status == "approved"
        actions = [h["action"] for h in approved.history]
        # Refs #1470: service 픽스처에 no-op executor 가 등록되어 approve
        # 직후 ``executed`` history 가 자동 추가된다.
        assert actions == [
            "created",
            "rejected",
            "reopened",
            "approved",
            "executed",
        ]


# ── suppress_notification (#516) ───────────────────


class TestSuppressNotification:
    """suppress_notification=True 시 NotificationEvent 미발행, 도메인 이벤트는 유지."""

    async def test_approve_suppress_skips_notification(self, service, eventbus):
        """approve(suppress_notification=True) 시 NotificationEvent 미발행."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []
        resolved: list[ApprovalResolvedEvent] = []

        async def on_notification(event: NotificationEvent) -> None:
            if event.category == "approval" and event.title == "결재 처리 완료":
                notifications.append(event)

        async def on_resolved(event: ApprovalResolvedEvent) -> None:
            resolved.append(event)

        eventbus.subscribe(NotificationEvent, on_notification)
        eventbus.subscribe(ApprovalResolvedEvent, on_resolved)

        req = await service.create(
            type="budget_change",
            requester="agent",
            title="알림 억제 테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id, suppress_notification=True)

        # 도메인 이벤트는 발행됨
        assert len(resolved) == 1
        assert resolved[0].resolution == "approved"

        # NotificationEvent는 미발행
        assert len(notifications) == 0

    async def test_approve_default_sends_notification(self, service, eventbus):
        """approve() 기본 동작은 NotificationEvent 발행."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []

        async def on_notification(event: NotificationEvent) -> None:
            if event.category == "approval" and event.title == "결재 처리 완료":
                notifications.append(event)

        eventbus.subscribe(NotificationEvent, on_notification)

        req = await service.create(
            type="budget_change",
            requester="agent",
            title="기본 동작 테스트",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        assert len(notifications) == 1

    async def test_reject_suppress_skips_notification(self, service, eventbus):
        """reject(suppress_notification=True) 시 NotificationEvent 미발행."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []
        resolved: list[ApprovalResolvedEvent] = []

        async def on_notification(event: NotificationEvent) -> None:
            if event.category == "approval" and event.title == "결재 처리 완료":
                notifications.append(event)

        async def on_resolved(event: ApprovalResolvedEvent) -> None:
            resolved.append(event)

        eventbus.subscribe(NotificationEvent, on_notification)
        eventbus.subscribe(ApprovalResolvedEvent, on_resolved)

        req = await service.create(
            type="budget_change",
            requester="agent",
            title="거절 알림 억제",
            params={"account_id": "acc-test"},
        )
        await service.reject(req.id, suppress_notification=True)

        # 도메인 이벤트는 발행됨
        assert len(resolved) == 1
        assert resolved[0].resolution == "rejected"

        # NotificationEvent는 미발행
        assert len(notifications) == 0

    async def test_reject_default_sends_notification(self, service, eventbus):
        """reject() 기본 동작은 NotificationEvent 발행."""
        from ante.eventbus.events import NotificationEvent

        notifications: list[NotificationEvent] = []

        async def on_notification(event: NotificationEvent) -> None:
            if event.category == "approval" and event.title == "결재 처리 완료":
                notifications.append(event)

        eventbus.subscribe(NotificationEvent, on_notification)

        req = await service.create(
            type="budget_change",
            requester="agent",
            title="거절 기본 동작",
            params={"account_id": "acc-test"},
        )
        await service.reject(req.id)

        assert len(notifications) == 1


class TestListSearch:
    """list() search 파라미터 테스트."""

    async def test_search_by_title(self, service):
        """title LIKE 검색."""
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="예산 증액 요청",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="strategy_adopt", requester="agent-02", title="전략 채택 요청"
        )

        results = await service.list_approvals(search="예산")
        assert len(results) == 1
        assert results[0].title == "예산 증액 요청"

    async def test_search_by_requester(self, service):
        """requester LIKE 검색."""
        await service.create(
            type="budget_change",
            requester="agent-alpha",
            title="요청 A",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="budget_change",
            requester="agent-beta",
            title="요청 B",
            params={"account_id": "acc-test"},
        )

        results = await service.list_approvals(search="alpha")
        assert len(results) == 1
        assert results[0].requester == "agent-alpha"

    async def test_search_matches_title_or_requester(self, service):
        """title 또는 requester 중 하나라도 매치되면 반환."""
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="검색어포함",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="budget_change",
            requester="검색어포함",
            title="일반 제목",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="budget_change",
            requester="agent-02",
            title="관련 없는 제목",
            params={"account_id": "acc-test"},
        )

        results = await service.list_approvals(search="검색어포함")
        assert len(results) == 2

    async def test_search_no_match(self, service):
        """매치 없으면 빈 목록."""
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="예산 요청",
            params={"account_id": "acc-test"},
        )

        results = await service.list_approvals(search="존재하지않는키워드")
        assert len(results) == 0

    async def test_search_empty_string(self, service):
        """빈 문자열이면 전체 반환 (search 미지정과 동일)."""
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="요청 1",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="budget_change",
            requester="agent-02",
            title="요청 2",
            params={"account_id": "acc-test"},
        )

        results = await service.list_approvals(search="")
        assert len(results) == 2

    async def test_search_combined_with_status_filter(self, service):
        """search와 status 필터 조합."""
        req = await service.create(
            type="budget_change",
            requester="agent-01",
            title="승인될 요청",
            params={"account_id": "acc-test"},
        )
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="대기 중 요청",
            params={"account_id": "acc-test"},
        )
        await service.approve(req.id)

        results = await service.list_approvals(search="요청", status="pending")
        assert len(results) == 1
        assert results[0].title == "대기 중 요청"

    async def test_search_none_returns_all(self, service):
        """search=None이면 기존 동작 (전체 반환)."""
        await service.create(
            type="budget_change",
            requester="agent-01",
            title="요청 1",
            params={"account_id": "acc-test"},
        )

        results = await service.list_approvals(search=None)
        assert len(results) == 1


# ── Refs #1241 SPLIT-2: account-scoped payload validation ───────────


class TestAccountScopedPayloadValidation:
    """Refs #1217 → #1241 SPLIT-2.

    ``ApprovalService.create`` / ``ApprovalService.reopen`` 가
    account-scoped 결재 유형 (`budget_change`, `rule_change`, `bot_create`)
    에 대해 ``params`` 의 account_id 를 :func:`require_account_id` 로
    검증하는지 보장한다.

    글로벌 결재 (``strategy_adopt``/``strategy_retire``) 와 bot-id scoped
    결재 (``bot_stop``/``bot_resume``/``bot_delete``/``bot_assign_strategy``/
    ``bot_change_strategy``) 는 account_id 없이도 통과해야 한다.
    """

    async def test_approval_create_account_scoped_payload_validation(self, service):
        """budget_change / rule_change / bot_create 는 account_id 가 필수."""
        from ante.account.errors import InvalidAccountIdError

        # account_id 누락 → 거부
        with pytest.raises(InvalidAccountIdError, match="account_id"):
            await service.create(
                type="budget_change",
                requester="agent",
                title="누락",
                params={"bot_id": "bot-1", "amount": 1_000_000},
            )

        # 빈 문자열 → 거부
        with pytest.raises(InvalidAccountIdError):
            await service.create(
                type="rule_change",
                requester="agent",
                title="빈 값",
                params={"account_id": "", "bot_id": "bot-1", "rules": []},
            )

        # ``"default"`` 예약어 → 거부
        with pytest.raises(InvalidAccountIdError):
            await service.create(
                type="bot_create",
                requester="agent",
                title="default 예약어",
                params={"account_id": "default", "strategy_id": "s1"},
            )

        # 정상 account_id → 통과
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="정상",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 1_000_000,
            },
        )
        assert req.status == ApprovalStatus.PENDING
        assert req.params["account_id"] == "acc-test"

    async def test_approval_create_account_scoped_config_first(self, service):
        """config-first → flat fallback 우선순위.

        ``params["config"]["account_id"]`` 가 우선 사용되고, 없으면
        ``params["account_id"]`` 로 폴백한다 (web/CLI 가 BotConfig 형태로
        래핑해 보내는 신규 형태 호환).
        """
        # config-nested 에 account_id 가 있으면 통과
        req = await service.create(
            type="bot_create",
            requester="agent",
            title="config nested",
            params={
                "config": {"account_id": "acc-test", "strategy_id": "s1"},
            },
        )
        assert req.status == ApprovalStatus.PENDING

        # config-nested 에 account_id 가 없고 flat 에도 없으면 거부
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await service.create(
                type="bot_create",
                requester="agent",
                title="누락",
                params={"config": {"strategy_id": "s1"}},
            )

    async def test_bot_create_mode_paper_no_longer_auto_approves(self, db, eventbus):
        """mode 값은 bot_create 자동승인 근거가 아니다."""

        async def resolve_account(account_id: str) -> Account | None:
            if account_id == "acc-test":
                return Account(
                    account_id="acc-test",
                    name="실전 계좌",
                    exchange="KRX",
                    currency="KRW",
                    trading_mode=TradingMode.LIVE,
                )
            return None

        svc = ApprovalService(
            db=db,
            eventbus=eventbus,
            auto_approve_evaluator=AutoApproveEvaluator(
                config=AutoApproveConfig(enabled=True, bot_create_virtual=True),
                account_resolver=resolve_account,
            ),
        )
        await svc.initialize()

        req = await svc.create(
            type="bot_create",
            requester="agent",
            title="mode 값은 무시",
            params={"account_id": "acc-test", "mode": "paper", "strategy_id": "s1"},
        )

        assert req.status == ApprovalStatus.PENDING
        assert req.resolved_by == ""

    async def test_approval_create_global_types_pass_without_account(self, service):
        """글로벌 결재 (strategy_*) + bot-id scoped 는 account_id 없이 통과."""
        # strategy_adopt / strategy_retire 는 글로벌 결재 → account_id 불필요
        for global_type in ("strategy_adopt", "strategy_retire"):
            req = await service.create(
                type=global_type,
                requester="agent",
                title=f"{global_type} payload",
                params={"strategy_id": "s1", "report_id": "rpt-1"},
            )
            assert req.status == ApprovalStatus.PENDING

        # bot-id scoped: bot_stop / bot_resume / bot_delete / bot_assign_strategy /
        # bot_change_strategy → bot_id 로 account 가 결정되므로 account_id 불필요
        for bot_type in (
            "bot_stop",
            "bot_resume",
            "bot_delete",
            "bot_assign_strategy",
            "bot_change_strategy",
        ):
            req = await service.create(
                type=bot_type,
                requester="agent",
                title=f"{bot_type} payload",
                params={"bot_id": "bot-1"},
            )
            assert req.status == ApprovalStatus.PENDING

    async def test_approval_reopen_account_scoped_payload_validation(self, service):
        """reopen 시 갱신된 params 에 대해 account_id 재검증.

        params=None 이면 기존 검증된 params 를 유지하므로 스킵한다.
        params 갱신 시 invalid 면 거부.
        """
        from ante.account.errors import InvalidAccountIdError

        # 정상 생성 → 거절
        req = await service.create(
            type="budget_change",
            requester="agent",
            title="원본",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 1_000_000,
            },
        )
        await service.reject(req.id, reject_reason="검토 필요")

        # params=None reopen → 기존 params 유지, 통과
        reopened = await service.reopen(req.id, requester="agent")
        assert reopened.status == ApprovalStatus.PENDING
        assert reopened.params["account_id"] == "acc-test"

        # 다시 거절
        await service.reject(req.id, reject_reason="다시 검토")

        # params 갱신 시 account_id 누락 → 거부
        with pytest.raises(InvalidAccountIdError, match="account_id"):
            await service.reopen(
                req.id,
                requester="agent",
                params={"bot_id": "bot-1", "amount": 2_000_000},
            )

        # 정상 갱신 → 통과
        reopened2 = await service.reopen(
            req.id,
            requester="agent",
            params={
                "account_id": "acc-test",
                "bot_id": "bot-1",
                "amount": 2_000_000,
            },
        )
        assert reopened2.status == ApprovalStatus.PENDING
        assert reopened2.params["amount"] == 2_000_000
