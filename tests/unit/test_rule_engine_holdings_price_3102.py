"""봇의 미실현 손익을 모든 보유 종목의 동기화 시세로 평가한다 (#3102).

스펙: `docs/specs/rule-engine/07-rule-engine-core.md` 「보유 종목 시세 (#3102)」,
`05-rule-context.md`의 ``unrealized_pnl`` 행, `06-rule-catalog.md` 미실현 손실률,
`treasury/04-treasury-interface.md` 「성공한 동기화의 범위 (#3102)」.

실제 Database·FillApplier·PositionHistory·TradeService·Treasury 동기화·RuleEngine으로
돈다. 실전 동기화는 실제 ``KISDomesticAdapter.get_positions``를 쓰고 HTTP 호출만 가짜다.
포지션의 ``updated_at``은 SQLite가 실제 시각으로 찍으므로, 시계는 「동기화 진입 <
실제 체결 시각 ≤ 평가 때의 지금」이 되게 맞춘다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, tzinfo
from typing import Any

import pytest

from ante.account.models import TradingMode
from ante.broker.kis import KISDomesticAdapter
from ante.core import clock
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    NotificationEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult
from ante.rule.strategy_rules import UnrealizedLossLimitRule
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import FillOutbox
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService
from ante.treasury.treasury import (
    SYNCED_PRICE_MISSING,
    SYNCED_PRICE_STALE,
    Treasury,
)
from tests.unit._readiness_gate_helpers import make_account, ready_registry

ACCT = "acc-3102"
BOT = "bot-h"
INTERVAL = 300
A = "005930"
B = "000660"
C = "035420"
PREFIX = "holding_quote_unavailable"
PREFLIGHT_ERROR = "OrderRequest preflight error (see logs)"


class _Clock:
    """시각과 단조 값을 따로, 앞뒤로 옮길 수 있는 시계."""

    def __init__(self, at: datetime) -> None:
        self.at = at
        self.mono = 1000.0

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self.at.astimezone().replace(tzinfo=None)
        return self.at.astimezone(tz)

    def monotonic(self) -> float:
        return self.mono


class _Recorder(Rule):
    """평가 입력을 기록하고 통과시킨다."""

    def __init__(self) -> None:
        super().__init__("rec", {"priority": -100})
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


class _KisHttp:
    """KIS 어댑터의 HTTP 두 진입점을 대신하고 호출을 센다."""

    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []
        self.calls = 0

    async def request(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "output2": [{"dnca_tot_amt": "10000000", "tot_evlu_amt": "10000000"}],
            "output": {"stck_prpr": "1000"},
        }

    async def paginated(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.calls += 1
        return [dict(r) for r in self.rows]


def _kis_row(symbol: str, qty: float, prpr: float) -> dict[str, Any]:
    return {
        "pdno": symbol,
        "prdt_name": symbol,
        "hldg_qty": str(qty),
        "pchs_avg_pric": "0",
        "prpr": str(prpr),
        "evlu_amt": "0",
        "evlu_pfls_amt": "0",
        "evlu_erng_rt": "0",
    }


class _H:
    def __init__(self, db: Database, clk: _Clock, *, live: bool) -> None:
        mode = TradingMode.LIVE if live else TradingMode.VIRTUAL
        broker_type = "kis-domestic" if live else "test"
        self.db = db
        self.clk = clk
        self.live = live
        self.bus = EventBus()
        self.position_history = PositionHistory(db)
        self.recorder = TradeRecorder(db, self.position_history)
        self.tracker = OrderTracker(db)
        self.outbox = FillOutbox(db)
        self.applier = FillApplier(
            db=db,
            order_tracker=self.tracker,
            position_history=self.position_history,
            eventbus=self.bus,
            outbox=self.outbox,
        )
        registry = ready_registry(ACCT, broker_type=broker_type, trading_mode=mode)
        self.treasury = Treasury(
            db,
            self.bus,
            account_id=ACCT,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            runtime_readiness=registry,
            broker_type=broker_type,
            trading_mode=mode,
        )
        self.trade_service = TradeService(
            self.recorder, self.position_history, PerformanceTracker(db)
        )
        self.engine = RuleEngine(
            eventbus=self.bus,
            account_id=ACCT,
            treasury=self.treasury,
            trade_service=self.trade_service,
            account=make_account(ACCT, broker_type=broker_type, trading_mode=mode),
            runtime_readiness=registry,
        )
        self.http = _KisHttp()
        self.adapter = KISDomesticAdapter(
            config={
                "app_key": "k",
                "app_secret": "s",
                "account_no": "1234567890",
                "is_paper": True,
            }
        )
        self.adapter._request = self.http.request  # type: ignore[method-assign]
        self.adapter._request_paginated = self.http.paginated  # type: ignore[method-assign]
        self.virtual_prices: dict[str, float] = {}
        self.virtual_calls = 0
        self.market_calls: list[str] = []
        self.market_price = 10_000.0
        self.rec = _Recorder()
        self.validated: list[OrderValidatedEvent] = []
        self.rejected: list[OrderRejectedEvent] = []
        self.modify_rejected: list[OrderModifyRejectedEvent] = []
        self.notifications: list[NotificationEvent] = []
        self.reads = {"price": 0, "coverage": 0}
        self._seq = 0

    async def start(self, budget: float | None = 1_000_000.0) -> None:
        await self.position_history.initialize()
        await self.recorder.initialize()
        await self.tracker.initialize()
        await self.outbox.initialize()
        await self.treasury.initialize()
        await self.treasury.set_account_balance(10_000_000.0)
        if budget is not None:
            await self.treasury.allocate(BOT, budget)
        self.engine.add_account_rule(self.rec)
        self.engine.set_market_price_resolver(self._market)
        self.engine.start()
        self.bus.subscribe(OrderValidatedEvent, self.validated.append, priority=-1000)
        self.bus.subscribe(OrderRejectedEvent, self.rejected.append, priority=-1000)
        self.bus.subscribe(
            OrderModifyRejectedEvent, self.modify_rejected.append, priority=-1000
        )
        self.bus.subscribe(NotificationEvent, self.notifications.append, priority=-1000)
        self.treasury.start_sync(
            self.adapter if self.live else None,
            self.position_history,
            interval_seconds=INTERVAL,
            trading_mode="live" if self.live else "virtual",
        )
        await self.treasury.stop_sync()
        self._spy_treasury()

    def _spy_treasury(self) -> None:
        price = self.treasury.get_synced_price
        coverage = getattr(self.treasury, "get_last_sync_coverage", lambda: None)

        def _price(symbol: str) -> Any:
            self.reads["price"] += 1
            return price(symbol)

        def _coverage() -> Any:
            self.reads["coverage"] += 1
            return coverage()

        self.treasury.get_synced_price = _price  # type: ignore[method-assign]
        self.treasury.get_last_sync_coverage = _coverage  # type: ignore[method-assign]

    async def _market(self, symbol: str) -> float:
        self.market_calls.append(symbol)
        return self.market_price

    async def _virtual(self, symbol: str) -> float:
        self.virtual_calls += 1
        if symbol not in self.virtual_prices:
            raise RuntimeError(f"no quote {symbol}")
        return self.virtual_prices[symbol]

    def ul(self, pct: float = 0.05, *, account: bool = False, **cfg: Any) -> None:
        rule = UnrealizedLossLimitRule(
            "ul", {"max_unrealized_loss_percent": pct, **cfg}
        )
        if account:
            self.engine.add_account_rule(rule)
        else:
            self.engine.add_strategy_rule("s1", rule)

    async def db_now(self) -> datetime:
        row = await self.db.fetch_one("SELECT datetime('now') AS t")
        assert row is not None
        return datetime.fromisoformat(row["t"]).replace(tzinfo=UTC)

    async def fill(
        self, symbol: str, qty: float, price: float, side: str = "buy"
    ) -> None:
        self._seq += 1
        await self.applier.apply_direct_fill(
            account_id=ACCT,
            order_id=f"f-{self._seq}",
            bot_id=BOT,
            strategy_id="s1",
            symbol=symbol,
            side=side,
            quantity=qty,
            price=price,
            commission=0.0,
            order_type="limit",
            exchange="KRX",
            timestamp=self.clk.at,
        )

    async def sync(self, prices: dict[str, float], **extra: float) -> None:
        """진입을 실제 시각의 60초 앞으로 두고 동기화한 뒤, 지금을 120초 뒤로 둔다."""
        real = await self.db_now()
        self.clk.at = real - timedelta(seconds=60)
        if self.live:
            held = await self.position_history.get_all_positions(account_id=ACCT)
            qty = {p.symbol: p.quantity for p in held}
            self.http.rows = [
                _kis_row(s, qty.get(s, 1.0), p) for s, p in {**prices, **extra}.items()
            ]
            await self.treasury._do_sync(self.adapter, self.position_history)
        else:
            self.virtual_prices = dict(prices)
            await self.treasury._do_sync_virtual(self.position_history, self._virtual)
        self.clk.at = real + timedelta(seconds=120)

    async def order(
        self,
        symbol: str,
        *,
        side: str = "buy",
        order_type: str = "limit",
        price: float | None = 10_000.0,
    ) -> None:
        await self.bus.publish(
            OrderRequestEvent(
                account_id=ACCT,
                bot_id=BOT,
                strategy_id="s1",
                symbol=symbol,
                side=side,
                quantity=1.0,
                order_type=order_type,
                price=None if order_type == "market" else price,
            )
        )

    async def set_updated_at(self, symbol: str, value: str | None) -> None:
        await self.db.execute(
            "UPDATE positions SET updated_at = ? WHERE bot_id = ? AND symbol = ?",
            (value, BOT, symbol),
        )

    def reasons(self) -> list[str]:
        return [e.reason for e in self.rejected]


@pytest.fixture
def clk() -> Iterator[_Clock]:
    manual = _Clock(datetime(2026, 1, 2, 3, 0, 0, tzinfo=UTC))
    with clock.use_clock(manual):
        yield manual


@pytest.fixture
async def db(tmp_path: Any) -> Any:
    database = Database(str(tmp_path / "holdings.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture(params=["live", "virtual"])
async def h(request: pytest.FixtureRequest, db: Database, clk: _Clock) -> _H:
    stack = _H(db, clk, live=request.param == "live")
    await stack.start()
    return stack


@pytest.fixture
async def live(db: Database, clk: _Clock) -> _H:
    stack = _H(db, clk, live=True)
    await stack.start()
    return stack


@pytest.fixture
async def virtual(db: Database, clk: _Clock) -> _H:
    stack = _H(db, clk, live=False)
    await stack.start()
    return stack


def _ul_rejected(h: _H) -> bool:
    return any("Unrealized loss" in r for r in h.reasons())


# ── R1 재현: 다른 종목의 손실 ─────────────────────────────────────────────


@pytest.mark.parametrize("order_type", ["limit", "market"])
async def test_r1_other_symbol_loss_rejects_buy(h: _H, order_type: str) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05)

    await h.order(B, order_type=order_type)

    assert h.validated == []
    assert _ul_rejected(h)
    assert h.rec.contexts[-1].unrealized_pnl == -100_000.0


# ── R2 지정가: 주문가가 아니라 시세 ──────────────────────────────────────


async def test_r2_high_limit_does_not_hide_loss(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05)

    await h.order(A, price=61_000.0)

    assert h.validated == []
    assert _ul_rejected(h)


async def test_r2_low_limit_no_longer_over_rejects(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 60_000.0})
    h.ul(0.05)

    await h.order(A, price=50_000.0)

    assert len(h.validated) == 1
    assert h.rec.contexts[-1].unrealized_pnl == 0.0


async def test_r3_profit_on_other_symbol_offsets(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(C, 10, 10_000.0)
    await h.sync({A: 50_000.0, C: 20_000.0})
    h.ul(0.05)

    await h.order(A, price=50_000.0)

    assert len(h.validated) == 1
    assert h.rec.contexts[-1].unrealized_pnl == 0.0


async def test_account_tier_rule_also_enables(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05, account=True)

    await h.order(B)

    assert _ul_rejected(h)


# ── R4 읽지 않는 경우: 계산은 base 근사 그대로 ──────────────────────────────


async def _assert_base_approximation(h: _H, price: float) -> None:
    assert h.reads == {"price": 0, "coverage": 0}
    ctx = h.rec.contexts[-1]
    assert ctx.unrealized_pnl == (price - 60_000.0) * 10


async def test_r4_no_rule_reads_nothing(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.sync({A: 50_000.0, B: 1.0})

    await h.order(A, price=61_000.0)

    assert len(h.validated) == 1
    await _assert_base_approximation(h, 61_000.0)


async def test_r4_disabled_rule_reads_nothing(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.sync({A: 50_000.0, B: 1.0})
    h.ul(0.05, enabled=False)
    h.ul(0.05, account=True, enabled=False)

    await h.order(A, price=61_000.0)

    assert len(h.validated) == 1
    await _assert_base_approximation(h, 61_000.0)


async def test_r4_zero_budget_reads_nothing(db: Database, clk: _Clock) -> None:
    h = _H(db, clk, live=False)
    await h.start(budget=None)
    await h.fill(A, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.sync({A: 50_000.0, B: 1.0})
    h.ul(0.05)

    await h.order(A, price=61_000.0)

    assert h.rec.contexts[-1].bot_allocated_budget == 0.0
    assert len(h.validated) == 1
    await _assert_base_approximation(h, 61_000.0)


async def test_r4_sell_reads_nothing_and_passes(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05)

    await h.order(A, side="sell", price=61_000.0)

    assert len(h.validated) == 1
    await _assert_base_approximation(h, 61_000.0)


async def test_r4_modify_reads_nothing(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05)

    await h.bus.publish(
        OrderModifyEvent(
            account_id=ACCT,
            order_id="mod-1",
            bot_id=BOT,
            strategy_id="s1",
            symbol=A,
            side="buy",
            quantity=1.0,
            price=61_000.0,
        )
    )

    assert h.modify_rejected == []
    await _assert_base_approximation(h, 61_000.0)


# ── R5 시장가 주문 종목: 방금 조회한 시세 ─────────────────────────────────


async def test_r5_market_order_symbol_uses_resolved_quote(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 50_000.0})
    h.ul(0.05)
    h.market_price = 60_000.0

    await h.order(A, order_type="market")

    assert h.market_calls == [A]
    assert len(h.validated) == 1
    assert h.rec.contexts[-1].unrealized_pnl == 0.0


# ── R6 방금 산 종목 ─────────────────────────────────────────────────────


async def test_r6_symbol_bought_after_sync_counts_at_average(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 60_000.0})
    h.ul(0.05)
    await h.fill(B, 10, 90_000.0)

    await h.order(C)

    assert len(h.validated) == 1
    assert h.rec.contexts[-1].unrealized_pnl == 0.0

    await h.sync({A: 60_000.0, B: 80_000.0})
    await h.order(C)

    assert h.rec.contexts[-1].unrealized_pnl == -100_000.0
    assert _ul_rejected(h)


# ── R7 동기화가 본 종목 ─────────────────────────────────────────────────


async def test_r7_seen_symbol_without_price_rejects(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 0.0} if h.live else {})
    h.ul(0.05)

    await h.order(B)
    assert h.reasons() == [f"{PREFIX}: {A}: {SYNCED_PRICE_MISSING}"]

    await h.fill(A, 1, 60_000.0)
    await h.order(B)
    assert h.reasons()[-1] == f"{PREFIX}: {A}: {SYNCED_PRICE_MISSING}"
    assert h.validated == []


async def test_r7_stale_price_rejects(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 60_000.0})
    h.ul(0.05)
    h.clk.mono += 2 * INTERVAL + 1

    await h.order(B)

    assert h.reasons() == [f"{PREFIX}: {A}: {SYNCED_PRICE_STALE}"]
    assert h.validated == []


async def test_r7b_internal_only_symbol_is_seen_in_live(live: _H) -> None:
    await live.fill(A, 10, 60_000.0)
    await live.fill(C, 10, 60_000.0)
    await live.sync({C: 60_000.0})
    assert {r["pdno"] for r in live.http.rows} == {C}
    live.ul(0.05)

    for _ in range(2):
        await live.fill(A, 1, 60_000.0)
        await live.order(B)
        assert live.reasons()[-1] == f"{PREFIX}: {A}: {SYNCED_PRICE_MISSING}"
    assert live.validated == []


async def test_live_symbol_key_matches_internal_symbol(live: _H) -> None:
    await live.fill(A, 10, 60_000.0)
    await live.sync({A: 55_000.0})

    held = await live.position_history.get_all_positions(account_id=ACCT)
    broker = await live.adapter.get_positions()
    assert {p.symbol for p in held} == {r["symbol"] for r in broker} == {A}
    assert live.treasury.get_synced_price(A) == (55_000.0, None)


# ── R8 성공한 동기화 없음 ───────────────────────────────────────────────


async def test_r8_restart_rejects_even_after_restored_last_synced_at(
    h: _H, db: Database, clk: _Clock
) -> None:
    await h.sync({})
    await h.fill(B, 10, 60_000.0)

    restarted = _H(db, clk, live=h.live)
    await restarted.start(budget=None)
    assert restarted.treasury.last_synced_at is not None
    restarted.ul(0.05)

    await restarted.order(C)

    assert restarted.reasons() == [f"{PREFIX}: {B}: {SYNCED_PRICE_MISSING}"]


async def test_r8_coverage_expires_after_two_intervals(h: _H) -> None:
    await h.sync({})
    await h.fill(B, 10, 60_000.0)
    h.ul(0.05)

    h.clk.mono += 2 * INTERVAL
    await h.order(C)
    assert len(h.validated) == 1

    h.clk.mono += 1
    await h.order(C)
    assert h.reasons() == [f"{PREFIX}: {B}: {SYNCED_PRICE_MISSING}"]


async def test_r8_restart_of_sync_clears_coverage(h: _H) -> None:
    await h.sync({})
    await h.fill(B, 10, 60_000.0)
    h.ul(0.05)
    h.treasury.start_sync(
        h.adapter if h.live else None,
        h.position_history,
        interval_seconds=INTERVAL,
        trading_mode="live" if h.live else "virtual",
    )
    await h.treasury.stop_sync()

    await h.order(C)

    assert h.reasons() == [f"{PREFIX}: {B}: {SYNCED_PRICE_MISSING}"]


# ── R9 변경 시각을 믿을 수 없음 ─────────────────────────────────────────


@pytest.mark.parametrize("value", [None, "", "garbage", "FUTURE"])
async def test_r9_untrusted_updated_at_rejects(h: _H, value: str | None) -> None:
    await h.sync({})
    await h.fill(B, 10, 60_000.0)
    h.ul(0.05)
    if value == "FUTURE":
        value = (h.clk.at + timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")
    await h.set_updated_at(B, value)

    await h.order(C)

    assert h.reasons() == [f"{PREFIX}: {B}: {SYNCED_PRICE_MISSING}"]


@pytest.mark.parametrize(
    ("stamp", "passes"),
    [("2026-01-02 12:00:00", False), ("2026-01-02 12:00:01", True)],
)
async def test_r9b_same_second_as_entry_rejects(
    h: _H, stamp: str, passes: bool
) -> None:
    entry = datetime(2026, 1, 2, 12, 0, 0, 0, tzinfo=UTC)
    h.clk.at = entry
    if h.live:
        await h.treasury._do_sync(h.adapter, h.position_history)
    else:
        await h.treasury._do_sync_virtual(h.position_history, h._virtual)
    await h.fill(B, 10, 60_000.0)
    await h.set_updated_at(B, stamp)
    h.clk.at = entry + timedelta(hours=1)
    h.ul(0.05)

    await h.order(C)

    assert (len(h.validated) == 1) is passes


async def test_updated_at_with_timezone_is_honoured(h: _H) -> None:
    entry = datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)
    h.clk.at = entry
    if h.live:
        await h.treasury._do_sync(h.adapter, h.position_history)
    else:
        await h.treasury._do_sync_virtual(h.position_history, h._virtual)
    await h.fill(B, 10, 60_000.0)
    await h.set_updated_at(B, "2026-01-02T21:30:00+09:00")
    h.clk.at = entry + timedelta(hours=1)
    h.ul(0.05)

    await h.order(C)

    assert len(h.validated) == 1


# ── R10 사유·알림·매도·우선순위·예외 ─────────────────────────────────────


async def test_r10_first_failure_in_sorted_order_and_no_notification(h: _H) -> None:
    await h.fill(C, 10, 60_000.0)
    await h.fill(B, 10, 60_000.0)
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 60_000.0})
    h.ul(0.05)

    await h.order(A)

    assert h.reasons() == [f"{PREFIX}: {B}: {SYNCED_PRICE_MISSING}"]
    assert h.notifications == []
    assert h.rec.contexts == []


async def test_r10_sell_passes_when_quotes_missing(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({})
    h.ul(0.05)

    await h.order(A, side="sell")

    assert len(h.validated) == 1


async def test_r10_account_not_ready_wins(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({})
    h.ul(0.05)

    async def _boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("positions down")

    h.trade_service.get_positions = _boom  # type: ignore[method-assign]
    await h.order(B)

    assert h.reasons() == ["account_not_ready: positions_unavailable"]
    assert h.reads == {"price": 0, "coverage": 0}


async def test_r10_market_quote_failure_wins(h: _H) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({})
    h.ul(0.05)

    async def _down(symbol: str) -> float:
        raise RuntimeError("down")

    h.engine.set_market_price_resolver(_down)
    await h.order(B, order_type="market")

    assert h.reasons() == ["market_buy_quote_unavailable: down"]
    assert h.reads == {"price": 0, "coverage": 0}


async def test_r10_treasury_exceptions_reject_buy_but_not_sell(h: _H) -> None:
    await h.sync({})
    await h.fill(B, 10, 60_000.0)
    h.ul(0.05)

    def _raise(*args: Any) -> Any:
        raise RuntimeError("treasury broke")

    h.treasury.get_last_sync_coverage = _raise  # type: ignore[method-assign]
    await h.order(C)
    assert h.reasons() == [PREFLIGHT_ERROR]

    h.treasury.get_last_sync_coverage = lambda: None  # type: ignore[method-assign]
    h.treasury.get_synced_price = _raise  # type: ignore[method-assign]
    await h.order(C)
    assert h.reasons() == [PREFLIGHT_ERROR, PREFLIGHT_ERROR]
    assert h.validated == []

    await h.order(B, side="sell")
    assert len(h.validated) == 1


@pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf"), True, "1"])
async def test_r10_bad_synced_value_is_missing(h: _H, bad: Any) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.sync({A: 60_000.0})
    h.ul(0.05)
    h.treasury.get_synced_price = lambda symbol: (bad, None)  # type: ignore[method-assign]

    await h.order(B)

    assert h.reasons() == [f"{PREFIX}: {A}: {SYNCED_PRICE_MISSING}"]


# ── R11 평가 경로의 외부 호출 ───────────────────────────────────────────


@pytest.mark.parametrize("order_type", ["limit", "market"])
async def test_r11_evaluation_adds_no_broker_or_gateway_call(
    h: _H, order_type: str
) -> None:
    await h.fill(A, 10, 60_000.0)
    await h.fill(C, 10, 60_000.0)
    await h.sync({A: 60_000.0, C: 60_000.0})
    h.ul(0.05)
    http_before = h.http.calls
    virtual_before = h.virtual_calls

    await h.order(B, order_type=order_type)

    assert len(h.validated) == 1
    assert h.http.calls == http_before
    assert h.virtual_calls == virtual_before
    assert h.market_calls == ([B] if order_type == "market" else [])


# ── Treasury: 성공한 동기화의 범위 ──────────────────────────────────────


async def test_coverage_is_none_before_any_sync(h: _H) -> None:
    assert h.treasury.get_last_sync_coverage() is None


async def test_coverage_holds_entry_wall_and_union(live: _H) -> None:
    await live.fill(A, 10, 60_000.0)
    real = await live.db_now()
    live.clk.at = real
    live.http.rows = [_kis_row(C, 1.0, 1.0)]

    await live.treasury._do_sync(live.adapter, live.position_history)

    assert live.treasury.get_last_sync_coverage() == (real, frozenset({A, C}))


async def test_coverage_not_updated_by_failed_sync(live: _H) -> None:
    await live.sync({A: 1.0})
    before = live.treasury.get_last_sync_coverage()
    assert before is not None

    async def _fail(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("positions down")

    live.adapter._request_paginated = _fail  # type: ignore[method-assign]
    live.clk.at += timedelta(seconds=30)
    with pytest.raises(RuntimeError):
        await live.treasury._do_sync(live.adapter, live.position_history)

    assert live.treasury.get_last_sync_coverage() == before


@pytest.mark.parametrize("mode", ["live", "virtual"])
async def test_coverage_not_updated_when_failing_before_prune(
    db: Database, clk: _Clock, mode: str
) -> None:
    h = _H(db, clk, live=mode == "live")
    await h.start()
    await h.sync({A: 1.0})
    before = h.treasury.get_last_sync_coverage()

    async def _fail(event: Any) -> None:
        raise RuntimeError("bus down")

    await h.fill(B, 1, 1.0)
    h.treasury._eventbus.publish = _fail  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        await h.sync({A: 1.0, B: 1.0})

    assert h.treasury.get_last_sync_coverage() == before


@pytest.mark.parametrize("interval", [0, -1, float("nan"), "300", None])
async def test_coverage_none_for_bad_interval(h: _H, interval: Any) -> None:
    await h.sync({})
    h.treasury._sync_interval_seconds = interval

    assert h.treasury.get_last_sync_coverage() is None


async def test_stop_sync_clears_coverage(virtual: _H) -> None:
    await virtual.sync({})
    assert virtual.treasury.get_last_sync_coverage() is not None

    await virtual.treasury.stop_sync()

    assert virtual.treasury.get_last_sync_coverage() is None
