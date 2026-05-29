"""FillOutbox / FillOutboxPublisher 단위·통합 테스트 (#1949).

durability/at-least-once 무손실 전달:
- (a) commit↔publish 사이 crash 주입 → 재기동 publisher.catch_up_once 가 outbox
  에서 이벤트 재전달(현 한계 해소).
- (b) fill_dedup_key 가 CAS 확정 cumulative 기반 canonical·재전달 결정적.
- (d) 같은 fill 2회 관측 시 outbox UNIQUE(fill_dedup_key) 로 중복 row 미생성.
- 퍼블리셔 publish 성공 → mark 순서, publish 실패 시 미마킹(재전달 대기).

소비자 멱등화(#1957)는 본 범위 밖이다. 여기서는 outbox 무손실 전달 + 결정적
키 제공까지만 검증한다.
"""

from __future__ import annotations

import json

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import (
    FillOutbox,
    FillOutboxPublisher,
    canonical_cumulative,
    make_fill_dedup_key,
)
from ante.trade.order_tracker import OrderTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder

ACCT = "acct-A"
DATE = "20260529"


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "outbox.db"))
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
async def outbox(db):
    ob = FillOutbox(db)
    await ob.initialize()
    return ob


@pytest.fixture
async def trades_schema(db, position_history):
    # trades 스키마는 TradeRecorder.initialize 로 생성.
    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    return rec


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


def _make_applier(db, tracker, position_history, eventbus, outbox, publisher=None):
    return FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
        outbox=outbox,
        publisher=publisher,
    )


# ── fill_dedup_key 결정성 (b) ────────────────────────


def test_canonical_cumulative_is_deterministic():
    """같은 double 값은 항상 같은 canonical 문자열 → 재전달 키 결정적."""
    assert canonical_cumulative(40.0) == canonical_cumulative(40.0)
    assert canonical_cumulative(40.0) == "40.0"
    # int/float 동일 값 정규화.
    assert canonical_cumulative(40) == canonical_cumulative(40.0)
    # 서로 다른 값은 서로 다른 키 (충돌 없음).
    assert canonical_cumulative(40.0) != canonical_cumulative(40.5)


def test_make_fill_dedup_key_shape():
    assert make_fill_dedup_key("ord-1", 40.0) == "ord-1:40.0"
    assert make_fill_dedup_key("ord-1", 100.0) == "ord-1:100.0"


# ── transactional outbox durability (a) ──────────────


async def test_outbox_enqueued_in_same_transaction(
    db, tracker, position_history, eventbus, outbox, trades_schema
):
    """체결 적용 시 outbox row 가 trade/position 과 동일 커밋으로 기록된다."""
    applier = _make_applier(db, tracker, position_history, eventbus, outbox)
    await _seed(tracker)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 40.0

    rows = await outbox.fetch_unpublished()
    assert len(rows) == 1
    payload = json.loads(rows[0]["payload"])
    assert payload["order_id"] == "ord-1"
    assert payload["quantity"] == 40.0
    assert payload["account_id"] == ACCT
    # fill_dedup_key 는 CAS 확정 cumulative(40.0) 기반.
    assert rows[0]["fill_dedup_key"] == "ord-1:40.0"
    assert payload["fill_dedup_key"] == "ord-1:40.0"


async def test_crash_between_commit_and_publish_redelivers_on_restart(
    db, tracker, position_history, eventbus, outbox, trades_schema
):
    """commit 후 publish 직전 crash 주입 → 재기동 publisher 가 재전달 (현 한계 해소).

    publisher 를 주입하지 않고 apply_cumulative 를 호출하면, outbox 에 row 는
    커밋되지만 어떤 발행도 일어나지 않는다(= commit↔publish 사이 crash 와 동일한
    상태: 이벤트 미발행). 이후 새 publisher 가 기동 재전달(catch_up_once)하면
    소비자가 이벤트를 수신한다.
    """
    # crash 모사: publisher 미주입 → enqueue 만 되고 발행 트리거 없음.
    applier = _make_applier(
        db, tracker, position_history, eventbus, outbox, publisher=None
    )
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )

    # crash 직전: 소비자는 아직 아무 이벤트도 못 받았다.
    events = _collect_filled(eventbus)
    assert events == []
    assert len(await outbox.fetch_unpublished()) == 1

    # 재기동: 소비자 구독 후 publisher 가 미발행분을 재전달.
    publisher = FillOutboxPublisher(outbox=outbox, eventbus=eventbus)
    redelivered = await publisher.catch_up_once()

    assert redelivered == 1
    assert len(events) == 1
    assert events[0].order_id == "ord-1"
    assert events[0].quantity == 40.0
    assert events[0].fill_dedup_key == "ord-1:40.0"
    # 발행 완료로 마킹 → 더 이상 미발행 row 없음.
    assert await outbox.fetch_unpublished() == []


async def test_publisher_drains_via_notify(
    db, tracker, position_history, eventbus, outbox, trades_schema
):
    """FillApplier 가 publisher.notify() 로 즉시 드레인 트리거 → 정상 발행."""
    events = _collect_filled(eventbus)
    publisher = FillOutboxPublisher(outbox=outbox, eventbus=eventbus)
    applier = _make_applier(
        db, tracker, position_history, eventbus, outbox, publisher=publisher
    )
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    # notify 만으로는 워커 루프가 없으면 드레인되지 않으므로, 명시적 드레인으로
    # 발행을 확인한다(루프 기동은 lifecycle 테스트가 별도 검증).
    await publisher.catch_up_once()
    assert len(events) == 1
    assert events[0].fill_dedup_key == "ord-1:40.0"


# ── 같은 fill 2회 관측 → UNIQUE 로 중복 row 미생성 (d) ─


async def test_same_fill_twice_no_duplicate_outbox_row(
    db, tracker, position_history, eventbus, outbox, trades_schema
):
    """같은 누적 2회 관측 → 첫 회만 outbox row, 둘째는 no-op(중복 row 없음).

    둘째 관측은 record_fill delta<=0 으로 enqueue 자체에 도달하지 않지만, 설령
    동일 키가 다시 enqueue 돼도 UNIQUE(fill_dedup_key) + ON CONFLICT DO NOTHING
    으로 중복 row 가 생기지 않는다(방어). 두 측면을 모두 확인한다.
    """
    applier = _make_applier(db, tracker, position_history, eventbus, outbox)
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    # 같은 누적 재관측 → record_fill no-op → outbox 미증가.
    second = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert second == 0.0
    rows = await db.fetch_all("SELECT * FROM fill_outbox", ())
    assert len(rows) == 1

    # UNIQUE 방어: 같은 키를 직접 두 번 enqueue 해도 row 는 1개.
    await outbox.enqueue(fill_dedup_key="ord-1:40.0", payload={"x": 1})
    rows = await db.fetch_all("SELECT * FROM fill_outbox", ())
    assert len(rows) == 1


# ── publish 성공 → mark 순서 / 실패 시 미마킹 ─────────


async def test_publish_failure_does_not_mark(
    db, tracker, position_history, eventbus, outbox, trades_schema, monkeypatch
):
    """publish 가 예외를 던지면 mark_published 하지 않아 다음 사이클 재전달.

    역순 금지(mark 가 publish 보다 먼저 일어나지 않음)를 락한다.
    """
    applier = _make_applier(db, tracker, position_history, eventbus, outbox)
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )

    publisher = FillOutboxPublisher(outbox=outbox, eventbus=eventbus)

    # publish 자체를 실패시킨다(EventBus 핸들러 예외가 아니라 publish 호출 실패).
    calls = {"n": 0}
    orig_publish = eventbus.publish

    async def _boom(event):
        calls["n"] += 1
        raise RuntimeError("publish transport failed")

    monkeypatch.setattr(eventbus, "publish", _boom)
    redelivered = await publisher.catch_up_once()
    assert redelivered == 0
    assert calls["n"] == 1
    # 실패 → 미마킹 → 여전히 미발행 row.
    assert len(await outbox.fetch_unpublished()) == 1

    # 복구 후 재전달 → 정상 발행 + 마킹.
    monkeypatch.setattr(eventbus, "publish", orig_publish)
    events = _collect_filled(eventbus)
    redelivered = await publisher.catch_up_once()
    assert redelivered == 1
    assert len(events) == 1
    assert await outbox.fetch_unpublished() == []


# ── lifecycle (start/stop graceful) ──────────────────


async def test_publisher_start_stop_lifecycle(
    db, tracker, position_history, eventbus, outbox, trades_schema
):
    """start → enqueue → notify drain → stop graceful (워커 루프 동작 확인)."""
    events = _collect_filled(eventbus)
    publisher = FillOutboxPublisher(outbox=outbox, eventbus=eventbus, drain_interval=10)
    applier = _make_applier(
        db, tracker, position_history, eventbus, outbox, publisher=publisher
    )
    await publisher.start()
    try:
        await _seed(tracker)
        await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=40.0,
            avg_price=1000.0,
            submitted_date=DATE,
        )
        # notify 로 워커가 깨어 드레인할 때까지 잠시 양보.
        import asyncio

        for _ in range(50):
            if events:
                break
            await asyncio.sleep(0.01)
        assert len(events) == 1
        assert events[0].fill_dedup_key == "ord-1:40.0"
    finally:
        await publisher.stop()
    # stop 후 task 정리 확인 — 재호출 안전.
    await publisher.stop()
