"""OrderTracker order_price seed/round-trip 테스트 (#2391).

``OrderSubmittedEvent.price`` → ``OrderTracker.open(order_price=...)`` →
``OrderTrackerRecord.order_price`` round-trip 을 잠근다. 주문 정정 v1
(price-only)의 buy 가격↓ fail-closed 판정 출처다. market/미지정 주문 또는
legacy(마이그레이션 이전) row 는 None 으로 보존된다.
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.trade.order_tracker import OrderTracker


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "tracker.db"))
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
async def tracker(db):
    t = OrderTracker(db)
    await t.initialize()
    return t


async def _seed(tracker: OrderTracker, *, order_price: float | None) -> None:
    await tracker.open(
        order_id="ord-1",
        account_id="acct-A",
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="005930",
        side="buy",
        order_type="limit",
        ordered_qty=10.0,
        submitted_date="20260601",
        order_price=order_price,
    )


async def test_order_price_seeded_and_roundtrip(tracker: OrderTracker) -> None:
    """order_price 가 DB 에 저장되고 record 로 복원된다."""
    await _seed(tracker, order_price=50000.0)
    rec = await tracker.get("ord-1")
    assert rec is not None
    assert rec.order_price == 50000.0


async def test_order_price_none_for_market(tracker: OrderTracker) -> None:
    """market/미지정 주문은 order_price=None 으로 보존된다."""
    await _seed(tracker, order_price=None)
    rec = await tracker.get("ord-1")
    assert rec is not None
    assert rec.order_price is None


async def test_order_price_in_open_cache(tracker: OrderTracker) -> None:
    """open 캐시 record 도 order_price 를 보존한다 (sync 백엔드 회귀)."""
    await _seed(tracker, order_price=70000.0)
    records = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    assert len(records) == 1
    assert records[0].order_price == 70000.0


async def test_legacy_null_order_price_from_row(db: Database) -> None:
    """order_price 컬럼이 NULL 인 legacy row → record.order_price None."""
    tracker = OrderTracker(db)
    await tracker.initialize()
    # order_price 미지정으로 직접 INSERT (legacy row 시뮬레이션).
    await db.execute(
        """INSERT INTO order_tracker
               (order_id, account_id, bot_id, strategy_id, broker_order_id,
                symbol, side, order_type, ordered_qty, recorded_filled_qty,
                avg_fill_price, status, submitted_date)
           VALUES ('ord-legacy', 'acct-A', 'bot-1', 'strat-1', '0009',
                   '005930', 'buy', 'limit', 10.0, 0.0, 0.0, 'open',
                   '20260601')""",
    )
    rec = await tracker.get("ord-legacy")
    assert rec is not None
    assert rec.order_price is None
