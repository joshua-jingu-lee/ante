"""#3139 시장가 매수 예약의 시세 검사가 공용 가격 판정을 쓴다."""

import logging
from decimal import Decimal

import pytest

from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderRejectedEvent,
    OrderValidatedEvent,
)
from ante.treasury import Treasury

ACCOUNT_ID = "domestic"
PREFIX = "market_buy_quote_unavailable: non-finite or non-positive quote "
HUGE = 10**400
UNRENDERABLE = 10**5000


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def _run(db, caplog, quote, quantity=3.0):
    eventbus = EventBus()

    async def resolver(symbol: str) -> object:
        return quote

    registry = RuntimeReadinessRegistry()
    registry.mark_ready(ACCOUNT_ID, ReadinessFlag.TREASURY_SYNC)
    t = Treasury(
        db=db,
        eventbus=eventbus,
        account_id=ACCOUNT_ID,
        currency="KRW",
        buy_commission_rate=0.0,
        sell_commission_rate=0.00195,
        market_order_reserve_buffer_rate=Decimal("0"),
        order_reserve_price_resolver=resolver,
        runtime_readiness=registry,
    )
    await t.initialize()
    await t.set_account_balance(10_000_000.0)
    await t.allocate("bot1", 1_000_000.0)

    approved: list = []
    rejected: list = []
    eventbus.subscribe(OrderApprovedEvent, lambda e: approved.append(e))
    eventbus.subscribe(OrderRejectedEvent, lambda e: rejected.append(e))
    with caplog.at_level(logging.ERROR):
        await eventbus.publish(
            OrderValidatedEvent(
                order_id="ord-3139",
                bot_id="bot1",
                strategy_id="s1",
                symbol="A",
                side="buy",
                quantity=quantity,
                price=None,
                order_type="market",
                account_id=ACCOUNT_ID,
            )
        )
    budget = t.get_budget("bot1")
    assert budget is not None
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    return approved, rejected, budget, errors


@pytest.mark.parametrize(
    ("quote", "expected_repr"),
    [
        (HUGE, repr(HUGE)),
        (UNRENDERABLE, "<unrenderable int>"),
        (True, "True"),
        (False, "False"),
        (0, "0"),
        (-1.0, "-1.0"),
        (float("nan"), "nan"),
        (float("inf"), "inf"),
        (float("-inf"), "-inf"),
        ("1000", "'1000'"),
        (None, "None"),
    ],
    ids=[
        "int-10e400",
        "int-10e5000",
        "true",
        "false",
        "zero",
        "negative",
        "nan",
        "inf",
        "-inf",
        "str",
        "none",
    ],
)
async def test_invalid_quote_rejected_without_handler_error(
    db, caplog, quote, expected_repr
):
    """판정에 걸리는 시세는 기존 사유로 거부되고 예약·예산이 그대로다."""
    approved, rejected, budget, errors = await _run(db, caplog, quote)

    assert approved == []
    assert len(rejected) == 1
    assert rejected[0].order_id == "ord-3139"
    assert rejected[0].reason == PREFIX + expected_repr
    assert budget.reserved == 0.0
    assert budget.available == 1_000_000.0
    assert errors == []


async def test_valid_float_quote_approved_and_reserved(db, caplog):
    """대조군: 정상 float 시세는 수량 × 시세로 예약·승인된다."""
    approved, rejected, budget, errors = await _run(db, caplog, 1000.0)

    assert rejected == []
    assert len(approved) == 1
    assert approved[0].reserved_amount == 3000.0
    assert budget.reserved == 3000.0
    assert budget.available == 997_000.0
    assert errors == []


async def test_float_convertible_huge_int_rejected_as_insufficient_budget(db, caplog):
    """대조군: float로 바뀌는 큰 정수는 판정을 지나 예산 부족으로 거부된다."""
    approved, rejected, budget, errors = await _run(db, caplog, 10**20)

    assert approved == []
    assert len(rejected) == 1
    assert rejected[0].reason.startswith("insufficient_budget:")
    assert budget.reserved == 0.0
    assert budget.available == 1_000_000.0
    assert errors == []
