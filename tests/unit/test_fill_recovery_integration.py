"""체결 반영 통합·회귀 테스트 (#1946 / #1945 직격).

- 재기동 카치업 + barrier: fill 복구 → position reconcile 순서로 reconciler
  무오분류("외부 매수" 미발생).
- #1945 paper 시나리오: 폴로 체결 복구 → positions 정확 → 반복 buy/외부매수
  오분류/반복 sell 미발생.
- EOD 만료.
"""

from __future__ import annotations

import pytest

from ante.broker.fill_scheduler import FillReconcileScheduler, business_date_kst
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderFilledEvent,
    OrderSubmittedEvent,
    PositionMismatchEvent,
)
from ante.trade.fill_applier import FillApplier
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.reconciler import PositionReconciler
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService

ACCT = "acct-paper"
BOT = "bot-1"
STRAT = "strat-1"
SYMBOL = "005930"
DATE = business_date_kst()


class FakeBroker:
    def __init__(self, history=None, positions=None) -> None:
        self._history = history or []
        self._positions = positions or []
        self.history_calls = 0

    async def get_order_history(self, from_date=None, to_date=None):
        self.history_calls += 1
        return list(self._history)

    async def get_account_positions(self):
        return list(self._positions)


@pytest.fixture
async def db(tmp_path):
    db = Database(str(tmp_path / "integ.db"))
    await db.connect()
    try:
        yield db
    finally:
        await db.close()


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
async def stack(db, eventbus):
    """OrderTracker + FillApplier + TradeRecorder + reconciler 전체 스택."""
    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()
    rec.subscribe(eventbus)
    perf = PerformanceTracker(db)
    service = TradeService(rec, ph, perf)
    tracker = OrderTracker(db)
    await tracker.initialize()
    applier = FillApplier(
        db=db, order_tracker=tracker, position_history=ph, eventbus=eventbus
    )
    reconciler = PositionReconciler(trade_service=service, eventbus=eventbus)
    return {
        "ph": ph,
        "tracker": tracker,
        "applier": applier,
        "reconciler": reconciler,
        "service": service,
    }


async def _submit(eventbus, tracker, *, order_id, broker_order_id, qty, side="buy"):
    """OrderSubmittedEvent 발행 경로를 흉내내 tracker seed."""
    await tracker.open(
        order_id=order_id,
        account_id=ACCT,
        bot_id=BOT,
        strategy_id=STRAT,
        broker_order_id=broker_order_id,
        symbol=SYMBOL,
        side=side,
        order_type="market",
        ordered_qty=qty,
        submitted_date=DATE,
    )


def _hist(broker_order_id, cumulative, price, side="buy"):
    return {
        "order_id": broker_order_id,
        "symbol": SYMBOL,
        "side": side,
        "quantity": cumulative,
        "filled_quantity": cumulative,
        "price": price,
        "status": "filled",
        "timestamp": DATE,
    }


# ── barrier: fill 복구 선행 → reconciler 무오분류 ─────


async def test_barrier_fill_before_reconcile_no_misclassification(stack, eventbus):
    """fill 복구가 position reconcile 보다 선행하면, reconciler 가 ante 체결을
    "외부 매수" 로 오분류하지 않는다.

    시나리오: paper 주문 100주 제출 → 다운타임 중 체결(스트림 못 받음) →
    재기동 카치업이 먼저 100주 복구 → 이후 reconcile 은 내부=브로커=100 →
    불일치 없음(PositionMismatchEvent 미발행).
    """
    mismatches: list[PositionMismatchEvent] = []

    async def _mh(e):
        if isinstance(e, PositionMismatchEvent):
            mismatches.append(e)

    eventbus.subscribe(PositionMismatchEvent, _mh)

    await _submit(
        eventbus, stack["tracker"], order_id="ord-1", broker_order_id="0001", qty=100.0
    )

    broker = FakeBroker(
        history=[_hist("0001", 100.0, 70000.0)],
        positions=[{"symbol": SYMBOL, "quantity": 100.0, "avg_price": 70000.0}],
    )

    # 1) 기동 카치업 (barrier — reconcile 보다 먼저 await).
    fill_sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=stack["tracker"],
        fill_applier=stack["applier"],
        account_id=ACCT,
    )
    applied = await fill_sched.catch_up_once()
    assert applied == 1

    pos = await stack["ph"].get_current(BOT, SYMBOL, account_id=ACCT)
    assert pos["quantity"] == 100.0

    # 2) 이제 reconcile — 내부=100=브로커 → 불일치 없음.
    corrections = await stack["reconciler"].reconcile(
        bot_id=BOT,
        broker_positions=await broker.get_account_positions(),
        account_id=ACCT,
    )
    assert corrections == []
    assert mismatches == []  # "외부 매수" 오분류 미발생.


async def test_without_barrier_reconcile_would_misclassify(stack, eventbus):
    """대조군: fill 복구 전에 reconcile 하면 "외부 매수" 로 오분류한다.

    barrier 의 필요성을 명시적으로 락한다 (#1945 근본 원인 재현).
    """
    mismatches: list[PositionMismatchEvent] = []

    async def _mh(e):
        if isinstance(e, PositionMismatchEvent):
            mismatches.append(e)

    eventbus.subscribe(PositionMismatchEvent, _mh)

    await _submit(
        eventbus, stack["tracker"], order_id="ord-1", broker_order_id="0001", qty=100.0
    )

    broker = FakeBroker(
        positions=[{"symbol": SYMBOL, "quantity": 100.0, "avg_price": 70000.0}],
    )
    # fill 복구 없이 곧장 reconcile → 내부=0, 브로커=100 → 외부 매수.
    corrections = await stack["reconciler"].reconcile(
        bot_id=BOT,
        broker_positions=await broker.get_account_positions(),
        account_id=ACCT,
    )
    assert len(corrections) == 1
    assert len(mismatches) == 1
    assert mismatches[0].reason == "외부 매수"


# ── 스트림 + 폴 이중경로 → 포지션 1회만 ──────────────


async def test_stream_and_poll_position_applied_once(stack, eventbus):
    """submit → 스트림 증분 + 폴 같은 주문 체결 통보 → 포지션 1회만."""
    filled: list[OrderFilledEvent] = []

    async def _fh(e):
        if isinstance(e, OrderFilledEvent):
            filled.append(e)

    eventbus.subscribe(OrderFilledEvent, _fh)

    await _submit(
        eventbus, stack["tracker"], order_id="ord-1", broker_order_id="0001", qty=50.0
    )

    # 스트림: 50주 증분.
    await stack["applier"].apply_stream_increment(
        account_id=ACCT,
        broker_order_id="0001",
        increment=50.0,
        avg_price=70000.0,
        submitted_date=DATE,
    )
    # 폴: 같은 누적 50 관측.
    broker = FakeBroker(history=[_hist("0001", 50.0, 70000.0)])
    fill_sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=stack["tracker"],
        fill_applier=stack["applier"],
        account_id=ACCT,
    )
    await fill_sched.catch_up_once()

    pos = await stack["ph"].get_current(BOT, SYMBOL, account_id=ACCT)
    assert pos["quantity"] == 50.0  # 100 이면 이중계상 회귀.
    assert len(filled) == 1


# ── #1945 회귀: paper 폴 체결 복구 → positions 정확 ──


async def test_1945_regression_paper_poll_recovery(stack, eventbus):
    """#1945 직격: paper 계좌에서 스트림 체결 통보 없이 폴로 체결을 복구하면,
    positions 가 정확해지고 반복 buy/외부매수 오분류/반복 sell 연쇄가 발생하지
    않는다.

    1) buy 100 제출 → 폴 복구 → positions=100, 외부매수 오분류 없음.
    2) 같은 종목 보유가 인지되므로 전략은 (포지션 0 으로 오인한) 반복 buy 를
       하지 않는다 (positions=100 노출).
    3) sell 100 제출 → 폴 복구 → positions=0, 정확.
    """
    mismatches: list[PositionMismatchEvent] = []

    async def _mh(e):
        if isinstance(e, PositionMismatchEvent):
            mismatches.append(e)

    eventbus.subscribe(PositionMismatchEvent, _mh)

    # 1) buy 100 복구.
    await _submit(
        eventbus,
        stack["tracker"],
        order_id="ord-buy",
        broker_order_id="0001",
        qty=100.0,
        side="buy",
    )
    broker = FakeBroker(
        history=[_hist("0001", 100.0, 70000.0, side="buy")],
        positions=[{"symbol": SYMBOL, "quantity": 100.0, "avg_price": 70000.0}],
    )
    fill_sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=stack["tracker"],
        fill_applier=stack["applier"],
        account_id=ACCT,
    )
    await fill_sched.catch_up_once()

    pos = await stack["ph"].get_current(BOT, SYMBOL, account_id=ACCT)
    assert pos["quantity"] == 100.0  # positions 정확 — 0 고정(원인) 아님.

    # reconcile 도 무오분류.
    await stack["reconciler"].reconcile(
        bot_id=BOT,
        broker_positions=await broker.get_account_positions(),
        account_id=ACCT,
    )
    assert mismatches == []  # 외부매수 오분류 미발생.

    # 전략이 보는 포지션 = 100 (반복 buy 의 전제인 "0 보유 오인" 제거).
    snapshots = await stack["ph"].get_positions(BOT, account_id=ACCT)
    assert any(s.symbol == SYMBOL and s.quantity == 100.0 for s in snapshots)

    # 2) sell 100 복구 → positions=0.
    await _submit(
        eventbus,
        stack["tracker"],
        order_id="ord-sell",
        broker_order_id="0002",
        qty=100.0,
        side="sell",
    )
    broker._history = [_hist("0002", 100.0, 71000.0, side="sell")]
    broker._positions = []
    await fill_sched.catch_up_once()

    pos2 = await stack["ph"].get_current(BOT, SYMBOL, account_id=ACCT)
    assert pos2["quantity"] == 0.0  # 정확히 청산.


# ── EOD 만료 ─────────────────────────────────────────


async def test_eod_expiry_terminal(stack):
    """EOD 경과한 open 주문 → expired (무한 폴 방지)."""
    tracker = stack["tracker"]
    await tracker.open(
        order_id="ord-stale",
        account_id=ACCT,
        bot_id=BOT,
        strategy_id=STRAT,
        broker_order_id="0001",
        symbol=SYMBOL,
        side="buy",
        order_type="market",
        ordered_qty=10.0,
        submitted_date="20260101",
    )
    count = await tracker.expire_stale(ACCT, before_date=DATE)
    assert count == 1
    assert (await tracker.get("ord-stale")).status == "expired"
    # 만료 후 open 목록에서 빠져 폴 대상이 아니다.
    assert await tracker.get_open_orders(ACCT) == []


# ── OrderSubmittedEvent 구독 경로 (main 배선 검증) ───


async def test_submitted_event_seeds_tracker(db, eventbus):
    """OrderSubmittedEvent → OrderTracker.open seed (main._subscribe_order_tracker)."""
    from ante.main import _subscribe_order_tracker

    tracker = OrderTracker(db)
    await tracker.initialize()
    _subscribe_order_tracker(eventbus, tracker)

    await eventbus.publish(
        OrderSubmittedEvent(
            account_id=ACCT,
            order_id="ord-1",
            bot_id=BOT,
            strategy_id=STRAT,
            broker_order_id="0001",
            symbol=SYMBOL,
            side="buy",
            quantity=100.0,
            order_type="market",
        )
    )
    rec = await tracker.get("ord-1")
    assert rec is not None
    assert rec.broker_order_id == "0001"
    assert rec.ordered_qty == 100.0
    assert rec.status == "open"


async def test_terminal_event_marks_tracker(db, eventbus):
    """OrderCancelledEvent → mark_terminal."""
    from ante.eventbus.events import OrderCancelledEvent
    from ante.main import _subscribe_order_tracker

    tracker = OrderTracker(db)
    await tracker.initialize()
    _subscribe_order_tracker(eventbus, tracker)

    await eventbus.publish(
        OrderSubmittedEvent(
            account_id=ACCT,
            order_id="ord-1",
            bot_id=BOT,
            strategy_id=STRAT,
            broker_order_id="0001",
            symbol=SYMBOL,
            side="buy",
            quantity=100.0,
            order_type="market",
        )
    )
    await eventbus.publish(
        OrderCancelledEvent(
            account_id=ACCT,
            order_id="ord-1",
            bot_id=BOT,
            strategy_id=STRAT,
            symbol=SYMBOL,
            side="buy",
            quantity=100.0,
            reason="user cancel",
        )
    )
    assert (await tracker.get("ord-1")).status == "cancelled"
