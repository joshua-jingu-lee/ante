"""Treasury 모듈 단위 테스트."""

import pytest

from ante.account.errors import InvalidAccountIdError
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
        b = BotBudget(bot_id="bot1", account_id="acc-test")
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


# -- Treasury DB schema ----------------------------------------


class TestTreasurySchema:
    async def test_bot_budgets_account_id_has_no_fallback_default(self, db, treasury):
        """fresh bot_budgets DDL은 fallback account default를 만들지 않는다."""
        columns = await db.fetch_all("PRAGMA table_info(bot_budgets)")
        account_col = next(row for row in columns if row["name"] == "account_id")
        assert account_col["notnull"] == 1
        assert account_col["dflt_value"] is None

    async def test_treasury_account_indexes_exist(self, db, treasury):
        """Treasury account 단위 조회용 index가 존재한다."""
        indexes = await db.fetch_all(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'index' AND tbl_name IN "
            "('bot_budgets', 'treasury_transactions')"
        )
        names = {row["name"] for row in indexes}
        assert "idx_bot_budgets_account" in names
        assert "idx_treasury_transactions_account" in names

    async def test_save_budget_rejects_invalid_account_id(self, treasury):
        """BotBudget 생성 우회를 하더라도 write boundary가 fallback을 막는다."""
        budget = BotBudget(bot_id="bot1", account_id=ACCOUNT_ID)
        budget.account_id = ""

        with pytest.raises(InvalidAccountIdError, match="account_id"):
            await treasury._save_budget(budget)


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

    async def test_reserve_zero_amount_raises(self, treasury):
        """amount가 0이면 ValueError 발생."""
        await treasury.allocate("bot1", 1_000_000.0)
        with pytest.raises(ValueError, match="amount must be positive"):
            await treasury.reserve_for_order("bot1", "ord1", 0)

    async def test_reserve_negative_amount_raises(self, treasury):
        """음수 amount이면 ValueError 발생."""
        await treasury.allocate("bot1", 1_000_000.0)
        with pytest.raises(ValueError, match="amount must be positive"):
            await treasury.reserve_for_order("bot1", "ord1", -100_000.0)

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

    async def test_event_without_account_id_rejected(self, treasury, eventbus):
        """account_id가 비어있는 이벤트는 생성 단계에서 거부된다 (#1217)."""
        await treasury.allocate("bot1", 1_000_000.0)

        with pytest.raises(InvalidAccountIdError):
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


# -- _on_order_validated guard 회귀 테스트 (#1292) --------------


class TestOnOrderValidatedGuards:
    """매수 시장가 quote 부재, reserve 실패 등 terminal event 누락 회귀 테스트."""

    async def test_on_order_validated_market_buy_without_price_publishes_rejected(
        self, treasury, eventbus, monkeypatch
    ):
        """market buy + price=None & resolver 미주입 -> reserve 호출 없이
        OrderRejected 발행 (#1333).

        Order lifecycle invariant: terminal event(OrderRejected)가 정확히 1건
        발행되어야 하고, reserve_for_order는 호출되지 않아야 한다.
        """
        await treasury.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        reserve_calls: list = []

        async def spy_reserve(bot_id, order_id, amount):
            reserve_calls.append((bot_id, order_id, amount))
            return True

        monkeypatch.setattr(treasury, "reserve_for_order", spy_reserve)

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-buy",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 0
        assert len(rejected) == 1
        # #1333: reason은 ``market_buy_quote_unavailable: ...`` prefix.
        # resolver 미주입 시 ``resolver not configured`` detail 이 포함된다.
        assert rejected[0].reason.startswith("market_buy_quote_unavailable")
        assert "resolver not configured" in rejected[0].reason
        assert rejected[0].account_id == ACCOUNT_ID
        assert rejected[0].order_id == "ord-mkt-buy"
        # reserve_for_order는 절대 호출되지 않아야 한다.
        assert reserve_calls == []

        # 예산도 변경 없음.
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_on_order_validated_market_sell_without_price_publishes_approved(
        self, treasury, eventbus
    ):
        """market sell + price=None -> Approved 발행 (회귀 가드)."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list = []
        rejected: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-sell",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 0
        assert len(approved) == 1
        assert approved[0].reserved_amount == 0.0
        assert approved[0].order_id == "ord-mkt-sell"

    async def test_on_order_validated_limit_buy_with_budget_publishes_approved(
        self, treasury, eventbus
    ):
        """limit buy with sufficient budget -> 기존 동작 유지."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list = []
        rejected: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-lim-buy",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="limit",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 0
        assert len(approved) == 1
        assert approved[0].reserved_amount > 0

        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved > 0

    async def test_on_order_validated_zero_quantity_market_buy_publishes_rejected_with_reserve_amount_invalid(  # noqa: E501
        self, treasury, eventbus
    ):
        """quantity=0 + price 양수 시장가 매수 -> reserve_amount_invalid 거부.

        price=None이면 market_buy_quote_unavailable이 먼저, price 양수+quantity=0이면
        reserve_amount_invalid가 발행된다.
        """
        await treasury.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        # price 양수 + quantity=0 -> Guard 1을 통과하고 Guard 2에서 거부.
        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-zero-qty",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=0.0,
                price=50_000.0,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 0
        assert len(rejected) == 1
        assert rejected[0].reason.startswith("reserve_amount_invalid")
        assert "total_reserve=0" in rejected[0].reason

        # price=None + quantity=0 -> Guard 1이 먼저 매칭.
        rejected.clear()
        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-zero-qty-no-price",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=0.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 1
        assert rejected[0].reason.startswith("market_buy_quote_unavailable")

    async def test_on_order_validated_reserve_for_order_exception_publishes_rejected(
        self, treasury, eventbus, monkeypatch
    ):
        """reserve_for_order가 예외를 던져도 OrderRejected가 발행된다."""
        await treasury.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        async def boom(bot_id, order_id, amount):
            raise RuntimeError("simulated reserve failure")

        monkeypatch.setattr(treasury, "reserve_for_order", boom)

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-exc",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=50_000.0,
                order_type="limit",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 0
        assert len(rejected) == 1
        assert rejected[0].reason.startswith("reserve_failed")
        assert "simulated reserve failure" in rejected[0].reason

    async def test_on_order_validated_account_id_mismatch_does_not_publish(
        self, treasury, eventbus
    ):
        """다른 account_id 이벤트는 새 guard보다 먼저 _is_my_event 필터에서 무시.

        market buy + price=None 시그니처라도, 다른 계좌의 이벤트라면
        OrderRejected/OrderApproved 어느 쪽도 publish되지 않아야 한다.
        """
        await treasury.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-other",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=None,
                order_type="market",
                account_id="other-account",
            )
        )

        assert len(rejected) == 0
        assert len(approved) == 0

    async def test_on_order_validated_warn_path_market_buy_publishes_rejected(
        self, treasury, eventbus
    ):
        """RuleEngine WARN 분기에서 발행된 OrderValidatedEvent도 동일하게 거부.

        WARN 경로에서도 동일한 OrderValidatedEvent가 publish되므로
        Treasury 핸들러는 같은 guard를 적용해야 한다 (이슈 #1292의
        실제 재현 경로).
        """
        await treasury.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        # WARN 분기는 reason 필드에 경고 텍스트를 담아 publish한다.
        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-warn",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
                reason="WARN: position size near limit",
            )
        )

        assert len(approved) == 0
        assert len(rejected) == 1
        assert rejected[0].reason.startswith("market_buy_quote_unavailable")


# -- #1333 시장가 매수 reserve estimate (quote resolver) -----


class TestMarketBuyQuoteResolver:
    """Account-scoped quote resolver 가 주입돼 있을 때 market buy + price=None
    이 정상 reserve 후 OrderApproved 로 흘러가는지, 미주입/실패 시 terminal
    reject 인지 검증한다 (#1333).
    """

    async def _make_treasury_with_buffer(
        self,
        db,
        eventbus,
        *,
        buffer: str,
        resolver=None,
    ):
        from decimal import Decimal as _Decimal

        t = Treasury(
            db=db,
            eventbus=eventbus,
            account_id=ACCOUNT_ID,
            currency=CURRENCY,
            buy_commission_rate=0.00015,
            sell_commission_rate=0.00195,
            market_order_reserve_buffer_rate=_Decimal(buffer),
            order_reserve_price_resolver=resolver,
        )
        await t.initialize()
        await t.set_account_balance(10_000_000.0)
        return t

    async def test_market_buy_resolver_success_publishes_approved_with_price_none(
        self, db, eventbus
    ):
        """resolver 가 quote 를 반환하면 reserve 산정 후 OrderApproved 가
        ``price=None`` + ``reserved_amount > 0`` 로 발행된다.
        """

        async def resolver(symbol: str) -> float:
            assert symbol == "069500"
            return 10_000.0

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        rejected: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="069500",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 0
        assert len(approved) == 1
        ev = approved[0]
        # resolved quote 는 OrderApprovedEvent.price 에 절대 들어가지 않는다.
        assert ev.price is None
        # reserve 금액에 buffer (0.5%) + buy_commission (0.015%) 반영.
        # 1 * 10_000 * (1 + 0.005) * (1 + 0.00015) = 10_051.5075...
        expected = 1.0 * 10_000.0 * (1 + 0.005) * (1 + 0.00015)
        assert ev.reserved_amount == pytest.approx(expected)

    async def test_market_buy_buffer_and_commission_in_reserve_amount(
        self, db, eventbus
    ):
        """buffer = 0 일 때 reserve = quantity * quote * (1 + commission)
        가 그대로 적용되는지 검증 (commission 단독 영향 분리).
        """

        async def resolver(symbol: str) -> float:
            return 5_000.0

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-2",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=2.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        # 2 * 5_000 * (1 + 0) * (1 + 0.00015) = 10_001.5
        expected = 2.0 * 5_000.0 * (1 + 0) * (1 + 0.00015)
        assert approved[0].reserved_amount == pytest.approx(expected)

    async def test_market_buy_resolver_missing_publishes_rejected(self, db, eventbus):
        """resolver 미주입 상태에서 terminal reject (resolver not configured)."""
        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=None
        )
        await t.allocate("bot1", 1_000_000.0)

        rejected: list = []
        approved: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-3",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 0
        assert len(rejected) == 1
        assert rejected[0].reason.startswith("market_buy_quote_unavailable")
        assert "resolver not configured" in rejected[0].reason

    async def test_market_buy_resolver_raises_publishes_rejected(self, db, eventbus):
        """resolver 가 예외를 raise 하면 terminal reject 로 변환."""

        async def resolver(symbol: str) -> float:
            raise RuntimeError("KIS quote API 503")

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        rejected: list = []
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-4",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 1
        assert rejected[0].reason.startswith("market_buy_quote_unavailable")
        assert "KIS quote API 503" in rejected[0].reason

    async def test_market_sell_price_none_unchanged(self, db, eventbus):
        """market **sell** + price=None 은 기존 거동대로 reserve 없이 즉시 승인."""

        async def resolver(symbol: str) -> float:
            return 99_999.0  # 호출돼서는 안 됨

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-sell",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="sell",
                quantity=1.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        # sell-side 는 reserve 0
        assert approved[0].reserved_amount == 0.0
        assert approved[0].side == "sell"
        # resolver 가 호출되더라도 reserve estimate 산정에는 쓰이지 않는다.
        # budget 도 변동 없음.
        budget = t.get_budget("bot1")
        assert budget is not None
        assert budget.available == 1_000_000.0
        assert budget.reserved == 0.0

    async def test_limit_buy_unchanged_no_resolver_call(self, db, eventbus):
        """limit buy (price 명시) 는 기존 reserve 산식이 그대로 적용되며
        resolver 가 호출되지 않는다.
        """
        resolver_calls: list = []

        async def resolver(symbol: str) -> float:
            resolver_calls.append(symbol)
            return 99_999.0

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-limit-buy",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=2.0,
                price=1_000.0,
                order_type="limit",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        # 기존 limit buy 산식: quantity * price + commission (buffer 적용 안 함).
        expected = 2.0 * 1_000.0 + (2.0 * 1_000.0) * 0.00015
        assert approved[0].reserved_amount == pytest.approx(expected)
        # market buy quote resolver 는 호출되지 않는다.
        assert resolver_calls == []

    async def test_buy_stop_does_not_reach_market_resolver(self, db, eventbus):
        """buy stop 분기 (#1337) 가 진입 우선순위 1로 유지되어 #1333 resolver
        분기에 도달하지 않는다 — Stop Condition 반영.
        """
        resolver_calls: list = []

        async def resolver(symbol: str) -> float:
            resolver_calls.append(symbol)
            return 99_999.0

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        rejected: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-stop",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="stop",
                stop_price=900.0,
                account_id=ACCOUNT_ID,
            )
        )

        # #1337: stop 은 트리거 전이라 reserve 0 으로 즉시 OrderApproved.
        assert len(rejected) == 0
        assert len(approved) == 1
        assert approved[0].reserved_amount == 0.0
        # resolver 는 호출되지 않는다.
        assert resolver_calls == []

    async def test_buy_stop_limit_does_not_reach_market_resolver(self, db, eventbus):
        """buy stop_limit 도 #1337 분기 우선순위 1 유지 — resolver 미호출."""
        resolver_calls: list = []

        async def resolver(symbol: str) -> float:
            resolver_calls.append(symbol)
            return 99_999.0

        t = await self._make_treasury_with_buffer(
            db, eventbus, buffer="0.005", resolver=resolver
        )
        await t.allocate("bot1", 1_000_000.0)

        approved: list = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-stop-limit",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=1.0,
                price=910.0,
                order_type="stop_limit",
                stop_price=900.0,
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        assert approved[0].reserved_amount == 0.0
        assert resolver_calls == []


# -- #1333 shortfall 정산 -----


class TestMarketOrderReserveShortfall:
    """체결가가 reserve 보다 높은 시장가 매수의 정산 invariant 검증 (#1333)."""

    async def test_buy_fill_actual_cost_exceeds_reserved_warns_and_decrements_available(
        self, db, eventbus, caplog
    ):
        """actual_cost > reserved_amount 면 초과분이 available 에서 추가 차감되며
        ``market_order_reserve_shortfall`` warning 이 logged 된다. available 이
        음수가 되는 것이 invariant 다 (#1333 정책 5).
        """
        import logging as _logging

        async def resolver(symbol: str) -> float:
            return 1_000.0  # buffer 0 이라 reserve = 1 * 1000 * (1 + 0.00015)

        from decimal import Decimal as _Decimal

        t = Treasury(
            db=db,
            eventbus=eventbus,
            account_id=ACCOUNT_ID,
            currency=CURRENCY,
            buy_commission_rate=0.00015,
            sell_commission_rate=0.00195,
            market_order_reserve_buffer_rate=_Decimal("0"),
            order_reserve_price_resolver=resolver,
        )
        await t.initialize()
        await t.set_account_balance(10_000_000.0)
        await t.allocate("bot1", 1_100.0)

        # 1) market buy → reserve 산정.
        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-fill-1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )
        budget = t.get_budget("bot1")
        assert budget is not None
        reserved_before = budget.reserved
        assert reserved_before > 0

        # 2) 실체결가가 reserve 보다 높다 → shortfall 정산.
        with caplog.at_level(_logging.WARNING):
            await eventbus.publish(
                OrderFilledEvent(
                    order_id="ord-fill-1",
                    bot_id="bot1",
                    strategy_id="s1",
                    symbol="A",
                    side="buy",
                    quantity=1.0,
                    price=2_000.0,  # reserve(=1000.15)보다 훨씬 높다
                    commission=0.3,
                    account_id=ACCOUNT_ID,
                )
            )

        budget = t.get_budget("bot1")
        assert budget is not None
        # actual_cost = 1*2000 + 0.3 = 2000.3, reserved ~= 1000.15 → extra 1000.15+
        # available 은 (1100 - 1000.15) - extra = 음수 가능.
        assert budget.available < 0
        assert budget.reserved == pytest.approx(0.0, abs=1e-6)
        # warning 로그 점검.
        assert any(
            "market_order_reserve_shortfall" in rec.getMessage()
            for rec in caplog.records
        )


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
