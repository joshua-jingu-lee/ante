"""FillApplier 단위·통합 테스트 (#1946).

- unknown odno 무시, delta>0 1회 발행, ≤0 no-op, 단일 txn(crash rollback).
- 스트림+폴 이중경로 → 포지션 1회만 적용.
- R5 락: TradeRecorder ↔ FillApplier 이중 position update 없음.
"""

from __future__ import annotations

import asyncio

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


# ── #1948 R2: txn rollback ↔ sync open 캐시 정합 (NEW blocking 회귀) ──


async def test_rollback_does_not_advance_sync_open_cache(
    db, tracker, position_history, eventbus, monkeypatch
):
    """record_fill 성공 후 _save_trade/position 실패 → rollback → sync
    get_open_orders 가 **stale advance 를 미반환** (R2 핵심 회귀 락).

    캐시는 record_fill 에서 건드리지 않고 commit 직후 mirror_fill_to_cache 로만
    갱신되므로, rollback 시 캐시는 DB(원복)와 일관되게 불변이어야 한다.
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
    # warm 직후 캐시는 open, recorded=0.
    before = tracker.get_open_orders_for_bot_sync(ACCT, "bot-1")
    assert len(before) == 1
    assert before[0].recorded_filled_qty == 0.0

    orig_on_trade = position_history.on_trade

    async def _boom(record):
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

    # rollback — DB 미advance + 캐시도 stale advance 없음 (여전히 recorded=0, open).
    rec_row = await tracker.get("ord-1")
    assert rec_row.recorded_filled_qty == 0.0
    cached = tracker.get_open_orders_for_bot_sync(ACCT, "bot-1")
    assert len(cached) == 1
    assert cached[0].recorded_filled_qty == 0.0
    assert cached[0].status == "open"

    # 복구 후 정상 적용 → commit 직후 mirror 로 캐시가 advance 된다.
    monkeypatch.setattr(position_history, "on_trade", orig_on_trade)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 40.0
    advanced = tracker.get_open_orders_for_bot_sync(ACCT, "bot-1")
    assert len(advanced) == 1
    assert advanced[0].recorded_filled_qty == 40.0
    assert advanced[0].status == "partially_filled"


async def test_full_fill_evicts_sync_open_cache_post_commit(
    applier, tracker, position_history
):
    """완전 체결 commit 후 mirror 가 캐시에서 evict → sync 미노출."""
    await _seed(tracker)
    assert len(tracker.get_open_orders_for_bot_sync(ACCT, "bot-1")) == 1
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=100.0,  # ordered_qty 도달 → filled
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 100.0
    assert tracker.get_open_orders_for_bot_sync(ACCT, "bot-1") == []


# ── Lock 직렬화 / fallback 발행 ──────────────────────


HANG_GUARD_SECONDS = 5.0


async def _yield_loop(times: int = 20) -> None:
    for _ in range(times):
        await asyncio.sleep(0)


async def _bounded(awaitable):
    return await asyncio.wait_for(awaitable, timeout=HANG_GUARD_SECONDS)


async def _apply(applier, kind: str, amount: float) -> float:
    if kind == "cumulative":
        return await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=amount,
            avg_price=1000.0,
            submitted_date=DATE,
        )
    return await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=amount,
        avg_price=1000.0,
        submitted_date=DATE,
    )


@pytest.mark.parametrize(
    ("first", "second", "second_amount", "expected_second_delta"),
    [
        ("cumulative", "cumulative", 60.0, 20.0),
        ("cumulative", "stream", 30.0, 30.0),
        ("stream", "cumulative", 60.0, 20.0),
        ("stream", "stream", 30.0, 30.0),
    ],
)
async def test_second_apply_waits_for_first_transaction_before_reading(
    applier,
    tracker,
    position_history,
    monkeypatch,
    first,
    second,
    second_amount,
    expected_second_delta,
):
    """첫 적용이 트랜잭션 안에서 멈춘 동안 둘째 적용은 추적 주문을 읽지 못한다."""
    await _seed(tracker)
    entered = asyncio.Event()
    release = asyncio.Event()
    orig_on_trade = position_history.on_trade
    on_trade_calls = 0

    async def _paused_on_trade(trade):
        nonlocal on_trade_calls
        on_trade_calls += 1
        if on_trade_calls == 1:
            entered.set()
            await release.wait()
        await orig_on_trade(trade)

    lookups: list[str] = []
    orig_lookup = tracker.lookup_order_id

    async def _spy_lookup(*args, **kwargs):
        lookups.append(args[1])
        return await orig_lookup(*args, **kwargs)

    monkeypatch.setattr(position_history, "on_trade", _paused_on_trade)
    monkeypatch.setattr(tracker, "lookup_order_id", _spy_lookup)

    t1 = asyncio.create_task(_apply(applier, first, 40.0))
    await _bounded(entered.wait())
    t2 = asyncio.create_task(_apply(applier, second, second_amount))
    await _yield_loop()
    assert lookups == ["0001"]
    assert not t2.done()

    release.set()
    assert await _bounded(t1) == 40.0
    assert await _bounded(t2) == expected_second_delta
    assert lookups == ["0001", "0001"]
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 40.0 + expected_second_delta


@pytest.mark.parametrize("first", ["cumulative", "stream"])
async def test_lock_holds_from_read_through_transaction(
    applier, tracker, position_history, monkeypatch, first
):
    """첫 적용이 주문을 읽는 중이면 둘째 스트림 증분은 그 적용이 끝난 뒤에 읽는다."""
    await _seed(tracker)
    entered = asyncio.Event()
    release = asyncio.Event()
    orig_get = tracker.get
    get_calls = 0

    async def _paused_get(order_id):
        nonlocal get_calls
        get_calls += 1
        if get_calls == 1:
            entered.set()
            await release.wait()
        return await orig_get(order_id)

    monkeypatch.setattr(tracker, "get", _paused_get)

    t1 = asyncio.create_task(_apply(applier, first, 40.0))
    await _bounded(entered.wait())
    t2 = asyncio.create_task(_apply(applier, "stream", 30.0))
    await _yield_loop()
    assert not t2.done()

    release.set()
    deltas = (await _bounded(t1), await _bounded(t2))

    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert (deltas, pos["quantity"]) == ((40.0, 30.0), 70.0)
    assert (await orig_get("ord-1")).recorded_filled_qty == 70.0


@pytest.mark.parametrize("failing_step", ["save_trade", "on_trade", "enqueue"])
async def test_any_step_failure_in_fill_transaction_leaves_nothing_committed(
    db, tracker, position_history, eventbus, monkeypatch, failing_step
):
    """txn 의 어느 단계가 실패해도 recorded·trade·position·outbox 가 모두 없다."""
    from ante.trade.fill_outbox import FillOutbox

    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    outbox = FillOutbox(db)
    await outbox.initialize()
    applier = FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
        outbox=outbox,
    )
    await _seed(tracker)
    calls: list[str] = []

    async def _fail(*args, **kwargs):
        calls.append(failing_step)
        raise RuntimeError(f"{failing_step} failed")

    target = {
        "save_trade": (applier, "_save_trade"),
        "on_trade": (position_history, "on_trade"),
        "enqueue": (outbox, "enqueue"),
    }[failing_step]
    monkeypatch.setattr(*target, _fail)

    with pytest.raises(RuntimeError, match=f"{failing_step} failed"):
        await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=40.0,
            avg_price=1000.0,
            submitted_date=DATE,
        )

    assert calls == [failing_step]
    assert (await tracker.get("ord-1")).recorded_filled_qty == 0.0
    assert (
        await db.fetch_all("SELECT * FROM trades WHERE account_id = ?", (ACCT,)) == []
    )
    assert await db.fetch_all("SELECT * FROM fill_outbox", ()) == []
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 0.0


async def test_fallback_publish_without_outbox_leaves_dedup_key_empty(
    applier, tracker, eventbus
):
    """outbox 미주입 경로의 직접 발행은 fill_dedup_key를 비운다."""
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
    assert events[0].fill_dedup_key == ""


async def _applier_with_outbox(db, tracker, position_history, eventbus):
    from ante.trade.fill_outbox import FillOutbox

    rec = TradeRecorder(db, position_history)
    await rec.initialize()
    outbox = FillOutbox(db)
    await outbox.initialize()
    applier = FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=position_history,
        eventbus=eventbus,
        outbox=outbox,
    )
    return applier, outbox


def _inject_failure(monkeypatch, position_history, outbox, failing_step):
    raised = (
        asyncio.CancelledError
        if failing_step == "cancelled_before_commit"
        else RuntimeError
    )

    async def _fail(*args, **kwargs):
        raise raised(failing_step)

    target = {
        "save_history": (position_history, "_save_history"),
        "enqueue": (outbox, "enqueue"),
        "cancelled_before_commit": (outbox, "enqueue"),
    }[failing_step]
    monkeypatch.setattr(*target, _fail)
    return raised


FAILING_STEPS = ["save_history", "enqueue", "cancelled_before_commit"]


@pytest.mark.parametrize("failing_step", FAILING_STEPS)
async def test_rolled_back_fill_leaves_position_cache_unchanged(
    db, tracker, position_history, eventbus, monkeypatch, failing_step
):
    """#2819: 롤백된 체결은 포지션 캐시에 남지 않고, 커밋된 재적용만 반영된다."""
    applier, outbox = await _applier_with_outbox(
        db, tracker, position_history, eventbus
    )
    await _seed(tracker)
    raised = _inject_failure(monkeypatch, position_history, outbox, failing_step)

    with pytest.raises(raised):
        await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=40.0,
            avg_price=1000.0,
            submitted_date=DATE,
        )

    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 0.0
    assert position_history.get_positions_sync("bot-1", account_id=ACCT) == []

    monkeypatch.undo()
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=40.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    assert delta == 40.0
    cached = position_history.get_positions_sync("bot-1", account_id=ACCT)
    assert [(p.symbol, p.quantity) for p in cached] == [("005930", 40.0)]


@pytest.mark.parametrize("failing_step", FAILING_STEPS)
async def test_rolled_back_sell_keeps_cached_holding(
    db, tracker, position_history, eventbus, monkeypatch, failing_step
):
    """#2819: 롤백된 매도는 캐시의 보유 수량을 줄이거나 지우지 않는다."""
    applier, outbox = await _applier_with_outbox(
        db, tracker, position_history, eventbus
    )
    await _seed(tracker)
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=100.0,
        avg_price=1000.0,
        submitted_date=DATE,
    )
    await _seed(
        tracker, order_id="ord-2", broker_order_id="0002", qty=100.0, side="sell"
    )
    raised = _inject_failure(monkeypatch, position_history, outbox, failing_step)

    with pytest.raises(raised):
        await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0002",
            observed_cumulative=100.0,
            avg_price=1100.0,
            submitted_date=DATE,
        )

    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 100.0
    cached = position_history.get_positions_sync("bot-1", account_id=ACCT)
    assert [(p.symbol, p.quantity) for p in cached] == [("005930", 100.0)]


# ── 종결된 주문의 늦은 체결 (#2705) ───────────────────


async def _terminate(tracker, status):
    if status == "expired":
        assert await tracker.expire_stale(ACCT, "20260530") == 1
    else:
        await tracker.mark_terminal("ord-1", status)


async def _tracker_row(db):
    row = await db.fetch_one(
        "SELECT status, terminal_at, recorded_filled_qty FROM order_tracker"
        " WHERE order_id = ?",
        ("ord-1",),
    )
    return dict(row)


@pytest.mark.parametrize("status", ["cancelled", "expired", "rejected"])
@pytest.mark.parametrize("path", ["cumulative", "stream"])
async def test_late_fill_on_same_day_terminal_order_is_applied(
    db, tracker, position_history, eventbus, status, path
):
    """같은 날짜의 종결 행에 관측된 체결은 반영되고, 상태·종결 시각은 그대로다."""
    applier, _outbox = await _applier_with_outbox(
        db, tracker, position_history, eventbus
    )
    await _seed(tracker, qty=10.0)
    await _terminate(tracker, status)
    before = await _tracker_row(db)
    if path == "cumulative":
        delta = await applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0001",
            observed_cumulative=4.0,
            avg_price=10_000.0,
            submitted_date=DATE,
        )
    else:
        delta = await applier.apply_stream_increment(
            account_id=ACCT,
            broker_order_id="0001",
            increment=4.0,
            avg_price=10_000.0,
            submitted_date=DATE,
        )
    assert delta == 4.0
    after = await _tracker_row(db)
    assert (after["status"], after["terminal_at"]) == (
        status,
        before["terminal_at"],
    )
    assert after["recorded_filled_qty"] == 4.0
    trades = await db.fetch_all(
        "SELECT status, quantity FROM trades WHERE order_id = ?", ("ord-1",)
    )
    assert [(r["status"], r["quantity"]) for r in trades] == [("filled", 4.0)]
    outbox_rows = await db.fetch_all("SELECT fill_dedup_key FROM fill_outbox", ())
    assert len(outbox_rows) == 1
    pos = await position_history.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 4.0
    assert tracker.get_open_orders_for_bot_sync(ACCT, "bot-1") == []


@pytest.mark.parametrize("status", ["cancelled", "expired"])
async def test_late_fill_on_other_day_terminal_order_is_ignored(
    db, tracker, applier, position_history, status
):
    """날짜가 다른 종결 행(odno 재사용)에는 체결을 잇지 않는다."""
    await _seed(tracker, qty=10.0)
    await _terminate(tracker, status)
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=4.0,
        avg_price=10_000.0,
        submitted_date="20260530",
    )
    increment = await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=4.0,
        avg_price=10_000.0,
        submitted_date="20260530",
    )
    assert (delta, increment) == (0.0, 0.0)
    assert (await _tracker_row(db))["recorded_filled_qty"] == 0.0
    assert await db.fetch_all("SELECT * FROM trades", ()) == []
