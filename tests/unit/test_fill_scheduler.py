"""FillReconcileScheduler 단위·통합 테스트 (#1946).

- rate budget: open 없으면 get_order_history 0콜, 있으면 사이클당 ≤1콜.
- 기동 카치업(catch_up_once)으로 다운타임 체결 복구.
- 폴 단독 복구 → 포지션 정확.
- business_date_kst 영업일 매핑.
"""

from __future__ import annotations

import pytest

from ante.broker import fill_scheduler as fill_scheduler_module
from ante.broker.fill_scheduler import (
    MIN_POLL_INTERVAL,
    CatchUpResult,
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
    """추적 open 주문이 없으면 get_order_history 0콜. open-없음은 성공으로 본다."""
    app, _ph, _eb = applier
    broker = FakeBroker()
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    result = await sched.catch_up_once()
    assert result.succeeded is True  # open-없음 = 명시적 성공.
    assert result.applied == 0
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
    result = await sched.catch_up_once()
    assert result.succeeded is True
    assert result.applied == 1
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
    assert first.succeeded is True
    assert first.applied == 1
    assert second.succeeded is True
    assert second.applied == 0
    pos = await ph.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 60.0


async def test_window_covers_earliest_open(tracker, applier):
    """get_order_history window 의 from_date 가 가장 이른 (당일) open 영업일.

    poll-first: 폴(복구)이 expire 보다 먼저 돌므로, 당일 open 이 살아 있어
    from_date 가 그 영업일(DATE)을 덮는다. to_date 는 오늘(KST).
    """
    app, _ph, _eb = applier
    await _seed(tracker, order_id="ord-today", broker_order_id="0001", qty=10.0)
    broker = FakeBroker(history=[])
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    await sched.catch_up_once()
    assert broker.last_args is not None
    from_date, to_date = broker.last_args
    assert from_date == DATE
    assert to_date == DATE


async def test_window_covers_prior_day_open_before_expire(tracker, applier):
    """poll-first: 전일 open 이 expire **전** 폴 window 를 거슬러 넓힌다 (I8).

    submitted_date < 오늘인 open 이 있을 때, 메타리뷰 이전 결함은 expire 를 먼저
    돌려 그 open 을 제거하고 from_date 를 좁혔다. poll-first 는 만료 전 open 을
    읽어 from_date 가 전일 영업일(20200101)을 덮으므로, 다운타임 체결분을 폴이
    복구할 수 있다.
    """
    app, _ph, _eb = applier
    await tracker.open(
        order_id="ord-prior",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="005930",
        side="buy",
        order_type="market",
        ordered_qty=10.0,
        submitted_date="20200101",  # 전일(EOD 경과 가정).
    )
    broker = FakeBroker(history=[])  # 체결 없음 → 복구 0건.
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    await sched.catch_up_once()
    # 폴이 expire 전에 실행 — 1콜, window from_date 가 전일을 덮는다.
    assert broker.call_count == 1
    assert broker.last_args is not None
    from_date, to_date = broker.last_args
    assert from_date == "20200101"  # 전일 open 을 덮는 window (I8).
    assert to_date == DATE
    # 체결이 없었으므로 폴 후 expire 가 genuinely-dead open 을 만료.
    assert (await tracker.get("ord-prior")).status == "expired"


@pytest.fixture(autouse=True)
def _fast_catch_up_backoff(monkeypatch):
    """카치업 backoff 를 0 으로 줄여 폴-실패 재시도 테스트를 빠르게 한다."""
    monkeypatch.setattr(fill_scheduler_module, "CATCH_UP_BACKOFF_BASE", 0.0)


class BoomBroker:
    """get_order_history 가 항상 실패하고 호출 횟수를 세는 fake broker."""

    def __init__(self) -> None:
        self.call_count = 0

    async def get_order_history(self, from_date=None, to_date=None):
        self.call_count += 1
        raise RuntimeError("circuit open")


# ── Finding 1: catch_up 폴 실패 → succeeded=False (barrier 신호) ──


async def test_catch_up_poll_failure_reports_not_succeeded(tracker, applier):
    """get_order_history 실패(CB/rate/network) → succeeded=False (≠ 0건 성공).

    startup 폴 실패를 "0건 성공" 으로 삼키면 barrier 가 우회된다(#1946 Finding 1).
    실패는 명시적으로 succeeded=False 로 보고돼야 한다.
    """
    app, _ph, _eb = applier
    await _seed(tracker)
    broker = BoomBroker()
    sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
    )
    result = await sched.catch_up_once()
    assert isinstance(result, CatchUpResult)
    assert result.succeeded is False  # 폴 실패 — barrier 가 external-buy 연기.
    assert result.applied == 0


async def test_catch_up_poll_failure_bounded_retries(tracker, applier):
    """카치업 폴 실패 시 bounded backoff 로 재시도한 뒤 포기한다 (무한 루프 아님)."""
    app, _ph, _eb = applier
    await _seed(tracker)
    broker = BoomBroker()
    sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
    )
    result = await sched.catch_up_once()
    assert result.succeeded is False
    # CATCH_UP_MAX_ATTEMPTS 회 정확히 시도 (bounded).
    assert broker.call_count == fill_scheduler_module.CATCH_UP_MAX_ATTEMPTS


async def test_periodic_loop_swallows_poll_failure(tracker, applier):
    """주기 루프는 폴 실패를 삼키고 crash 하지 않는다 (다음 사이클 멱등 재시도).

    catch_up 과 달리 주기 폴 실패는 barrier 영향이 없으므로 루프가 죽지 않아야
    한다.
    """
    import asyncio as _asyncio

    app, _ph, _eb = applier
    await _seed(tracker)
    broker = BoomBroker()
    sched = FillReconcileScheduler(
        broker=broker,  # type: ignore[arg-type]
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
        poll_interval=MIN_POLL_INTERVAL,
    )
    # _poll_and_apply 가 예외를 던져도 _loop 가 잡아 삼키는지 직접 확인.
    sched._running = True
    # 한 사이클 흉내: 예외 전파 확인 후 루프 가드가 삼킴.
    with pytest.raises(RuntimeError):
        await sched._poll_and_apply()
    # 루프 태스크를 짧게 돌려 crash 없이 살아있는지 확인.
    sched._poll_interval = 0.01
    task = _asyncio.create_task(sched._loop())
    await _asyncio.sleep(0.05)
    assert not task.done()  # 폴 실패에도 루프 생존.
    sched._running = False
    task.cancel()
    try:
        await task
    except _asyncio.CancelledError:
        pass
    assert broker.call_count >= 1


# ── Finding 2: 폴 사이클의 EOD 만료 → 만료 주문 더는 폴 안 됨 ──


async def test_poll_first_then_expire_stale_no_more_poll(tracker, applier):
    """poll-first: EOD 경과 open 은 **폴(복구 시도) 후** expire 되고, 다음
    사이클부턴 폴되지 않는다 (무한 폴 방지하되 복구 우선).

    submitted_date < 오늘인 open 만 있을 때, catch_up_once 는 get_open_orders →
    get_order_history(복구) → expire_stale 순으로 동작한다. 첫 사이클은 만료 전
    open 이 살아 있어 폴 1콜(체결 없음 → applied=0), 그 후 genuinely-dead open
    을 expired 로 전이한다. 둘째 사이클은 open 이 비어 0콜.
    (#1946 메타리뷰: expire 를 폴 앞에 두면 다운타임 체결분 복구 실패 → 회귀.)
    """
    app, _ph, _eb = applier
    # 과거 영업일 open 주문 (어제, EOD 경과 가정).
    await tracker.open(
        order_id="ord-stale",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="005930",
        side="buy",
        order_type="market",
        ordered_qty=10.0,
        submitted_date="20200101",
    )
    broker = FakeBroker(history=[])  # 체결 없음 → genuinely-dead.
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    result = await sched.catch_up_once()
    assert result.succeeded is True
    assert result.applied == 0
    # poll-first — 첫 사이클은 만료 전 open 을 폴(복구 시도)한다 → 1콜.
    assert broker.call_count == 1
    # 체결이 없으므로 폴 후 genuinely-dead open 을 expired 로 종료.
    assert (await tracker.get("ord-stale")).status == "expired"
    # 이후 get_open_orders 에도 없음.
    assert await tracker.get_open_orders(ACCT) == []
    # 둘째 사이클: open 이 비어 더는 폴되지 않음 (무한 폴 없음).
    await sched.catch_up_once()
    assert broker.call_count == 1


async def test_poll_keeps_today_open(tracker, applier):
    """당일 open 주문은 expire_stale 가 만료시키지 않고 정상 폴한다."""
    app, _ph, _eb = applier
    await _seed(tracker, order_id="ord-today", broker_order_id="0001", qty=10.0)
    broker = FakeBroker(history=[])
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    result = await sched.catch_up_once()
    assert result.succeeded is True
    # 당일 주문은 유지 → 폴 1콜.
    assert broker.call_count == 1
    assert (await tracker.get("ord-today")).status == "open"


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
