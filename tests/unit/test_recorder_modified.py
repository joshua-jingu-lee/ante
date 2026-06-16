"""TradeRecorder OrderModifyExecutedEvent → MODIFIED row 기록 테스트 (#2391).

정정 완료 이벤트는 별도 ``trades`` row(status=modified)로 멱등(trade_id PK,
INSERT OR IGNORE) 기록된다. price=신규 정정가, quantity=원주문 수량(불변).
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderModifyExecutedEvent
from ante.trade.models import TradeStatus
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "test.db"))
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def position_history(db):
    ph = PositionHistory(db)
    await ph.initialize()
    return ph


@pytest.fixture
async def recorder(db, position_history):
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    return rec


async def test_modify_executed_records_modified_row(
    recorder: TradeRecorder, db: Database
) -> None:
    """OrderModifyExecutedEvent → status=modified row 저장."""
    event = OrderModifyExecutedEvent(
        account_id="acc-test",
        order_id="ord-mod-1",
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=10.0,
        price=45000.0,
        reason="adjust",
    )
    await recorder._on_modified(event)

    rows = await db.fetch_all("SELECT * FROM trades WHERE status = 'modified'")
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == TradeStatus.MODIFIED.value
    assert row["price"] == 45000.0
    assert row["quantity"] == 10.0
    assert row["order_id"] == "ord-mod-1"
    assert row["symbol"] == "005930"
    assert row["side"] == "buy"


async def test_modify_executed_idempotent_on_event_id(
    recorder: TradeRecorder, db: Database
) -> None:
    """동일 event_id 재전달 → trade_id PK 멱등(중복 row 없음)."""
    event = OrderModifyExecutedEvent(
        account_id="acc-test",
        order_id="ord-mod-2",
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side="sell",
        quantity=5.0,
        price=60000.0,
        reason="adjust",
    )
    await recorder._on_modified(event)
    await recorder._on_modified(event)

    rows = await db.fetch_all(
        "SELECT * FROM trades WHERE trade_id = ?", (str(event.event_id),)
    )
    assert len(rows) == 1


async def test_modify_executed_subscribed_end_to_end(
    recorder: TradeRecorder, db: Database
) -> None:
    """subscribe 후 publish → MODIFIED row 가 기록되는지 end-to-end 확인."""
    bus = EventBus()
    recorder.subscribe(bus)

    event = OrderModifyExecutedEvent(
        account_id="acc-test",
        order_id="ord-mod-3",
        bot_id="bot1",
        strategy_id="s1",
        symbol="005930",
        side="buy",
        quantity=3.0,
        price=40000.0,
        reason="adjust",
    )
    await bus.publish(event)

    rows = await db.fetch_all("SELECT * FROM trades WHERE order_id = 'ord-mod-3'")
    assert len(rows) == 1
    assert rows[0]["status"] == TradeStatus.MODIFIED.value
