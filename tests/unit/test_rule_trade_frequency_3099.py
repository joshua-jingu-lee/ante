"""거래 빈도 룰의 최근 체결 주문 수 (#3099).

스펙: `docs/specs/rule-engine/06-rule-catalog.md` 「용어 산식」의 최근 체결 주문 수,
`05-rule-context.md`의 ``metadata`` 행, `07-rule-engine-core.md` 「판정 입력 조회
실패」·「시장가 매수 시세」 판정 순서. 실제 Database·FillApplier·OrderTracker·
TradeRecorder·PerformanceTracker·TradeService·RuleEngine으로 돈다.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from ante.core import clock
from ante.core.database import Database
from ante.eventbus.events import (
    NotificationEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderModifyEvent,
    OrderModifyExecutedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
)
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult
from ante.rule.strategy_rules import TradeFrequencyRule
from ante.trade.performance import PerformanceTracker
from tests.conftest import ManualClock
from tests.unit.test_rule_daily_loss_source_2622 import (
    ACCT,
    BOT,
    OTHER_ACCT,
    SYMBOL,
    _Stack,
)

NOW = datetime(2026, 1, 2, 3, 0, 0, tzinfo=UTC)
NOT_READY = "account_not_ready: positions_unavailable"


class _StrategyRecorder(Rule):
    """전략 계층의 평가 입력을 기록하고 통과시킨다."""

    def __init__(self) -> None:
        super().__init__("srec", {"priority": -100})
        self.contexts: list[RuleContext] = []

    def evaluate(self, context: RuleContext) -> RuleEvaluation:
        self.contexts.append(context)
        return RuleEvaluation(
            rule_id=self.rule_id,
            rule_name=self.name,
            result=RuleResult.PASS,
            action=RuleAction.LOG,
            message="recorded",
        )


class _TFStack(_Stack):
    def __init__(self, db: Database) -> None:
        super().__init__(db)
        self.notifications: list[NotificationEvent] = []
        self._seq = 0

    async def start(self) -> None:
        await super().start()
        self.bus.subscribe(
            NotificationEvent, self.notifications.append, priority=-1000
        )

    def strategy_tf(self, limit: int, **config: Any) -> TradeFrequencyRule:
        rule = TradeFrequencyRule(
            "tf-s", {"max_trades_per_hour": limit, **config}
        )
        self.engine.add_strategy_rule("s1", rule)
        return rule

    def account_tf(self, limit: int, **config: Any) -> TradeFrequencyRule:
        rule = TradeFrequencyRule(
            "tf-a", {"max_trades_per_hour": limit, **config}
        )
        self.engine.add_account_rule(rule)
        return rule

    async def fill(
        self,
        at: datetime,
        *,
        order_id: str | None = None,
        strategy_id: str = "s1",
        account_id: str = ACCT,
        side: str = "buy",
    ) -> None:
        self._seq += 1
        await self.applier.apply_direct_fill(
            account_id=account_id,
            order_id=order_id or f"o-{self._seq}",
            bot_id=BOT,
            strategy_id=strategy_id,
            symbol=SYMBOL,
            side=side,
            quantity=1.0,
            price=10_000.0,
            commission=0.0,
            order_type="limit",
            exchange="KRX",
            timestamp=at,
        )

    async def fills(self, n: int, **kw: Any) -> None:
        for i in range(n):
            await self.fill(NOW - timedelta(minutes=50) + timedelta(minutes=i), **kw)

    async def order(self, side: str = "buy", order_type: str = "limit") -> None:
        await self.bus.publish(
            OrderRequestEvent(
                account_id=ACCT,
                bot_id=BOT,
                strategy_id="s1",
                symbol=SYMBOL,
                side=side,
                quantity=1.0,
                order_type=order_type,
                price=None if order_type == "market" else 10_000.0,
            )
        )

    async def modify(self, side: str = "buy") -> None:
        await self.bus.publish(
            OrderModifyEvent(
                account_id=ACCT,
                order_id="mod-1",
                bot_id=BOT,
                strategy_id="s1",
                symbol=SYMBOL,
                side=side,
                quantity=1.0,
                price=10_000.0,
            )
        )

    def spy(self, **kw: Any) -> AsyncMock:
        mock = AsyncMock(**kw)
        self.trade_service.count_filled_orders = mock  # type: ignore[method-assign]
        return mock


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "trade_frequency.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def stack(db: Database, manual_clock: Any) -> _TFStack:
    s = _TFStack(db)
    await s.start()
    return s


def _tf_rejections(stack: _TFStack) -> list[str]:
    return [e.reason for e in stack.rejected]


# ── T1 재현 ───────────────────────────────────────────────────────────────


async def test_t1_ten_filled_orders_reject_buy(stack: _TFStack) -> None:
    await stack.fills(10)
    stack.strategy_tf(10)

    await stack.order()

    assert stack.validated == []
    assert _tf_rejections(stack) == ["Trade frequency limit exceeded: 10 >= 10"]


# ── T2 창 ─────────────────────────────────────────────────────────────────


async def test_t2_window_boundary(stack: _TFStack) -> None:
    await stack.fill(NOW - timedelta(minutes=60))
    await stack.fill(NOW - timedelta(minutes=60, seconds=1))
    stack.strategy_tf(1)
    srec = _StrategyRecorder()
    stack.engine.add_strategy_rule("s1", srec)

    await stack.order()

    assert srec.contexts[-1].metadata["recent_trade_count"] == 1
    assert _tf_rejections(stack) == ["Trade frequency limit exceeded: 1 >= 1"]


async def test_t2_partial_fills_straddling_window_count_once(
    stack: _TFStack,
) -> None:
    await stack.tracker.open(
        order_id="straddle",
        account_id=ACCT,
        bot_id=BOT,
        strategy_id="s1",
        broker_order_id="0001",
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        ordered_qty=10.0,
        submitted_date="20260102",
    )
    common: dict[str, Any] = {
        "account_id": ACCT,
        "broker_order_id": "0001",
        "avg_price": 10_000.0,
        "submitted_date": "20260102",
    }
    with clock.use_clock(ManualClock(NOW - timedelta(minutes=90))):
        await stack.applier.apply_cumulative(**common, observed_cumulative=3.0)
    await stack.applier.apply_cumulative(**common, observed_cumulative=6.0)
    stack.strategy_tf(10)
    srec = _StrategyRecorder()
    stack.engine.add_strategy_rule("s1", srec)

    await stack.order()

    assert srec.contexts[-1].metadata["recent_trade_count"] == 1


# ── T3 주문 단위 ──────────────────────────────────────────────────────────


async def test_t3_partial_fills_of_one_order_count_once(stack: _TFStack) -> None:
    await stack.tracker.open(
        order_id="multi",
        account_id=ACCT,
        bot_id=BOT,
        strategy_id="s1",
        broker_order_id="0002",
        symbol=SYMBOL,
        side="buy",
        order_type="limit",
        ordered_qty=10.0,
        submitted_date="20260102",
    )
    for cumulative in (2.0, 5.0, 10.0):
        await stack.applier.apply_cumulative(
            account_id=ACCT,
            broker_order_id="0002",
            observed_cumulative=cumulative,
            avg_price=10_000.0,
            submitted_date="20260102",
        )
    rows = await stack.db.fetch_all(
        "SELECT order_id FROM trades WHERE status = 'filled'", ()
    )
    assert len(rows) == 3
    stack.strategy_tf(2)

    await stack.order()

    assert _tf_rejections(stack) == []
    assert len(stack.validated) == 1


async def test_t3_blank_order_id_rows_count_per_row(stack: _TFStack) -> None:
    at = (NOW - timedelta(minutes=10)).isoformat()
    for trade_id, order_id in (("b1", None), ("b2", ""), ("b3", "")):
        await stack.db.execute(
            """INSERT INTO trades
               (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                status, order_type, timestamp, order_id, account_id)
               VALUES (?, ?, 's1', ?, 'buy', 1.0, 10000.0, 'filled', 'limit',
                       ?, ?, ?)""",
            (trade_id, BOT, SYMBOL, at, order_id, ACCT),
        )
    count = await stack.trade_service.count_filled_orders(
        account_id=ACCT, since=NOW - timedelta(minutes=60), strategy_id="s1"
    )
    assert count == 3


# ── T4 범위 ───────────────────────────────────────────────────────────────


async def test_t4_strategy_rule_ignores_other_strategy_and_account(
    stack: _TFStack,
) -> None:
    await stack.fills(3, strategy_id="s2")
    await stack.fills(3, account_id=OTHER_ACCT)
    await stack.fills(1)
    stack.strategy_tf(2)

    await stack.order()

    assert _tf_rejections(stack) == []
    assert len(stack.validated) == 1


async def test_t4_account_rule_counts_whole_account(stack: _TFStack) -> None:
    await stack.fills(3, strategy_id="s2")
    await stack.fills(3, account_id=OTHER_ACCT)
    await stack.fills(1)
    stack.account_tf(4)

    await stack.order()

    assert _tf_rejections(stack) == ["Trade frequency limit exceeded: 4 >= 4"]


async def test_t4_both_tiers_judge_with_their_own_counts(stack: _TFStack) -> None:
    await stack.fills(3, strategy_id="s2")
    await stack.fills(1)
    stack.account_tf(10)
    stack.strategy_tf(1)
    srec = _StrategyRecorder()
    stack.engine.add_strategy_rule("s1", srec)

    await stack.order()

    assert stack.rec.contexts[-1].metadata["recent_trade_count"] == 4
    assert srec.contexts[-1].metadata["recent_trade_count"] == 1
    assert _tf_rejections(stack) == ["Trade frequency limit exceeded: 1 >= 1"]


# ── T5 상태 ───────────────────────────────────────────────────────────────


async def test_t5_only_filled_rows_count_and_sells_count(stack: _TFStack) -> None:
    at = NOW - timedelta(minutes=5)
    common: dict[str, Any] = {
        "account_id": ACCT,
        "bot_id": BOT,
        "strategy_id": "s1",
        "symbol": SYMBOL,
        "side": "buy",
        "quantity": 1.0,
        "timestamp": at,
    }
    await stack.recorder._on_rejected(
        OrderRejectedEvent(**common, order_type="limit", price=1.0, reason="r")
    )
    await stack.recorder._on_failed(
        OrderFailedEvent(**common, order_type="limit", error_message="f")
    )
    await stack.recorder._on_cancelled(
        OrderCancelledEvent(**common, order_id="c1", reason="c")
    )
    await stack.recorder._on_modified(
        OrderModifyExecutedEvent(**common, order_id="m1", price=1.0)
    )
    await stack.recorder.save_adjustment(
        BOT, SYMBOL, 1.0, 2.0, "adj", account_id=ACCT
    )
    statuses = await stack.db.fetch_all(
        "SELECT DISTINCT status FROM trades ORDER BY status", ()
    )
    assert [r["status"] for r in statuses] == [
        "adjusted",
        "cancelled",
        "failed",
        "modified",
        "rejected",
    ]
    for sid in ("s1", None):
        assert (
            await stack.trade_service.count_filled_orders(
                account_id=ACCT, since=NOW - timedelta(minutes=60), strategy_id=sid
            )
            == 0
        )
    await stack.fill(at, side="sell")
    assert (
        await stack.trade_service.count_filled_orders(
            account_id=ACCT, since=NOW - timedelta(minutes=60), strategy_id="s1"
        )
        == 1
    )


# ── T6 경계(>=) ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(("n", "rejected"), [(9, False), (10, True)])
async def test_t6_limit_is_inclusive(stack: _TFStack, n: int, rejected: bool) -> None:
    await stack.fills(n)
    stack.strategy_tf(10)

    await stack.order()

    assert bool(stack.rejected) is rejected
    assert bool(stack.validated) is not rejected


# ── T7 매도 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize("limit", [0, 5])
async def test_t7_sell_passes_without_query(stack: _TFStack, limit: int) -> None:
    await stack.fills(10)
    stack.strategy_tf(limit)
    stack.account_tf(limit)
    spy = stack.spy(return_value=10)

    await stack.order(side="sell")

    assert stack.rejected == []
    assert len(stack.validated) == 1
    spy.assert_not_awaited()


# ── T8 실패 ───────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "kw",
    [
        {"side_effect": RuntimeError("db down")},
        {"return_value": "3"},
        {"return_value": True},
        {"return_value": -1},
        {"return_value": math.nan},
        {"return_value": 3.0},
    ],
    ids=["raises", "str", "bool", "negative", "nan", "float"],
)
async def test_t8_bad_count_rejects_buy_and_notifies(
    stack: _TFStack, kw: dict[str, Any]
) -> None:
    stack.strategy_tf(10)
    stack.spy(**kw)

    await stack.order()

    assert stack.validated == []
    assert _tf_rejections(stack) == [NOT_READY]
    assert len(stack.notifications) == 1
    assert stack.rec.contexts == []


async def test_t8_bad_count_does_not_block_sell(stack: _TFStack) -> None:
    stack.strategy_tf(10)
    stack.spy(side_effect=RuntimeError("db down"))

    await stack.order(side="sell")

    assert stack.rejected == []
    assert len(stack.validated) == 1


# ── T9 조회 0회 ───────────────────────────────────────────────────────────


@pytest.mark.parametrize("setup", ["none", "disabled"])
async def test_t9_no_enabled_rule_no_query(stack: _TFStack, setup: str) -> None:
    if setup == "disabled":
        stack.strategy_tf(0, enabled=False)
        stack.account_tf(0, enabled=False)
    spy = stack.spy(side_effect=RuntimeError("must not be called"))

    await stack.order()

    spy.assert_not_awaited()
    assert stack.rejected == []
    assert len(stack.validated) == 1
    assert "recent_trade_count" not in stack.rec.contexts[-1].metadata


async def test_t9_other_strategy_rule_no_query(stack: _TFStack) -> None:
    stack.engine.add_strategy_rule(
        "s2", TradeFrequencyRule("tf-s2", {"max_trades_per_hour": 0})
    )
    spy = stack.spy(side_effect=RuntimeError("must not be called"))

    await stack.order()

    spy.assert_not_awaited()
    assert len(stack.validated) == 1


@pytest.mark.parametrize("failure", ["treasury", "positions", "quote"])
async def test_t9_no_query_after_other_input_failure(
    stack: _TFStack, failure: str
) -> None:
    stack.strategy_tf(10)
    spy = stack.spy(return_value=0)
    order_type = "limit"
    if failure == "treasury":
        stack.treasury.get_summary = _raise  # type: ignore[method-assign]
    elif failure == "positions":
        stack.trade_service.get_positions = AsyncMock(  # type: ignore[method-assign]
            side_effect=RuntimeError("positions down")
        )
    else:
        order_type = "market"

    await stack.order(order_type=order_type)

    spy.assert_not_awaited()
    assert stack.validated == []
    assert len(stack.rejected) == 1


def _raise(*_a: Any, **_k: Any) -> Any:
    raise RuntimeError("treasury down")


# ── T10 정정 ──────────────────────────────────────────────────────────────


async def test_t10_modify_skips_trade_frequency(stack: _TFStack) -> None:
    stack.strategy_tf(0)
    stack.account_tf(0)
    spy = stack.spy(return_value=10)

    await stack.modify()

    spy.assert_not_awaited()
    assert stack.modify_rejected == []
    assert "recent_trade_count" not in stack.rec.contexts[-1].metadata


# ── T11 count_filled_orders ───────────────────────────────────────────────


async def test_t11_naive_since_raises(db: Database) -> None:
    perf = PerformanceTracker(db)
    with pytest.raises(ValueError):
        await perf.count_filled_orders(account_id=ACCT, since=datetime(2026, 1, 2))


async def test_t11_missing_table_is_zero(db: Database) -> None:
    perf = PerformanceTracker(db)
    assert await perf.count_filled_orders(account_id=ACCT, since=NOW) == 0
