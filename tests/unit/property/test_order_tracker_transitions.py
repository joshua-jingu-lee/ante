"""OrderTracker 주문 상태 전이의 상태 기반 속성 테스트 (#2769).

주문 상태는 런타임 전이 함수가 없다. 상태를 쓰는 SQL 넷(``open``의 INSERT,
``record_fill``, ``mark_terminal``, ``expire_stale``)과 그 ``WHERE`` 가드가 전부다.
임의의 순서에서 매 걸음 뒤에 DB의 모든 행과 열린 캐시를 본다.

- O1: 행이 바뀐 걸음의 ``(전, 후)`` 상태 쌍이 ``ORDER_STATUS_TRANSITIONS``에 있다.
  새 행은 ``open``으로 생긴다. 행은 사라지지 않는다. ``filled``에서는 나가지 않는다
- R(규칙별 변화): 걸음마다 규칙이 만들 수 있는 변화만 일어난다. 대상이 아닌 행은
  한 열도 바뀌지 않는다. 중복 등록·재시작은 어떤 행도 바꾸지 않는다. 체결은 대상
  행을 누적이 늘 때만 바꾼다. 열린 행은 ``partially_filled``·``filled``로 바꾸고,
  종결된 행은 상태와 ``terminal_at``을 그대로 둔 채 누적·평단·``last_polled_at``만
  바꾼다(#2705). ``mark_terminal``은 대상 행을 요청한 상태로만, ``expire_stale``은
  그 계좌의 기한 지난 ``open`` 행만 ``expired``로 바꾼다. ``mark_terminal``은 열린
  행만 바꾼다
- O2: ``recorded_filled_qty``는 줄지 않고 ``ordered_qty``를 넘지 않는다
- O3: ``terminal_at IS NULL`` ⟺ 상태가 열린 상태(``open``·``partially_filled``)
- O4: 열린 캐시의 주문 집합 == DB의 열린 행 집합, 재시작 뒤에도.
  캐시 레코드의 상태·누적 수량은 DB와 같다
- S: 상태 값은 모든 경로(캐시, ``get``, ``get_open_orders``, ``record_fill``의
  결과)에서 평문 ``str``이다(#2707)

체결의 누적은 브로커의 계약대로 ``ordered_qty`` 이하로 만든다. 그보다 작거나 같은
누적(비증가)도 넣는다. O2의 알려진 한계: 주문 수량을 넘는 누적은 생성하지 않는다.
``record_fill``은 넘는 누적을 clamp하지 않고 그대로 저장하고 ``filled``로 쓴다 —
이 경로는 탐색 밖이다. 거부는 정상 결과다(``record_fill``의 no-op, 중복 ``open``의
무시, 비종결 상태를 준 ``mark_terminal``의 ``ValueError``).
"""

from __future__ import annotations

import asyncio
import itertools
import shutil
import tempfile
from collections.abc import Coroutine
from pathlib import Path
from typing import Any, TypeVar

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, invariant, precondition, rule

from ante.core.database import Database
from ante.trade.order_tracker import (
    OPEN_STATUSES,
    ORDER_STATUS_TRANSITIONS,
    TERMINAL_STATUSES,
    OrderStatus,
    OrderTracker,
    OrderTrackerRecord,
)

T = TypeVar("T")

ACCOUNT_ID = "domestic"
BOTS = ("bot-a", "bot-b")
DAYS = ("2026-11-20", "2026-11-21", "2026-11-22", "2026-11-23")
OPEN = {s.value for s in OPEN_STATUSES}
TERMINAL = {s.value for s in TERMINAL_STATUSES}
# ``mark_terminal``의 런타임 호출자(``main.py``의 ``_on_terminal``)가 주는 상태와,
# 거부되어야 할 비종결 상태. ``filled``·``expired``도 받지만 호출자가 없다.
MARK_STATUSES = ("cancelled", "rejected", "failed", "open", "partially_filled")
ALLOWED = {
    (a.value, b.value) for a, nexts in ORDER_STATUS_TRANSITIONS.items() for b in nexts
}

Row = dict[str, Any]
# 규칙이 대상 행에서 바꿀 수 있는 열.
STATUS_COLUMNS = {"status", "terminal_at"}
LATE_FILL_COLUMNS = {"recorded_filled_qty", "avg_fill_price", "last_polled_at"}
FILL_COLUMNS = STATUS_COLUMNS | LATE_FILL_COLUMNS


class OrderTrackerMachine(RuleBasedStateMachine):
    """한 계좌의 OrderTracker에 등록·체결·종결·만료·재시작을 임의 순서로 건다."""

    def __init__(self) -> None:
        super().__init__()
        self._tmp = Path(tempfile.mkdtemp(prefix="ante-prop-tracker-"))
        self._runner = asyncio.Runner()
        self._db = Database(str(self._tmp / "tracker.db"))
        self._run(self._db.connect())
        self._seq = itertools.count()
        self.ordered: dict[str, int] = {}
        self.rows: dict[str, Row] = {}
        self.touched: set[str] = set()
        self.steps = 0
        self.last_restart = 0
        self.last_expire = 0
        self.tracker = self._boot()

    # ── 대역 ────────────────────────────────────────────────────────

    def _run(self, coro: Coroutine[Any, Any, T]) -> T:
        return self._runner.run(coro)

    def _boot(self) -> OrderTracker:
        tracker = OrderTracker(db=self._db)
        self._run(tracker.initialize())
        return tracker

    def teardown(self) -> None:
        try:
            self._run(self._db.close())
        finally:
            self._runner.close()
            shutil.rmtree(self._tmp, ignore_errors=True)

    def _fetch_rows(self) -> dict[str, Row]:
        rows = self._run(self._db.fetch_all("SELECT * FROM order_tracker"))
        return {r["order_id"]: dict(r) for r in rows}

    def _observe(self, via: str, target: str | None = None, **expect: Any) -> None:
        """걸음 하나의 끝. 이전 스냅숏과 견줘 O1·O2·R을 보고 스냅숏을 바꾼다.

        ``via``는 규칙의 종류, ``target``은 그 규칙의 대상 주문이다.
        """
        after = self._fetch_rows()
        assert after.keys() >= self.rows.keys(), "O1: 행이 사라졌다"
        for oid, row in after.items():
            prev = self.rows.get(oid)
            if prev is None:
                assert via == "open" and oid == target, f"R: {via}가 새 행 {oid}"
                assert row["status"] == OrderStatus.OPEN, f"O1: 새 행 {row}"
                continue
            if row == prev:
                continue
            b, a = prev["status"], row["status"]
            assert row["recorded_filled_qty"] >= prev["recorded_filled_qty"], (
                f"O2: {oid} 누적이 줄었다 {prev} -> {row}"
            )
            advanced = row["recorded_filled_qty"] > prev["recorded_filled_qty"]
            if b != a or advanced:
                assert (b, a) in ALLOWED, f"O1: {oid} {b} -> {a} ({via})"
            assert b != OrderStatus.FILLED or a == b, f"O1: filled에서 나갔다 {oid}"
            self._check_rule_change(via, target, oid, prev, row, expect)
        self.touched = {o for o, r in after.items() if self.rows.get(o) != r}
        self.rows = after
        self.steps += 1

    @staticmethod
    def _check_rule_change(
        via: str, target: str | None, oid: str, prev: Row, row: Row, expect: Any
    ) -> None:
        """R: 바뀐 행 하나가 그 걸음의 규칙이 만들 수 있는 변화인가."""
        changed = {k for k in row if row[k] != prev[k]}
        where = f"R: {via} {oid} {prev['status']} -> {row['status']} {sorted(changed)}"
        if via == "fill":
            assert oid == target, where
            assert row["recorded_filled_qty"] > prev["recorded_filled_qty"], where
            if prev["status"] in OPEN:
                assert row["status"] in {"partially_filled", "filled"}, where
                assert changed <= FILL_COLUMNS, where
            else:
                assert changed <= LATE_FILL_COLUMNS, where
        elif via == "mark_terminal":
            assert oid == target and expect["status"] in TERMINAL, where
            assert prev["status"] in OPEN, where
            assert row["status"] == expect["status"], where
            assert changed <= STATUS_COLUMNS, where
        elif via == "expire_stale":
            assert row["account_id"] == expect["account"], where
            assert prev["status"] == OrderStatus.OPEN, where
            assert prev["submitted_date"] < expect["before_date"], where
            assert row["status"] == OrderStatus.EXPIRED, where
            assert changed <= STATUS_COLUMNS, where
        else:
            # 등록(기존 행)·중복 등록·재시작은 어떤 행도 바꾸지 않는다.
            raise AssertionError(where)

    # ── 규칙 ────────────────────────────────────────────────────────

    @rule(
        bot=st.sampled_from(BOTS),
        spec=st.tuples(st.integers(1, 5), st.sampled_from(DAYS)),
    )
    def open_order(self, bot: str, spec: tuple[int, str]) -> None:
        """새 주문의 seed(``OrderSubmittedEvent``)."""
        qty, day = spec
        order_id = f"ord-{next(self._seq)}"
        self._open(order_id, bot, qty, day)
        self.ordered[order_id] = qty
        self._observe("open", order_id)

    def _open(self, order_id: str, bot: str, qty: int, day: str) -> None:
        self._run(
            self.tracker.open(
                order_id=order_id,
                account_id=ACCOUNT_ID,
                bot_id=bot,
                strategy_id="s1",
                broker_order_id=f"bk-{order_id}",
                symbol="005930",
                side="buy",
                order_type="limit",
                ordered_qty=float(qty),
                submitted_date=day,
            )
        )

    @precondition(lambda self: bool(self.ordered))
    @rule(data=st.data())
    def reopen_order(self, data: st.DataObject) -> None:
        """같은 주문 id의 중복 seed. 무시된다(행과 캐시가 그대로)."""
        order_id = data.draw(st.sampled_from(sorted(self.ordered)), "order")
        row = self.rows[order_id]
        before = self._cache_view()
        self._open(order_id, row["bot_id"], 1, row["submitted_date"])
        assert self._cache_view() == before, "중복 seed가 캐시를 바꿨다"
        self._observe("reopen")
        assert self.rows[order_id] == row, "중복 seed가 행을 바꿨다"

    @precondition(lambda self: bool(self.ordered))
    @rule(data=st.data())
    def fill(self, data: st.DataObject) -> None:
        """FillApplier의 순서: 트랜잭션 안의 ``record_fill`` → 증분이 있으면 미러.

        종결된 주문에도 건다(취소·체결의 경합).
        """
        order_id = data.draw(st.sampled_from(sorted(self.ordered)), "order")
        cumulative = data.draw(st.integers(0, self.ordered[order_id]), "cumulative")

        async def apply() -> Any:
            async with self._db.transaction():
                return await self.tracker.record_fill(
                    order_id, float(cumulative), 1000.0
                )

        result = self._run(apply())
        assert type(result.new_status) is str, f"S: {result!r}"
        if result.delta > 0:
            self.tracker.mirror_fill_to_cache(
                order_id, result.confirmed_cumulative, result.new_status
            )
        self._observe("fill", order_id)

    @precondition(lambda self: bool(self.ordered))
    @rule(data=st.data(), status=st.sampled_from(MARK_STATUSES))
    def mark_terminal(self, data: st.DataObject, status: str) -> None:
        """취소·거절·실패의 표기. 비종결 상태를 주면 ``ValueError``로 거부된다."""
        order_id = data.draw(st.sampled_from(sorted(self.ordered)), "order")
        if status in TERMINAL:
            self._run(self.tracker.mark_terminal(order_id, status))
        else:
            with pytest.raises(ValueError):
                self._run(self.tracker.mark_terminal(order_id, status))
        self._observe("mark_terminal", order_id, status=status)

    # 전제가 없으면 걸음의 6할이 만료였다(전제가 없는 규칙을 hypothesis가 자주 고른다).
    @precondition(lambda self: self.steps - self.last_expire >= 3)
    @rule(before_date=st.sampled_from(DAYS), own=st.booleans())
    def expire_stale(self, before_date: str, own: bool) -> None:
        """장 마감 만료. 다른 계좌를 주면 이 계좌의 행은 그대로다."""
        account = ACCOUNT_ID if own else "overseas"
        count = self._run(self.tracker.expire_stale(account, before_date))
        self.last_expire = self.steps
        prev = self.rows
        self._observe("expire_stale", account=account, before_date=before_date)
        expired = [o for o, r in self.rows.items() if prev[o]["status"] != r["status"]]
        assert count == len(expired), f"만료 건수 {count} != {expired}"
        if not own:
            assert expired == [], f"다른 계좌의 만료가 이 계좌를 바꿨다 {expired}"
        else:
            left = [
                o
                for o, r in self.rows.items()
                if r["status"] == OrderStatus.OPEN and r["submitted_date"] < before_date
            ]
            assert left == [], f"만료되지 않은 open {left}"
        for o in expired:
            assert prev[o]["status"] == OrderStatus.OPEN, f"{o}: open이 아닌 행"
            assert prev[o]["submitted_date"] < before_date
            assert self.rows[o]["status"] == OrderStatus.EXPIRED

    # 인자 없는 규칙은 hypothesis가 자주 고른다. 전제로 빈도를 누른다.
    @precondition(lambda self: self.steps - self.last_restart >= 5)
    @rule()
    def restart(self) -> None:
        """같은 DB로 새 OrderTracker를 올린다. 캐시는 DB에서 다시 적재된다."""
        self.tracker = self._boot()
        self.last_restart = self.steps
        self._observe("restart")

    # ── 불변식 ──────────────────────────────────────────────────────

    def _cache_view(self) -> dict[str, tuple[str, float]]:
        records: list[OrderTrackerRecord] = []
        for bot in BOTS:
            records += self.tracker.get_open_orders_for_bot_sync(ACCOUNT_ID, bot)
        for r in records:
            assert type(r.status) is str, f"S: 캐시 {r!r}"
        return {r.order_id: (r.status, r.recorded_filled_qty) for r in records}

    @invariant()
    def o2_quantity_bounds(self) -> None:
        for oid, row in self.rows.items():
            assert 0 <= row["recorded_filled_qty"] <= row["ordered_qty"], f"O2: {oid}"

    @invariant()
    def o3_terminal_at(self) -> None:
        for oid, row in self.rows.items():
            assert (row["terminal_at"] is None) == (row["status"] in OPEN), (
                f"O3: {oid} {row['status']} terminal_at={row['terminal_at']}"
            )

    @invariant()
    def o4_open_cache(self) -> None:
        cache = self._cache_view()
        db_open = {o: r for o, r in self.rows.items() if r["status"] in OPEN}
        assert cache.keys() == db_open.keys(), (
            f"O4: 캐시 {sorted(cache)} DB {sorted(db_open)}"
        )
        for oid, (status, qty) in cache.items():
            row = db_open[oid]
            assert (status, qty) == (row["status"], row["recorded_filled_qty"]), (
                f"O4: {oid} 캐시 {(status, qty)} DB {row}"
            )

    @invariant()
    def s_plain_str_status(self) -> None:
        # 모든 행의 ``get``은 걸음마다 행 수만큼의 조회라 바뀐 행만 본다.
        for oid in self.touched:
            record = self._run(self.tracker.get(oid))
            assert record is not None and type(record.status) is str, f"S: {record!r}"
        for record in self._run(self.tracker.get_open_orders(ACCOUNT_ID)):
            assert type(record.status) is str, f"S: {record!r}"


TestOrderTrackerMachine = OrderTrackerMachine.TestCase
TestOrderTrackerMachine.settings = settings()


# ── 기계가 찾은 결함의 최소 순서 ───────────────────────────────────
#
# 각 테스트의 xfail은 마지막 단언의 AssertionError만 받는다. 준비 단계의 이상은
# pytest.fail(Failed)로 내 xfail에 흡수되지 않게 한다.


async def _tracker_with_order(
    tmp_path: Path, qty: float
) -> tuple[Database, OrderTracker]:
    db = Database(str(tmp_path / "tracker.db"))
    await db.connect()
    tracker = OrderTracker(db=db)
    await tracker.initialize()
    await tracker.open(
        order_id="ord-0",
        account_id=ACCOUNT_ID,
        bot_id="bot-a",
        strategy_id="s1",
        broker_order_id="bk-ord-0",
        symbol="005930",
        side="buy",
        order_type="limit",
        ordered_qty=qty,
        submitted_date=DAYS[0],
    )
    return db, tracker


async def _status(tracker: OrderTracker) -> str:
    record = await tracker.get("ord-0")
    if record is None:
        pytest.fail("준비: 주문 행이 없다")
    return record.status


async def test_fill_after_cancel_keeps_open_cache_in_sync(tmp_path: Path) -> None:
    """취소된 주문에 체결이 와도 열린 캐시와 DB의 열린 상태가 일치한다(O4).

    최소 순서: 등록(수량 2) → 취소 → 누적 1의 체결(FillApplier의 순서). 체결 반영은
    종결된 행을 되살리지 않으므로(#2705) 그 주문은 DB에서도 캐시에서도 열려 있지 않다.
    """
    db, tracker = await _tracker_with_order(tmp_path, 2.0)
    try:
        await tracker.mark_terminal("ord-0", "cancelled")
        async with db.transaction():
            result = await tracker.record_fill("ord-0", 1.0, 1000.0)
        tracker.mirror_fill_to_cache(
            "ord-0", result.confirmed_cumulative, result.new_status
        )
        status = await _status(tracker)
        if result.delta != 1.0:
            pytest.fail(f"준비: 체결이 반영되지 않았다 {result!r}")

        cached = tracker.get_open_orders_for_bot_sync(ACCOUNT_ID, "bot-a")
        in_cache = "ord-0" in {r.order_id for r in cached}
        assert in_cache == (status in OPEN), f"캐시 {in_cache}, DB {status}"
        assert (status, in_cache) == ("cancelled", False)
    finally:
        await db.close()


async def test_terminal_status_is_not_overwritten(tmp_path: Path) -> None:
    """종결된 주문은 다른 종결 상태로 바뀌지 않는다.

    최소 순서: 등록 → 취소 → 거절. 첫 종결이 이긴다 — 상태도 ``terminal_at``도
    그대로다. ``terminal_at``은 초 단위라 센티널로 바꿔 두고 행 전체를 비교한다.
    """
    db, tracker = await _tracker_with_order(tmp_path, 2.0)
    try:
        await tracker.mark_terminal("ord-0", "cancelled")
        if await _status(tracker) != "cancelled":
            pytest.fail("준비: 취소가 반영되지 않았다")
        await db.execute(
            "UPDATE order_tracker SET terminal_at = ? WHERE order_id = ?",
            ("2000-01-01 00:00:00", "ord-0"),
        )
        query = "SELECT * FROM order_tracker WHERE order_id = ?"
        before = await db.fetch_one(query, ("ord-0",))
        await tracker.mark_terminal("ord-0", "rejected")

        assert await _status(tracker) == "cancelled"
        assert await db.fetch_one(query, ("ord-0",)) == before
    finally:
        await db.close()
