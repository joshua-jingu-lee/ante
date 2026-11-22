"""OrderTracker 주문 상태 전이의 상태 기반 속성 테스트 (#2769).

주문 상태는 런타임 전이 함수가 없다. 상태를 쓰는 SQL 넷(``open``의 INSERT,
``record_fill``, ``mark_terminal``, ``expire_stale``)과 그 ``WHERE`` 가드가 전부다.
임의의 순서에서 매 걸음 뒤에 DB의 모든 행과 열린 캐시를 본다.

- O1: 행이 바뀐 걸음의 ``(전, 후)`` 상태 쌍이 ``ORDER_STATUS_TRANSITIONS``에 있다.
  새 행은 ``open``으로 생긴다. 행은 사라지지 않는다
- O1t: ``filled``에서는 나가지 않는다. 다른 종결 상태에서 나가는 것은 두 경로뿐이다 —
  체결 반영이 종결된 행을 되살리는 것(#2705)과 ``mark_terminal``이 종결 상태를 다른
  종결 상태로 덮어쓰는 것(등록 대기). 그 밖의 탈출은 실패다
- O2: ``recorded_filled_qty``는 줄지 않고 ``ordered_qty``를 넘지 않는다
- O3: ``terminal_at IS NULL`` ⟺ 상태가 열린 상태(``open``·``partially_filled``)
- O4: 열린 캐시의 주문 집합 == DB의 열린 행 집합 − 되살아난 행(#2705), 재시작 뒤에도.
  캐시 레코드의 상태·누적 수량은 DB와 같다
- S: 상태 값은 모든 경로(캐시, ``get``, ``get_open_orders``, ``record_fill``의
  결과)에서 평문 ``str``이다(#2707)

체결의 누적은 브로커의 계약대로 ``ordered_qty`` 이하로 만든다. 그보다 작거나 같은
누적(비증가)도 넣는다. 거부는 정상 결과다(``record_fill``의 no-op, 중복 ``open``의
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
        # 종결된 뒤 체결 반영으로 열린 상태가 된 행(#2705). 캐시에 다시 들지 않는다.
        self.revived: set[str] = set()
        # 관측된 상태 쌍(같은 상태로 남되 누적이 늘어난 것을 포함)과 종결 탈출의 경로.
        self.pairs: set[tuple[str, str]] = set()
        self.terminal_exits: set[tuple[str, str, str]] = set()
        self.rows: dict[str, Row] = {}
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

    def _observe(self, via: str) -> None:
        """걸음 하나의 끝. 이전 스냅숏과 견줘 O1·O1t·O2를 보고 스냅숏을 바꾼다."""
        after = self._fetch_rows()
        assert after.keys() >= self.rows.keys(), "O1: 행이 사라졌다"
        for oid, row in after.items():
            prev = self.rows.get(oid)
            if prev is None:
                assert row["status"] == OrderStatus.OPEN, f"O1: 새 행 {row}"
                continue
            b, a = prev["status"], row["status"]
            assert row["recorded_filled_qty"] >= prev["recorded_filled_qty"], (
                f"O2: {oid} 누적이 줄었다 {prev} -> {row}"
            )
            advanced = row["recorded_filled_qty"] > prev["recorded_filled_qty"]
            if b != a or advanced:
                assert (b, a) in ALLOWED, f"O1: {oid} {b} -> {a} ({via})"
                self.pairs.add((b, a))
            if b in TERMINAL and b != a:
                assert b != OrderStatus.FILLED, f"O1t: filled에서 나갔다 -> {a}"
                kind = "revive" if a in OPEN | {"filled"} else "overwrite"
                expected_via = "fill" if kind == "revive" else "mark_terminal"
                assert via == expected_via, f"O1t: {oid} {b} -> {a} ({via})"
                self.terminal_exits.add((b, a, via))
        self.rows = after
        self.revived &= {o for o, r in after.items() if r["status"] in OPEN}
        self.steps += 1

    # ── 규칙 ────────────────────────────────────────────────────────

    @rule(
        bot=st.sampled_from(BOTS),
        spec=st.tuples(st.integers(1, 10), st.sampled_from(DAYS)),
    )
    def open_order(self, bot: str, spec: tuple[int, str]) -> None:
        """새 주문의 seed(``OrderSubmittedEvent``)."""
        qty, day = spec
        order_id = f"ord-{next(self._seq)}"
        self._open(order_id, bot, qty, day)
        self.ordered[order_id] = qty
        self._observe("open")

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
        before = self.rows[order_id]["status"]

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
        self._observe("fill")
        after = self.rows[order_id]["status"]
        if before in TERMINAL and after in OPEN:
            self.revived.add(order_id)

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
        self._observe("mark_terminal")

    # 전제가 없으면 걸음의 6할이 만료였다(전제가 없는 규칙을 hypothesis가 자주 고른다).
    @precondition(lambda self: self.steps - self.last_expire >= 3)
    @rule(before_date=st.sampled_from(DAYS), own=st.booleans())
    def expire_stale(self, before_date: str, own: bool) -> None:
        """장 마감 만료. 다른 계좌를 주면 이 계좌의 행은 그대로다."""
        account = ACCOUNT_ID if own else "overseas"
        count = self._run(self.tracker.expire_stale(account, before_date))
        self.last_expire = self.steps
        prev = self.rows
        self._observe("expire_stale")
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
        self.revived.clear()
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
        assert self.revived <= db_open.keys()
        assert cache.keys() == db_open.keys() - self.revived, (
            f"O4: 캐시 {sorted(cache)} DB {sorted(db_open)} 되살아남 "
            f"{sorted(self.revived)}"
        )
        for oid, (status, qty) in cache.items():
            row = db_open[oid]
            assert (status, qty) == (row["status"], row["recorded_filled_qty"]), (
                f"O4: {oid} 캐시 {(status, qty)} DB {row}"
            )

    @invariant()
    def s_plain_str_status(self) -> None:
        for oid in self.rows:
            record = self._run(self.tracker.get(oid))
            assert record is not None and type(record.status) is str, f"S: {record!r}"
        for record in self._run(self.tracker.get_open_orders(ACCOUNT_ID)):
            assert type(record.status) is str, f"S: {record!r}"


TestOrderTrackerMachine = OrderTrackerMachine.TestCase
TestOrderTrackerMachine.settings = settings()
