"""FillReconcileScheduler 단위·통합 테스트 (#1946).

- rate budget: open 없으면 get_order_history 0콜, 있으면 사이클당 ≤1콜.
- 기동 카치업(catch_up_once)으로 다운타임 체결 복구.
- 폴 단독 복구 → 포지션 정확.
- business_date_kst 영업일 매핑.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ante.broker import fill_scheduler as fill_scheduler_module
from ante.broker.fill_scheduler import (
    _KST,
    MIN_POLL_INTERVAL,
    CatchUpResult,
    FillReconcileScheduler,
    _normalize_history_date,
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
    # 2026-05-29 23:30 UTC == 2026-05-30 08:30 KST.
    moment = datetime(2026, 5, 29, 23, 30, tzinfo=UTC)
    assert business_date_kst(moment) == "20260530"


# ── #2004: get_order_history timestamp 정규화 ─────────


def test_normalize_history_date_yyyymmdd_passthrough():
    """YYYYMMDD(KIS ord_dt)는 그대로 통과한다 (회귀 방지)."""
    assert _normalize_history_date("20260102") == "20260102"


def test_normalize_history_date_iso_tzaware_to_kst_business_date():
    """tz-aware ISO timestamp → KST 영업일 YYYYMMDD (Test/Mock 어댑터 형식)."""
    # 2026-01-02 09:01 UTC == 2026-01-02 18:01 KST.
    assert _normalize_history_date("2026-01-02T09:01:00+00:00") == "20260102"


def test_normalize_history_date_iso_tzaware_crosses_kst_midnight():
    """UTC 자정 직전 tz-aware ISO → KST 익일 영업일로 환산."""
    # 2026-01-02 23:30 UTC == 2026-01-03 08:30 KST.
    assert _normalize_history_date("2026-01-02T23:30:00+00:00") == "20260103"


def test_normalize_history_date_naive_iso_assumes_utc():
    """tzinfo 없는 naive ISO 는 UTC 로 가정 후 KST 영업일로 환산."""
    # naive 2026-01-02 09:01 → UTC 가정 == 2026-01-02 18:01 KST.
    assert _normalize_history_date("2026-01-02T09:01:00") == "20260102"


def test_normalize_history_date_empty_returns_empty():
    """빈 문자열은 빈 문자열 → 호출부 to_date fallback."""
    assert _normalize_history_date("") == ""


def test_normalize_history_date_unparseable_returns_empty():
    """파싱 불가 문자열은 빈 문자열 → 호출부 to_date fallback."""
    assert _normalize_history_date("not-a-date") == ""


class _SpyApplier:
    """apply_cumulative 호출 인자(submitted_date)를 캡처하는 spy."""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def apply_cumulative(self, **kwargs):
        self.calls.append(kwargs)
        # delta>0 를 흉내내 applied 카운트를 올린다.
        return float(kwargs["observed_cumulative"])


async def test_iso_timestamp_normalized_to_business_date_for_applier(tracker):
    """(a) ISO timestamp item → submitted_date 가 KST 영업일 YYYYMMDD 로 정규화."""
    spy = _SpyApplier()
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 100.0,
                "price": 1000.0,
                "timestamp": "2026-01-02T09:01:00+00:00",
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=spy,  # type: ignore[arg-type]
        account_id=ACCT,
    )
    result = await sched.catch_up_once()
    assert result.succeeded is True
    assert result.applied == 1
    assert len(spy.calls) == 1
    submitted_date = spy.calls[0]["submitted_date"]
    assert submitted_date == "20260102"  # KST 영업일, ISO 아님.
    assert "T" not in submitted_date


async def test_yyyymmdd_timestamp_passthrough_for_applier(tracker):
    """(b) YYYYMMDD timestamp(KIS) → 그대로 submitted_date (회귀)."""
    spy = _SpyApplier()
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 100.0,
                "price": 1000.0,
                "timestamp": "20260102",
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=spy,  # type: ignore[arg-type]
        account_id=ACCT,
    )
    await sched.catch_up_once()
    assert spy.calls[0]["submitted_date"] == "20260102"


async def test_naive_iso_timestamp_normalized_for_applier(tracker):
    """(c) naive ISO timestamp → UTC 가정 KST 영업일 YYYYMMDD."""
    spy = _SpyApplier()
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 100.0,
                "price": 1000.0,
                "timestamp": "2026-01-02T09:01:00",
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=spy,  # type: ignore[arg-type]
        account_id=ACCT,
    )
    await sched.catch_up_once()
    assert spy.calls[0]["submitted_date"] == "20260102"


async def test_empty_timestamp_falls_back_to_to_date_for_applier(tracker):
    """(d) 빈/파싱불가 timestamp → to_date(오늘 KST) fallback."""
    spy = _SpyApplier()
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    broker = FakeBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 100.0,
                "price": 1000.0,
                "timestamp": "",
            },
            {
                "order_id": "0002",
                "filled_quantity": 50.0,
                "price": 1000.0,
                "timestamp": "garbage",
            },
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=spy,  # type: ignore[arg-type]
        account_id=ACCT,
    )
    await sched.catch_up_once()
    assert len(spy.calls) == 2
    assert spy.calls[0]["submitted_date"] == DATE  # to_date == today(KST).
    assert spy.calls[1]["submitted_date"] == DATE


async def test_catch_up_recovers_iso_timestamp_end_to_end(tracker, applier):
    """(e) end-to-end: ISO timestamp(Test/Mock 형식) history → 복구 applied>0.

    #2004 회귀: tracker 는 KST 영업일 DATE 로 seed 됐는데, ISO timestamp 를
    정규화하지 않고 submitted_date 로 넘기면 lookup_order_id 의
    ``submitted_date <= observed_date(YYYYMMDD)`` 문자열 비교에서 ISO 가 항상
    크게 잡혀 매핑 누락 → applied=0(no-op)이 된다. 정규화 후엔 영업일 매칭으로
    복구가 성공해야 한다.
    """
    app, ph, _eb = applier
    await _seed(tracker, broker_order_id="0001", qty=100.0)
    # Test/Mock 어댑터의 created_at.isoformat() 과 동일한 tz-aware ISO.
    # DATE(영업일 YYYYMMDD)에서 파생한 KST 정오를 써서 now 비의존(완전 결정적)으로
    # 같은 영업일을 보장한다 (#2277: UTC 저녁이면 hour=3 UTC 구성이 KST 익일로
    # 넘어가 business_date_kst != DATE 가 되는 wall-clock flaky 제거).
    ref = datetime.strptime(DATE, "%Y%m%d").replace(
        hour=12, minute=0, second=0, tzinfo=_KST
    )
    iso_ts = ref.isoformat()
    assert business_date_kst(datetime.fromisoformat(iso_ts)) == DATE
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
                "timestamp": iso_ts,
            }
        ]
    )
    sched = FillReconcileScheduler(
        broker=broker, order_tracker=tracker, fill_applier=app, account_id=ACCT
    )
    result = await sched.catch_up_once()
    assert result.succeeded is True
    assert result.applied == 1  # 정규화 덕분에 복구 성공 (no-op 아님).
    pos = await ph.get_current("bot-1", "005930", account_id=ACCT)
    assert pos["quantity"] == 100.0
    assert (await tracker.get("ord-1")).status == "filled"


# ═══════════════════════════════════════════════════════════════════════
# position-derived bounded fallback (#2314·#2316 §11)
# ═══════════════════════════════════════════════════════════════════════


class FallbackBroker:
    """get_order_history + get_positions 를 흉내내는 fake broker (#2314).

    ``is_paper`` 로 §11.6 paper 게이트를, ``positions_calls`` 로 §11.2 rate budget
    (미복구 open buy 없으면 get_positions 미호출)을 단언한다.
    """

    def __init__(
        self,
        *,
        history: list[dict] | None = None,
        positions: list[dict] | None = None,
        is_paper: bool = True,
    ) -> None:
        self._history = history or []
        self._positions = positions or []
        self.is_paper = is_paper
        self.history_calls = 0
        self.positions_calls = 0

    def set_history(self, history: list[dict]) -> None:
        self._history = history

    def set_positions(self, positions: list[dict]) -> None:
        self._positions = positions

    async def get_order_history(self, from_date=None, to_date=None):
        self.history_calls += 1
        return list(self._history)

    async def get_positions(self):
        self.positions_calls += 1
        return list(self._positions)


@pytest.fixture
async def fallback_applier(db, tracker):
    """FillApplier + PositionHistory + TradeService(get_all_positions) + EventBus.

    fallback 은 internal_account_qty 조회에 TradeService.get_all_positions 를,
    late-ccld alert 발행에 EventBus 를 쓴다. 실 컴포넌트로 통합 경로를 검증한다.
    """
    from ante.trade.performance import PerformanceTracker
    from ante.trade.service import TradeService

    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()
    perf = PerformanceTracker(db)
    eb = EventBus()
    app = FillApplier(db=db, order_tracker=tracker, position_history=ph, eventbus=eb)
    svc = TradeService(recorder=rec, position_history=ph, performance=perf)
    return app, ph, eb, svc


def _pos(symbol: str, quantity: float, avg_price: float = 1000.0) -> dict:
    return {"symbol": symbol, "quantity": quantity, "avg_price": avg_price}


def _make_fallback_sched(
    broker, tracker, app, svc, *, eventbus=None, fallback_enabled=True
):
    return FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
        trade_service=svc,
        eventbus=eventbus,
        fallback_enabled=fallback_enabled,
    )


# ── 시나리오 1 (핵심·#2314 재현): ccld 0건 + 잔고 1주 → fallback 수렴 ──


async def test_fallback_recovers_full_fill_from_balance(fallback_applier, tracker):
    """ccld 0건 + 잔고 069500 1주 + 유일 미복구 open buy(ordered 1, recorded 0)
    → fallback 이 FillApplier 로 1주 수렴 → recorded==1, status=filled, 포지션 1주.
    """
    app, ph, eb, svc = fallback_applier
    events: list[OrderFilledEvent] = []

    async def _h(e):
        if isinstance(e, OrderFilledEvent):
            events.append(e)

    eb.subscribe(OrderFilledEvent, _h)

    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0, 9500.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, eventbus=eb)
    result = await sched.catch_up_once()

    assert result.succeeded is True
    assert result.applied == 1
    # ccld 0건 → fallback 이 잔고에서 역도출.
    assert broker.history_calls == 1
    assert broker.positions_calls == 1
    rec = await tracker.get("ord-fb")
    assert rec.recorded_filled_qty == 1.0
    assert rec.status == "filled"
    pos = await ph.get_current("bot-1", "069500", account_id=ACCT)
    assert pos["quantity"] == 1.0
    # avg_price 는 잔고 평단(§11.4).
    assert pos["avg_entry_price"] == 9500.0
    # OrderFilledEvent 1회 발행 (시나리오 2 의 일부).
    assert len(events) == 1
    assert events[0].quantity == 1.0


# ── 시나리오 2: OrderFilledEvent 1회 + outbox fill_dedup_key 결정성 ──


async def test_fallback_emits_single_event_and_deterministic_dedup_key(db, tracker):
    """fallback 수렴 → OrderFilledEvent **1회** 발행 + outbox fill_dedup_key 결정성.

    outbox 주입 경로로 fill_dedup_key = order_id:canonical(confirmed_cumulative)
    가 결정적으로 채워지는지 검증한다.
    """
    from ante.trade.fill_outbox import FillOutbox, make_fill_dedup_key
    from ante.trade.performance import PerformanceTracker
    from ante.trade.service import TradeService

    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()
    perf = PerformanceTracker(db)
    eb = EventBus()
    outbox = FillOutbox(db=db)
    await outbox.initialize()
    app = FillApplier(
        db=db,
        order_tracker=tracker,
        position_history=ph,
        eventbus=eb,
        outbox=outbox,
    )
    svc = TradeService(recorder=rec, position_history=ph, performance=perf)

    await tracker.open(
        order_id="ord-fb2",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=2.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 2.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, eventbus=eb)
    await sched.catch_up_once()

    rows = await db.fetch_all("SELECT * FROM fill_outbox")
    assert len(rows) == 1  # 단일 outbox row(= 단일 OrderFilledEvent).
    # confirmed_cumulative == ordered_qty == 2.0 → 결정적 키.
    expected_key = make_fill_dedup_key("ord-fb2", 2.0)
    assert rows[0]["fill_dedup_key"] == expected_key


# ── 시나리오 3: 멱등 (같은 상태 재폴 → 추가 반영 0) ──


async def test_fallback_idempotent_on_repoll(fallback_applier, tracker):
    """fallback 수렴 후 같은 상태 재폴 → 추가 반영 0(이중 반영 없음).

    재폴 시 order 가 filled(terminal)라 미복구 open buy 후보가 없어
    get_positions 도 호출되지 않는다(§11.2 rate budget).
    """
    app, ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)

    first = await sched.catch_up_once()
    assert first.applied == 1
    assert broker.positions_calls == 1

    second = await sched.catch_up_once()
    assert second.applied == 0  # 멱등 — 추가 반영 없음.
    # filled terminal → open 없음 → 폴 0콜, 잔고도 미호출.
    assert broker.history_calls == 1  # 둘째 사이클은 open 없어 0콜(누계 유지).
    assert broker.positions_calls == 1
    pos = await ph.get_current("bot-1", "069500", account_id=ACCT)
    assert pos["quantity"] == 1.0


# ── 시나리오 4a: late-ccld 같은 누적 → CAS no-op (멱등) ──


async def test_fallback_then_ccld_same_cumulative_noop(fallback_applier, tracker):
    """fallback 수렴 후 ccld 가 같은 절대 누적을 반환 → record_fill CAS no-op."""
    app, ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)
    first = await sched.catch_up_once()
    assert first.applied == 1

    # 이제 ccld 가 같은 체결(절대 누적 1)을 반환. 하지만 order 는 filled 라
    # open 후보가 없어 폴되지 않는다 → no-op 보장(멱등). 포지션 불변.
    broker.set_history(
        [
            {
                "order_id": "0001",
                "filled_quantity": 1.0,
                "price": 1000.0,
                "timestamp": DATE,
            }
        ]
    )
    second = await sched.catch_up_once()
    assert second.applied == 0
    pos = await ph.get_current("bot-1", "069500", account_id=ACCT)
    assert pos["quantity"] == 1.0


# ── 시나리오 4b: late-ccld 더 낮은 값 → reconcile alert 발행 ──


async def test_late_ccld_lower_cumulative_emits_reconcile_alert(
    fallback_applier, tracker
):
    """fallback 이 full fill 로 올린 뒤 ccld 가 **더 낮은** 누적 → no-op + alert.

    §11.4: 비가역(CAS 단조)이라 정정은 못 하나 PositionMismatchEvent +
    NotificationEvent 로 over-attribution 가능성을 surface 한다.
    """
    from ante.eventbus.events import NotificationEvent, PositionMismatchEvent

    app, ph, eb, svc = fallback_applier
    mismatches: list[PositionMismatchEvent] = []
    notifs: list[NotificationEvent] = []
    eb.subscribe(
        PositionMismatchEvent,
        lambda e: (
            mismatches.append(e) if isinstance(e, PositionMismatchEvent) else None
        ),
    )
    eb.subscribe(
        NotificationEvent,
        lambda e: notifs.append(e) if isinstance(e, NotificationEvent) else None,
    )

    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=2.0,
        submitted_date=DATE,
    )
    # fallback: 잔고 2주 == ordered 2 → full fill 로 recorded=2.
    broker = FallbackBroker(history=[], positions=[_pos("069500", 2.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, eventbus=eb)
    await sched.catch_up_once()
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 2.0

    # late ccld: 실 체결 누적이 1(더 낮음) 이라고 반환. order 는 filled 라
    # lookup_order_id(non-terminal scope)에 안 잡혀 폴 자체가 0콜이 되는 것을
    # 막기 위해, alert 경로(_maybe_alert_late_ccld)는 history loop 에서 직접
    # 호출된다. order 가 filled 여서 open 폴이 0콜이 되므로, alert 검증은
    # _maybe_alert_late_ccld 를 직접 호출해 확인한다.
    await sched._maybe_alert_late_ccld(
        broker_order_id="0001",
        observed_cumulative=1.0,
        submitted_date=DATE,
    )
    assert len(mismatches) == 1
    assert mismatches[0].internal_qty == 2.0
    assert mismatches[0].broker_qty == 1.0
    assert "late_ccld_over_attribution" in mismatches[0].reason
    assert len(notifs) == 1
    assert notifs[0].level == "warning"


async def test_late_ccld_alert_not_emitted_when_ccld_higher_or_equal(
    fallback_applier, tracker
):
    """ccld 가 recorded 이상(정상 advance/멱등)이면 alert 미발행 (오경보 방지)."""
    from ante.eventbus.events import PositionMismatchEvent

    app, _ph, eb, svc = fallback_applier
    mismatches: list[PositionMismatchEvent] = []
    eb.subscribe(
        PositionMismatchEvent,
        lambda e: (
            mismatches.append(e) if isinstance(e, PositionMismatchEvent) else None
        ),
    )
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=2.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 2.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, eventbus=eb)
    await sched.catch_up_once()  # recorded=2.

    # ccld == recorded (멱등) → alert 없음.
    await sched._maybe_alert_late_ccld(
        broker_order_id="0001", observed_cumulative=2.0, submitted_date=DATE
    )
    # ccld > recorded (정상 추가 advance) → alert 없음.
    await sched._maybe_alert_late_ccld(
        broker_order_id="0001", observed_cumulative=3.0, submitted_date=DATE
    )
    assert mismatches == []


# ── 시나리오 5: self/external 경계 (excess != ordered, 다중 open buy) ──


async def test_fallback_skipped_when_excess_not_equal_ordered(
    fallback_applier, tracker
):
    """excess != ordered_qty(예: 60 vs ordered 100) → 미적용 (D+1 ccld 대기)."""
    app, ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=100.0,
        submitted_date=DATE,
    )
    # 잔고 60주 → excess 60 != ordered 100 → partial/모호 → 미적용.
    broker = FallbackBroker(history=[], positions=[_pos("069500", 60.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)
    result = await sched.catch_up_once()

    assert result.applied == 0
    assert broker.positions_calls == 1  # 후보 있어 잔고는 봤으나 매칭 실패.
    rec = await tracker.get("ord-fb")
    assert rec.recorded_filled_qty == 0.0  # 미적용 — 미반영 유지.
    assert rec.status == "open"
    # 포지션 미반영(빈 포지션 = quantity 0).
    pos = await ph.get_current("bot-1", "069500", account_id=ACCT)
    assert pos["quantity"] == 0.0


async def test_fallback_skipped_when_multiple_open_buys_same_symbol(
    fallback_applier, tracker
):
    """다중 open buy(같은 symbol) → 미적용 (귀속 불가, 외부/혼재 위험 회피)."""
    app, _ph, _eb, svc = fallback_applier
    for oid, odno in (("ord-a", "0001"), ("ord-b", "0002")):
        await tracker.open(
            order_id=oid,
            account_id=ACCT,
            bot_id="bot-1",
            strategy_id="strat-1",
            broker_order_id=odno,
            symbol="069500",
            side="buy",
            order_type="market",
            ordered_qty=1.0,
            submitted_date=DATE,
        )
    # 잔고 2주 == 합 ordered 2 라도 어느 주문에 귀속할지 불가 → 미적용.
    broker = FallbackBroker(history=[], positions=[_pos("069500", 2.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)
    result = await sched.catch_up_once()

    assert result.applied == 0
    assert (await tracker.get("ord-a")).recorded_filled_qty == 0.0
    assert (await tracker.get("ord-b")).recorded_filled_qty == 0.0


async def test_fallback_excludes_external_qty_via_internal_subtraction(
    fallback_applier, tracker
):
    """internal_account_qty 차감으로 기존 보유분이 excess 에 혼입되지 않는다(§11.1).

    이미 internal 5주 보유(타 bot) + 잔고 6주 → excess 1 == ordered 1 → 적용.
    (잔고 총량 6 을 self 로 오귀속하지 않음.)
    """
    from ante.trade.models import TradeRecord, TradeStatus

    app, ph, _eb, svc = fallback_applier
    # 타 bot 의 기존 보유 5주를 positions 에 직접 적재.
    await ph.on_trade(
        TradeRecord(
            trade_id=__import__("uuid").uuid4(),
            bot_id="bot-other",
            strategy_id="strat-x",
            symbol="069500",
            side="buy",
            quantity=5.0,
            price=1000.0,
            status=TradeStatus.FILLED,
            order_type="market",
            account_id=ACCT,
        )
    )
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    # 잔고 6주(기존 5 + self 1). excess = 6 - 5 = 1 == ordered 1.
    broker = FallbackBroker(history=[], positions=[_pos("069500", 6.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)
    result = await sched.catch_up_once()

    assert result.applied == 1
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 1.0
    # bot-1 포지션만 1주 증가, bot-other 는 불변.
    pos1 = await ph.get_current("bot-1", "069500", account_id=ACCT)
    assert pos1["quantity"] == 1.0


# ── 시나리오 6: rate budget (ccld 채우면 get_positions 미호출) ──


async def test_get_positions_not_called_when_ccld_fills(fallback_applier, tracker):
    """ccld 가 체결을 주면 미복구 open buy 가 없어 get_positions 미호출(§11.2)."""
    app, ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    # ccld 가 체결 1 을 줌 → recorded advance → 미복구 후보 없음.
    broker = FallbackBroker(
        history=[
            {
                "order_id": "0001",
                "filled_quantity": 1.0,
                "price": 1000.0,
                "timestamp": DATE,
            }
        ],
        positions=[_pos("069500", 1.0)],
    )
    sched = _make_fallback_sched(broker, tracker, app, svc)
    result = await sched.catch_up_once()

    assert result.applied == 1  # ccld 로 복구.
    assert broker.history_calls == 1
    assert broker.positions_calls == 0  # rate budget — 잔고 미호출.
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 1.0


async def test_get_positions_not_called_when_no_open_buy(fallback_applier, tracker):
    """미복구 open buy 가 애초에 없으면 get_positions 미호출(§11.2).

    open 이 sell 뿐이거나 0건이면 후보가 없어 잔고를 보지 않는다.
    """
    app, _ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-sell",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="sell",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc)
    await sched.catch_up_once()
    assert broker.positions_calls == 0  # buy 후보 없음 → 잔고 미호출.


# ── 시나리오 7: disable flag / paper 게이트 ──


async def test_fallback_disabled_flag_no_op(fallback_applier, tracker):
    """fallback_enabled=False → fallback 미동작 (get_positions 미호출, 미반영)."""
    app, _ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, fallback_enabled=False)
    result = await sched.catch_up_once()

    assert result.applied == 0
    assert broker.positions_calls == 0  # disable → 잔고 미호출.
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 0.0


async def test_fallback_skipped_when_broker_not_paper(fallback_applier, tracker):
    """broker.is_paper=False(실전) → fallback 미동작(§11.6 live 분리)."""
    app, _ph, _eb, svc = fallback_applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)], is_paper=False)
    sched = _make_fallback_sched(broker, tracker, app, svc)
    result = await sched.catch_up_once()

    assert result.applied == 0
    assert broker.positions_calls == 0  # 실전 → 잔고 미호출.
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 0.0


async def test_fallback_no_op_without_trade_service(applier, tracker):
    """trade_service 미주입(legacy/partial wiring) → fallback 미동작."""
    app, _ph, _eb = applier
    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    # trade_service=None (기본).
    sched = FillReconcileScheduler(
        broker=broker,
        order_tracker=tracker,
        fill_applier=app,
        account_id=ACCT,
    )
    result = await sched.catch_up_once()
    assert result.applied == 0
    assert broker.positions_calls == 0
    assert (await tracker.get("ord-fb")).recorded_filled_qty == 0.0


# ── 시나리오 8: 통합 — Treasury/TradeRecorder/캐시 evict (FillApplier 경로) ──


async def test_fallback_integrates_full_fill_applier_path(db, tracker):
    """fallback 이 FillApplier 단일 경로로 수렴 → trades insert · open 캐시 evict.

    §11.8 단일 권위: fallback 도 FillApplier.apply_cumulative 만 거치므로
    trades insert(TradeRecorder 스키마) · positions · open 캐시 evict 가 기존
    FillApplier 경로로 정상 동작한다(통합).
    """
    from ante.trade.performance import PerformanceTracker
    from ante.trade.service import TradeService

    ph = PositionHistory(db)
    await ph.initialize()
    rec = TradeRecorder(db, ph)
    await rec.initialize()
    perf = PerformanceTracker(db)
    eb = EventBus()
    app = FillApplier(db=db, order_tracker=tracker, position_history=ph, eventbus=eb)
    svc = TradeService(recorder=rec, position_history=ph, performance=perf)

    await tracker.open(
        order_id="ord-fb",
        account_id=ACCT,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id="0001",
        symbol="069500",
        side="buy",
        order_type="market",
        ordered_qty=1.0,
        submitted_date=DATE,
    )
    # open 캐시에 진입돼 있어야 한다(sync 백엔드).
    assert tracker.get_open_orders_for_bot_sync(ACCT, "bot-1")

    broker = FallbackBroker(history=[], positions=[_pos("069500", 1.0)])
    sched = _make_fallback_sched(broker, tracker, app, svc, eventbus=eb)
    await sched.catch_up_once()

    # trades insert(FillApplier _save_trade 경로).
    trades = await db.fetch_all("SELECT * FROM trades WHERE order_id = ?", ("ord-fb",))
    assert len(trades) == 1
    assert trades[0]["quantity"] == 1.0
    # open 캐시 evict(filled → mirror_fill_to_cache evict).
    assert tracker.get_open_orders_for_bot_sync(ACCT, "bot-1") == []
