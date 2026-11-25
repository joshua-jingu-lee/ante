"""Treasury 자금 보존의 상태 기반 속성 테스트 (#2769).

임의의 연산 순서에서 매 걸음 뒤에 아래 불변식을 본다. 식은 ``treasury.py``에서 읽었다.

- F1: ``available == allocated - reserved - spent + returned`` (봇마다)
- F2: ``unallocated == account_balance - Σ allocated``
- F3: ``reserved == Σ 주문별 잔여 예약``, 잔여 >= 0, ``reserved >= 0``.
  예산 레코드가 없는 봇은 예약도 없다
- F4: ``account_balance ==
  unallocated + Σ(available + reserved) + Σ(spent - returned)``.
  F1과 F2를 더한 항등식이라 따로 실패하지 않는다. 체결은 ``account_balance``를
  바꾸지 않으므로 계좌 현금의 보존을 증명하지 않는다
- D: DB의 ``bot_budgets``·``treasury_state``·``treasury_reservations``가 메모리 값과
  같다
- E: 이벤트 핸들러 예외 0건(실제 ``EventBus``는 예외를 로그로만 남긴다)
- F5(재시작 기계): 같은 DB로 새 ``Treasury``를 올리면 다섯 값과 미배분, 주문별 예약
  표가 같다(#2770)

거부는 연산의 정상 결과다. 다만 거부는 문서화된 Treasury 예외(``TreasuryError``)로만
와야 한다. 그 밖의 예외는 실패다. 예외: 같은 id의 재예약은
``DuplicateReservationError``(``ValueError``)로 거부된다(#2775).
"""

from __future__ import annotations

import asyncio
import itertools
import math
import shutil
import tempfile
from collections.abc import Awaitable, Coroutine
from dataclasses import dataclass
from inspect import isawaitable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import (
    RuleBasedStateMachine,
    initialize,
    invariant,
    precondition,
    rule,
)

from ante.core.database import Database
from ante.eventbus.bus import EventBus, EventHandler
from ante.eventbus.events import (
    BotStoppedEvent,
    Event,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
)
from ante.trade.order_tracker import OrderTracker
from ante.treasury.exceptions import DuplicateReservationError, TreasuryError
from ante.treasury.treasury import Treasury

T = TypeVar("T")

ACCOUNT_ID = "domestic"
BOTS = ("bot-a", "bot-b", "bot-c")
BUY_RATE = 0.00015
SELL_RATE = 0.00195
FIELDS = ("allocated", "available", "reserved", "spent", "returned")

# 금액은 원 단위 정수다. 작은 값으로 줄어드는(shrink) 정수를 그대로 쓰면 배분이
# 몇 원에 머물러 예약이 늘 거부된다. 그래서 계좌·예산 금액은 10만 원 단위로 만든다.
UNIT = 100_000
balances = st.integers(0, 1_000).map(lambda n: n * UNIT)
amounts = st.integers(1, 300).map(lambda n: n * UNIT)
quantities = st.integers(1, 50)
prices = st.integers(100, 50_000)


def _close(actual: float, expected: float) -> bool:
    # 수수료가 소수를 만든다. 0 근처는 상대 오차가 뜻이 없어 1e-6원을 함께 둔다.
    return actual == pytest.approx(expected, rel=1e-9, abs=1e-6)


class RecordingEventBus(EventBus):
    """핸들러 예외를 목록에 기록하는 버스(불변식 E). 전달 동작은 실제 버스와 같다."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__()
        self._errors = errors

    def subscribe(
        self, event_type: type[Event], handler: EventHandler, priority: int = 0
    ) -> None:
        errors = self._errors

        async def recording(event: Any) -> None:
            try:
                result = handler(event)
                if isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(
                    f"{handler.__qualname__} <- {type(event).__name__}: {exc!r}"
                )
                raise

        recording.__qualname__ = handler.__qualname__
        super().subscribe(event_type, recording, priority)


@dataclass
class _Order:
    """모델이 기억하는 예약 주문."""

    bot_id: str
    tracked: bool
    qty: int
    price: int
    filled: int = 0


class TreasuryMachine(RuleBasedStateMachine):
    """한 계좌의 Treasury에 예산·주문·체결 연산을 임의 순서로 건다. 재시작은 없다."""

    def __init__(self) -> None:
        super().__init__()
        self._tmp = Path(tempfile.mkdtemp(prefix="ante-prop-treasury-"))
        self._runner = asyncio.Runner()
        self._db = Database(str(self._tmp / "treasury.db"))
        self._run(self._db.connect())
        self._seq = itertools.count()
        self.handler_errors: list[str] = []
        self.open_orders: dict[str, _Order] = {}
        self.order_bot: dict[str, str] = {}
        self.keyed_fills: list[OrderFilledEvent] = []
        # 예산 레코드가 있는 봇(모델). 배분 성공으로 생기고 예산 해제로 없어진다.
        self.funded: set[str] = set()
        self.steps = 0
        self.last_restart = 0
        self._start()

    # ── 대역 ────────────────────────────────────────────────────────

    def _run(self, coro: Coroutine[Any, Any, T] | Awaitable[T]) -> T:
        async def wrap() -> T:
            return await coro

        return self._runner.run(wrap())

    def _start(self) -> None:
        """새 버스·OrderTracker·Treasury를 같은 DB에 올린다(재시작에도 쓴다)."""
        self.bus = RecordingEventBus(self.handler_errors)
        self.tracker = OrderTracker(db=self._db)
        self._run(self.tracker.initialize())
        self.treasury = Treasury(
            db=self._db,
            eventbus=self.bus,
            account_id=ACCOUNT_ID,
            buy_commission_rate=BUY_RATE,
            sell_commission_rate=SELL_RATE,
            order_tracker=self.tracker,
        )
        self._run(self.treasury.initialize())

    def _domain(self, coro: Coroutine[Any, Any, Any]) -> bool:
        """연산을 돌린다. Treasury 예외의 거부는 False, 그 밖의 예외는 그대로 낸다."""
        try:
            self._run(coro)
        except TreasuryError:
            return False
        return True

    def _publish(self, event: Event) -> None:
        self._run(self.bus.publish(event))

    def _close_bot_orders(self, bot_id: str, *, untracked_only: bool = False) -> None:
        for order_id in [
            o
            for o, v in self.open_orders.items()
            if v.bot_id == bot_id and not (untracked_only and v.tracked)
        ]:
            del self.open_orders[order_id]

    def _budget_values(self) -> dict[str, tuple[float, ...]]:
        return {
            b.bot_id: tuple(getattr(b, f) for f in FIELDS)
            for b in self.treasury.list_budgets()
        }

    def _reservation_table(self) -> dict[str, tuple[str, float]]:
        return {
            order_id: (bot, amount)
            for bot in BOTS
            for order_id, amount in self.treasury.get_reservations(bot).items()
        }

    def teardown(self) -> None:
        try:
            self._run(self._db.close())
        finally:
            self._runner.close()
            shutil.rmtree(self._tmp, ignore_errors=True)

    # ── 계좌·예산 ───────────────────────────────────────────────────

    @initialize(balance=st.integers(100, 1_000).map(lambda n: n * UNIT))
    def opening_balance(self, balance: int) -> None:
        self._run(self.treasury.set_account_balance(float(balance)))

    @rule(cash=balances, via_sync=st.booleans())
    def account_cash(self, cash: int, via_sync: bool) -> None:
        """계좌 잔고의 설정, 또는 브로커 잔고 동기화."""
        if via_sync:
            self._run(self.treasury.sync_balance({"cash": float(cash)}))
        else:
            self._run(self.treasury.set_account_balance(float(cash)))

    @rule(bot=st.sampled_from(BOTS), amount=amounts)
    def allocate(self, bot: str, amount: int) -> None:
        if self._domain(self.treasury.allocate(bot, float(amount))):
            self.funded.add(bot)

    @rule(bot=st.sampled_from(BOTS), amount=amounts)
    def deallocate(self, bot: str, amount: int) -> None:
        self._domain(self.treasury.deallocate(bot, float(amount)))

    @rule(bot=st.sampled_from(BOTS), goal=st.integers(0, 300).map(lambda n: n * UNIT))
    def update_budget(self, bot: str, goal: int) -> None:
        if self._domain(self.treasury.update_budget(bot, float(goal))) and goal > 0:
            self.funded.add(bot)

    @rule(bot=st.sampled_from(BOTS), delete=st.booleans())
    def bot_stopped_or_deleted(self, bot: str, delete: bool) -> None:
        """봇 정지(``BotStoppedEvent``) 또는 봇 삭제(``release_budget``).

        한 규칙으로 묶는 이유: hypothesis는 인자가 적은 규칙을 앞에 두고 앞의 규칙을
        자주 고른다. 따로 두면 주문을 닫는 이 둘이 걸음의 3할을 차지했다.

        정지는 추적기에서 열린 주문의 예약을 남기고 미추적 주문의 예약만 회수한다
        (#3048). 그래서 정지 뒤에도 추적 주문의 체결·취소·실패가 이어진다. 삭제는
        그 봇의 주문을 모두 닫는다.
        """
        if delete:
            self._run(self.treasury.release_budget(bot))
            self.funded.discard(bot)
            self._close_bot_orders(bot)
            return
        table = self.treasury.get_reservations(bot)
        kept = {
            o: table[o]
            for o, v in self.open_orders.items()
            if v.bot_id == bot and v.tracked and o in table
        }
        self._publish(BotStoppedEvent(account_id=ACCOUNT_ID, bot_id=bot))
        after = self.treasury.get_reservations(bot)
        assert {o: after.get(o) for o in kept} == kept, (
            "정지가 열린 주문의 예약을 회수했다"
        )
        assert set(after) <= set(kept), f"정지가 남긴 예약 {after} != 열린 주문 {kept}"
        self._close_bot_orders(bot, untracked_only=True)

    # ── 주문 ────────────────────────────────────────────────────────

    @rule(data=st.data(), spec=st.tuples(quantities, prices, st.booleans()))
    def reserve_for_order(
        self, data: st.DataObject, spec: tuple[int, int, bool]
    ) -> None:
        """매수 주문의 예약. 주문 id는 매번 새로 만든다(같은 id는 ``reserve_again``).

        봇은 예산이 있는 봇에서 고른다(없으면 셋 가운데에서 — 예약은 False다).
        """
        bot = data.draw(st.sampled_from(sorted(self.funded) or BOTS), "bot")
        qty, price, tracked = spec
        order_id = f"ord-{next(self._seq)}"
        amount = math.ceil(qty * price * (1 + BUY_RATE))
        ok = self._run(self.treasury.reserve_for_order(bot, order_id, float(amount)))
        if not ok:
            return
        if tracked:
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
                    submitted_date="2026-11-23",
                )
            )
        self.open_orders[order_id] = _Order(bot, tracked, qty, price)
        self.order_bot[order_id] = bot

    @precondition(lambda self: bool(self.open_orders))
    @rule(data=st.data(), amount=amounts)
    def reserve_again(self, data: st.DataObject, amount: int) -> None:
        """열린 주문의 id로 다시 예약한다. 전용 예외로 거부되고 그대로다(#2775)."""
        order_id = data.draw(st.sampled_from(sorted(self.open_orders)), "order")
        bot = self.open_orders[order_id].bot_id
        before = (self._budget_values(), self._reservation_table())
        with pytest.raises(DuplicateReservationError):
            self._run(self.treasury.reserve_for_order(bot, order_id, float(amount)))
        assert (self._budget_values(), self._reservation_table()) == before

    @precondition(lambda self: bool(self.open_orders))
    @rule(data=st.data())
    def buy_fill(self, data: st.DataObject) -> None:
        """예약 주문의 매수 체결. 추적 주문은 부분 체결, 미추적은 전량 체결."""
        order_id = data.draw(st.sampled_from(sorted(self.open_orders)), "order")
        order = self.open_orders[order_id]
        left = order.qty - order.filled
        qty = data.draw(st.integers(1, left), "qty") if order.tracked else left
        # 예약가의 0.5–1.5배: surplus와 shortfall 분기를 모두 지난다.
        price = data.draw(
            st.integers(max(1, order.price // 2), order.price * 3 // 2), "price"
        )
        cumulative = order.filled + qty
        key = ""
        if order.tracked:
            self._run(
                self.tracker.record_fill(order_id, float(cumulative), float(price))
            )
            key = f"{order_id}:{cumulative}"
        event = OrderFilledEvent(
            account_id=ACCOUNT_ID,
            order_id=order_id,
            broker_order_id=f"bk-{order_id}",
            bot_id=order.bot_id,
            strategy_id="s1",
            symbol="005930",
            side="buy",
            quantity=float(qty),
            price=float(price),
            commission=qty * price * BUY_RATE,
            order_type="limit",
            fill_dedup_key=key,
        )
        self._publish(event)
        order.filled = cumulative
        if key:
            self.keyed_fills.append(event)
        if cumulative >= order.qty:
            del self.open_orders[order_id]

    @rule(bot=st.sampled_from(BOTS), spec=st.tuples(quantities, prices, st.booleans()))
    def sell_fill(self, bot: str, spec: tuple[int, int, bool]) -> None:
        """매도 체결. 예약이 없다. 키가 있으면 재전달 대상이 된다."""
        qty, price, keyed = spec
        order_id = f"sell-{next(self._seq)}"
        event = OrderFilledEvent(
            account_id=ACCOUNT_ID,
            order_id=order_id,
            broker_order_id=f"bk-{order_id}",
            bot_id=bot,
            strategy_id="s1",
            symbol="005930",
            side="sell",
            quantity=float(qty),
            price=float(price),
            commission=qty * price * SELL_RATE,
            order_type="limit",
            fill_dedup_key=f"{order_id}:{qty}" if keyed else "",
        )
        before = self._budget_values()
        self._publish(event)
        if bot not in self.funded:
            # 예산 레코드가 없는 봇의 체결은 무시된다(재전달 대상도 아니다).
            assert self._budget_values() == before, "예산 없는 봇의 체결이 정산됐다"
        elif keyed:
            self.keyed_fills.append(event)

    @precondition(lambda self: bool(self.keyed_fills))
    @rule(data=st.data())
    def redeliver_fill(self, data: st.DataObject) -> None:
        """이미 정산한 체결의 재전달. 정산은 0회 더해져야 한다."""
        event = data.draw(st.sampled_from(self.keyed_fills), "event")
        before = self._budget_values()
        self._publish(event)
        assert self._budget_values() == before, "재전달이 다시 정산됐다"

    @precondition(lambda self: bool(self.order_bot))
    @rule(data=st.data(), failed=st.booleans())
    def cancel_or_fail(self, data: st.DataObject, failed: bool) -> None:
        """주문 취소/실패. 이미 끝난 주문에 늦게 온 이벤트도 포함한다."""
        order_id = data.draw(st.sampled_from(sorted(self.order_bot)), "order")
        bot = self.order_bot[order_id]
        order = self.open_orders.pop(order_id, None)
        if order is not None and order.tracked:
            status = "failed" if failed else "cancelled"
            self._run(self.tracker.mark_terminal(order_id, status))
        event_type = OrderFailedEvent if failed else OrderCancelledEvent
        self._publish(event_type(account_id=ACCOUNT_ID, order_id=order_id, bot_id=bot))

    # ── 불변식 ──────────────────────────────────────────────────────

    @invariant()
    def f1_budget_identity(self) -> None:
        for b in self.treasury.list_budgets():
            expected = b.allocated - b.reserved - b.spent + b.returned
            assert _close(b.available, expected), f"F1: {b}"

    @invariant()
    def f2_unallocated(self) -> None:
        t = self.treasury
        total = sum(b.allocated for b in t.list_budgets())
        assert _close(t.unallocated, t.account_balance - total), (
            f"F2: unallocated={t.unallocated} balance={t.account_balance} "
            f"allocated={total}"
        )

    @invariant()
    def f3_reservations(self) -> None:
        t = self.treasury
        for bot in BOTS:
            table = t.get_reservations(bot)
            budget = t.get_budget(bot)
            if budget is None:
                assert table == {}, f"F3: 예산 없는 봇 {bot}의 예약 {table}"
                continue
            assert all(v >= 0 for v in table.values()), f"F3: {bot} {table}"
            assert budget.reserved >= 0, f"F3: {budget}"
            assert _close(budget.reserved, sum(table.values())), (
                f"F3: {bot} reserved={budget.reserved} table={table}"
            )

    @invariant()
    def f4_cash_identity(self) -> None:
        t = self.treasury
        budgets = t.list_budgets()
        held = sum(b.available + b.reserved for b in budgets)
        invested = sum(b.spent - b.returned for b in budgets)
        assert _close(t.account_balance, t.unallocated + held + invested), "F4"

    @invariant()
    def d_db_mirror(self) -> None:
        rows = self._run(
            self._db.fetch_all(
                "SELECT * FROM bot_budgets WHERE account_id = ?", (ACCOUNT_ID,)
            )
        )
        stored = {r["bot_id"]: tuple(float(r[f]) for f in FIELDS) for r in rows}
        assert stored == self._budget_values(), "D: bot_budgets != 메모리"
        state = self._run(
            self._db.fetch_one(
                "SELECT account_balance FROM treasury_state WHERE account_id = ?",
                (ACCOUNT_ID,),
            )
        )
        balance = float(state["account_balance"]) if state else 0.0
        assert balance == self.treasury.account_balance, "D: treasury_state != 메모리"
        rows = self._run(
            self._db.fetch_all(
                "SELECT order_id, bot_id, remaining FROM treasury_reservations "
                "WHERE account_id = ?",
                (ACCOUNT_ID,),
            )
        )
        reserved = {r["order_id"]: (r["bot_id"], float(r["remaining"])) for r in rows}
        assert reserved == self._reservation_table(), (
            "D: treasury_reservations != 메모리"
        )

    @invariant()
    def e_no_handler_errors(self) -> None:
        assert self.handler_errors == [], f"E: {self.handler_errors}"
        # 불변식은 매 걸음 뒤에 돈다. 걸음 수는 재시작 규칙의 전제에 쓴다.
        self.steps += 1


class TreasuryRestartMachine(TreasuryMachine):
    """``TreasuryMachine``에 재시작을 더한다(F5).

    재시작은 주문별 예약 표를 ``treasury_reservations``에서 되살린다(#2770). 그래서
    재시작 뒤에도 F3은 ``reserved == Σ 표``로 그대로 본다.
    """

    # 인자 없는 규칙은 hypothesis가 자주 고른다. 전제가 없으면 걸음의 2할이
    # 재시작이었다.
    @precondition(lambda self: self.steps - self.last_restart >= 5)
    @rule()
    def restart(self) -> None:
        before = self._budget_values()
        unallocated = self.treasury.unallocated
        balance = self.treasury.account_balance
        table = self._reservation_table()
        self._start()
        self.last_restart = self.steps
        after = self._budget_values()
        assert after.keys() == before.keys(), "F5: 봇 집합"
        for bot, values in before.items():
            assert all(map(_close, after[bot], values)), f"F5: {bot}"
        assert _close(self.treasury.unallocated, unallocated), "F5: unallocated"
        assert self.treasury.account_balance == balance, "F5: account_balance"
        assert self._reservation_table() == table, "F5: 주문별 예약 표"


TestTreasuryMachine = TreasuryMachine.TestCase
TestTreasuryMachine.settings = settings()
TestTreasuryRestartMachine = TreasuryRestartMachine.TestCase
TestTreasuryRestartMachine.settings = settings()


async def test_restart_restores_reservations(tmp_path: Path) -> None:
    """재시작 뒤에도 미종결 주문의 예약이 예약 표에 남는다(F3, #2770).

    #2770 전에 ``TreasuryRestartMachine``이 F3에서 찾은 최소 순서를 손으로 옮겼다:
    배분 → 예약 → 재시작. 재시작 뒤 ``reserved``가 101이면 표에도 101이 있어야
    뒤따르는 취소가 예약을 돌려준다.
    """
    db = Database(str(tmp_path / "treasury.db"))
    await db.connect()
    errors: list[str] = []

    async def boot() -> Treasury:
        treasury = Treasury(
            db=db,
            eventbus=RecordingEventBus(errors),
            account_id=ACCOUNT_ID,
            buy_commission_rate=BUY_RATE,
            sell_commission_rate=SELL_RATE,
        )
        await treasury.initialize()
        return treasury

    try:
        treasury = await boot()
        await treasury.set_account_balance(100_000.0)
        await treasury.update_budget("bot-a", 100_000.0)
        if not await treasury.reserve_for_order("bot-a", "ord-0", 101.0):
            pytest.fail("준비: 예약이 거부됐다")

        treasury = await boot()

        budget = treasury.get_budget("bot-a")
        if budget is None or budget.reserved != 101.0:
            pytest.fail(f"준비: 재시작 뒤 예산이 복원되지 않았다: {budget}")
        if errors:
            pytest.fail(f"준비: 핸들러 예외 {errors}")
        assert treasury.get_reservations("bot-a") == {"ord-0": 101.0}
    finally:
        await db.close()
