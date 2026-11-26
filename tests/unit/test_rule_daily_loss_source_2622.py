"""일일 손실 한도의 분자·분모 출처 (#2622).

스펙: `docs/specs/rule-engine/06-rule-catalog.md` 「용어 산식」,
`07-rule-engine-core.md` 「판정 입력 조회 실패」.
분자는 KST 오늘의 체결 매도 실현 손익 합, 분모는 KST 오늘 이전의 가장 최근
일별 스냅샷의 ``total_asset``이다. 실제 Database·Treasury·FillApplier·
PositionHistory·PerformanceTracker·TradeService로 돈다.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Any

import pytest

from ante.account.models import TradingMode
from ante.bot.providers.virtual import VirtualExecutor
from ante.core import clock
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderFailedEvent,
    OrderFilledEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderValidatedEvent,
)
from ante.rule import RuleEngine
from ante.rule.base import Rule, RuleAction, RuleContext, RuleEvaluation, RuleResult
from ante.rule.global_rules import DailyLossLimitRule
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import FillOutbox
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from ante.trade.service import TradeService
from ante.treasury.treasury import Treasury
from tests.unit._readiness_gate_helpers import make_account, ready_registry
from tests.unit._rule_engine_helpers import StubTreasury

KST = timezone(timedelta(hours=9))
ACCT = "test"
OTHER_ACCT = "other"
BOT = "bot-d"
SYMBOL = "000001"
ENGINE_LOGGER = "ante.rule.engine"
SKIP_WARNING = "일일 손실 판정 건너뜀"

# 2026-01-02 12:00 KST (manual_clock 기본값)
TODAY_KST = "2026-01-02"


class _UtcHostClock:
    """호스트 TZ=UTC를 흉내 낸다: ``now(None)``이 UTC naive를 돌려준다."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self, tz: tzinfo | None) -> datetime:
        if tz is None:
            return self._at.astimezone(UTC).replace(tzinfo=None)
        return self._at.astimezone(tz)

    def monotonic(self) -> float:
        return 1000.0


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


def _account_service() -> Any:
    from unittest.mock import AsyncMock, MagicMock

    svc = MagicMock()
    svc.get = AsyncMock(
        return_value=make_account(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
    )
    return svc


class _Stack:
    def __init__(self, db: Database) -> None:
        self.db = db
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
        self.registry = ready_registry(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
        self.treasury = Treasury(
            db,
            self.bus,
            account_id=ACCT,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            runtime_readiness=self.registry,
            broker_type="test",
            trading_mode=TradingMode.VIRTUAL,
        )
        self.performance = PerformanceTracker(db)
        self.trade_service = TradeService(
            self.recorder, self.position_history, self.performance
        )
        self.engine = RuleEngine(
            eventbus=self.bus,
            account_id=ACCT,
            treasury=self.treasury,
            trade_service=self.trade_service,
            account=make_account(
                ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
            ),
            runtime_readiness=self.registry,
        )
        self.rec = _Recorder()
        self.validated: list[OrderValidatedEvent] = []
        self.rejected: list[OrderRejectedEvent] = []
        self.modify_rejected: list[OrderModifyRejectedEvent] = []
        self.events: list[Any] = []

    async def start(self) -> None:
        await self.position_history.initialize()
        await self.recorder.initialize()
        await self.tracker.initialize()
        await self.outbox.initialize()
        await self.treasury.initialize()
        await self.treasury.set_account_balance(10_000_000.0)
        await self.treasury.allocate(BOT, 1_000_000.0)
        self.engine.add_account_rule(self.rec)
        self.engine.start()
        self.bus.subscribe(OrderValidatedEvent, self.validated.append, priority=-1000)
        self.bus.subscribe(OrderRejectedEvent, self.rejected.append, priority=-1000)
        self.bus.subscribe(
            OrderModifyRejectedEvent, self.modify_rejected.append, priority=-1000
        )
        for cls in (OrderFilledEvent, OrderFailedEvent):
            self.bus.subscribe(cls, self.events.append, priority=-1000)

    def add_daily_loss_rule(self, **config: Any) -> None:
        self.engine.add_account_rule(
            DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05, **config})
        )

    async def snapshot(
        self, snapshot_date: str, total_asset: float, daily_pnl: float = 0.0
    ) -> None:
        await self.db.execute(
            """INSERT INTO treasury_daily_snapshots
               (account_id, snapshot_date, total_asset, daily_pnl)
               VALUES (?, ?, ?, ?)""",
            (ACCT, snapshot_date, total_asset, daily_pnl),
        )

    async def round_trip(
        self,
        tag: str,
        *,
        buy_at: datetime,
        sell_at: datetime,
        loss: float,
        account_id: str = ACCT,
    ) -> None:
        """10주를 70,000에 사서 ``loss``만큼 손실을 내고 판다(수수료 0)."""
        common: dict[str, Any] = {
            "account_id": account_id,
            "bot_id": BOT,
            "strategy_id": "s1",
            "symbol": SYMBOL,
            "quantity": 10.0,
            "commission": 0.0,
            "order_type": "limit",
            "exchange": "KRX",
        }
        await self.applier.apply_direct_fill(
            **common,
            order_id=f"{tag}-buy",
            side="buy",
            price=70_000.0,
            timestamp=buy_at,
        )
        await self.applier.apply_direct_fill(
            **common,
            order_id=f"{tag}-sell",
            side="sell",
            price=70_000.0 - loss / 10.0,
            timestamp=sell_at,
        )

    async def buy(self, price: float = 10_000.0) -> None:
        await self.bus.publish(_order("buy", price))


def _order(side: str, price: float, quantity: float = 1.0) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCT,
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side=side,
        quantity=quantity,
        order_type="limit",
        price=price,
    )


@pytest.fixture
async def db(tmp_path) -> Any:
    database = Database(str(tmp_path / "daily_loss.db"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
async def stack(db: Database, manual_clock: Any) -> _Stack:
    s = _Stack(db)
    await s.start()
    return s


def _kst(day: int, hour: int, minute: int = 0, month: int = 1) -> datetime:
    return datetime(2026, month, day, hour, minute, tzinfo=KST).astimezone(UTC)


def _skip_warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        r
        for r in caplog.records
        if r.name == ENGINE_LOGGER
        and r.levelno == logging.WARNING
        and SKIP_WARNING in r.getMessage()
    ]


# ── T1·T2: 당일 실현 손익이 분자다 ─────────────────────────────────────────


async def test_t1_todays_realized_loss_over_limit_rejects_buy(stack: _Stack) -> None:
    await stack.snapshot("2026-01-01", 1_000_000.0, daily_pnl=-10_000.0)
    await stack.round_trip(
        "t1", buy_at=_kst(2, 9, 10), sell_at=_kst(2, 10), loss=100_000.0
    )
    stack.add_daily_loss_rule()

    await stack.buy()

    assert stack.validated == []
    assert len(stack.rejected) == 1
    assert "Daily loss limit exceeded: 10.00% > 5.00%" in stack.rejected[0].reason
    (ctx,) = stack.rec.contexts
    assert ctx.daily_pnl == pytest.approx(-100_000.0)
    assert ctx.prev_day_total_asset == pytest.approx(1_000_000.0)


async def test_t2_only_yesterdays_loss_over_limit_validates_buy(
    stack: _Stack,
) -> None:
    await stack.snapshot("2026-01-01", 1_000_000.0, daily_pnl=-100_000.0)
    await stack.round_trip(
        "t2", buy_at=_kst(2, 9, 10), sell_at=_kst(2, 10), loss=10_000.0
    )
    stack.add_daily_loss_rule()

    await stack.buy()

    assert stack.rejected == []
    assert len(stack.validated) == 1
    (ctx,) = stack.rec.contexts
    assert ctx.daily_pnl == pytest.approx(-10_000.0)


# ── T3: 날짜는 KST로 자른다 ───────────────────────────────────────────────


@pytest.fixture
def utc_host_clock() -> Iterator[_UtcHostClock]:
    host = _UtcHostClock(datetime(2026, 11, 25, 23, 30, tzinfo=UTC))
    with clock.use_clock(host):
        yield host


async def test_t3_kst_day_with_utc_host(db: Database, utc_host_clock: Any) -> None:
    s = _Stack(db)
    await s.start()
    await s.snapshot("2026-11-24", 2_000_000.0)
    await s.snapshot("2026-11-25", 1_000_000.0)
    await s.round_trip(
        "prev",
        buy_at=datetime(2026, 11, 25, 14, 0, tzinfo=UTC),
        sell_at=datetime(2026, 11, 25, 14, 30, tzinfo=UTC),
        loss=40_000.0,
    )
    await s.round_trip(
        "today",
        buy_at=datetime(2026, 11, 25, 22, 0, tzinfo=UTC),
        sell_at=datetime(2026, 11, 25, 23, 0, tzinfo=UTC),
        loss=60_000.0,
    )
    s.add_daily_loss_rule()

    await s.buy()

    (ctx,) = s.rec.contexts
    assert ctx.daily_pnl == pytest.approx(-60_000.0)
    assert ctx.prev_day_total_asset == pytest.approx(1_000_000.0)
    assert len(s.rejected) == 1
    assert "6.00% > 5.00%" in s.rejected[0].reason


# ── T4: 며칠 묵은 스냅샷, 오늘 행은 쓰지 않는다 ─────────────────────────────


async def test_t4_stale_snapshot_is_denominator_and_today_row_ignored(
    stack: _Stack,
) -> None:
    await stack.snapshot("2025-12-30", 1_000_000.0)
    await stack.snapshot(TODAY_KST, 5_000_000.0, daily_pnl=0.0)
    await stack.round_trip(
        "t4", buy_at=_kst(2, 9, 10), sell_at=_kst(2, 10), loss=60_000.0
    )
    stack.add_daily_loss_rule()

    await stack.buy()

    (ctx,) = stack.rec.contexts
    assert ctx.prev_day_total_asset == pytest.approx(1_000_000.0)
    assert len(stack.rejected) == 1


# ── T5: 분모가 없으면 건너뛰고, 규칙이 켜진 계좌에서만 warning ─────────────


@pytest.mark.parametrize("rows", [[], [("2026-01-01", 0.0)]], ids=["none", "zero"])
async def test_t5_missing_denominator_passes_with_warning(
    stack: _Stack, caplog: pytest.LogCaptureFixture, rows: list[tuple[str, float]]
) -> None:
    for snapshot_date, total_asset in rows:
        await stack.snapshot(snapshot_date, total_asset)
    await stack.round_trip(
        "t5", buy_at=_kst(2, 9, 10), sell_at=_kst(2, 10), loss=100_000.0
    )
    stack.add_daily_loss_rule()
    caplog.set_level(logging.WARNING, logger=ENGINE_LOGGER)

    await stack.buy()

    assert stack.rejected == []
    assert len(stack.validated) == 1
    (record,) = _skip_warnings(caplog)
    assert ACCT in record.getMessage()


@pytest.mark.parametrize("rule", ["absent", "disabled"])
async def test_t5_no_warning_without_active_rule(
    stack: _Stack, caplog: pytest.LogCaptureFixture, rule: str
) -> None:
    if rule == "disabled":
        stack.add_daily_loss_rule(enabled=False)
    caplog.set_level(logging.WARNING, logger=ENGINE_LOGGER)

    await stack.buy()

    assert len(stack.validated) == 1
    assert _skip_warnings(caplog) == []


# ── T6: 가상 계좌의 체결 경로 끝까지 ───────────────────────────────────────


async def test_t6_virtual_fills_end_to_end_reject_buy(stack: _Stack) -> None:
    executor = VirtualExecutor(
        eventbus=stack.bus,
        runtime_readiness=stack.registry,
        account_service=_account_service(),
        fill_applier=stack.applier,
    )
    executor.register_bot(BOT)
    executor.subscribe()
    await stack.snapshot("2026-01-01", 1_000_000.0, daily_pnl=-10_000.0)

    await stack.bus.publish(_order("buy", 70_000.0, quantity=10.0))
    await stack.bus.publish(_order("sell", 60_000.0, quantity=10.0))
    fills = [e for e in stack.events if isinstance(e, OrderFilledEvent)]
    assert [e.side for e in fills] == ["buy", "sell"]
    stack.add_daily_loss_rule()

    sell = await stack.db.fetch_one(
        "SELECT pnl FROM position_history WHERE action = 'sell'"
    )
    assert sell is not None
    assert sell["pnl"] < -100_000.0

    await stack.bus.publish(_order("buy", 10_000.0))

    assert len(stack.rejected) == 1
    assert "Daily loss limit exceeded" in stack.rejected[0].reason
    assert stack.rec.contexts[-1].daily_pnl == pytest.approx(sell["pnl"])


# ── 정정도 같은 당일 손익을 받는다 ────────────────────────────────────────


async def test_modify_buy_rejected_by_todays_realized_loss(stack: _Stack) -> None:
    await stack.snapshot("2026-01-01", 1_000_000.0)
    await stack.round_trip(
        "m", buy_at=_kst(2, 9, 10), sell_at=_kst(2, 10), loss=100_000.0
    )
    stack.add_daily_loss_rule()

    await stack.bus.publish(
        OrderModifyEvent(
            account_id=ACCT,
            bot_id=BOT,
            strategy_id="s1",
            order_id="o-1",
            symbol=SYMBOL,
            side="buy",
            quantity=1.0,
            price=9_000.0,
        )
    )

    assert len(stack.modify_rejected) == 1
    assert stack.rec.contexts[-1].daily_pnl == pytest.approx(-100_000.0)


# ── T8: PerformanceTracker.get_realized_pnl 단위 ──────────────────────────


async def test_t8_rejects_naive_datetime(stack: _Stack) -> None:
    with pytest.raises(ValueError):
        await stack.performance.get_realized_pnl(
            account_id=ACCT,
            start=datetime(2026, 1, 2),
            end=datetime(2026, 1, 3, tzinfo=KST),
        )


async def test_t8_kst_day_boundaries(stack: _Stack) -> None:
    await stack.round_trip(
        "at-start", buy_at=_kst(1, 23), sell_at=_kst(2, 0), loss=1_000.0
    )
    await stack.round_trip(
        "before", buy_at=_kst(1, 22), sell_at=_kst(1, 23, 59), loss=20_000.0
    )
    await stack.round_trip(
        "at-end", buy_at=_kst(2, 23), sell_at=_kst(3, 0), loss=300_000.0
    )

    total = await stack.performance.get_realized_pnl(
        account_id=ACCT,
        start=datetime(2026, 1, 2, tzinfo=KST),
        end=datetime(2026, 1, 3, tzinfo=KST),
    )

    assert total == pytest.approx(-1_000.0)


async def test_t8_matches_daily_summary_and_excludes_buys_and_other_accounts(
    stack: _Stack,
) -> None:
    await stack.round_trip("a", buy_at=_kst(2, 9), sell_at=_kst(2, 10), loss=7_000.0)
    await stack.round_trip("b", buy_at=_kst(2, 11), sell_at=_kst(2, 12), loss=-3_000.0)
    await stack.applier.apply_direct_fill(
        account_id=ACCT,
        order_id="open-buy",
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side="buy",
        quantity=1.0,
        price=70_000.0,
        commission=0.0,
        order_type="limit",
        exchange="KRX",
        timestamp=_kst(2, 13),
    )
    await stack.round_trip(
        "o",
        buy_at=_kst(2, 9),
        sell_at=_kst(2, 10),
        loss=50_000.0,
        account_id=OTHER_ACCT,
    )
    await stack.db.execute(
        """INSERT INTO position_history
           (bot_id, symbol, action, quantity, price, pnl, timestamp, account_id)
           VALUES (?, ?, 'buy', 1, 70000, -900000, ?, ?)""",
        (BOT, SYMBOL, _kst(2, 14).isoformat(), ACCT),
    )

    total = await stack.performance.get_realized_pnl(
        account_id=ACCT,
        start=datetime(2026, 1, 2, tzinfo=KST),
        end=datetime(2026, 1, 3, tzinfo=KST),
    )
    (summary,) = await stack.performance.get_daily_summary(
        start_date="2026-01-02", end_date="2026-01-02", account_id=ACCT
    )

    assert total == pytest.approx(-4_000.0)
    assert summary.realized_pnl == pytest.approx(total)


# ── 한 주문의 평가는 KST 오늘을 한 번만 읽는다 ─────────────────────────────


class _MidnightTreasury(StubTreasury):
    """분모 조회 중에 시계가 2초 나아간다(자정 직전이면 자정을 넘긴다)."""

    def __init__(self, manual: Any, total_asset: Any = 1_000_000.0) -> None:
        super().__init__(
            summary={
                "total_profit_loss": 0.0,
                "total_evaluation": 1_000_000.0,
                "ante_eval_amount": 0.0,
            },
            budget=1_000_000.0,
            prev_snapshot={"snapshot_date": "2026-01-01", "total_asset": total_asset},
        )
        self._manual = manual
        self.before_dates: list[str] = []

    async def get_prev_day_snapshot(self, before_date: str) -> dict[str, Any] | None:
        self.before_dates.append(before_date)
        self._manual.advance(2.0)
        return await super().get_prev_day_snapshot(before_date)


class _DateRecordingTradeService:
    def __init__(self, realized: Any = 0.0) -> None:
        self.realized = realized
        self.starts: list[datetime] = []

    async def get_positions(self, bot_id: str, *args: Any, **kwargs: Any) -> list:
        return []

    async def get_realized_pnl(
        self, *, account_id: str, start: datetime, end: datetime
    ) -> Any:
        self.starts.append(start)
        return self.realized


def _stub_engine(treasury: Any, trade_service: Any, *rules: Rule) -> EventBus:
    bus = EventBus()
    engine = RuleEngine(
        eventbus=bus,
        account_id=ACCT,
        treasury=treasury,
        trade_service=trade_service,
        account=make_account(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        ),
        runtime_readiness=ready_registry(
            ACCT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        ),
    )
    for rule in rules:
        engine.add_account_rule(rule)
    engine.start()
    return bus


def _modify(side: str = "buy") -> OrderModifyEvent:
    return OrderModifyEvent(
        account_id=ACCT,
        bot_id=BOT,
        strategy_id="s1",
        order_id=f"o-{side}",
        symbol=SYMBOL,
        side=side,
        quantity=1.0,
        price=9_000.0,
    )


@pytest.mark.parametrize(
    "manual_clock", [datetime(2026, 1, 2, 14, 59, 59, tzinfo=UTC)], indirect=True
)
async def test_one_kst_date_per_evaluation_across_midnight(manual_clock: Any) -> None:
    treasury = _MidnightTreasury(manual_clock)
    trade_service = _DateRecordingTradeService()
    bus = _stub_engine(treasury, trade_service)

    await bus.publish(_order("buy", 10_000.0))
    manual_clock.advance(24 * 3600.0 - 2.0)
    await bus.publish(
        OrderModifyEvent(
            account_id=ACCT,
            bot_id=BOT,
            strategy_id="s1",
            order_id="o-1",
            symbol=SYMBOL,
            side="buy",
            quantity=1.0,
            price=9_000.0,
        )
    )

    assert treasury.before_dates == [TODAY_KST, "2026-01-03"]
    assert [s.date().isoformat() for s in trade_service.starts] == [
        TODAY_KST,
        "2026-01-03",
    ]


# ── 수가 아니거나 유한하지 않은 실현 손익은 조회 실패와 같다 ───────────────
# bool은 int의 하위형이라 수로 통과한다(덜 바꾸는 쪽).


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, None, "x"])
async def test_non_finite_realized_pnl_is_query_failure(
    manual_clock: Any, value: Any
) -> None:
    rec = _Recorder()
    bus = _stub_engine(
        _MidnightTreasury(manual_clock),
        _DateRecordingTradeService(realized=value),
        rec,
    )
    rejected: list[OrderRejectedEvent] = []
    validated: list[OrderValidatedEvent] = []
    modify_rejected: list[OrderModifyRejectedEvent] = []
    bus.subscribe(OrderRejectedEvent, rejected.append)
    bus.subscribe(OrderValidatedEvent, validated.append)
    bus.subscribe(OrderModifyRejectedEvent, modify_rejected.append)

    await bus.publish(_order("buy", 10_000.0))
    await bus.publish(_order("sell", 10_000.0))
    for side in ("buy", "sell"):
        await bus.publish(_modify(side))

    assert [e.reason for e in rejected] == ["account_not_ready: positions_unavailable"]
    assert [e.side for e in validated] == ["sell"]
    assert modify_rejected == []
    assert [(c.side, c.daily_pnl) for c in rec.contexts] == [
        ("sell", 0.0),
        ("buy", 0.0),
        ("sell", 0.0),
    ]


# ── 수가 아니거나 유한하지 않은 분모는 스냅샷 없음과 같다 ──────────────────


@pytest.mark.parametrize("total_asset", [None, "x", math.nan, math.inf, True])
async def test_non_numeric_denominator_skips_judgment(
    manual_clock: Any, caplog: pytest.LogCaptureFixture, total_asset: Any
) -> None:
    rec = _Recorder()
    bus = _stub_engine(
        _MidnightTreasury(manual_clock, total_asset=total_asset),
        _DateRecordingTradeService(realized=-100_000.0),
        rec,
        DailyLossLimitRule("dl", {"max_daily_loss_percent": 0.05}),
    )
    rejected: list[OrderRejectedEvent] = []
    validated: list[OrderValidatedEvent] = []
    modify_rejected: list[OrderModifyRejectedEvent] = []
    bus.subscribe(OrderRejectedEvent, rejected.append)
    bus.subscribe(OrderValidatedEvent, validated.append)
    bus.subscribe(OrderModifyRejectedEvent, modify_rejected.append)
    caplog.set_level(logging.WARNING, logger=ENGINE_LOGGER)

    for side in ("buy", "sell"):
        await bus.publish(_order(side, 10_000.0))
        await bus.publish(_modify(side))

    assert rejected == []
    assert modify_rejected == []
    assert [e.side for e in validated] == ["buy", "sell"]
    assert {c.prev_day_total_asset for c in rec.contexts} == {0.0}
    assert len(_skip_warnings(caplog)) == 4
