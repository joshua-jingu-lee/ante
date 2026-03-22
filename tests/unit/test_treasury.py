"""Treasury 모듈 단위 테스트."""

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotStoppedEvent,
    OrderApprovedEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderValidatedEvent,
)
from ante.treasury import BotBudget, Treasury

# -- Fixtures -------------------------------------------------

ACCOUNT_ID = "domestic"
CURRENCY = "KRW"


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
    t = Treasury(
        db=db,
        eventbus=eventbus,
        account_id=ACCOUNT_ID,
        currency=CURRENCY,
        buy_commission_rate=0.00015,
        sell_commission_rate=0.00195,
    )
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    return t


# -- BotBudget 모델 -------------------------------------------


class TestBotBudget:
    def test_defaults(self):
        """BotBudget 기본값 확인."""
        b = BotBudget(bot_id="bot1")
        assert b.allocated == 0.0
        assert b.available == 0.0
        assert b.reserved == 0.0
        assert b.spent == 0.0
        assert b.returned == 0.0

    def test_account_id_field(self):
        """BotBudget에 account_id 필드가 존재한다."""
        b = BotBudget(bot_id="bot1", account_id="domestic")
        assert b.account_id == "domestic"


# -- Treasury 계좌 속성 ----------------------------------------


class TestTreasuryAccountProperties:
    async def test_account_id(self, treasury):
        """Treasury에 account_id가 설정된다."""
        assert treasury.account_id == ACCOUNT_ID

    async def test_currency(self, treasury):
        """Treasury에 currency가 설정된다."""
        assert treasury.currency == CURRENCY

    async def test_buy_commission_rate(self, treasury):
        """buy_commission_rate 프로퍼티."""
        assert treasury.buy_commission_rate == 0.00015

    async def test_sell_commission_rate(self, treasury):
        """sell_commission_rate 프로퍼티."""
        assert treasury.sell_commission_rate == 0.00195

    async def test_update_commission_rates(self, treasury):
        """수수료율 업데이트."""
        treasury.update_commission_rates(0.001, 0.002)
        assert treasury.buy_commission_rate == 0.001
        assert treasury.sell_commission_rate == 0.002

    async def test_summary_includes_currency(self, treasury):
        """get_summary()에 currency가 포함된다."""
        summary = treasury.get_summary()
        assert summary["currency"] == CURRENCY


# -- 계좌 잔고 -----------------------------------------------


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


# -- 예산 할당/회수 ------------------------------------------


class TestAllocation:
    async def test_allocate(self, treasury):
        """예산 할당."""
        result = await treasury.allocate("bot1", 1_000_000.0)
        assert result is True
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 1_000_000.0
        assert budget.available == 1_000_000.0

    async def test_allocate_sets_account_id(self, treasury):
        """예산 할당 시 BotBudget에 account_id가 설정된다."""
        await treasury.allocate("bot1", 1_000_000.0)
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.account_id == ACCOUNT_ID

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
        budget = treasury.get_budget("bot1")
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
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 800_000.0
        assert budget.available == 800_000.0


# -- 봇 상태 검증 (예산 변경 시) --------------------------------


class TestBotStatusCheck:
    """운용 중인 봇에 대한 예산 변경을 거부한다."""

    @pytest.fixture
    async def treasury_with_checker(self, db, eventbus):
        """봇 상태 확인 콜백이 설정된 Treasury."""
        bot_statuses: dict[str, str] = {}
        t = Treasury(
            db=db,
            eventbus=eventbus,
            account_id=ACCOUNT_ID,
            bot_status_checker=lambda bid: bot_statuses.get(bid, ""),
        )
        await t.initialize()
        await t.set_account_balance(10_000_000.0)
        return t, bot_statuses

    async def test_allocate_stopped_bot(self, treasury_with_checker):
        """중지된 봇에 예산 할당 성공."""
        t, statuses = treasury_with_checker
        statuses["bot1"] = "stopped"
        result = await t.allocate("bot1", 1_000_000.0)
        assert result is True

    async def test_allocate_created_bot(self, treasury_with_checker):
        """생성 직후 봇에 예산 할당 성공."""
        t, statuses = treasury_with_checker
        statuses["bot1"] = "created"
        result = await t.allocate("bot1", 1_000_000.0)
        assert result is True

    async def test_allocate_error_bot(self, treasury_with_checker):
        """에러 상태 봇에 예산 할당 성공."""
        t, statuses = treasury_with_checker
        statuses["bot1"] = "error"
        result = await t.allocate("bot1", 1_000_000.0)
        assert result is True

    async def test_allocate_running_bot_raises(self, treasury_with_checker):
        """운용 중인 봇에 예산 할당 시 BotNotStoppedError."""
        from ante.treasury.exceptions import BotNotStoppedError

        t, statuses = treasury_with_checker
        statuses["bot1"] = "running"
        with pytest.raises(BotNotStoppedError, match="running"):
            await t.allocate("bot1", 1_000_000.0)

    async def test_allocate_stopping_bot_raises(self, treasury_with_checker):
        """중지 중인 봇에 예산 할당 시 BotNotStoppedError."""
        from ante.treasury.exceptions import BotNotStoppedError

        t, statuses = treasury_with_checker
        statuses["bot1"] = "stopping"
        with pytest.raises(BotNotStoppedError, match="stopping"):
            await t.allocate("bot1", 1_000_000.0)

    async def test_deallocate_running_bot_raises(self, treasury_with_checker):
        """운용 중인 봇에서 예산 회수 시 BotNotStoppedError."""
        from ante.treasury.exceptions import BotNotStoppedError

        t, statuses = treasury_with_checker
        statuses["bot1"] = "stopped"
        await t.allocate("bot1", 1_000_000.0)
        statuses["bot1"] = "running"
        with pytest.raises(BotNotStoppedError, match="running"):
            await t.deallocate("bot1", 500_000.0)

    async def test_deallocate_stopped_bot(self, treasury_with_checker):
        """중지된 봇에서 예산 회수 성공."""
        t, statuses = treasury_with_checker
        statuses["bot1"] = "stopped"
        await t.allocate("bot1", 1_000_000.0)
        result = await t.deallocate("bot1", 500_000.0)
        assert result is True

    async def test_allocate_unknown_bot_no_checker(self, treasury):
        """checker 미설정 시 기존 동작 유지 (에러 없음)."""
        result = await treasury.allocate("bot1", 1_000_000.0)
        assert result is True

    async def test_allocate_new_bot_no_status(self, treasury_with_checker):
        """봇 상태가 없는 경우 (BotManager에 미등록) 할당 허용."""
        t, statuses = treasury_with_checker
        result = await t.allocate("new_bot", 1_000_000.0)
        assert result is True


# -- 주문 자금 예약/해제 -------------------------------------


class TestReservation:
    async def test_reserve(self, treasury):
        """자금 예약."""
        await treasury.allocate("bot1", 1_000_000.0)
        result = await treasury.reserve_for_order("bot1", "ord1", 500_000.0)
        assert result is True
        budget = treasury.get_budget("bot1")
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
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_release_unknown_order(self, treasury):
        """존재하지 않는 주문 해제는 무시."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.release_reservation("bot1", "unknown_ord")
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0


# -- EventBus 통합 (account_id 필터링 포함) --------------------


class TestTreasuryEvents:
    async def test_validated_buy_approved(self, treasury, eventbus):
        """매수 주문 검증 통과 -> 자금 예약 -> OrderApprovedEvent."""
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
                account_id=ACCOUNT_ID,
            )
        )

        assert len(received) == 1
        assert received[0].order_id == "ord1"
        assert received[0].reserved_amount > 0
        assert received[0].account_id == ACCOUNT_ID

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved > 0
        assert budget.available < 1_000_000.0

    async def test_validated_buy_insufficient_rejected(self, treasury, eventbus):
        """매수 자금 부족 -> OrderRejectedEvent."""
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
                account_id=ACCOUNT_ID,
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
                account_id=ACCOUNT_ID,
            )
        )

        assert len(received) == 1
        assert received[0].reserved_amount == 0.0

    async def test_event_filtered_by_account_id(self, treasury, eventbus):
        """다른 계좌의 이벤트는 무시한다."""
        await treasury.allocate("bot1", 1_000_000.0)

        received = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: received.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: received.append(e))

        # 다른 계좌 ID로 이벤트 발행
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
                account_id="other-account",
            )
        )

        # Treasury가 이 이벤트를 무시했으므로 Approved/Rejected 모두 없어야 함
        assert len(received) == 0

        # 예산도 변경 없음
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_event_without_account_id_processed(self, treasury, eventbus):
        """account_id가 비어있는 이벤트는 하위 호환으로 처리한다."""
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
                account_id="",
            )
        )

        # account_id 비어있으면 처리
        assert len(received) == 1

    async def test_filled_event_filtered_by_account(self, treasury, eventbus):
        """다른 계좌의 체결 이벤트는 무시한다."""
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
                account_id="other-account",
            )
        )

        # 무시되었으므로 reserved 변경 없음
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == 500_100.0

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
                account_id=ACCOUNT_ID,
            )
        )

        budget = treasury.get_budget("bot1")
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
                account_id=ACCOUNT_ID,
            )
        )

        budget = treasury.get_budget("bot1")
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
                account_id=ACCOUNT_ID,
            )
        )

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_cancelled_event_filtered_by_account(self, treasury, eventbus):
        """다른 계좌의 취소 이벤트는 무시한다."""
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
                account_id="other-account",
            )
        )

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == 500_000.0

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
                account_id=ACCOUNT_ID,
            )
        )

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_bot_stopped_releases_all(self, treasury, eventbus):
        """봇 중지 시 모든 예약 자금 해제."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 200_000.0)
        await treasury.reserve_for_order("bot1", "ord2", 300_000.0)

        await eventbus.publish(
            BotStoppedEvent(
                bot_id="bot1",
                account_id=ACCOUNT_ID,
            )
        )

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == 0.0
        assert budget.available == 1_000_000.0

    async def test_bot_stopped_filtered_by_account(self, treasury, eventbus):
        """다른 계좌의 BotStopped는 무시한다."""
        await treasury.allocate("bot1", 1_000_000.0)
        await treasury.reserve_for_order("bot1", "ord1", 200_000.0)

        await eventbus.publish(
            BotStoppedEvent(
                bot_id="bot1",
                account_id="other-account",
            )
        )

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == 200_000.0


# -- 모니터링 -------------------------------------------------


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


# -- DB 영속화 -----------------------------------------------


class TestTreasuryPersistence:
    async def test_persists_across_instances(self, db, eventbus):
        """Treasury 재시작 후 상태 복원."""
        t1 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t1.initialize()
        await t1.set_account_balance(5_000_000.0)
        await t1.allocate("bot1", 2_000_000.0)

        # 새 인스턴스 생성
        t2 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t2.initialize()

        assert t2.account_balance == 5_000_000.0
        assert t2.unallocated == 3_000_000.0
        budget = t2.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 2_000_000.0
        assert budget.available == 2_000_000.0
        assert budget.account_id == ACCOUNT_ID

    async def test_separate_accounts_isolated(self, db, eventbus):
        """서로 다른 계좌의 Treasury는 데이터가 격리된다."""
        t1 = Treasury(db=db, eventbus=eventbus, account_id="domestic")
        await t1.initialize()
        await t1.set_account_balance(10_000_000.0)
        await t1.allocate("bot1", 3_000_000.0)

        t2 = Treasury(db=db, eventbus=eventbus, account_id="us-stock")
        await t2.initialize()
        await t2.set_account_balance(5_000.0)
        await t2.allocate("bot2", 2_000.0)

        # 각자의 데이터만 보여야 한다
        assert t1.account_balance == 10_000_000.0
        assert t1.unallocated == 7_000_000.0
        assert t1.get_budget("bot1") is not None
        assert t1.get_budget("bot2") is None

        assert t2.account_balance == 5_000.0
        assert t2.unallocated == 3_000.0
        assert t2.get_budget("bot2") is not None
        assert t2.get_budget("bot1") is None

    async def test_persistence_with_separate_accounts(self, db, eventbus):
        """서로 다른 계좌 재시작 후에도 데이터 격리 유지."""
        t1 = Treasury(db=db, eventbus=eventbus, account_id="domestic")
        await t1.initialize()
        await t1.set_account_balance(10_000_000.0)
        await t1.allocate("bot1", 3_000_000.0)

        t2 = Treasury(db=db, eventbus=eventbus, account_id="us-stock")
        await t2.initialize()
        await t2.set_account_balance(5_000.0)

        # 새 인스턴스로 복원
        t1_new = Treasury(db=db, eventbus=eventbus, account_id="domestic")
        await t1_new.initialize()

        t2_new = Treasury(db=db, eventbus=eventbus, account_id="us-stock")
        await t2_new.initialize()

        assert t1_new.account_balance == 10_000_000.0
        assert t1_new.get_budget("bot1") is not None
        assert t1_new.get_budget("bot1").allocated == 3_000_000.0

        assert t2_new.account_balance == 5_000.0
        assert t2_new.get_budget("bot1") is None

    async def test_persists_evaluation_fields(self, db, eventbus):
        """재시작 후 평가액/매입액/손익/외부 필드가 복원된다."""
        t1 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t1.initialize()
        await t1.set_account_balance(10_000_000.0)

        # sync_balance로 평가액 필드 설정
        await t1.sync_balance(
            {
                "cash": 10_000_000.0,
                "purchasable_amount": 8_000_000.0,
                "total_assets": 12_000_000.0,
                "purchase_amount": 7_000_000.0,
                "eval_amount": 7_200_000.0,
                "total_profit_loss": 200_000.0,
            }
        )

        # 외부 종목 금액 설정을 위해 내부 속성 직접 설정 후 저장
        t1._external_purchase_amount = 1_000_000.0
        t1._external_eval_amount = 1_100_000.0
        await t1._save_state()

        # 새 인스턴스로 복원
        t2 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t2.initialize()

        summary = t2.get_summary()
        assert summary["account_balance"] == 10_000_000.0
        assert summary["purchasable_amount"] == 8_000_000.0
        assert summary["total_evaluation"] == 12_000_000.0
        assert summary["purchase_amount"] == 7_000_000.0
        assert summary["eval_amount"] == 7_200_000.0
        assert summary["total_profit_loss"] == 200_000.0
        assert summary["external_purchase_amount"] == 1_000_000.0
        assert summary["external_eval_amount"] == 1_100_000.0

    async def test_persists_last_synced_at(self, db, eventbus):
        """재시작 후 last_synced_at이 복원된다."""
        from datetime import UTC, datetime

        t1 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t1.initialize()

        # last_synced_at 설정 후 저장
        now = datetime.now(UTC)
        t1._last_synced_at = now
        await t1._save_state()

        # 새 인스턴스로 복원
        t2 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t2.initialize()

        assert t2.last_synced_at is not None
        assert t2.last_synced_at.isoformat() == now.isoformat()

    async def test_persists_last_synced_at_none(self, db, eventbus):
        """last_synced_at이 None이면 복원 후에도 None이다."""
        t1 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t1.initialize()
        await t1.set_account_balance(1_000_000.0)

        # 새 인스턴스로 복원
        t2 = Treasury(db=db, eventbus=eventbus, account_id=ACCOUNT_ID)
        await t2.initialize()

        assert t2.last_synced_at is None


# -- update_budget -------------------------------------------


class TestUpdateBudget:
    """Treasury.update_budget() 단위 테스트."""

    async def test_increase_budget(self, treasury):
        """기존 봇의 예산 증액."""
        await treasury.allocate("bot1", 2_000_000.0)
        await treasury.update_budget("bot1", 5_000_000.0)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 5_000_000.0
        assert budget.available == 5_000_000.0
        assert treasury.unallocated == 5_000_000.0

    async def test_decrease_budget(self, treasury):
        """기존 봇의 예산 감액."""
        await treasury.allocate("bot1", 5_000_000.0)
        await treasury.update_budget("bot1", 3_000_000.0)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 3_000_000.0
        assert budget.available == 3_000_000.0
        assert treasury.unallocated == 7_000_000.0

    async def test_new_bot_budget(self, treasury):
        """예산이 없는 봇에 최초 할당."""
        await treasury.update_budget("new_bot", 3_000_000.0)

        budget = treasury.get_budget("new_bot")
        assert budget is not None
        assert budget.allocated == 3_000_000.0
        assert budget.available == 3_000_000.0
        assert treasury.unallocated == 7_000_000.0

    async def test_same_amount_noop(self, treasury):
        """동일 금액이면 변경 없음."""
        await treasury.allocate("bot1", 3_000_000.0)
        await treasury.update_budget("bot1", 3_000_000.0)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 3_000_000.0

    async def test_increase_insufficient_funds(self, treasury):
        """증액 시 미할당 잔액 부족이면 InsufficientFundsError."""
        from ante.treasury.exceptions import InsufficientFundsError

        await treasury.allocate("bot1", 8_000_000.0)
        with pytest.raises(InsufficientFundsError, match="미할당 잔액 부족"):
            await treasury.update_budget("bot1", 15_000_000.0)

        # 원래 상태 유지
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 8_000_000.0

    async def test_decrease_exceeds_available(self, treasury):
        """감액 시 가용 예산 부족이면 InsufficientFundsError."""
        from ante.treasury.exceptions import InsufficientFundsError

        await treasury.allocate("bot1", 5_000_000.0)
        # 자금 예약으로 available을 줄임
        await treasury.reserve_for_order("bot1", "ord1", 4_000_000.0)

        with pytest.raises(InsufficientFundsError, match="예산 회수 실패"):
            await treasury.update_budget("bot1", 0.0)

    async def test_negative_target_raises(self, treasury):
        """목표 금액이 음수면 ValueError."""
        with pytest.raises(ValueError, match="0 이상"):
            await treasury.update_budget("bot1", -100.0)

    async def test_set_to_zero(self, treasury):
        """예산을 0으로 설정."""
        await treasury.allocate("bot1", 3_000_000.0)
        await treasury.update_budget("bot1", 0.0)

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.allocated == 0.0
        assert budget.available == 0.0
        assert treasury.unallocated == 10_000_000.0
