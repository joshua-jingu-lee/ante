"""주문 추적기 상태 전이의 특성 테스트 (#2707).

상태의 정본은 DB 의 ``order_tracker.status`` 다. 상태를 쓰는 자리는
``OrderTracker`` 의 SQL 넷(``open`` 의 ``INSERT``, ``record_fill``·
``mark_terminal``·``expire_stale`` 의 ``UPDATE``)이다. 이 파일은 그 자리들이
지금 어떤 이전 상태에서 무엇을 쓰고, 무엇을 그대로 두고, 무엇을 거부하는지를
반환값과 DB 값(``status``, ``terminal_at`` 이 ``NULL`` 인지,
``recorded_filled_qty``)으로 잠근다.

이전 상태는 공개 API로 만든다.

- ``open``: ``open``
- ``partially_filled``·``filled``: ``record_fill``
- ``cancelled``·``rejected``·``failed``: ``mark_terminal``
- ``expired``: ``expire_stale``

직접 SQL은 두 가지에만 쓴다: 쓰기가 실제로 일어났는지 보려고 ``terminal_at`` 에
센티널을 두는 것, 그리고 복원 사례에서 공개 API로 만들 수 없는 DB 값(``legacy``)
을 넣는 것.

순서가 뒤바뀐 경우는 ``get`` 이 ``mark_terminal`` 을 먼저 부르고 돌아가는 대역으로
``FillApplier`` 의 조회와 트랜잭션 사이를 결정적으로 정한다(시간·잠으로 맞추지
않는다).

기대값은 모두 리터럴(상태 문자열, 예외 종류와 전체 메시지, 건수)이다.

뒤쪽 49쌍 동작 테스트는 7×7 쌍마다 그 다음 상태를 쓸 수 있는 모든 공개 쓰기를
시도해, 쓰기가 그 행을 실제로 바꾼 쌍의 집합이 리터럴 17쌍과 같은지 본다. 종결
상태의 자기 전이는 체결 반영이 상태를 유지한 채 누적을 올린 쌍이다(#2705). 맨 뒤는
``OrderStatus`` 의 값이 DB 문자열과 같은지, 전이표가 리터럴 17쌍과 같은지 본다.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest

from ante.bot.providers.live import LiveOrderView
from ante.broker.fill_scheduler import FillReconcileScheduler
from ante.core import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderRejectedEvent,
)
from ante.main import _subscribe_order_tracker
from ante.trade.fill_applier import FillApplier
from ante.trade.order_tracker import (
    OPEN_STATUSES,
    ORDER_STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    OrderStatus,
    OrderTracker,
    OrderTrackerRecord,
)
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder

ACCT = "acct-A"
BOT = "bot-1"
DATE = "20260105"
NEXT_DATE = "20260106"
SENTINEL = "SENTINEL"

ORDER_STATUSES = [
    "open",
    "partially_filled",
    "filled",
    "cancelled",
    "rejected",
    "failed",
    "expired",
]


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(str(tmp_path / "order_state.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def tracker(db: Database) -> OrderTracker:
    t = OrderTracker(db)
    await t.initialize()
    return t


async def _open(
    tracker: OrderTracker,
    order_id: str = "ord-1",
    *,
    account_id: str = ACCT,
    broker_order_id: str | None = None,
    submitted_date: str = DATE,
    ordered_qty: float = 10.0,
) -> None:
    await tracker.open(
        order_id=order_id,
        account_id=account_id,
        bot_id=BOT,
        strategy_id="strat-1",
        broker_order_id=broker_order_id or f"B-{order_id}",
        symbol="005930",
        side="buy",
        order_type="limit",
        ordered_qty=ordered_qty,
        submitted_date=submitted_date,
        submitted_at="2026-01-05T09:00:00+09:00",
        order_price=70000.0,
    )


async def _row(db: Database, order_id: str = "ord-1") -> dict[str, Any] | None:
    row = await db.fetch_one(
        """SELECT status, terminal_at IS NULL AS terminal_null,
                  recorded_filled_qty, terminal_at
             FROM order_tracker WHERE order_id = ?""",
        (order_id,),
    )
    return dict(row) if row is not None else None


async def _state(db: Database, order_id: str = "ord-1") -> tuple[str, bool, float]:
    row = await _row(db, order_id)
    assert row is not None
    return (row["status"], bool(row["terminal_null"]), row["recorded_filled_qty"])


def _cached_ids(tracker: OrderTracker) -> list[tuple[str, str]]:
    return [
        (r.order_id, r.status) for r in tracker.get_open_orders_for_bot_sync(ACCT, BOT)
    ]


async def _enter(
    tracker: OrderTracker,
    prior: str,
    order_id: str = "ord-1",
    *,
    account_id: str = ACCT,
    small_filled: bool = False,
) -> None:
    await _open(tracker, order_id, account_id=account_id)
    if prior == "partially_filled":
        await tracker.record_fill(order_id, 3.0, 70000.0)
    elif prior == "filled" and small_filled:
        await tracker.record_fill(order_id, 3.0, 70000.0)
        await tracker.mark_terminal(order_id, "filled")
    elif prior == "filled":
        await tracker.record_fill(order_id, 10.0, 70000.0)
    elif prior in ("cancelled", "rejected", "failed"):
        await tracker.mark_terminal(order_id, prior)
    elif prior == "expired":
        await tracker.expire_stale(account_id, NEXT_DATE)


# ── 이전 상태 만들기 ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("prior", "small_filled", "expected"),
    [
        ("open", False, ("open", True, 0.0)),
        ("partially_filled", False, ("partially_filled", True, 3.0)),
        ("filled", False, ("filled", False, 10.0)),
        ("filled", True, ("filled", False, 3.0)),
        ("cancelled", False, ("cancelled", False, 0.0)),
        ("rejected", False, ("rejected", False, 0.0)),
        ("failed", False, ("failed", False, 0.0)),
        ("expired", False, ("expired", False, 0.0)),
    ],
)
async def test_entering_each_prior_state(db, tracker, prior, small_filled, expected):
    await _enter(tracker, prior, small_filled=small_filled)
    assert await _state(db) == expected


# ── open ─────────────────────────────────────────────────────────


async def test_open_inserts_open_row_and_caches_it(db, tracker):
    await _open(tracker)
    assert await _state(db) == ("open", True, 0.0)
    assert _cached_ids(tracker) == [("ord-1", "open")]


async def test_open_again_with_same_order_id_keeps_cancelled_row(db, tracker):
    await _open(tracker)
    await tracker.mark_terminal("ord-1", "cancelled")
    await _open(tracker)
    assert await _state(db) == ("cancelled", False, 0.0)
    assert _cached_ids(tracker) == []


async def test_open_with_unique_conflict_writes_nothing(db, tracker):
    await _open(tracker, "ord-1", broker_order_id="0001")
    await tracker.mark_terminal("ord-1", "cancelled")
    await _open(tracker, "ord-2", broker_order_id="0001")
    assert await _state(db, "ord-1") == ("cancelled", False, 0.0)
    assert await _row(db, "ord-2") is None
    assert _cached_ids(tracker) == []


async def test_open_order_dict_json_is_unchanged(tracker):
    await _open(tracker)
    (record,) = tracker.get_open_orders_for_bot_sync(ACCT, BOT)
    assert json.dumps(record.to_open_order_dict()) == (
        '{"order_id": "ord-1", "symbol": "005930", "side": "buy",'
        ' "ordered_qty": 10.0, "recorded_filled_qty": 0.0,'
        ' "remaining_qty": 10.0, "status": "open",'
        ' "submitted_at": "2026-01-05T09:00:00+09:00"}'
    )
    assert record.to_open_order_dict()["status"] == "open"


# ── record_fill ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("prior", "cumulative", "expected_status", "terminal_null"),
    [
        ("open", 4.0, "partially_filled", True),
        ("open", 10.0, "filled", False),
        ("open", 12.0, "filled", False),
        ("partially_filled", 4.0, "partially_filled", True),
        ("partially_filled", 10.0, "filled", False),
        ("cancelled", 4.0, "cancelled", False),
        ("cancelled", 10.0, "cancelled", False),
        ("expired", 4.0, "expired", False),
        ("expired", 10.0, "expired", False),
    ],
)
async def test_record_fill_writes_by_cumulative(
    db, tracker, prior, cumulative, expected_status, terminal_null
):
    await _enter(tracker, prior)
    before = (await _state(db))[2]
    result = await tracker.record_fill("ord-1", cumulative, 70000.0)
    assert result.delta == cumulative - before
    assert result.confirmed_cumulative == cumulative
    assert result.new_status == expected_status
    assert await _state(db) == (expected_status, terminal_null, cumulative)


async def test_record_fill_with_zero_ordered_qty_stays_partially_filled(db, tracker):
    await _open(tracker, ordered_qty=0.0)
    result = await tracker.record_fill("ord-1", 50.0, 70000.0)
    assert result.new_status == "partially_filled"
    assert result.delta == 50.0
    assert await _state(db) == ("partially_filled", True, 50.0)


@pytest.mark.parametrize("cumulative", [3.0, 2.0])
async def test_record_fill_not_above_recorded_writes_nothing(db, tracker, cumulative):
    await _enter(tracker, "partially_filled")
    result = await tracker.record_fill("ord-1", cumulative, 70000.0)
    assert (result.delta, result.confirmed_cumulative, result.new_status) == (
        0.0,
        3.0,
        "partially_filled",
    )
    assert await _state(db) == ("partially_filled", True, 3.0)


async def test_record_fill_unknown_order_returns_empty(tracker):
    result = await tracker.record_fill("missing", 5.0, 70000.0)
    assert (result.delta, result.confirmed_cumulative, result.new_status) == (
        0.0,
        0.0,
        "",
    )


# ── mark_terminal ────────────────────────────────────────────────


@pytest.mark.parametrize("prior", ["open", "partially_filled"])
@pytest.mark.parametrize(
    "target", ["cancelled", "rejected", "failed", "expired", "filled"]
)
async def test_mark_terminal_writes_target(db, tracker, prior, target):
    await _enter(tracker, prior)
    before_qty = (await _state(db))[2]
    await tracker.mark_terminal("ord-1", target)
    assert await _state(db) == (target, False, before_qty)
    assert _cached_ids(tracker) == []


@pytest.mark.parametrize("small_filled", [False, True])
async def test_mark_terminal_keeps_filled_row(db, tracker, small_filled):
    await _enter(tracker, "filled", small_filled=small_filled)
    before = await _row(db)
    await tracker.mark_terminal("ord-1", "cancelled")
    assert await _row(db) == before


@pytest.mark.parametrize("prior", ["cancelled", "rejected", "failed", "expired"])
@pytest.mark.parametrize(
    "target", ["cancelled", "rejected", "failed", "expired", "filled"]
)
async def test_mark_terminal_keeps_terminal_row(db, tracker, prior, target):
    await _enter(tracker, prior)
    await db.execute(
        "UPDATE order_tracker SET terminal_at = ? WHERE order_id = ?",
        (SENTINEL, "ord-1"),
    )
    before = await _row(db)
    await tracker.mark_terminal("ord-1", target)
    assert await _row(db) == before
    assert _cached_ids(tracker) == []


@pytest.mark.parametrize(
    ("status", "message"),
    [
        ("open", "비-terminal status: 'open'"),
        ("partially_filled", "비-terminal status: 'partially_filled'"),
        ("bogus", "비-terminal status: 'bogus'"),
    ],
)
async def test_mark_terminal_rejects_non_terminal(db, tracker, status, message):
    await _enter(tracker, "partially_filled")
    with pytest.raises(ValueError) as excinfo:
        await tracker.mark_terminal("ord-1", status)
    assert type(excinfo.value) is ValueError
    assert str(excinfo.value) == message
    assert await _state(db) == ("partially_filled", True, 3.0)
    assert _cached_ids(tracker) == [("ord-1", "open")]


async def test_mark_terminal_evicts_only_that_order(tracker):
    await _open(tracker, "ord-1")
    await _open(tracker, "ord-2")
    await tracker.mark_terminal("ord-1", "cancelled")
    assert _cached_ids(tracker) == [("ord-2", "open")]


async def test_duplicate_terminal_event_keeps_terminal_at(db, tracker):
    await _enter(tracker, "cancelled")
    await db.execute(
        "UPDATE order_tracker SET terminal_at = ? WHERE order_id = ?",
        (SENTINEL, "ord-1"),
    )
    await tracker.mark_terminal("ord-1", "cancelled")
    row = await _row(db)
    assert row is not None
    assert row["status"] == "cancelled"
    assert row["terminal_at"] == SENTINEL


# ── expire_stale ─────────────────────────────────────────────────


async def test_expire_stale_expires_only_older_open_rows(db, tracker):
    await _open(tracker, "o-open")
    await _open(tracker, "o-same-day", submitted_date=NEXT_DATE)
    await _open(tracker, "o-partial")
    await tracker.record_fill("o-partial", 3.0, 70000.0)
    await _open(tracker, "o-filled")
    await tracker.record_fill("o-filled", 10.0, 70000.0)
    await _open(tracker, "o-cancelled")
    await tracker.mark_terminal("o-cancelled", "cancelled")

    count = await tracker.expire_stale(ACCT, NEXT_DATE)

    assert count == 1
    assert await _state(db, "o-open") == ("expired", False, 0.0)
    assert await _state(db, "o-same-day") == ("open", True, 0.0)
    assert await _state(db, "o-partial") == ("partially_filled", True, 3.0)
    assert await _state(db, "o-filled") == ("filled", False, 10.0)
    assert await _state(db, "o-cancelled") == ("cancelled", False, 0.0)
    assert sorted(_cached_ids(tracker)) == [
        ("o-filled", "open"),
        ("o-partial", "open"),
        ("o-same-day", "open"),
    ]


async def test_expire_stale_with_nothing_to_expire_returns_zero(db, tracker):
    await _open(tracker, submitted_date=NEXT_DATE)
    assert await tracker.expire_stale(ACCT, NEXT_DATE) == 0
    assert await _state(db) == ("open", True, 0.0)


# ── 이벤트 변환 (main._subscribe_order_tracker) ───────────────────


@pytest.mark.parametrize(
    ("event_type", "expected"),
    [
        (OrderCancelledEvent, "cancelled"),
        (OrderRejectedEvent, "rejected"),
        (OrderFailedEvent, "failed"),
    ],
)
async def test_terminal_events_write_status(db, tracker, event_type, expected):
    eventbus = EventBus()
    _subscribe_order_tracker(eventbus, tracker)
    await _open(tracker)
    await eventbus.publish(event_type(account_id=ACCT, order_id="ord-1"))
    assert await _state(db) == (expected, False, 0.0)


@pytest.mark.parametrize(
    "event_type", [OrderCancelledEvent, OrderRejectedEvent, OrderFailedEvent]
)
async def test_terminal_event_without_order_id_writes_nothing(db, tracker, event_type):
    eventbus = EventBus()
    _subscribe_order_tracker(eventbus, tracker)
    await _open(tracker)
    await eventbus.publish(event_type(account_id=ACCT, order_id=""))
    assert await _state(db) == ("open", True, 0.0)


# ── 순서가 뒤바뀐 경우 (FillApplier) ──────────────────────────────


class _CancelOnGet(OrderTracker):
    """``get`` 이 한 번 ``mark_terminal`` 을 먼저 커밋하고 돌아가는 대역."""

    def __init__(self, db: Database) -> None:
        super().__init__(db)
        self.cancel_next_get = False

    async def get(self, order_id: str) -> OrderTrackerRecord | None:
        if self.cancel_next_get:
            self.cancel_next_get = False
            await self.mark_terminal(order_id, "cancelled")
        return await super().get(order_id)


async def _applier(db: Database, tracker: OrderTracker) -> FillApplier:
    history = PositionHistory(db)
    await history.initialize()
    recorder = TradeRecorder(db, history)
    await recorder.initialize()
    return FillApplier(
        db=db, order_tracker=tracker, position_history=history, eventbus=EventBus()
    )


async def _trade_count(db: Database) -> int:
    row = await db.fetch_one("SELECT COUNT(*) AS n FROM trades", ())
    assert row is not None
    return int(row["n"])


@pytest.fixture
async def racing(db: Database) -> _CancelOnGet:
    t = _CancelOnGet(db)
    await t.initialize()
    return t


@pytest.mark.parametrize(
    ("cumulative", "expected"),
    [(4.0, ("cancelled", False, 4.0)), (10.0, ("cancelled", False, 10.0))],
)
async def test_cancel_committed_between_lookup_and_fill_keeps_cancelled(
    db, racing, cumulative, expected
):
    applier = await _applier(db, racing)
    await _open(racing, broker_order_id="0001")
    racing.cancel_next_get = True
    delta = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=cumulative,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    assert delta == cumulative
    assert await _state(db) == expected
    assert await _trade_count(db) == 1
    assert _cached_ids(racing) == []


async def test_cancel_committed_before_fill_applies_the_fill(db, tracker):
    applier = await _applier(db, tracker)
    await _open(tracker, broker_order_id="0001")
    await tracker.mark_terminal("ord-1", "cancelled")
    cumulative = await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=4.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    increment = await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=4.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    assert (cumulative, increment) == (4.0, 4.0)
    assert await _state(db) == ("cancelled", False, 8.0)
    assert await _trade_count(db) == 2
    assert _cached_ids(tracker) == []


async def test_cancel_after_partial_fill_is_cancelled(db, tracker):
    applier = await _applier(db, tracker)
    await _open(tracker, broker_order_id="0001")
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=4.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    assert _cached_ids(tracker) == [("ord-1", "partially_filled")]
    await tracker.mark_terminal("ord-1", "cancelled")
    assert await _state(db) == ("cancelled", False, 4.0)
    assert _cached_ids(tracker) == []


# ── 캐시 ─────────────────────────────────────────────────────────


async def test_cache_mirrors_partial_and_evicts_filled(db, tracker):
    applier = await _applier(db, tracker)
    await _open(tracker, broker_order_id="0001")
    await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=4.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    (record,) = tracker.get_open_orders_for_bot_sync(ACCT, BOT)
    assert (record.status, record.recorded_filled_qty) == ("partially_filled", 4.0)
    await applier.apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=6.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    assert await _state(db) == ("filled", False, 10.0)
    assert _cached_ids(tracker) == []


# ── 체결 복구의 한 사이클 ────────────────────────────────────────


class _History:
    def __init__(self, history: list[dict[str, Any]]) -> None:
        self._history = history

    async def get_order_history(
        self, from_date: str | None = None, to_date: str | None = None
    ) -> list[dict[str, Any]]:
        return list(self._history)


def _hist(broker_order_id: str, cumulative: float) -> dict[str, Any]:
    return {
        "order_id": broker_order_id,
        "symbol": "005930",
        "side": "buy",
        "quantity": cumulative,
        "filled_quantity": cumulative,
        "price": 70000.0,
        "status": "filled",
        "timestamp": "20200102",
    }


@pytest.mark.parametrize(
    ("history", "expected"),
    [
        ([_hist("0001", 4.0)], ("partially_filled", True, 4.0)),
        ([_hist("0001", 10.0)], ("filled", False, 10.0)),
        ([], ("expired", False, 0.0)),
    ],
)
async def test_fill_recovery_cycle_fills_or_expires(db, tracker, history, expected):
    applier = await _applier(db, tracker)
    await _open(tracker, broker_order_id="0001", submitted_date="20200102")
    broker: Any = _History(history)
    scheduler = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=applier,
        account_id=ACCT,
    )
    result = await scheduler.catch_up_once()
    assert result.succeeded is True
    assert await _state(db) == expected


# ── 복원 ─────────────────────────────────────────────────────────


async def _insert_raw(db: Database, order_id: str, status: str) -> None:
    await db.execute(
        """INSERT INTO order_tracker
               (order_id, account_id, bot_id, strategy_id, broker_order_id,
                symbol, side, ordered_qty, status, submitted_date)
           VALUES (?, ?, ?, 's', ?, '005930', 'buy', 10.0, ?, ?)""",
        (order_id, ACCT, BOT, f"B-{order_id}", status, DATE),
    )


@pytest.mark.parametrize("status", [*ORDER_STATUSES, "legacy"])
async def test_restore_reads_db_string_as_is(db, tracker, status):
    await _insert_raw(db, "raw", status)
    record = await tracker.get("raw")
    found = await tracker.find_by_broker_order(ACCT, "B-raw", DATE)
    assert record is not None and found is not None
    assert record.status == status
    assert found.status == status
    assert type(record.status) is str


async def test_initialize_warms_cache_with_open_rows_only(db, tracker):
    for status in [*ORDER_STATUSES, "legacy"]:
        await _insert_raw(db, f"raw-{status}", status)
    fresh = OrderTracker(db)
    await fresh.initialize()
    assert sorted(_cached_ids(fresh)) == [
        ("raw-open", "open"),
        ("raw-partially_filled", "partially_filled"),
    ]


# ── 상태 값의 타입 ───────────────────────────────────────────────


async def test_open_record_status_is_plain_str(tracker):
    await _open(tracker)
    (record,) = tracker.get_open_orders_for_bot_sync(ACCT, BOT)
    assert type(record.status) is str
    assert repr(record.status) == "'open'"
    view = LiveOrderView(tracker, ACCT)
    (order,) = view.get_open_orders(BOT)
    assert type(order["status"]) is str


@pytest.mark.parametrize(
    ("cumulative", "expected"),
    [(4.0, "partially_filled"), (10.0, "filled"), (0.0, "open")],
)
async def test_record_fill_result_status_is_plain_str(tracker, cumulative, expected):
    await _open(tracker)
    result = await tracker.record_fill("ord-1", cumulative, 70000.0)
    assert result.new_status == expected
    assert type(result.new_status) is str


async def test_record_fill_not_above_recorded_status_is_plain_str(db, tracker):
    await _enter(tracker, "partially_filled")
    result = await tracker.record_fill("ord-1", 2.0, 70000.0)
    assert (result.delta, result.new_status) == (0.0, "partially_filled")
    assert type(result.new_status) is str


async def test_mirrored_cache_status_is_plain_str(db, tracker):
    applier = await _applier(db, tracker)
    await _open(tracker, broker_order_id="0001")
    await applier.apply_cumulative(
        account_id=ACCT,
        broker_order_id="0001",
        observed_cumulative=4.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    (record,) = tracker.get_open_orders_for_bot_sync(ACCT, BOT)
    assert record.status == "partially_filled"
    assert type(record.status) is str
    (order,) = LiveOrderView(tracker, ACCT).get_open_orders(BOT)
    assert type(order["status"]) is str


async def test_db_read_status_is_plain_str(db, tracker):
    await _open(tracker)
    await tracker.record_fill("ord-1", 4.0, 70000.0)
    record = await tracker.get("ord-1")
    (listed,) = await tracker.get_open_orders(ACCT)
    assert record is not None
    assert type(record.status) is str
    assert type(listed.status) is str
    assert listed.status == "partially_filled"


# ── 49쌍 ─────────────────────────────────────────────────────────

EXPECTED_OBSERVED_PAIRS = {
    ("open", "partially_filled"),
    ("open", "filled"),
    ("open", "cancelled"),
    ("open", "rejected"),
    ("open", "failed"),
    ("open", "expired"),
    ("partially_filled", "partially_filled"),
    ("partially_filled", "filled"),
    ("partially_filled", "cancelled"),
    ("partially_filled", "rejected"),
    ("partially_filled", "failed"),
    ("partially_filled", "expired"),
    ("filled", "filled"),
    ("cancelled", "cancelled"),
    ("rejected", "rejected"),
    ("failed", "failed"),
    ("expired", "expired"),
}

EXPECTED_UNOBSERVED_PAIRS = {
    ("open", "open"),
    ("partially_filled", "open"),
    ("filled", "open"),
    ("cancelled", "open"),
    ("rejected", "open"),
    ("failed", "open"),
    ("expired", "open"),
    ("filled", "partially_filled"),
    ("cancelled", "partially_filled"),
    ("cancelled", "filled"),
    ("rejected", "partially_filled"),
    ("rejected", "filled"),
    ("failed", "partially_filled"),
    ("failed", "filled"),
    ("expired", "partially_filled"),
    ("expired", "filled"),
    ("filled", "cancelled"),
    ("filled", "rejected"),
    ("filled", "failed"),
    ("filled", "expired"),
    ("cancelled", "rejected"),
    ("cancelled", "failed"),
    ("cancelled", "expired"),
    ("rejected", "cancelled"),
    ("rejected", "failed"),
    ("rejected", "expired"),
    ("failed", "cancelled"),
    ("failed", "rejected"),
    ("failed", "expired"),
    ("expired", "cancelled"),
    ("expired", "rejected"),
    ("expired", "failed"),
}


def _writers(prior: str, target: str) -> list[str]:
    writers: list[str] = []
    if target in ("partially_filled", "filled") or (
        target == prior and target in ("cancelled", "rejected", "failed", "expired")
    ):
        writers.append("record_fill")
    if target in ("filled", "cancelled", "rejected", "failed", "expired", "open"):
        writers.append("mark_terminal")
    if target == "expired":
        writers.append("expire_stale")
    if target == "open":
        writers.extend(["open_same_order_id", "open_same_unique_key"])
    return writers


async def _attempt(
    db: Database,
    tracker: OrderTracker,
    *,
    order_id: str,
    account_id: str,
    writer: str,
    target: str,
) -> bool | None:
    before = await _row(db, order_id)
    assert before is not None
    await db.execute(
        "UPDATE order_tracker SET terminal_at = ? WHERE order_id = ?",
        (SENTINEL, order_id),
    )
    delta = 0.0
    if writer == "record_fill":
        prev = float(before["recorded_filled_qty"])
        cumulative = prev + 1.0 if target != "filled" else max(10.0, prev + 1)
        if target != "filled" and cumulative >= 10.0:
            return None
        delta = (await tracker.record_fill(order_id, cumulative, 70000.0)).delta
    elif writer == "mark_terminal":
        try:
            await tracker.mark_terminal(order_id, target)
        except ValueError as exc:
            assert str(exc) == f"비-terminal status: {target!r}"
    elif writer == "expire_stale":
        await tracker.expire_stale(account_id, NEXT_DATE)
    elif writer == "open_same_order_id":
        await _open(tracker, order_id, account_id=account_id)
    elif writer == "open_same_unique_key":
        await _open(
            tracker,
            f"{order_id}-again",
            account_id=account_id,
            broker_order_id=f"B-{order_id}",
        )
    after = await _row(db, order_id)
    assert after is not None
    return after["status"] == target and (
        after["status"] != before["status"]
        or after["terminal_at"] != SENTINEL
        or delta > 0
    )


async def test_order_status_writes_over_all_49_pairs(db, tracker):
    observed: set[tuple[str, str]] = set()
    pairs: set[tuple[str, str]] = set()
    attempts = 0
    n = 0
    for prior in ORDER_STATUSES:
        for small_filled in [False, True] if prior == "filled" else [False]:
            for target in ORDER_STATUSES:
                pairs.add((prior, target))
                for writer in _writers(prior, target):
                    n += 1
                    order_id = f"o{n}"
                    account_id = f"acct-{n}"
                    await _enter(
                        tracker,
                        prior,
                        order_id,
                        account_id=account_id,
                        small_filled=small_filled,
                    )
                    assert (await _state(db, order_id))[0] == prior
                    wrote = await _attempt(
                        db,
                        tracker,
                        order_id=order_id,
                        account_id=account_id,
                        writer=writer,
                        target=target,
                    )
                    if wrote is None:
                        continue
                    attempts += 1
                    if wrote:
                        observed.add((prior, target))
    assert len(pairs) == 49
    assert attempts == 91
    assert len(observed) == 17
    assert observed == EXPECTED_OBSERVED_PAIRS
    assert pairs - observed == EXPECTED_UNOBSERVED_PAIRS
    assert len(pairs - observed) == 32


# ── enum과 전이표 ────────────────────────────────────────────────


def test_order_status_values_equal_db_strings():
    assert len(OrderStatus) == 7
    assert {member.value for member in OrderStatus} == {
        "open",
        "partially_filled",
        "filled",
        "cancelled",
        "rejected",
        "failed",
        "expired",
    }
    assert [member.value for member in OrderStatus] == ORDER_STATUSES


def test_open_and_terminal_sets_are_unchanged():
    assert sorted(OPEN_STATUSES) == ["open", "partially_filled"]
    assert sorted(TERMINAL_STATUSES) == [
        "cancelled",
        "expired",
        "failed",
        "filled",
        "rejected",
    ]


def test_order_transition_table_equals_the_17_literal_pairs():
    assert sorted(str(k) for k in ORDER_STATUS_TRANSITIONS) == sorted(ORDER_STATUSES)
    assert all(type(v) is set for v in ORDER_STATUS_TRANSITIONS.values())
    table = {
        (str(current), str(target))
        for current, targets in ORDER_STATUS_TRANSITIONS.items()
        for target in targets
    }
    assert table == EXPECTED_OBSERVED_PAIRS
    assert len(table) == 17
    every = {(a, b) for a in ORDER_STATUSES for b in ORDER_STATUSES}
    assert every - table == EXPECTED_UNOBSERVED_PAIRS


async def test_order_status_member_binds_as_text(db):
    await db.execute("CREATE TABLE enum_probe (value)")
    for member in OrderStatus:
        await db.execute("INSERT INTO enum_probe (value) VALUES (?)", (member,))
    rows = await db.fetch_all(
        "SELECT typeof(value) AS kind, value FROM enum_probe ORDER BY rowid"
    )
    assert [(r["kind"], r["value"]) for r in rows] == [
        ("text", "open"),
        ("text", "partially_filled"),
        ("text", "filled"),
        ("text", "cancelled"),
        ("text", "rejected"),
        ("text", "failed"),
        ("text", "expired"),
    ]
    row = await db.fetch_one(
        "SELECT COUNT(*) AS n FROM enum_probe WHERE value = 'open'"
    )
    assert row is not None and row["n"] == 1


@pytest.mark.parametrize(
    ("status", "member"),
    [
        ("open", "OPEN"),
        ("partially_filled", "PARTIALLY_FILLED"),
        ("filled", "FILLED"),
        ("cancelled", "CANCELLED"),
        ("rejected", "REJECTED"),
        ("failed", "FAILED"),
        ("expired", "EXPIRED"),
    ],
)
async def test_restored_status_is_an_order_status_value(db, tracker, status, member):
    await _insert_raw(db, "raw", status)
    record = await tracker.get("raw")
    assert record is not None
    assert OrderStatus(record.status) is OrderStatus[member]
