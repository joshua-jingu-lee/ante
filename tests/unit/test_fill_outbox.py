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

import asyncio
import json
import sqlite3

import pytest

from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import NotificationEvent, OrderFilledEvent
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import (
    _DB_CORRUPTION_SIGNATURES,
    _ESCALATE_THRESHOLD,
    LOOP_BACKOFF_MULTIPLIER_CAP,
    FillOutbox,
    FillOutboxPublisher,
    _is_db_corruption,
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


# ── _loop DB 손상 escalation/backoff (#2407 O1–O6) ───
#
# 실대기 금지: 가짜 monotonic 시계(loop.time)와 _wakeup.wait 를 제어하는 harness 로
# _loop 사이클을 결정적으로 진행시킨다. _drain 을 stub 으로 교체해 사이클마다 원하는
# 예외/성공을 주입하고, sleep/wait_for 실시간 대기를 제거한다.


class _LoopHarness:
    """``_loop`` 를 실시간 대기 없이 결정적으로 사이클 진행시키는 테스트 harness.

    - ``loop.time`` 을 가짜 monotonic clock 으로 대체(``now`` 누적). backoff 대기는
      ``wait_for`` 가 timeout 만큼 clock 을 전진시켜 즉시 반환되게 한다(실대기 없음).
    - ``_drain`` 을 stub 으로 교체해 사이클별 동작(예외/성공)을 주입한다. stub 은
      drain 호출 직후 매번 ``cycles`` 를 감소시키고 0 이 되면 ``_running=False`` 로
      루프를 종료한다.
    - 각 드레인 직전 ``loop.time`` 값(=드레인이 허용된 시각)을 ``drain_times`` 에
      기록해, 연속 실패 시 backoff(다음 드레인까지 간격)가 증가하는지 검증한다.
    """

    def __init__(self, publisher: FillOutboxPublisher, monkeypatch) -> None:
        self._publisher = publisher
        self._monkeypatch = monkeypatch
        self.now = 0.0
        self.drain_times: list[float] = []
        self.drain_outcomes: list = []  # 각 사이클에 주입할 예외(None=성공)
        self.wakeup_during_wait = False  # True 면 wait 중 _wakeup 이 set 된 상태로 깨움

    def install(self) -> None:
        real_loop = asyncio.get_event_loop()

        def _fake_time() -> float:
            return self.now

        self._monkeypatch.setattr(real_loop, "time", _fake_time)

        async def _fake_wait_for(awaitable, timeout):
            # awaitable(=_wakeup.wait()) 코루틴을 소비해 경고를 피한다.
            awaitable.close()
            if self.wakeup_during_wait and self._publisher._wakeup.is_set():
                # notify() 로 깨어난 상황 — 시간 전진 없이 즉시 반환(O5 우회 시도).
                return None
            # 백스톱/backoff 만료 — clock 을 timeout 만큼 전진시키고 TimeoutError.
            self.now += timeout
            raise TimeoutError

        self._monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)

        outcomes = iter(self.drain_outcomes)

        async def _fake_drain() -> int:
            # outcomes 가 소진되면 CancelledError 로 루프를 종료한다. (return 0 으로
            # 끝내면 _loop 의 success 분기가 카운터를 reset 해 마지막 상태가 오염되므로,
            # 시각 기록도 카운터 reset 도 없이 깨끗이 빠져나가게 한다.) 주입된 outcome
            # 이 있을 때만 그 사이클의 드레인 허용 시각을 기록한다.
            try:
                outcome = next(outcomes)
            except StopIteration:
                self._publisher._running = False
                raise asyncio.CancelledError from None
            self.drain_times.append(self.now)
            if outcome is not None:
                raise outcome
            return 0

        self._monkeypatch.setattr(self._publisher, "_drain", _fake_drain)

    async def run(self) -> None:
        self._publisher._running = True
        try:
            await self._publisher._loop()
        except asyncio.CancelledError:
            # harness 의 outcomes 소진 종료 신호 — 정상 종료로 취급.
            pass


async def test_loop_backoff_increases_on_consecutive_db_failures(eventbus, monkeypatch):
    """(a) 연속 sqlite3.DatabaseError → backoff 지수 증가(1초 즉시 재시도 아님)."""
    ob = object.__new__(FillOutbox)  # _drain stub 이라 실제 DB 불필요.
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # 4회 연속 DB 손상 후 루프 종료(StopIteration).
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed"),
        sqlite3.OperationalError("file is not a database"),
        sqlite3.OperationalError("database disk image is malformed"),
        sqlite3.OperationalError("file is not a database"),
    ]
    harness.install()
    await harness.run()

    # 첫 드레인은 정상 백스톱(drain_interval=1s) 뒤, 이후 간격 = 직전 실패의 backoff.
    intervals = [
        harness.drain_times[i + 1] - harness.drain_times[i]
        for i in range(len(harness.drain_times) - 1)
    ]
    # 1회 실패→×2, 2회→×4, 3회→×8(cap). 고정 1초가 아니라 증가한다.
    assert intervals == [2.0, 4.0, 8.0]
    # 연속 실패 카운터가 누적됐다(reset 안 됨).
    assert publisher._consecutive_failures == 4


async def test_loop_failure_blocks_notify_bypass(eventbus, monkeypatch):
    """(b) 실패 지속 중 notify() 로 깨워도 backoff 우회 즉시 재드레인 안 됨(O5).

    notify() 가 _wakeup 을 set 한 상태로 wait 에서 깨어나도, backoff deadline 이
    미경과면 _wakeup.clear() 후 잔여 backoff 를 재대기해야 한다(즉시 드레인 금지).
    """
    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # 첫 드레인 DB 실패(backoff 진입) → 두 번째 드레인은 backoff 경과 후 성공.
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed"),
        None,
    ]
    harness.install()

    # 첫 드레인 실패 후 backoff(2초) 구간에서 notify() 로 깨어나는 상황을 모사.
    # wait_for 가 wakeup-set 상태로 즉시 반환되도록 토글한다.
    bypass_attempts = {"n": 0}

    async def _fake_wait_for(awaitable, timeout):
        awaitable.close()
        # 첫 실패 이후(backoff 구간) notify 가 set 된 채 깨어남을 1회 모사.
        if publisher._consecutive_failures > 0 and bypass_attempts["n"] == 0:
            bypass_attempts["n"] += 1
            publisher._wakeup.set()  # notify() 효과.
            return None  # 시간 전진 없이 즉시 반환(우회 시도).
        # 그 외엔 backoff/백스톱 만료로 clock 전진 + TimeoutError.
        harness.now += timeout
        raise TimeoutError

    monkeypatch.setattr(asyncio, "wait_for", _fake_wait_for)
    await harness.run()

    # 우회 시도가 발생했으나, notify 로 backoff 중간에 추가 드레인이 끼어들지 않았다.
    # 두 번째 드레인은 backoff deadline(2.0) 경과 후에만 허용됐다(즉시 재드레인 거부).
    assert bypass_attempts["n"] == 1
    assert len(harness.drain_times) == 2
    assert harness.drain_times[1] - harness.drain_times[0] >= 2.0
    # 우회 차단 과정에서 _wakeup 이 소거됐다(다음 정상 사이클에 stale set 잔류 없음).
    assert not publisher._wakeup.is_set()


async def test_loop_escalates_exactly_once_at_threshold(eventbus, monkeypatch):
    """(c) 임계 도달 시 CRITICAL + NotificationEvent(error/system) 정확히 1회(O2)."""
    notifications: list[NotificationEvent] = []

    async def _on_notify(event):
        if isinstance(event, NotificationEvent):
            notifications.append(event)

    eventbus.subscribe(NotificationEvent, _on_notify)

    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # 임계(10) + 임계 초과(2회 더) 연속 실패 → escalation 은 1회만이어야 한다.
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed")
        for _ in range(_ESCALATE_THRESHOLD + 2)
    ]
    harness.install()
    await harness.run()

    assert publisher._consecutive_failures == _ESCALATE_THRESHOLD + 2
    assert publisher._escalated is True
    # 임계 도달·초과에도 NotificationEvent 는 정확히 1회.
    assert len(notifications) == 1
    assert notifications[0].level == "error"
    assert notifications[0].category == "system"


async def test_loop_resets_on_drain_success(eventbus, monkeypatch):
    """(d) 정상 드레인 성공 시 카운터·escalation latch reset, base 주기 복귀."""
    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # 실패 2회 후 성공 1회 → 성공 시점에 카운터 0 으로 reset.
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed"),
        sqlite3.OperationalError("file is not a database"),
        None,  # 성공.
    ]
    harness.install()
    await harness.run()

    assert publisher._consecutive_failures == 0
    assert publisher._escalated is False
    # 성공 드레인(3번째)은 누적 backoff(2회 실패 → ×2, ×4) 경과 후 허용됐다.
    intervals = [
        harness.drain_times[i + 1] - harness.drain_times[i]
        for i in range(len(harness.drain_times) - 1)
    ]
    assert intervals == [2.0, 4.0]


async def test_loop_db_error_no_infinite_immediate_retry(eventbus, monkeypatch):
    """(e) sqlite3.OperationalError(malformed) → 1초 즉시 무한 재시도 부재.

    malformed 표면 타입은 sqlite3.OperationalError(RuntimeError 아님)이며, DB 분기로
    잡혀 backoff 가 걸린다. 동일 드레인이 매 사이클 t 증가 없이(=1초 고정) 반복되지
    않음을 backoff 간격 증가로 락한다.
    """
    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed") for _ in range(5)
    ]
    harness.install()
    await harness.run()

    intervals = [
        harness.drain_times[i + 1] - harness.drain_times[i]
        for i in range(len(harness.drain_times) - 1)
    ]
    # 어떤 간격도 1.0(고정 즉시 재시도)이 아니다 — 전부 backoff 로 늘어났다.
    assert all(iv >= 2.0 for iv in intervals)
    # cap(×8) 도달 후에도 1초로 떨어지지 않는다.
    assert intervals[-1] == publisher._drain_interval * LOOP_BACKOFF_MULTIPLIER_CAP


async def test_loop_non_db_exception_resets_counter(eventbus, monkeypatch):
    """(f) 비-DB 예외는 WARNING + 카운터 reset(은폐 금지, #2350 dual-branch 미러)."""
    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # DB 실패 2회로 카운터·backoff 가 올라간 뒤, 비-DB 예외(RuntimeError) 1회, 그 다음
    # 정상 드레인 1회(reset 후 base 주기로 복귀했는지 관측용).
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed"),
        sqlite3.OperationalError("file is not a database"),
        RuntimeError("internal bug"),
        None,
    ]
    harness.install()
    await harness.run()

    # 비-DB 예외에서 카운터가 0 으로 reset 됐다(은폐 안 함). 최종 성공으로도 0 유지.
    assert publisher._consecutive_failures == 0
    assert publisher._escalated is False
    # 비-DB 예외 직후 다음 드레인은 backoff 가 아닌 base 주기(drain_interval)로 복귀.
    # (비-DB 가 직전 DB 실패 backoff 로 은폐되지 않고 카운터·backoff 해제 — #2350 미러)
    last_interval = harness.drain_times[-1] - harness.drain_times[-2]
    assert last_interval == publisher._drain_interval


# ── _is_db_corruption predicate (#2407 Codex P2) ─────
#
# 손상(reconnect 회복 불가) 시그니처만 backoff/escalation 경로에 태우고, 비-손상
# DatabaseError(transient locked·내부 버그류)는 reset 경로로 보내기 위한 판별기.


def test_is_db_corruption_matches_only_corruption_signatures():
    """손상 시그니처만 True, transient/내부버그/비-DB 는 False.

    ``sqlite3.DatabaseError`` 타입 게이트 + 메시지 substring 매칭을 모두 락한다
    (타입만으로 손상을 판정하지 않는다).
    """
    # database.py:20-23 SSOT 손상 시그니처 → True (대소문자/표현 변형 견고).
    assert _is_db_corruption(
        sqlite3.OperationalError("database disk image is malformed")
    )
    assert _is_db_corruption(sqlite3.DatabaseError("file is not a database"))
    assert _is_db_corruption(sqlite3.OperationalError("FILE IS NOT A DATABASE"))
    assert _is_db_corruption(sqlite3.DatabaseError("MALFORMED database image"))

    # 비-손상 transient (외부 lock — 곧 회복) → False (손상 카운터/backoff 제외).
    assert not _is_db_corruption(sqlite3.OperationalError("database is locked"))
    # 내부 버그류(스키마/쿼리 결함) → False (backoff 로 은폐 금지).
    assert not _is_db_corruption(sqlite3.OperationalError("no such table: fill_outbox"))
    assert not _is_db_corruption(sqlite3.ProgrammingError("bad SQL"))
    # 비-DatabaseError → False (타입 게이트: 메시지에 손상 문구가 있어도 무시).
    assert not _is_db_corruption(RuntimeError("malformed"))
    assert not _is_db_corruption(ValueError("file is not a database"))


def test_db_corruption_signatures_align_with_database_ssot():
    """손상 시그니처가 database.py SSOT 재전파 문구(소문자)와 정합한다.

    database.py:20-23 은 ``database disk image is malformed`` / ``file is not a
    database`` 를 무결성 문제로 재전파한다. 본 predicate 시그니처가 그 문구의
    부분집합(소문자)이어야 손상을 정확히 좁혀 잡는다.
    """
    assert "malformed" in _DB_CORRUPTION_SIGNATURES
    assert "file is not a database" in _DB_CORRUPTION_SIGNATURES
    # database.py SSOT 재전파 문구가 각 시그니처를 포함한다(정합 락).
    assert "malformed" in "database disk image is malformed".lower()
    assert "file is not a database" in "file is not a database".lower()


async def test_loop_transient_locked_not_treated_as_corruption(eventbus, monkeypatch):
    """비-손상 transient ``database is locked`` → 손상 카운터 미누적·backoff 미발생.

    **이번 P2 회귀 락**: 이전에는 모든 ``sqlite3.DatabaseError`` 를 손상으로
    오분류해 ``database is locked``(외부 프로세스/긴 트랜잭션 — transient) 가
    손상 카운터를 누적시키고 backoff 로 notify 를 막았다. 이제 손상 predicate 로
    좁혀, locked 는 비-손상 reset 경로(즉시재시도)로 흘러 notify 즉시성이 보존된다.
    """
    notifications: list[NotificationEvent] = []

    async def _on_notify(event):
        if isinstance(event, NotificationEvent):
            notifications.append(event)

    eventbus.subscribe(NotificationEvent, _on_notify)

    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # locked 를 임계(10) 초과로 반복해도 손상 카운터가 누적되지 않아야 한다.
    harness.drain_outcomes = [
        sqlite3.OperationalError("database is locked")
        for _ in range(_ESCALATE_THRESHOLD + 3)
    ]
    harness.install()
    await harness.run()

    # 손상 카운터 누적 안 됨 + escalation latch 미설정.
    assert publisher._consecutive_failures == 0
    assert publisher._escalated is False
    # 잘못된 DB 손상 알림이 발행되지 않았다.
    assert notifications == []
    # 매 사이클 base 주기(drain_interval)로 즉시 재시도 — backoff escalation 미발생.
    # (notify 즉시성 보존: 손상 backoff 게이팅에 들어가지 않음)
    intervals = [
        harness.drain_times[i + 1] - harness.drain_times[i]
        for i in range(len(harness.drain_times) - 1)
    ]
    assert all(iv == publisher._drain_interval for iv in intervals)


async def test_loop_internal_bug_db_error_resets_counter(eventbus, monkeypatch):
    """내부 버그류 ``no such table``/``ProgrammingError`` → 카운터 reset(은폐 금지).

    비-손상 ``DatabaseError`` 도 backoff/escalation 으로 은폐하지 않고, 선행 손상
    실패 backoff 가 있었다면 reset 해 base 주기로 복귀한다(#2350 dual-branch 미러).
    """
    notifications: list[NotificationEvent] = []

    async def _on_notify(event):
        if isinstance(event, NotificationEvent):
            notifications.append(event)

    eventbus.subscribe(NotificationEvent, _on_notify)

    ob = object.__new__(FillOutbox)
    publisher = FillOutboxPublisher(outbox=ob, eventbus=eventbus, drain_interval=1.0)

    harness = _LoopHarness(publisher, monkeypatch)
    # 손상 2회로 카운터·backoff 가 올라간 뒤, 내부 버그류 DatabaseError(no such table,
    # ProgrammingError) → 카운터 reset, 그 다음 정상 드레인 1회(base 주기 복귀 관측).
    harness.drain_outcomes = [
        sqlite3.OperationalError("database disk image is malformed"),
        sqlite3.OperationalError("file is not a database"),
        sqlite3.OperationalError("no such table: fill_outbox"),
        sqlite3.ProgrammingError("syntax error near SELEKT"),
        None,
    ]
    harness.install()
    await harness.run()

    # 내부 버그류에서 손상 카운터가 0 으로 reset 됐다(은폐 안 함). 최종 성공으로 0 유지.
    assert publisher._consecutive_failures == 0
    assert publisher._escalated is False
    # escalation 미발생(잘못된 손상 알림 없음).
    assert notifications == []
    # 내부 버그류 직후 드레인은 base 주기(drain_interval)로 복귀(backoff 해제 — #2350).
    # drain_times: [손상1, 손상2, nosuchtable, programming, 성공]
    intervals = [
        harness.drain_times[i + 1] - harness.drain_times[i]
        for i in range(len(harness.drain_times) - 1)
    ]
    # 손상1→손상2 = ×2 backoff(2.0), 손상2→nosuchtable = ×4 backoff(4.0, 손상2 시점
    # next_drain_at 기준). nosuchtable·programming 은 reset 후라 매번 base 로 복귀.
    assert intervals[0] == 2.0
    assert intervals[1] == 4.0
    assert intervals[2] == publisher._drain_interval
    assert intervals[3] == publisher._drain_interval
