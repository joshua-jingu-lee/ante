"""DailyReportScheduler 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ante.eventbus.bus import EventBus
from ante.eventbus.events import DailyReportEvent, NotificationEvent
from ante.trade.daily_report import (
    DEFAULT_REPORT_TIME,
    DailyReportScheduler,
    compute_report_time,
    format_currency,
)
from ante.trade.models import DailySummary, PositionSnapshot, TradeRecord, TradeStatus

KST = timezone(timedelta(hours=9))


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
def performance_tracker():
    mock = AsyncMock()
    mock.get_daily_summary = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def trade_recorder():
    mock = AsyncMock()
    mock.get_trades = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def position_history():
    mock = AsyncMock()
    mock.get_all_positions = AsyncMock(return_value=[])
    return mock


@pytest.fixture
def eventbus():
    return EventBus()


@pytest.fixture
def treasury():
    mock = AsyncMock()
    mock.get_summary = lambda: {
        "ante_eval_amount": 10_000_000.0,
        "ante_purchase_amount": 9_500_000.0,
    }
    mock.get_daily_snapshot = AsyncMock(return_value=None)
    mock.save_daily_snapshot = AsyncMock()
    return mock


@pytest.fixture
def scheduler(
    performance_tracker, trade_recorder, position_history, eventbus, treasury
):
    return DailyReportScheduler(
        performance_tracker=performance_tracker,
        trade_recorder=trade_recorder,
        position_history=position_history,
        eventbus=eventbus,
        account_id="acc-1",
        currency="KRW",
        treasury=treasury,
    )


def _make_trade(
    side: str = "buy", price: float = 50000.0, quantity: float = 10.0
) -> TradeRecord:
    """Build a test trade record."""
    return TradeRecord(
        trade_id=uuid4(),
        bot_id="bot-1",
        strategy_id="strat-1",
        symbol="005930",
        side=side,
        quantity=quantity,
        price=price,
        status=TradeStatus.FILLED,
        timestamp=datetime.now(KST),
    )


# ── compute_report_time ─────────────────────────────


class TestComputeReportTime:
    def test_standard_krx(self):
        """KRX 15:30 + 30min = 16:00."""
        assert compute_report_time("15:30") == time(16, 0)

    def test_us_market(self):
        """US 16:00 + 30min = 16:30."""
        assert compute_report_time("16:00") == time(16, 30)

    def test_late_night(self):
        """23:59 + 30min wraps to 00:29."""
        assert compute_report_time("23:59") == time(0, 29)


# ── format_currency ──────────────────────────────────


class TestFormatCurrency:
    def test_krw_positive(self):
        assert format_currency(1250000.0, "KRW") == "+1,250,000원"

    def test_krw_negative(self):
        assert format_currency(-500000.0, "KRW") == "-500,000원"

    def test_krw_zero(self):
        assert format_currency(0.0, "KRW") == "+0원"

    def test_usd_positive(self):
        assert format_currency(1234.56, "USD") == "+$1,234.56"

    def test_usd_negative(self):
        assert format_currency(-99.99, "USD") == "-$99.99"

    def test_unknown_currency(self):
        """Unknown currency code is used as-is."""
        result = format_currency(100.0, "EUR")
        assert "EUR" in result


# ── run_once: DailyReportEvent always published ──────


class TestDailyReportEventAlwaysPublished:
    async def test_no_trades_still_publishes_daily_report(
        self, scheduler, trade_recorder, eventbus
    ):
        """Even with 0 trades, DailyReportEvent is published."""
        trade_recorder.get_trades.return_value = []

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        notif_events: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        result = await scheduler.run_once(target_date=date(2026, 3, 19))

        assert result is False
        assert len(report_events) == 1
        assert report_events[0].account_id == "acc-1"
        assert report_events[0].report_date == "2026-03-19"
        assert report_events[0].trade_count == 0
        assert report_events[0].has_trades is False
        # No NotificationEvent
        assert len(notif_events) == 0

    async def test_with_trades_publishes_both_events(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
        treasury,
    ):
        """With trades, both DailyReportEvent and NotificationEvent are published."""
        buy_trades = [_make_trade("buy") for _ in range(3)]
        sell_trades = [_make_trade("sell") for _ in range(2)]
        trade_recorder.get_trades.return_value = buy_trades + sell_trades

        performance_tracker.get_daily_summary.return_value = [
            DailySummary(
                date="2026-03-19",
                realized_pnl=500000.0,
                trade_count=5,
                win_rate=0.6,
            )
        ]
        position_history.get_all_positions.return_value = [
            PositionSnapshot(
                bot_id="bot-1",
                symbol="005930",
                quantity=100.0,
                avg_entry_price=50000.0,
            )
        ]

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        notif_events: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notif_events.append(e))

        result = await scheduler.run_once(target_date=date(2026, 3, 19))

        assert result is True
        assert len(report_events) == 1
        assert report_events[0].trade_count == 5
        assert report_events[0].has_trades is True
        assert len(notif_events) == 1


# ── run_once: performance metrics ────────────────────


class TestPerformanceMetrics:
    async def test_net_trade_amount_calculation(
        self, scheduler, trade_recorder, eventbus, treasury
    ):
        """net_trade_amount = sum(buy price*qty) - sum(sell price*qty)."""
        trades = [
            _make_trade("buy", price=50000.0, quantity=10.0),  # +500,000
            _make_trade("sell", price=55000.0, quantity=5.0),  # -275,000
        ]
        trade_recorder.get_trades.return_value = trades

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        # net = 500000 - 275000 = 225000
        assert report_events[0].net_trade_amount == pytest.approx(225000.0)

    async def test_daily_pnl_with_yesterday_snapshot(
        self, scheduler, trade_recorder, eventbus, treasury
    ):
        """daily_pnl = today_eval - net_trade - yesterday_eval."""
        trade_recorder.get_trades.return_value = [
            _make_trade("buy", price=50000.0, quantity=10.0),
        ]

        # today eval = 10,000,000 (from treasury mock)
        # yesterday eval = 9,000,000
        treasury.get_daily_snapshot.return_value = {
            "ante_eval_amount": 9_000_000.0,
            "ante_purchase_amount": 8_500_000.0,
        }

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        net_trade = 50000.0 * 10.0  # 500,000
        expected_pnl = 10_000_000 - net_trade - 9_000_000  # 500,000
        assert report_events[0].daily_pnl == pytest.approx(expected_pnl)

    async def test_daily_return_calculation(
        self, scheduler, trade_recorder, eventbus, treasury
    ):
        """daily_return = daily_pnl / yesterday_eval."""
        trade_recorder.get_trades.return_value = []

        treasury.get_daily_snapshot.return_value = {
            "ante_eval_amount": 10_000_000.0,
            "ante_purchase_amount": 9_500_000.0,
        }

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        # daily_pnl = 10M - 0 - 10M = 0
        # daily_return = 0 / 10M = 0
        assert report_events[0].daily_return == pytest.approx(0.0)

    async def test_daily_return_zero_when_no_prev_snapshot(
        self, scheduler, trade_recorder, eventbus, treasury
    ):
        """daily_return = 0 when no yesterday snapshot."""
        trade_recorder.get_trades.return_value = []
        treasury.get_daily_snapshot.return_value = None

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        assert report_events[0].daily_return == 0.0

    async def test_unrealized_pnl(self, scheduler, trade_recorder, eventbus, treasury):
        """unrealized_pnl = ante_eval - ante_purchase."""
        trade_recorder.get_trades.return_value = []

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        # 10M - 9.5M = 500,000
        assert report_events[0].unrealized_pnl == pytest.approx(500_000.0)

    async def test_saves_daily_snapshot(self, scheduler, trade_recorder, treasury):
        """run_once saves today's snapshot for next day's reference."""
        trade_recorder.get_trades.return_value = []

        await scheduler.run_once(target_date=date(2026, 3, 19))

        treasury.save_daily_snapshot.assert_called_once_with("2026-03-19")


# ── run_once: NotificationEvent ──────────────────────


class TestNotificationEvent:
    async def test_publishes_notification_with_trades(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
    ):
        """Trades present -> NotificationEvent published with correct data."""
        buy_trades = [_make_trade("buy") for _ in range(7)]
        sell_trades = [_make_trade("sell") for _ in range(5)]
        trade_recorder.get_trades.return_value = buy_trades + sell_trades

        performance_tracker.get_daily_summary.return_value = [
            DailySummary(
                date="2026-03-19",
                realized_pnl=1250000.0,
                trade_count=5,
                win_rate=0.8,
            )
        ]

        position_history.get_all_positions.return_value = [
            PositionSnapshot(
                bot_id="bot-1",
                symbol=f"00593{i}",
                quantity=100.0,
                avg_entry_price=50000.0,
            )
            for i in range(4)
        ]

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        result = await scheduler.run_once(target_date=date(2026, 3, 19))

        assert result is True
        assert len(received) == 1

        event = received[0]
        assert event.level == "info"
        assert "2026-03-19" in event.title
        assert "12건" in event.message
        assert "매수 7" in event.message
        assert "매도 5" in event.message
        assert "+1,250,000원" in event.message
        assert "4종목" in event.message

    async def test_negative_pnl_format(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
    ):
        """Negative PnL is displayed without explicit sign."""
        trade_recorder.get_trades.return_value = [_make_trade("sell")]
        performance_tracker.get_daily_summary.return_value = [
            DailySummary(
                date="2026-03-19",
                realized_pnl=-500000.0,
                trade_count=1,
                win_rate=0.0,
            )
        ]
        position_history.get_all_positions.return_value = []

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        assert "-500,000원" in received[0].message

    async def test_zero_pnl_when_no_daily_summary(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
    ):
        """No daily summary -> realized PnL shown as 0."""
        trade_recorder.get_trades.return_value = [_make_trade("buy")]
        performance_tracker.get_daily_summary.return_value = []
        position_history.get_all_positions.return_value = []

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        result = await scheduler.run_once(target_date=date(2026, 3, 19))

        assert result is True
        assert "+0원" in received[0].message

    async def test_notification_category_is_trade(
        self,
        scheduler,
        trade_recorder,
        eventbus,
    ):
        """Notification category is 'trade'."""
        trade_recorder.get_trades.return_value = [_make_trade("buy")]

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        assert received[0].category == "trade"


# ── Currency-aware notification ──────────────────────


class TestCurrencyAwareNotification:
    async def test_usd_currency_in_notification(
        self,
        performance_tracker,
        trade_recorder,
        position_history,
        eventbus,
        treasury,
    ):
        """USD account shows $ symbol in notification message."""
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
            account_id="acc-us",
            currency="USD",
            treasury=treasury,
        )

        trade_recorder.get_trades.return_value = [_make_trade("buy")]
        performance_tracker.get_daily_summary.return_value = [
            DailySummary(
                date="2026-03-19",
                realized_pnl=1234.56,
                trade_count=1,
                win_rate=1.0,
            )
        ]
        position_history.get_all_positions.return_value = []

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        await sched.run_once(target_date=date(2026, 3, 19))

        assert "+$1,234.56" in received[0].message


# ── start/stop ───────────────────────────────────────


class TestStartStop:
    async def test_start_creates_task(self, scheduler):
        """start() creates background task."""
        await scheduler.start()
        try:
            assert scheduler._task is not None
            assert not scheduler._task.done()
        finally:
            await scheduler.stop()

    async def test_stop_cancels_task(self, scheduler):
        """stop() cancels background task."""
        await scheduler.start()
        await scheduler.stop()

        assert scheduler._task is None

    async def test_double_start_ignored(self, scheduler):
        """Second start() is ignored when already running."""
        await scheduler.start()
        first_task = scheduler._task

        await scheduler.start()

        assert scheduler._task is first_task
        await scheduler.stop()

    async def test_stop_without_start(self, scheduler):
        """stop() without start() does not raise."""
        await scheduler.stop()


# ── Configuration ────────────────────────────────────


class TestConfiguration:
    def test_default_report_time(
        self, performance_tracker, trade_recorder, position_history, eventbus
    ):
        """Default report time is 16:00."""
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
        )
        assert sched._report_time == DEFAULT_REPORT_TIME
        assert DEFAULT_REPORT_TIME == time(16, 0)

    def test_custom_report_time(
        self, performance_tracker, trade_recorder, position_history, eventbus
    ):
        """report_time parameter overrides default."""
        custom_time = time(17, 30)
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
            report_time=custom_time,
        )
        assert sched._report_time == custom_time

    def test_account_id_and_currency(
        self, performance_tracker, trade_recorder, position_history, eventbus
    ):
        """account_id and currency are stored."""
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
            account_id="acc-1",
            currency="USD",
        )
        assert sched._account_id == "acc-1"
        assert sched._currency == "USD"


# ── No treasury fallback ────────────────────────────


class TestNoTreasuryFallback:
    async def test_works_without_treasury(
        self,
        performance_tracker,
        trade_recorder,
        position_history,
        eventbus,
    ):
        """Scheduler works with treasury=None (all metrics are 0)."""
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
        )

        trade_recorder.get_trades.return_value = []

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        result = await sched.run_once(target_date=date(2026, 3, 19))

        assert result is False
        assert len(report_events) == 1
        assert report_events[0].daily_pnl == 0.0
        assert report_events[0].unrealized_pnl == 0.0
