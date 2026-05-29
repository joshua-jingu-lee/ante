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
