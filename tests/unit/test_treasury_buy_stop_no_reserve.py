"""Treasury 매수 stop / stop_limit no-reserve 정책 회귀 테스트 (#1337).

정책 (사용자 승인, 2026-05-08):
- 매수 stop / stop_limit 주문은 등록 시점에 자금 잠금하지 않는다.
- 트리거 발동 시 변환된 일반 매수 주문이 정상 reserve 절차를 거친다.
- 매도 stop, market buy, limit buy 동작에는 영향이 없다.
"""

from __future__ import annotations

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderRejectedEvent,
    OrderValidatedEvent,
)
from ante.treasury import Treasury

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


class TestBuyStopNoReserve:
    async def test_buy_stop_approved_without_reserve(self, treasury, eventbus):
        """side=buy, order_type=stop, price=None이어도 reserve 없이 승인된다."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list[OrderApprovedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-stop-1",
                bot_id="bot1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="stop",
                stop_price=1000.0,
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 0, (
            "매수 stop은 reserve_amount_invalid 등으로 거부되어선 안 된다 (#1337)."
        )
        assert len(approved) == 1
        evt = approved[0]
        assert evt.order_id == "ord-stop-1"
        assert evt.order_type == "stop"
        assert evt.side == "buy"
        assert evt.reserved_amount == 0.0
        assert evt.stop_price == 1000.0
        assert evt.account_id == ACCOUNT_ID

    async def test_buy_stop_limit_approved_without_reserve(self, treasury, eventbus):
        """stop_limit (price/stop_price 모두 있음) → reserve 없이 승인."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list[OrderApprovedEvent] = []
        rejected: list[OrderRejectedEvent] = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
        eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-stoplim-1",
                bot_id="bot1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=2.0,
                price=1050.0,
                order_type="stop_limit",
                stop_price=1000.0,
                account_id=ACCOUNT_ID,
            )
        )

        assert len(rejected) == 0
        assert len(approved) == 1
        evt = approved[0]
        assert evt.order_type == "stop_limit"
        assert evt.reserved_amount == 0.0
        assert evt.price == 1050.0
        assert evt.stop_price == 1000.0

    async def test_buy_stop_does_not_alter_unallocated(self, treasury, eventbus):
        """매수 stop 처리 후 잔액 invariant가 유지된다.

        unallocated, budget.available, budget.reserved 모두 변하지 않아야
        reserve가 호출되지 않았음을 보장한다.
        """
        await treasury.allocate("bot1", 1_000_000.0)

        unalloc_before = treasury.unallocated
        budget_before = treasury.get_budget("bot1")
        assert budget_before is not None
        available_before = budget_before.available
        reserved_before = budget_before.reserved

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-stop-2",
                bot_id="bot1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                price=None,
                order_type="stop",
                stop_price=1000.0,
                account_id=ACCOUNT_ID,
            )
        )

        assert treasury.unallocated == unalloc_before
        budget_after = treasury.get_budget("bot1")
        assert budget_after is not None
        assert budget_after.available == available_before
        assert budget_after.reserved == reserved_before
        assert treasury.get_reservations("bot1") == {}

    async def test_sell_stop_unaffected(self, treasury, eventbus):
        """매도 stop은 기존 sell-side no-reserve 동작이 유지된다."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list[OrderApprovedEvent] = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-sell-stop-1",
                bot_id="bot1",
                strategy_id="A7",
                symbol="069500",
                side="sell",
                quantity=1.0,
                price=None,
                order_type="stop",
                stop_price=900.0,
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        assert approved[0].side == "sell"
        assert approved[0].order_type == "stop"
        assert approved[0].reserved_amount == 0.0

    async def test_buy_market_unchanged(self, treasury, eventbus):
        """일반 market buy의 reserve 동작은 회귀 없이 유지된다."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list[OrderApprovedEvent] = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-mkt-1",
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

        assert len(approved) == 1
        evt = approved[0]
        assert evt.order_type == "market"
        assert evt.reserved_amount > 0.0
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved > 0.0
        assert budget.available < 1_000_000.0

    async def test_buy_limit_unchanged(self, treasury, eventbus):
        """일반 limit buy의 reserve 동작은 회귀 없이 유지된다."""
        await treasury.allocate("bot1", 1_000_000.0)

        approved: list[OrderApprovedEvent] = []
        eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))

        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-lim-1",
                bot_id="bot1",
                strategy_id="s1",
                symbol="005930",
                side="buy",
                quantity=5.0,
                price=60_000.0,
                order_type="limit",
                account_id=ACCOUNT_ID,
            )
        )

        assert len(approved) == 1
        evt = approved[0]
        assert evt.order_type == "limit"
        # 5 * 60000 + commission(0.00015) ≈ 300_045
        assert evt.reserved_amount == pytest.approx(
            5.0 * 60_000.0 * (1 + 0.00015), rel=1e-6
        )
        budget = treasury.get_budget("bot1")
        assert budget is not None
        assert budget.reserved == pytest.approx(evt.reserved_amount, rel=1e-6)
