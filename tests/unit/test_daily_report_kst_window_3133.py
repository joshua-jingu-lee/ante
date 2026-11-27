"""일일 보고가 보고 날짜의 KST 하루 체결을 센다 (#3133).

스펙: `docs/specs/trade/07-notification-events.md` 「일일 성과 요약」.
보고의 거래 수·순매수·실현 손익은 KST ``[D 00:00, D+1 00:00)``의 체결이다.
실제 Database·FillApplier·TradeRecorder·PositionHistory·PerformanceTracker·
DailyReportScheduler로 돌고, 체결 시각은 시계 대역의 ``clock.now(UTC)``다.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import UTC, date, datetime, time, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.core import clock
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import DailyReportEvent, NotificationEvent
from ante.member.models import Member, MemberRole, MemberType
from ante.trade.daily_report import DailyReportScheduler
from ante.trade.fill_applier import FillApplier
from ante.trade.fill_outbox import FillOutbox
from ante.trade.models import TradeStatus
from ante.trade.order_tracker import OrderTracker
from ante.trade.performance import PerformanceTracker
from ante.trade.position import PositionHistory
from ante.trade.recorder import TradeRecorder
from tests.conftest import ManualClock

KST = timezone(timedelta(hours=9))
ACCT = "test"
BOT = "bot-r"
SYMBOL = "000001"
BUY_PRICE = 1_000.0


def _kst(
    month: int, day: int, hour: int, minute: int = 0, second: int = 0, us: int = 0
) -> datetime:
    return datetime(2026, month, day, hour, minute, second, us, tzinfo=KST)


class _Stack:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.bus = EventBus()
        self.positions = PositionHistory(db)
        self.recorder = TradeRecorder(db, self.positions)
        self.tracker = OrderTracker(db)
        self.outbox = FillOutbox(db)
        self.applier = FillApplier(
            db=db,
            order_tracker=self.tracker,
            position_history=self.positions,
            eventbus=self.bus,
            outbox=self.outbox,
        )
        self.performance = PerformanceTracker(db)
        self.scheduler = DailyReportScheduler(
            performance_tracker=self.performance,
            trade_recorder=self.recorder,
            position_history=self.positions,
            eventbus=self.bus,
            account_id=ACCT,
            report_time=time(0, 29),
        )
        self.reports: list[DailyReportEvent] = []
        self.notices: list[NotificationEvent] = []

    async def start(self) -> None:
        await self.positions.initialize()
        await self.recorder.initialize()
        await self.tracker.initialize()
        await self.outbox.initialize()
        self.bus.subscribe(DailyReportEvent, self.reports.append)
        self.bus.subscribe(NotificationEvent, self.notices.append)

    async def fill(
        self, order_id: str, side: str, at: datetime, price: float, qty: float = 1.0
    ) -> None:
        with clock.use_clock(ManualClock(at)):
            await self.applier.apply_direct_fill(
                account_id=ACCT,
                order_id=order_id,
                bot_id=BOT,
                strategy_id="s1",
                symbol=SYMBOL,
                side=side,
                quantity=qty,
                price=price,
                commission=0.0,
                order_type="limit",
                exchange="KRX",
                timestamp=clock.now(UTC),
            )

    async def stored(self) -> dict[str, str]:
        rows = await self.db.fetch_all("SELECT order_id, timestamp FROM trades")
        return {r["order_id"]: r["timestamp"] for r in rows}

    async def report(self, target: date, now: datetime) -> tuple[Any, list[str]]:
        self.reports.clear()
        self.notices.clear()
        with clock.use_clock(ManualClock(now)):
            await self.scheduler.run_once(target_date=target)
            start = datetime.combine(target, time.min, tzinfo=KST)
            trades = await self.recorder.get_trades(
                account_id=ACCT,
                status=TradeStatus.FILLED,
                from_date=start,
                to_date=datetime.combine(target, time.max, tzinfo=KST),
                limit=10000,
            )
        (event,) = self.reports
        return event, sorted(t.order_id for t in trades if t.order_id)


@pytest.fixture
async def stack(tmp_path) -> Any:
    db = Database(str(tmp_path / "report.db"))
    await db.connect()
    try:
        s = _Stack(db)
        await s.start()
        yield s
    finally:
        await db.close()


def _pnl_line(notice: NotificationEvent) -> str:
    (line,) = [ln for ln in notice.message.splitlines() if ln.startswith("실현 손익")]
    return line


async def test_stored_fill_times_are_utc(stack: _Stack) -> None:
    await stack.fill("buy", "buy", _kst(11, 26, 10), BUY_PRICE, qty=10.0)
    await stack.fill("a", "sell", _kst(11, 27, 8, 30), 1_010.0)

    stored = await stack.stored()

    assert stored == {
        "buy": "2026-11-26T01:00:00+00:00",
        "a": "2026-11-26T23:30:00+00:00",
    }


async def test_kst_morning_fill_counts_in_its_day(stack: _Stack) -> None:
    await stack.fill("buy", "buy", _kst(11, 26, 10), BUY_PRICE, qty=10.0)
    await stack.fill("a", "sell", _kst(11, 27, 8, 30), 1_010.0)
    await stack.fill("b", "sell", _kst(11, 27, 9, 30), 1_011.0)
    await stack.fill("c", "sell", _kst(11, 27, 23, 30), 1_012.0)

    event, _ = await stack.report(date(2026, 11, 27), _kst(11, 28, 12))

    assert event.trade_count == 3
    assert event.has_trades is True
    assert event.net_trade_amount == pytest.approx(-(1_010.0 + 1_011.0 + 1_012.0))
    (notice,) = stack.notices
    assert "거래: 3건 (매수 0 / 매도 3)" in notice.message
    assert _pnl_line(notice) == "실현 손익: +33원"
    start = _kst(11, 27, 0)
    assert await stack.performance.get_realized_pnl(
        account_id=ACCT, start=start, end=start + timedelta(days=1)
    ) == pytest.approx(33.0)


async def test_realized_pnl_queries_agree_on_a_utc_aligned_day(
    stack: _Stack,
) -> None:
    await stack.fill("buy", "buy", _kst(11, 26, 10), BUY_PRICE, qty=10.0)
    await stack.fill("b", "sell", _kst(11, 27, 9, 30), 1_011.0)
    await stack.fill("c", "sell", _kst(11, 27, 23, 30), 1_012.0)

    (summary,) = await stack.performance.get_daily_summary(
        start_date="2026-11-27", end_date="2026-11-27", account_id=ACCT
    )
    start = datetime(2026, 11, 27, tzinfo=UTC)
    realized = await stack.performance.get_realized_pnl(
        account_id=ACCT, start=start, end=start + timedelta(days=1)
    )

    assert summary.realized_pnl == pytest.approx(23.0)
    assert realized == pytest.approx(summary.realized_pnl)


async def test_day_edges_include_and_exclude(stack: _Stack) -> None:
    await stack.fill("buy", "buy", _kst(11, 26, 10), BUY_PRICE, qty=10.0)
    await stack.fill("x-prev-2330", "sell", _kst(11, 26, 23, 30), 1_001.0)
    await stack.fill("x-prev-2359", "sell", _kst(11, 26, 23, 59), 1_002.0)
    await stack.fill("in-0000", "sell", _kst(11, 27, 0), 1_010.0)
    await stack.fill("in-2359", "sell", _kst(11, 27, 23, 59, 59, 999_999), 1_020.0)
    await stack.fill("x-next-0000", "sell", _kst(11, 28, 0), 1_003.0)
    await stack.fill("x-next-0830", "sell", _kst(11, 28, 8, 30), 1_004.0)

    event, ids = await stack.report(date(2026, 11, 27), _kst(11, 28, 12))

    assert ids == ["in-0000", "in-2359"]
    assert event.trade_count == 2
    assert event.net_trade_amount == pytest.approx(-(1_010.0 + 1_020.0))
    (notice,) = stack.notices
    assert _pnl_line(notice) == "실현 손익: +30원"


async def test_after_midnight_reports_miss_no_fill(stack: _Stack) -> None:
    await stack.fill("buy", "buy", _kst(11, 25, 10), BUY_PRICE, qty=10.0)
    await stack.fill("d-0010", "sell", _kst(11, 26, 0, 10), 1_001.0)
    await stack.fill("d-2359", "sell", _kst(11, 26, 23, 59), 1_002.0)
    await stack.fill("e-0010", "sell", _kst(11, 27, 0, 10), 1_003.0)

    first, first_ids = await stack.report(date(2026, 11, 26), _kst(11, 27, 0, 29))
    await stack.fill("e-0500", "sell", _kst(11, 27, 5), 1_004.0)
    second, second_ids = await stack.report(date(2026, 11, 27), _kst(11, 28, 0, 29))

    assert first_ids == ["d-0010", "d-2359"]
    assert first.trade_count == 2
    assert second_ids == ["e-0010", "e-0500"]
    assert second.trade_count == 2
    sells = {k for k in await stack.stored() if k != "buy"}
    assert set(first_ids) | set(second_ids) == sells


async def _seed_edges(stack: _Stack) -> None:
    await stack.fill("buy", "buy", _kst(11, 26, 10), BUY_PRICE, qty=10.0)
    await stack.fill("x-prev-2359", "sell", _kst(11, 26, 23, 59), 1_002.0)
    await stack.fill("in-0000", "sell", _kst(11, 27, 0), 1_010.0)
    await stack.fill("in-2359", "sell", _kst(11, 27, 23, 59, 59, 999_999), 1_020.0)
    await stack.fill("x-next-0000", "sell", _kst(11, 28, 0), 1_003.0)
    await stack.fill("x-next-0830", "sell", _kst(11, 28, 8, 30), 1_004.0)


_KST_FROM = datetime.combine(date(2026, 11, 27), time.min, tzinfo=KST)
_KST_TO = datetime.combine(date(2026, 11, 27), time.max, tzinfo=KST)


async def test_get_trades_kst_bounds_equal_utc_bounds(stack: _Stack) -> None:
    await _seed_edges(stack)

    async def ids(from_date: datetime, to_date: datetime) -> list[str]:
        trades = await stack.recorder.get_trades(
            account_id=ACCT, from_date=from_date, to_date=to_date
        )
        return sorted(t.order_id for t in trades if t.order_id)

    kst = await ids(_KST_FROM, _KST_TO)
    utc = await ids(_KST_FROM.astimezone(UTC), _KST_TO.astimezone(UTC))

    assert kst == utc == ["in-0000", "in-2359"]


async def test_calculate_kst_bounds_equal_utc_bounds(stack: _Stack) -> None:
    await _seed_edges(stack)

    kst = await stack.performance.calculate(
        account_id=ACCT, from_date=_KST_FROM, to_date=_KST_TO
    )
    utc = await stack.performance.calculate(
        account_id=ACCT,
        from_date=_KST_FROM.astimezone(UTC),
        to_date=_KST_TO.astimezone(UTC),
    )
    everything = await stack.performance.calculate(account_id=ACCT)

    assert kst == utc
    assert kst.total_trades == 2
    assert everything.total_trades == 5


# ── CLI 거래 목록의 날짜 인자는 결과가 그대로다 ─────────────────────────────

_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)


def _runner() -> CliRunner:
    if "mix_stderr" in inspect.signature(CliRunner).parameters:
        return CliRunner(mix_stderr=False)
    return CliRunner()


def _trade_list(config_dir: str, *args: str) -> list[str]:
    def _set_member(ctx: Any) -> None:
        ctx.ensure_object(dict)
        ctx.obj["member"] = _MASTER

    with (
        patch("ante.cli.main.authenticate_member", side_effect=_set_member),
        patch("ante.cli.middleware._run_authenticate"),
    ):
        result = _runner().invoke(
            cli,
            ["--config-dir", config_dir, "--format", "json", "trade", "list", *args],
        )
    assert result.exit_code == 0, result.output
    return [t["trade_id"] for t in json.loads(result.stdout)["data"]["trades"]]


async def _seed_cli_db(path: str) -> dict[str, str]:
    db = Database(path)
    await db.connect()
    try:
        s = _Stack(db)
        await s.start()
        await s.fill("buy", "buy", datetime(2026, 11, 26, 1, tzinfo=UTC), 1_000.0, 10)
        for order_id, at in (
            ("utc-prev-1430", datetime(2026, 11, 26, 14, 30, tzinfo=UTC)),
            ("utc-prev-1600", datetime(2026, 11, 26, 16, tzinfo=UTC)),
            ("utc-prev-2350", datetime(2026, 11, 26, 23, 50, tzinfo=UTC)),
            ("utc-day-0000", datetime(2026, 11, 27, 0, tzinfo=UTC)),
            ("utc-day-1000", datetime(2026, 11, 27, 10, tzinfo=UTC)),
            ("utc-day-2359", datetime(2026, 11, 27, 23, 59, 59, 999_999, tzinfo=UTC)),
            ("utc-next-0000", datetime(2026, 11, 28, 0, tzinfo=UTC)),
        ):
            await s.fill(order_id, "sell", at, 1_001.0)
        rows = await db.fetch_all("SELECT trade_id, order_id FROM trades")
        return {r["trade_id"]: r["order_id"] for r in rows}
    finally:
        await db.close()


def test_cli_trade_list_same_day_range_is_the_utc_day(tmp_path) -> None:
    (tmp_path / "db").mkdir()
    order_of = asyncio.run(_seed_cli_db(str(tmp_path / "db" / "ante.db")))

    trade_ids = _trade_list(str(tmp_path), "--from", "2026-11-27", "--to", "2026-11-27")

    assert sorted(order_of[t] for t in trade_ids) == [
        "utc-day-0000",
        "utc-day-1000",
        "utc-day-2359",
    ]
