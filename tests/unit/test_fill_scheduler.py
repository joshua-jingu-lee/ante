"""FillReconcileScheduler 단위·통합 테스트 (#1946).

- rate budget: open 없으면 get_order_history 0콜, 있으면 사이클당 ≤1콜.
- 기동 카치업(catch_up_once)으로 다운타임 체결 복구.
- 폴 단독 복구 → 포지션 정확.
- business_date_kst 영업일 매핑.
"""

from __future__ import annotations

import pytest

from ante.broker.fill_scheduler import (
    MIN_POLL_INTERVAL,
    FillReconcileScheduler,
    business_date_kst,
)
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.trade.fill_applier import FillApplier
from ante.trade.order_tracker import OrderTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder

ACCT = "acct-A"
DATE = business_date_kst()


class FakeBroker:
    """get_order_history 호출 횟수를 세는 fake broker."""

    def __init__(self, history: list[dict] | None = None) -> None:
        self._history = history or []
        self.call_count = 0
        self.last_args: tuple | None = None

    def set_history(self, history: list[dict]) -> None:
        self._history = history

    async def get_order_history(self, from_date=None, to_date=None):
        self.call_count += 1
        self.last_args = (from_date, to_date)
        return list(self._history)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "sched.db"))
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


@pytest.fixture
async def applier(db, tracker):
    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()
    eb = EventBus()
    return (
        FillApplier(db=db, order_tracker=tracker, position_history=ph, eventbus=eb),
        ph,
        eb,
    )


async def _seed(tracker, *, order_id="ord-1", broker_order_id="0001", qty=100.0):
    await tracker.open(
        order_id=order_id,
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id=broker_order_id,
        symbol="005930",
        side="buy",
        order_type="market",
        ordered_qty=qty,
        submitted_date=DATE,
    )


# ── cadence 하한 ─────────────────────────────────────


def test_poll_interval_floor():
    """poll_interval 은 MIN_POLL_INTERVAL(60s) 미만으로 내려가지 않는다."""
    broker = FakeBroker()
    sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=None,  # type: ignore[arg-type]
        fill_applier=None,  # type: ignore[arg-type]
        account_id=ACCT,
        poll_interval=5.0,
    )
    assert sched._poll_interval == MIN_POLL_INTERVAL


# ── rate budget (event-gated) ────────────────────────


async def test_no_open_orders_zero_calls(tracker, applier):
    """추적 open 주문이 없으면 get_order_history 0콜."""
    app, _ph, _eb = applier
    broker = FakeBroker()
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    applied = await sched.catch_up_once()
    assert applied == 0
    assert broker.call_count == 0


async def test_open_orders_at_most_one_call_per_cycle(tracker, applier):
    """open 주문이 여럿이어도 사이클당 get_order_history 1콜."""
    app, _ph, _eb = applier
    await _seed(tracker, order_id="ord-1", broker_order_id="0001")
    await _seed(tracker, order_id="ord-2", broker_order_id="0002")
    broker = FakeBroker(history=[])
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    await sched.catch_up_once()
    assert broker.call_count == 1


# ── 폴 단독 복구 (catch_up) ──────────────────────────


async def test_catch_up_recovers_fill(tracker, applier):
    """기동 카치업: history 의 체결을 멱등 복구 → 포지션 정확 + 이벤트."""
    app, ph, eb = applier
    events: list[OrderFilledEvent] = []

    async def _h(e):
        if isinstance(e, OrderFilledEvent):
            events.append(e)

    eb.subscribe(OrderFilledEvent, _h)

    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "symbol": "005930",
                "side": "buy",
                "quantity": 100.0,
                "filled_quantity": 100.0,
                "price": 1000.0,
                "status": "filled",
                "timestamp": DATE,
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    applied = await sched.catch_up_once()
    assert applied == 1
    assert len(events) == 1
    pos = await ph.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 100.0
    # 주문이 filled 로 종료.
    assert (await tracker.get("ord-1")).status == "filled"


async def test_catch_up_idempotent(tracker, applier):
    """두 번째 카치업은 같은 누적 → no-op (포지션 유지)."""
    app, ph, _eb = applier
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 60.0,
                "price": 1000.0,
                "side": "buy",
                "symbol": "005930",
                "quantity": 100.0,
                "timestamp": DATE,
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    first = await sched.catch_up_once()
    second = await sched.catch_up_once()
    assert first == 1
    assert second == 0
    pos = await ph.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 60.0


async def test_window_covers_earliest_open(tracker, applier):
    """get_order_history window 의 from_date 가 가장 이른 open 영업일."""
    app, _ph, _eb = applier
    await tracker.open(
        order_id="ord-old",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="005930",
        side="buy",
        order_type="market",
        ordered_qty=10.0,
        submitted_date="20260527",
    )
    broker = FakeBroker(history=[])
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    await sched.catch_up_once()
    assert broker.last_args is not None
    from_date, _to = broker.last_args
    assert from_date == "20260527"


async def test_history_error_does_not_crash(tracker, applier):
    """get_order_history 실패(CB open 등) → 0건, 다음 사이클 멱등 재시도."""
    app, _ph, _eb = applier
    await _seed(tracker)

    class BoomBroker:
        async def get_order_history(self, from_date=None, to_date=None):
            raise RuntimeError("circuit open")

    sched = FillReconcileScheduler(
        broker=BoomBroker(),  # type: ignore[arg-type]
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
    )
    applied = await sched.catch_up_once()
    assert applied == 0


# ── business_date_kst ────────────────────────────────


def test_business_date_kst_format():
    d = business_date_kst()
    assert len(d) == 8
    assert d.isdigit()


def test_business_date_kst_crosses_utc_midnight():
    """UTC 자정 직후라도 KST 기준 영업일을 준다 (KIS ord_dt 매칭)."""
    from datetime import UTC, datetime

    # 2026-05-29 23:30 UTC == 2026-05-30 08:30 KST.
    moment = datetime(2026, 5, 29, 23, 30, tzinfo=UTC)
    assert business_date_kst(moment) == "20260530"
