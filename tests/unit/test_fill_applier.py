"""FillApplier 단위·통합 테스트 (#1946).

- unknown odno 무시, delta>0 1회 발행, ≤0 no-op, 단일 txn(crash rollback).
- 스트림+폴 이중경로 → 포지션 1회만 적용.
- R5 락: TradeRecorder ↔ FillApplier 이중 position update 없음.
"""

from __future__ import annotations

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.trade.fill_applier import FillApplier
from ante.trade.order_tracker import OrderTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder

ACCT = "acct-A"
DATE = "20260529"


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "applier.db"))
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
async def tracker(db):
    t = OrderTracker(db)
    await t.initialize()
    return t


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def applier(db, tracker, position_history, eventbus):
    # trades 스키마는 TradeRecorder.initialize 로 생성.
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    return FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
    )


async def _seed(
    tracker, *, order_id="ord-1", broker_order_id="0001", qty=100.0, side="buy"
):
    await tracker.open(
        order_id=order_id,
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id=broker_order_id,
        symbol="005930",
        side=side,
        order_type="market",
        ordered_qty=qty,
        submitted_date=DATE,
    )


def _collect_filled(eventbus):
    events: list[OrderFilledEvent] = []

    async def _h(event):
        if isinstance(event, OrderFilledEvent):
            events.append(event)

    eventbus.subscribe(OrderFilledEvent, _h)
    return events


# ── 기본 멱등 의미 ───────────────────────────────────


async def test_unknown_order_ignored(applier, position_history, eventbus):
    """추적되지 않는 odno → 무시 (delta 0, 포지션·이벤트 없음)."""
    events = _collect_filled(eventbus)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="UNKNOWN",
        observed_cumulative=50.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 0.0
    assert events == []
    positions = await position_history.get_positions("bot-1", account_id=ACCT)
    assert positions == []


async def test_delta_positive_applies_once(
    applier, tracker, position_history, eventbus
):
    events = _collect_filled(eventbus)
    await _seed(tracker)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 40.0
    assert len(events) == 1
    assert events[0].quantity == 40.0
    assert events[0].order_id == "ord-1"
    assert events[0].bot_id == "bot-1"
    assert events[0].strategy_id == "strat-1"
    assert events[0].account_id == ACCT
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0


async def test_same_cumulative_is_noop(applier, tracker, position_history, eventbus):
    """같은 누적 2회 → 둘째는 no-op (포지션 1회만, 이벤트 1개)."""
    events = _collect_filled(eventbus)
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    second = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert second == 0.0
    assert len(events) == 1
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0


async def test_incremental_cumulative_deltas(applier, tracker, position_history):
    """누적 증가 → 각 delta 정확, 포지션 = 최종 누적."""
    await _seed(tracker)
    d1 = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    d2 = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=100.0,
        avg_price=1010.0,
        submitted_date=DATE,
    )
    assert d1 == 40.0
    assert d2 == 60.0
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 100.0


# ── 스트림 + 폴 이중경로 멱등 ────────────────────────


async def test_stream_then_poll_position_once(
    applier, tracker, position_history, eventbus
):
    """스트림 증분 적용 후 폴이 같은 누적 관측 → 포지션 1회만 (delta 0)."""
    events = _collect_filled(eventbus)
    await _seed(tracker)
    # 스트림: per-execution 증분 40.
    s = await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    # 백스톱 폴: 누적 40 관측 → 이미 반영됨 → no-op.
    p = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert s == 40.0
    assert p == 0.0
    assert len(events) == 1
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0


async def test_poll_alone_recovers(applier, tracker, position_history, eventbus):
    """스트림 없이 폴 단독으로 체결 복구 → OrderFilledEvent + 포지션."""
    events = _collect_filled(eventbus)
    await _seed(tracker)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=100.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 100.0
    assert len(events) == 1
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 100.0


# ── R5 락: 이중 position update 없음 ─────────────────


async def test_no_double_position_update_with_trade_recorder(
    db, tracker, position_history, eventbus
):
    """TradeRecorder 와 FillApplier 가 같은 EventBus 에 구독돼도, fill 의 position
    갱신은 FillApplier(트랜잭션) 단일 권위자만 수행한다.

    FillApplier 가 OrderFilledEvent 를 발행하면 TradeRecorder._on_filled 가 받아
    알림만 발행하고 position 을 다시 갱신하지 않아야 한다. 포지션은 정확히 한 번
    (= delta) 만큼만 반영된다. (이중 적용이면 80 이 된다.)
    """
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    rec.subscribe(eventbus)  # OrderFilledEvent 구독 (priority=10)

    applier = FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
    )
    await _seed(tracker)

    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )

    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0  # 80 이면 이중 적용 회귀.

    # trades 도 정확히 1행 (FillApplier 가 insert, TradeRecorder 는 insert 안 함).
    rows = await db.fetch_all(
        "SELECT * FROM trades WHERE status = 'filled' AND account_id = ?",
        (ACCT,),
    )
    assert len(rows) == 1
    assert float(rows[0]["quantity"]) == 40.0


# ── crash 원자성 (단일 txn rollback) ─────────────────


async def test_crash_during_apply_rolls_back(
    db, tracker, position_history, eventbus, monkeypatch
):
    """position.on_trade 가 트랜잭션 중 예외 → rollback → recorded 미advance.

    재적용 시 동일 delta 가 다시 적용되어 무손실. (단일 트랜잭션 crash-safe.)
    """
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    applier = FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
    )
    await _seed(tracker)

    # 첫 적용: on_trade 가 raise → 트랜잭션 rollback.
    orig_on_trade = position_history.on_trade
    boom = {"fired": False}

    async def _boom(record):
        boom["fired"] = True
        raise RuntimeError("simulated crash mid-transaction")

    monkeypatch.setattr(position_history, "on_trade", _boom)
    with pytest.raises(RuntimeError):
        await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=40.0,
            avg_price=1000.0,
            submitted_date=DATE,
        )
    assert boom["fired"]

    # rollback 되어 recorded 가 advance 되지 않았다.
    rec_row = await tracker.get("ord-1")
    assert rec_row.recorded_filled_qty == 0.0
    # trades 도 insert 되지 않았다 (rollback).
    rows = await db.fetch_all(
        "SELECT * FROM trades WHERE status = 'filled' AND account_id = ?", (ACCT,)
    )
    assert rows == []

    # 복구 후 재적용 → 동일 delta 가 무손실 적용.
    monkeypatch.setattr(position_history, "on_trade", orig_on_trade)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 40.0
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0
