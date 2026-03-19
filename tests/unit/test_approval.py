"""Approval 모듈 단위 테스트."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from ante.approval.models import ApprovalRequest, ApprovalStatus, ApprovalType
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

    async def test_expire_event_published(self, service, eventbus):
        """만료 처리 시 건별 ApprovalResolvedEvent가 발행된다."""
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        await service.create(
            type="budget_change",
            requester="agent",
            title="만료 이벤트 테스트",
            expires_at=past,
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
