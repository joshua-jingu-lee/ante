"""재시작 뒤 주문별 잔여 예약의 복원 (#2770).

재시작은 같은 DB 파일로 새 ``EventBus``·``OrderTracker``·``Treasury``를 올리는 것이다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotStoppedEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
)
from ante.trade.order_tracker import OrderTracker
from ante.treasury import Treasury

ACCOUNT_ID = "domestic"
BOT = "bot-a"
ORDER = "ord-1"
ALLOCATED = 1_000_000.0
QTY = 10
PRICE = 10_000.0
RESERVED = QTY * PRICE


class Node:
    """한 번의 부팅: 버스·추적기·Treasury."""

    def __init__(self, bus: EventBus, tracker: OrderTracker, treasury: Treasury):
        self.bus = bus
        self.tracker = tracker
        self.treasury = treasury


@pytest.fixture
async def db(tmp_path: Path):
    database = Database(str(tmp_path / "treasury.db"))
    await database.connect()
    yield database
    await database.close()


async def boot(db: Database, account_id: str = ACCOUNT_ID) -> Node:
    bus = EventBus()
    tracker = OrderTracker(db=db)
    await tracker.initialize()
    treasury = Treasury(
        db=db,
        eventbus=bus,
        account_id=account_id,
        buy_commission_rate=0.0,
        sell_commission_rate=0.0,
        order_tracker=tracker,
    )
    await treasury.initialize()
    return Node(bus, tracker, treasury)


async def funded(db: Database, account_id: str = ACCOUNT_ID) -> Node:
    node = await boot(db, account_id)
    await node.treasury.set_account_balance(ALLOCATED)
    await node.treasury.allocate(BOT, ALLOCATED)
    return node


async def reserve(node: Node, *, tracked: bool = False) -> None:
    assert await node.treasury.reserve_for_order(BOT, ORDER, RESERVED)
    if tracked:
        await node.tracker.open(
            order_id=ORDER,
            account_id=node.treasury.account_id,
            bot_id=BOT,
            strategy_id="s1",
            broker_order_id=f"bk-{ORDER}",
            symbol="005930",
            side="buy",
            order_type="limit",
            ordered_qty=float(QTY),
            submitted_date="2026-11-23",
            order_price=PRICE,
        )


async def fill(node: Node, cumulative: int, qty: int, price: float) -> None:
    await node.tracker.record_fill(ORDER, float(cumulative), price)
    await node.bus.publish(
        OrderFilledEvent(
            account_id=ACCOUNT_ID,
            order_id=ORDER,
            broker_order_id=f"bk-{ORDER}",
            bot_id=BOT,
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=float(qty),
            price=price,
            commission=0.0,
            order_type="limit",
            fill_dedup_key=f"{ORDER}:{cumulative}",
        )
    )


async def stored(db: Database, account_id: str = ACCOUNT_ID) -> dict[str, float]:
    rows = await db.fetch_all(
        "SELECT order_id, remaining FROM treasury_reservations WHERE account_id = ?",
        (account_id,),
    )
    return {r["order_id"]: float(r["remaining"]) for r in rows}


def budget_of(node: Node):
    budget = node.treasury.get_budget(BOT)
    assert budget is not None
    return budget


async def test_restart_restores_reservation(db: Database) -> None:
    await reserve(await funded(db))

    node = await boot(db)

    assert node.treasury.get_reservations(BOT) == {ORDER: RESERVED}
    assert budget_of(node).reserved == RESERVED


@pytest.mark.parametrize("event_type", [OrderCancelledEvent, OrderFailedEvent])
async def test_cancel_or_fail_after_restart_releases(
    db: Database, event_type: type
) -> None:
    await reserve(await funded(db))

    node = await boot(db)
    await node.bus.publish(
        event_type(account_id=ACCOUNT_ID, order_id=ORDER, bot_id=BOT)
    )

    budget = budget_of(node)
    assert budget.reserved == 0.0
    assert budget.available == ALLOCATED
    assert node.treasury.get_reservations(BOT) == {}
    assert await stored(db) == {}


async def test_full_fill_after_restart_settles_once(db: Database) -> None:
    await reserve(await funded(db), tracked=True)
    cost = QTY * 9_000.0

    node = await boot(db)
    await fill(node, QTY, QTY, 9_000.0)

    budget = budget_of(node)
    assert budget.reserved == 0.0
    assert budget.spent == cost
    assert budget.available == ALLOCATED - cost
    assert await stored(db) == {}


async def test_partial_fill_remaining_survives_restart(db: Database) -> None:
    node = await funded(db)
    await reserve(node, tracked=True)
    first = 4 * PRICE
    await fill(node, 4, 4, PRICE)

    node = await boot(db)
    assert node.treasury.get_reservations(BOT) == {ORDER: RESERVED - first}

    await node.bus.publish(
        OrderCancelledEvent(account_id=ACCOUNT_ID, order_id=ORDER, bot_id=BOT)
    )
    budget = budget_of(node)
    assert budget.reserved == 0.0
    assert budget.available == ALLOCATED - first
    assert await stored(db) == {}


async def test_zero_remaining_then_cancel_deletes_row(db: Database) -> None:
    node = await funded(db)
    await reserve(node, tracked=True)
    await fill(node, 5, 5, 2 * PRICE)
    assert node.treasury.get_reservations(BOT) == {ORDER: 0.0}

    await node.bus.publish(
        OrderCancelledEvent(account_id=ACCOUNT_ID, order_id=ORDER, bot_id=BOT)
    )

    assert node.treasury.get_reservations(BOT) == {}
    assert await stored(db) == {}
    node = await boot(db)
    assert node.treasury.get_reservations(BOT) == {}


async def test_bot_stopped_after_restart_releases(db: Database) -> None:
    await reserve(await funded(db))

    node = await boot(db)
    await node.bus.publish(BotStoppedEvent(account_id=ACCOUNT_ID, bot_id=BOT))

    budget = budget_of(node)
    assert budget.reserved == 0.0
    assert budget.available == ALLOCATED
    assert await stored(db) == {}
    rows = await db.fetch_all(
        "SELECT amount FROM treasury_transactions "
        "WHERE transaction_type = 'bot_stopped_release'"
    )
    assert [float(r["amount"]) for r in rows] == [RESERVED]


async def test_release_budget_drops_rows(db: Database) -> None:
    node = await funded(db)
    await reserve(node)
    await node.treasury.release_budget(BOT)

    assert await stored(db) == {}
    node = await boot(db)
    assert node.treasury.get_reservations(BOT) == {}


async def test_other_account_rows_are_not_loaded(db: Database) -> None:
    other = await funded(db, "other")
    await reserve(other)

    node = await boot(db)

    assert node.treasury.get_reservations(BOT) == {}
    assert await stored(db, "other") == {ORDER: RESERVED}


async def test_reserve_rolls_back_memory_when_write_fails(db: Database) -> None:
    node = await funded(db)

    with (
        patch.object(node.treasury, "_save_budget", side_effect=RuntimeError("io")),
        pytest.raises(RuntimeError),
    ):
        await node.treasury.reserve_for_order(BOT, ORDER, RESERVED)

    budget = budget_of(node)
    assert (budget.available, budget.reserved) == (ALLOCATED, 0.0)
    assert node.treasury.get_reservations(BOT) == {}
    assert await stored(db) == {}


async def test_release_rolls_back_memory_when_write_fails(db: Database) -> None:
    node = await funded(db)
    await reserve(node)

    with (
        patch.object(node.treasury, "_save_budget", side_effect=RuntimeError("io")),
        pytest.raises(RuntimeError),
    ):
        await node.treasury.release_reservation(BOT, ORDER)

    budget = budget_of(node)
    assert (budget.available, budget.reserved) == (ALLOCATED - RESERVED, RESERVED)
    assert node.treasury.get_reservations(BOT) == {ORDER: RESERVED}
    assert await stored(db) == {ORDER: RESERVED}


async def test_unattributed_reserved_warns_without_change(
    db: Database, caplog: pytest.LogCaptureFixture
) -> None:
    await reserve(await funded(db))
    await db.execute(
        "UPDATE bot_budgets SET reserved = reserved + 500, available = available - 500"
    )

    with caplog.at_level(logging.WARNING, logger="ante.treasury.treasury"):
        node = await boot(db)

    budget = budget_of(node)
    assert budget.reserved == RESERVED + 500
    assert budget.available == ALLOCATED - RESERVED - 500
    assert node.treasury.get_reservations(BOT) == {ORDER: RESERVED}
    warned = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert any(BOT in r.getMessage() for r in warned)
