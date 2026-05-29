"""OrderTracker 단위 테스트 (#1946).

record_fill 단조·멱등·동시, composite lookup 격리(account/date), EOD 만료.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.core.database import Database
from ante.trade.order_tracker import OrderTracker

# ── Fixtures ─────────────────────────────────────────


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


async def _seed(
    tracker: OrderTracker,
    *,
    order_id: str = "ord-1",
    account_id: str = "acct-A",
    broker_order_id: str = "0001",
    submitted_date: str = "20260529",
    ordered_qty: float = 100.0,
    side: str = "buy",
) -> None:
    await tracker.open(
        order_id=order_id,
        account_id=account_id,
        bot_id="bot-1",
        strategy_id="strat-1",
        broker_order_id=broker_order_id,
        symbol="005930",
        side=side,
        order_type="market",
        ordered_qty=ordered_qty,
        submitted_date=submitted_date,
    )


# ── record_fill 단조·멱등 ─────────────────────────────


async def test_record_fill_first_advance(tracker):
    await _seed(tracker)
    # #1949: record_fill 은 RecordFillResult(delta, confirmed_cumulative) 반환.
    result = await tracker.record_fill("ord-1", 40.0, 1000.0)
    assert result.delta == 40.0
    # confirmed_cumulative 는 CAS RETURNING 확정값(= 입력 누적값과 일치).
    assert result.confirmed_cumulative == 40.0
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 40.0
    assert rec.status == "partially_filled"


async def test_record_fill_same_cumulative_twice_delta_zero(tracker):
    """같은 누적 2회 → 첫 회만 delta, 둘째는 0 (멱등)."""
    await _seed(tracker)
    first = await tracker.record_fill("ord-1", 40.0, 1000.0)
    second = await tracker.record_fill("ord-1", 40.0, 1000.0)
    assert first.delta == 40.0
    assert second.delta == 0.0
    # no-op 의 confirmed_cumulative 는 직전 확정값(40)을 그대로 반영 → 결정적 키.
    assert second.confirmed_cumulative == 40.0
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 40.0


async def test_record_fill_monotonic_increase(tracker):
    """누적 증가 → 정확한 delta (40 → 100: delta 60)."""
    await _seed(tracker)
    await tracker.record_fill("ord-1", 40.0, 1000.0)
    result = await tracker.record_fill("ord-1", 100.0, 1010.0)
    assert result.delta == 60.0
    assert result.confirmed_cumulative == 100.0
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 100.0
    # ordered_qty(100) 도달 → filled.
    assert rec.status == "filled"


async def test_record_fill_decrease_is_noop(tracker):
    """관측 역전(누적 감소) → 단조성 유지, no-op."""
    await _seed(tracker)
    await tracker.record_fill("ord-1", 100.0, 1000.0)
    result = await tracker.record_fill("ord-1", 60.0, 990.0)
    assert result.delta == 0.0
    # 역전 no-op 의 확정값은 직전 누적(100) — 재전달 키 결정성 유지.
    assert result.confirmed_cumulative == 100.0
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 100.0


async def test_record_fill_unknown_order_returns_zero(tracker):
    result = await tracker.record_fill("does-not-exist", 50.0, 1000.0)
    assert result.delta == 0.0
    assert result.confirmed_cumulative == 0.0


async def test_record_fill_concurrent_no_double(tracker):
    """동시 호출(같은 누적) → 단조성으로 중복 advance 없음.

    FillApplier 의 Lock 없이도 OrderTracker CAS(WHERE recorded < :c) 가 단조성을
    보장하는지 확인한다. 누적 합은 정확히 60.
    """
    await _seed(tracker)
    results = await asyncio.gather(
        tracker.record_fill("ord-1", 60.0, 1000.0),
        tracker.record_fill("ord-1", 60.0, 1000.0),
        tracker.record_fill("ord-1", 60.0, 1000.0),
    )
    # 정확히 한 호출만 delta>0(=60), 나머지는 0.
    positive = [r.delta for r in results if r.delta > 0]
    assert positive == [60.0]
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 60.0


# ── composite lookup 격리 ────────────────────────────


async def test_lookup_isolates_by_account(tracker):
    """같은 broker_order_id 라도 account 가 다르면 격리."""
    await _seed(tracker, order_id="ord-A", account_id="acct-A", broker_order_id="X")
    await _seed(tracker, order_id="ord-B", account_id="acct-B", broker_order_id="X")
    assert await tracker.lookup_order_id("acct-A", "X", "20260529") == "ord-A"
    assert await tracker.lookup_order_id("acct-B", "X", "20260529") == "ord-B"


async def test_lookup_isolates_by_date(tracker):
    """같은 account+broker_order_id 라도 영업일이 다르면 격리 (일자 재사용)."""
    await _seed(
        tracker, order_id="ord-old", broker_order_id="0001", submitted_date="20260528"
    )
    # 전날 주문을 종료시킨 뒤, 같은 odno 로 오늘 신규 주문.
    await tracker.mark_terminal("ord-old", "filled")
    await _seed(
        tracker, order_id="ord-new", broker_order_id="0001", submitted_date="20260529"
    )
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") == "ord-new"
    # 종료된 전날 주문은 매핑 대상에서 제외 (terminal scope).
    assert await tracker.lookup_order_id("acct-A", "0001", "20260528") is None


async def test_lookup_excludes_terminal(tracker):
    await _seed(tracker, order_id="ord-1", broker_order_id="0001")
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") == "ord-1"
    await tracker.mark_terminal("ord-1", "cancelled")
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") is None


async def test_lookup_matches_prior_day_open_with_later_observation(tracker):
    """spec §4.1 (I6): 전일 seed 된 non-terminal 주문을 당일 관측(observed_date)
    으로 매핑한다 (``submitted_date <= observed_date``).

    전일 open 이 다운타임 중 체결돼 당일 history(ord_dt) 로 관측될 때, 정확매칭
    이면 누락되어 복구가 실패한다. ``<=`` 완화가 이 케이스를 덮는다.
    """
    await _seed(
        tracker, order_id="ord-prior", broker_order_id="0001", submitted_date="20260528"
    )
    # 당일(또는 이후) 영업일로 관측 — 전일 open 이 매핑돼야 한다.
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") == "ord-prior"
    assert await tracker.lookup_order_id("acct-A", "0001", "20260528") == "ord-prior"


async def test_lookup_excludes_future_submitted(tracker):
    """``submitted_date > observed_date`` 인(미래 영업일 seed) 주문은 배제한다.

    일자 재사용 격리: 관측 영업일보다 미래에 seed 된 동일 odno 주문이 현재
    관측에 매핑되지 않게 한다.
    """
    await _seed(
        tracker,
        order_id="ord-future",
        broker_order_id="0001",
        submitted_date="20260530",
    )
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") is None


async def test_lookup_prefers_latest_nonterminal_on_reuse(tracker):
    """같은 odno 의 non-terminal 이 여러 영업일에 동시 존재하면 ``submitted_date``
    최신(MAX) 1건을 결정론적으로 고른다 ("가장 최근 주문 우선").
    """
    await _seed(
        tracker, order_id="ord-old", broker_order_id="0001", submitted_date="20260528"
    )
    await _seed(
        tracker, order_id="ord-new", broker_order_id="0001", submitted_date="20260529"
    )
    # 둘 다 non-terminal·관측일 이하 → 최신(20260529) 우선.
    assert await tracker.lookup_order_id("acct-A", "0001", "20260529") == "ord-new"


# ── open / terminal ──────────────────────────────────


async def test_open_is_idempotent(tracker):
    """같은 order_id seed 2회 → 멱등 (ON CONFLICT DO NOTHING)."""
    await _seed(tracker, order_id="ord-1")
    await tracker.record_fill("ord-1", 30.0, 1000.0)
    # 재제출(중복 OrderSubmittedEvent) — recorded 를 0 으로 리셋하면 안 됨.
    await _seed(tracker, order_id="ord-1")
    rec = await tracker.get("ord-1")
    assert rec.recorded_filled_qty == 30.0


async def test_mark_terminal_preserves_filled(tracker):
    """이미 filled 인 주문은 terminal 로 덮어쓰지 않는다."""
    await _seed(tracker, ordered_qty=100.0)
    await tracker.record_fill("ord-1", 100.0, 1000.0)
    assert (await tracker.get("ord-1")).status == "filled"
    await tracker.mark_terminal("ord-1", "cancelled")
    assert (await tracker.get("ord-1")).status == "filled"


async def test_mark_terminal_rejects_non_terminal_status(tracker):
    await _seed(tracker)
    with pytest.raises(ValueError):
        await tracker.mark_terminal("ord-1", "open")


async def test_get_open_orders_scoped(tracker):
    await _seed(tracker, order_id="ord-1", account_id="acct-A", broker_order_id="1")
    await _seed(tracker, order_id="ord-2", account_id="acct-A", broker_order_id="2")
    await _seed(tracker, order_id="ord-3", account_id="acct-B", broker_order_id="3")
    await tracker.mark_terminal("ord-2", "cancelled")
    open_a = await tracker.get_open_orders("acct-A")
    assert {o.order_id for o in open_a} == {"ord-1"}
    open_b = await tracker.get_open_orders("acct-B")
    assert {o.order_id for o in open_b} == {"ord-3"}


# ── EOD 만료 ─────────────────────────────────────────


async def test_expire_stale(tracker):
    """submitted_date < before_date 인 open → expired."""
    await _seed(
        tracker, order_id="ord-old", broker_order_id="1", submitted_date="20260528"
    )
    await _seed(
        tracker, order_id="ord-today", broker_order_id="2", submitted_date="20260529"
    )
    count = await tracker.expire_stale("acct-A", before_date="20260529")
    assert count == 1
    assert (await tracker.get("ord-old")).status == "expired"
    assert (await tracker.get("ord-today")).status == "open"


async def test_expire_stale_no_open(tracker):
    count = await tracker.expire_stale("acct-A", before_date="20260529")
    assert count == 0


async def test_expire_stale_excludes_partially_filled(tracker):
    """spec §8 (I2): EOD 경과해도 부분 체결(partially_filled)은 만료하지 않는다.

    체결이 관측·진행 중인 주문은 genuinely-dead 가 아니다. ``open`` 상태만
    만료 대상이다 (poll-first 복구로 partially_filled 가 된 다운타임 체결분이
    이어서 만료/오분류되지 않게 보장).
    """
    # 전일 seed 후 부분 체결로 partially_filled 전이.
    await _seed(
        tracker,
        order_id="ord-partial",
        broker_order_id="0001",
        submitted_date="20260528",
        ordered_qty=100.0,
    )
    result = await tracker.record_fill("ord-partial", 40.0, 1000.0)
    assert result.delta == 40.0
    assert (await tracker.get("ord-partial")).status == "partially_filled"

    # 전일 genuinely-dead open (체결 없음) 도 함께 둔다.
    await _seed(
        tracker, order_id="ord-dead", broker_order_id="0002", submitted_date="20260528"
    )

    count = await tracker.expire_stale("acct-A", before_date="20260529")
    # open 인 ord-dead 만 만료. partially_filled 는 제외.
    assert count == 1
    assert (await tracker.get("ord-partial")).status == "partially_filled"
    assert (await tracker.get("ord-dead")).status == "expired"


# ── #1948: sync open 캐시 + LIVE get_open_orders 백엔드 ──────


def _open_ids(tracker, account_id="acct-A", bot_id="bot-1"):
    return [
        r.order_id for r in tracker.get_open_orders_for_bot_sync(account_id, bot_id)
    ]


async def test_open_seeds_sync_cache(tracker):
    """open() 후 sync 캐시에 즉시 노출."""
    await _seed(tracker)
    assert _open_ids(tracker) == ["ord-1"]


async def test_duplicate_open_event_single_cache_entry(tracker):
    """중복 OrderSubmittedEvent(open) 2회 → 캐시 단일 entry (blind insert 회귀 락)."""
    await _seed(tracker)
    # 첫 체결로 캐시를 advance.
    await tracker.record_fill("ord-1", 40.0, 1000.0)
    tracker.mirror_fill_to_cache("ord-1", 40.0, "partially_filled")
    # 중복 open 이벤트(ON CONFLICT DO NOTHING — DB 미변경) 재수신.
    await _seed(tracker)
    records = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    assert len(records) == 1
    # 중복 open 이 advance 된 캐시(40)를 blind 하게 0 으로 덮어쓰지 않음.
    assert records[0].recorded_filled_qty == 40.0


async def test_record_fill_alone_does_not_touch_cache(tracker):
    """record_fill 단독 호출은 캐시 미변경 (캐시는 mirror_fill_to_cache 로만)."""
    await _seed(tracker)
    result = await tracker.record_fill("ord-1", 100.0, 1000.0)  # filled
    assert result.delta == 100.0
    assert result.new_status == "filled"
    # record_fill 만으로는 캐시가 그대로 — 여전히 open, recorded=0.
    records = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    assert len(records) == 1
    assert records[0].recorded_filled_qty == 0.0
    assert records[0].status == "open"


async def test_mirror_fill_partial_then_filled_evicts(tracker):
    """mirror_fill_to_cache: partial 은 미러, filled 는 evict."""
    await _seed(tracker)
    # partial 미러.
    await tracker.record_fill("ord-1", 40.0, 1000.0)
    tracker.mirror_fill_to_cache("ord-1", 40.0, "partially_filled")
    recs = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    assert len(recs) == 1
    assert recs[0].recorded_filled_qty == 40.0
    assert recs[0].status == "partially_filled"
    # filled 미러 → evict.
    await tracker.record_fill("ord-1", 100.0, 1010.0)
    tracker.mirror_fill_to_cache("ord-1", 100.0, "filled")
    assert _open_ids(tracker) == []


async def test_mark_terminal_evicts_cache(tracker):
    """mark_terminal 후 sync 조회에서 제외."""
    await _seed(tracker)
    assert _open_ids(tracker) == ["ord-1"]
    await tracker.mark_terminal("ord-1", "cancelled")
    assert _open_ids(tracker) == []


async def test_expire_stale_evicts_cache(tracker):
    """expire_stale 후 만료 주문 sync 미노출 (batch evict)."""
    await _seed(
        tracker, order_id="ord-old", broker_order_id="0009", submitted_date="20260528"
    )
    await _seed(
        tracker, order_id="ord-new", broker_order_id="0010", submitted_date="20260529"
    )
    assert sorted(_open_ids(tracker)) == ["ord-new", "ord-old"]
    count = await tracker.expire_stale("acct-A", before_date="20260529")
    assert count == 1
    # 만료된 ord-old 는 캐시에서 제거, ord-new 는 유지.
    assert _open_ids(tracker) == ["ord-new"]


async def test_expire_stale_returning_does_not_evict_non_open(tracker):
    """#1948 회귀: expire_stale 은 실제 open→expired 된 주문만 evict 한다.

    pre-SELECT→별도 UPDATE 구조였을 때는 SELECT↔UPDATE 사이에 fill 이 commit 돼
    open→partially_filled 로 전이되면, ``UPDATE … WHERE status='open'`` 은 그
    주문을 건드리지 않는데도 pre-SELECT 결과로 캐시에서 evict 되어 여전히 open(
    partial)인 주문이 sync 캐시에서 사라지는 TOCTOU race 가 있었다(캐시=commit 된
    DB open 미러 invariant 위반). UPDATE … RETURNING 단일 원자 연산으로 바꿔
    실제 expired 된 order_id 만 evict 하므로, 비-open 주문은 evict 후보에 구조적으로
    들어갈 수 없다.

    검증: 전일 ``open`` 1건 + 전일 ``partially_filled`` 1건(캐시에 미러)을 두고
    expire_stale 호출 시 — (a) count 는 open→expired 된 건수만, (b) partially_filled
    는 evict 되지 않고 sync 에 계속 노출(partially_filled ∈ OPEN_STATUSES), (c)
    expired 된 open 만 sync 에서 사라진다.
    """
    # 전일 open (genuinely-dead — 체결 없음).
    await _seed(
        tracker, order_id="ord-open", broker_order_id="0101", submitted_date="20260528"
    )
    # 전일 partially_filled — fill 이 관측·commit 되어 비-open 으로 전이된 주문.
    # record_fill(DB advance) 후 mirror_fill_to_cache(commit 직후 캐시 미러).
    await _seed(
        tracker,
        order_id="ord-partial",
        broker_order_id="0102",
        submitted_date="20260528",
        ordered_qty=100.0,
    )
    result = await tracker.record_fill("ord-partial", 40.0, 1000.0)
    assert result.new_status == "partially_filled"
    tracker.mirror_fill_to_cache("ord-partial", 40.0, "partially_filled")

    # 사전: 두 주문 모두 sync 캐시에 노출(open + partially_filled).
    assert sorted(_open_ids(tracker)) == ["ord-open", "ord-partial"]

    count = await tracker.expire_stale("acct-A", before_date="20260529")

    # (a) open → expired 된 1건만 count.
    assert count == 1
    # DB 상태: open 만 expired, partially_filled 는 보존.
    assert (await tracker.get("ord-open")).status == "expired"
    assert (await tracker.get("ord-partial")).status == "partially_filled"
    # (b)+(c) partially_filled 는 캐시 잔존(sync 노출), expired open 만 사라짐.
    assert _open_ids(tracker) == ["ord-partial"]
    # partially_filled 미러값(recorded=40)도 보존 — blind evict 흔적 없음.
    recs = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    assert len(recs) == 1
    assert recs[0].order_id == "ord-partial"
    assert recs[0].recorded_filled_qty == 40.0


async def test_sync_cache_account_bot_scope(tracker):
    """(account_id, bot_id) 스코프 — 타 account/bot 누출 없음."""
    await _seed(tracker, order_id="a1", account_id="acct-A", broker_order_id="0001")
    await _seed(tracker, order_id="b1", account_id="acct-B", broker_order_id="0002")
    # 타-봇 주문(다른 bot_id) 직접 open.
    await tracker.open(
        order_id="other-bot",
        account_id="acct-A",
        bot_id="bot-2",
        strategy_id="s",
        broker_order_id="0003",
        symbol="005930",
        side="buy",
        order_type="market",
        ordered_qty=10.0,
        submitted_date="20260529",
    )
    assert _open_ids(tracker, "acct-A", "bot-1") == ["a1"]
    assert _open_ids(tracker, "acct-B", "bot-1") == ["b1"]
    assert _open_ids(tracker, "acct-A", "bot-2") == ["other-bot"]


async def test_to_open_order_dict_schema(tracker):
    """통일 OpenOrder dict 스키마 + remaining_qty."""
    await _seed(tracker, ordered_qty=100.0)
    await tracker.record_fill("ord-1", 30.0, 1000.0)
    tracker.mirror_fill_to_cache("ord-1", 30.0, "partially_filled")
    recs = tracker.get_open_orders_for_bot_sync("acct-A", "bot-1")
    d = recs[0].to_open_order_dict()
    assert set(d.keys()) == {
        "order_id",
        "symbol",
        "side",
        "ordered_qty",
        "recorded_filled_qty",
        "remaining_qty",
        "status",
        "submitted_at",
    }
    assert "amount" not in d
    assert d["ordered_qty"] == 100.0
    assert d["recorded_filled_qty"] == 30.0
    assert d["remaining_qty"] == 70.0


async def test_warm_open_cache_from_db(db):
    """initialize() 가 DB 의 open/partially_filled 를 캐시에 warm."""
    # 1st tracker 로 DB 에 주문 seed + 부분 체결.
    t1 = OrderTracker(db)
    await t1.initialize()
    await _seed(t1, order_id="ord-open", broker_order_id="0001")
    await _seed(t1, order_id="ord-part", broker_order_id="0002")
    await t1.record_fill("ord-part", 40.0, 1000.0)
    t1.mirror_fill_to_cache("ord-part", 40.0, "partially_filled")
    await _seed(t1, order_id="ord-done", broker_order_id="0003")
    await t1.record_fill("ord-done", 100.0, 1000.0)  # filled (DB)
    t1.mirror_fill_to_cache("ord-done", 100.0, "filled")

    # 새 tracker 가 동일 DB 로 warm — terminal(filled) 제외, open/partial 만.
    t2 = OrderTracker(db)
    await t2.initialize()
    ids = sorted(_open_ids(t2))
    assert ids == ["ord-open", "ord-part"]
