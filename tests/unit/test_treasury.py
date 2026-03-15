"""Treasury 모듈 단위 테스트."""

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderValidatedEvent,
)
from ante.treasury import BotBudget, Treasury

# ── Fixtures ─────────────────────────────────────


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def treasury(db, eventbus):
    t = Treasury(db=db, eventbus=eventbus, commission_rate=0.00015)
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    return t


# ── BotBudget 모델 ───────────────────────────────


class TestBotBudget:
    def test_defaults(self):
        """BotBudget 기본값 확인."""
        b = BotBudget(bot_id="bot1")
        assert b.allocated == 0.0
        assert b.available == 0.0
        assert b.reserved == 0.0
        assert b.spent == 0.0
        assert b.returned == 0.0


# ── 계좌 잔고 ───────────────────────────────────


class TestAccountBalance:
    async def test_set_account_balance(self, treasury):
        """계좌 잔고 설정."""
        assert treasury.account_balance == 10_000_000.0
        assert treasury.unallocated == 10_000_000.0

    async def test_unallocated_after_allocation(self, treasury):
        """할당 후 미할당 자금 감소."""
        await treasury.allocate("bot1", 3_000_000.0)
        assert treasury.unallocated == 7_000_000.0

    async def test_set_balance_recalculates_unallocated(self, treasury):
        """잔고 재설정 시 미할당 재계산."""
        await treasury.allocate("bot1", 3_000_000.0)
        await treasury.set_account_balance(5_000_000.0)
        assert treasury.unallocated == 2_000_000.0


# ── 예산 할당/회수 ──────────────────────────────


class TestAllocation:
    async def test_allocate(self, treasury):
        """예산 할당."""
        result = await treasury.allocate("bot1", 1_000_000.0)
        assert result is True
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 1_000_000.0
        assert budget.available == 1_000_000.0

    async def test_allocate_insufficient(self, treasury):
        """미할당 자금 부족 시 실패."""
        result = await treasury.allocate("bot1", 20_000_000.0)
        assert result is False

    async def test_allocate_zero(self, treasury):
        """0 이하 할당 실패."""
        assert await treasury.allocate("bot1", 0) is False
        assert await treasury.allocate("bot1", -100) is False

    async def test_deallocate(self, treasury):
        """예산 회수."""
        await treasury.allocate("bot1", 1_000_000.0)
        result = await treasury.deallocate("bot1", 500_000.0)
        assert result is True
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 500_000.0
        assert budget.available == 500_000.0
        assert treasury.unallocated == 9_500_000.0

    async def test_deallocate_exceeds_available(self, treasury):
        """가용 예산 초과 회수 실패."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 800_000.0)
        result = await treasury.deallocate("bot1", 500_000.0)
        assert result is False

    async def test_deallocate_nonexistent(self, treasury):
        """존재하지 않는 봇 회수 실패."""
        result = await treasury.deallocate("nonexistent", 100.0)
        assert result is False

    async def test_multiple_allocations(self, treasury):
        """동일 봇에 추가 할당."""
        await treasury.allocate("bot1", 500_000.0)
        await treasury.allocate("bot1", 300_000.0)
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 800_000.0
        assert budget.available == 800_000.0


# ── 주문 자금 예약/해제 ─────────────────────────


class TestReservation:
    async def test_reserve(self, treasury):
        """자금 예약."""
        await treasury.allocate("bot1", 1_000_000.0)
        result = await treasury.reserve_for_order("bot1", "ord1", 500_000.0)
        assert result is True
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 500_000.0
        assert budget.reserved == 500_000.0

    async def test_reserve_insufficient(self, treasury):
        """가용 예산 부족 시 예약 실패."""
        await treasury.allocate("bot1", 100_000.0)
        result = await treasury.reserve_for_order("bot1", "ord1", 500_000.0)
        assert result is False

    async def test_release_reservation(self, treasury):
        """예약 해제."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_000.0)
        await treasury.release_reservation("bot1", "ord1")
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_release_unknown_order(self, treasury):
        """존재하지 않는 주문 해제는 무시."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.release_reservation("bot1", "unknown_ord")
        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0


# ── EventBus 통합 ───────────────────────────────


class TestTreasuryEvents:
    async def test_validated_buy_approved(self, treasury, eventbus):
        """매수 주문 검증 통과 → 자금 예약 → OrderApprovedEvent."""
        await treasury.allocate("bot1", 1_000_000.0)

        received = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="market",
            )
        )

        assert len(received) == 1
        assert received[0].order_id == "ord1"
        assert received[0].reserved_amount > 0

        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved > 0
        assert budget.available < 1_000_000.0

    async def test_validated_buy_insufficient_rejected(self, treasury, eventbus):
        """매수 자금 부족 → OrderRejectedEvent."""
        await treasury.allocate("bot1", 100.0)

        received = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="market",
            )
        )

        assert len(received) == 1
        assert "insufficient_budget" in received[0].reason

    async def test_validated_sell_approved_no_reserve(self, treasury, eventbus):
        """매도 주문은 자금 예약 없이 승인."""
        await treasury.allocate("bot1", 1_000_000.0)

        received = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: received.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                price=50_000.0,
                order_type="market",
            )
        )

        assert len(received) == 1
        assert received[0].reserved_amount == 0.0

    async def test_buy_filled_settles_reservation(self, treasury, eventbus):
        """매수 체결 시 예약 자금 정산."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_100.0)

        await eventbus.publish(
            OrderFilledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                commission=75.0,
                order_type="market",
            )
        )

        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == 0.0
        assert budget.spent == 500_075.0  # 500,000 + 75
        # available: 1M - 500,100 (reserved) + 25 (surplus) = 499,925
        assert budget.available == pytest.approx(499_925.0)

    async def test_sell_filled_returns_funds(self, treasury, eventbus):
        """매도 체결 시 자금 회수."""
        await treasury.allocate("bot1", 1_000_000.0)

        await eventbus.publish(
            OrderFilledEvent(
                order_id="ord2",
                broker_order_id="bk2",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                price=55_000.0,
                commission=82.5,
                order_type="market",
            )
        )

        budget = await treasury.get_budget("bot1")
        assert budget is not None
        expected_proceeds = 550_000.0 - 82.5
        assert budget.returned == expected_proceeds
        assert budget.available == 1_000_000.0 + expected_proceeds

    async def test_order_cancelled_releases(self, treasury, eventbus):
        """주문 취소 시 예약 해제."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_000.0)

        await eventbus.publish(
            OrderCancelledEvent(
                order_id="ord1",
                broker_order_id="bk1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
            )
        )

        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_order_failed_releases(self, treasury, eventbus):
        """주문 실패 시 예약 해제."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 500_000.0)

        await eventbus.publish(
            OrderFailedEvent(
                order_id="ord1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="market",
                error_message="broker error",
            )
        )

        budget = await treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0


# ── 모니터링 ────────────────────────────────────


class TestTreasurySummary:
    async def test_summary(self, treasury):
        """자금 현황 요약."""
        await treasury.allocate("bot1", 3_000_000.0)
        await treasury.allocate("bot2", 2_000_000.0)

        summary = treasury.get_summary()
        assert summary["account_balance"] == 10_000_000.0
        assert summary["total_allocated"] == 5_000_000.0
        assert summary["total_available"] == 5_000_000.0
        assert summary["unallocated"] == 5_000_000.0
        assert summary["bot_count"] == 2
        assert summary["budget_exceeds_purchasable"] is False

    async def test_budget_exceeds_purchasable_warning(self, treasury):
        """잔여예산 > 매수가능금액 시 경고 플래그."""
        await treasury.allocate("bot1", 5_000_000.0)
        await treasury.sync_balance(
            {"cash": 10_000_000.0, "purchasable_amount": 3_000_000.0}
        )

        summary = treasury.get_summary()
        assert summary["budget_exceeds_purchasable"] is True

    async def test_no_warning_when_purchasable_zero(self, treasury):
        """매수가능금액이 0이면 경고 미표시 (동기화 전)."""
        await treasury.allocate("bot1", 5_000_000.0)

        summary = treasury.get_summary()
        assert summary["budget_exceeds_purchasable"] is False


# ── DB 영속화 ───────────────────────────────────


class TestTreasuryPersistence:
    async def test_persists_across_instances(self, db, eventbus):
        """Treasury 재시작 후 상태 복원."""
        t1 = Treasury(db=db, eventbus=eventbus)
        await t1.initialize()
        await t1.set_account_balance(5_000_000.0)
        await t1.allocate("bot1", 2_000_000.0)

        # 새 인스턴스 생성
        t2 = Treasury(db=db, eventbus=eventbus)
        await t2.initialize()

        assert t2.account_balance == 5_000_000.0
        assert t2.unallocated == 3_000_000.0
        budget = await t2.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 2_000_000.0
        assert budget.available == 2_000_000.0
