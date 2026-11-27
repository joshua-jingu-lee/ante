"""DailyReportScheduler 단위 테스트."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ante.core import clock
from ante.eventbus.bus import EventBus
from ante.eventbus.events import DailyReportEvent, NotificationEvent
from ante.trade.daily_report import (
    DEFAULT_REPORT_TIME,
    DailyReportScheduler,
    compute_report_time,
    format_currency,
)
from ante.trade.models import PositionSnapshot, TradeRecord, TradeStatus

KST = timezone(timedelta(hours=9))


# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
def performance_tracker():
    mock = AsyncMock()
    mock.get_realized_pnl = AsyncMock(return_value=0.0)
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
        account_id="acc-test",
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

    @pytest.mark.parametrize(
        ("manual_clock", "expected"),
        [
            (datetime(2001, 5, 29, 14, 59, 59, tzinfo=UTC), date(2001, 5, 29)),
            (datetime(2001, 5, 29, 15, 0, 0, tzinfo=UTC), date(2001, 5, 30)),
        ],
        indirect=["manual_clock"],
        ids=["kst_23_59_59", "kst_00_00_00"],
    )
    async def test_missing_target_date_uses_kst_today(
        self, manual_clock, scheduler, trade_recorder, eventbus, expected
    ):
        """target_date가 없으면 KST 자정을 기준으로 오늘을 정한다(UTC·호스트 아님)."""
        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        await scheduler.run_once()

        assert [e.report_date for e in report_events] == [expected.isoformat()]
        from_date = trade_recorder.get_trades.call_args.kwargs["from_date"]
        assert from_date.date() == expected

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

        performance_tracker.get_realized_pnl.return_value = 500000.0
        position_history.get_all_positions.return_value = [
            PositionSnapshot(
                bot_id="bot-1",
                symbol="005930",
                quantity=100.0,
                avg_entry_price=50000.0,
                account_id="acc-test",
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

        performance_tracker.get_realized_pnl.return_value = 1250000.0

        position_history.get_all_positions.return_value = [
            PositionSnapshot(
                bot_id="bot-1",
                symbol=f"00593{i}",
                quantity=100.0,
                avg_entry_price=50000.0,
                account_id="acc-test",
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
        assert event.title == "일일 성과 요약 (2026-03-19)"
        assert event.message == (
            "계좌 `acc-1`\n"
            "거래: 12건 (매수 7 / 매도 5)\n"
            "실현 손익: +1,250,000원\n"
            "보유 포지션: 4종목"
        )

    async def test_same_numbers_on_two_accounts_both_pass_notification_dedup(
        self, performance_tracker, trade_recorder, position_history, eventbus
    ):
        """거래 수·손익·포지션 수가 같은 두 계좌의 알림이 실제 NotificationService 의
        중복 제거(수준+본문, 60초)를 둘 다 통과한다 — 본문 첫 줄의 계좌가 가른다."""
        from ante.notification.base import NotificationAdapter
        from ante.notification.service import NotificationService

        class _Recording(NotificationAdapter):
            def __init__(self) -> None:
                self.sent: list[tuple[str, str]] = []

            async def send(self, level, message):
                self.sent.append(("", message))
                return True

            async def send_rich(self, level, title, body, metadata=None):
                self.sent.append((title, body))
                return True

        trade_recorder.get_trades.return_value = [_make_trade("buy")]
        adapter = _Recording()
        NotificationService(adapter=adapter, eventbus=eventbus).subscribe()
        for account_id in ("kis-a", "kis-b"):
            await DailyReportScheduler(
                performance_tracker=performance_tracker,
                trade_recorder=trade_recorder,
                position_history=position_history,
                eventbus=eventbus,
                account_id=account_id,
            ).run_once(target_date=date(2026, 3, 19))

        assert [body.split("\n")[0] for _, body in adapter.sent] == [
            "계좌 `kis-a`",
            "계좌 `kis-b`",
        ]
        assert {title for title, _ in adapter.sent} == {"일일 성과 요약 (2026-03-19)"}

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
        performance_tracker.get_realized_pnl.return_value = -500000.0
        position_history.get_all_positions.return_value = []

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        assert "-500,000원" in received[0].message

    async def test_zero_pnl_when_no_realized_pnl(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
    ):
        """No daily summary -> realized PnL shown as 0."""
        trade_recorder.get_trades.return_value = [_make_trade("buy")]
        performance_tracker.get_realized_pnl.return_value = 0.0
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
        performance_tracker.get_realized_pnl.return_value = 1234.56
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
            account_id="acc-test",
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
            account_id="acc-test",
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
            account_id="acc-test",
        )

        trade_recorder.get_trades.return_value = []

        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        result = await sched.run_once(target_date=date(2026, 3, 19))

        assert result is False
        assert len(report_events) == 1
        assert report_events[0].daily_pnl == 0.0
        assert report_events[0].unrealized_pnl == 0.0


# ── #1240 review: cross-account 필터링 회귀 ─────────


class TestCrossAccountFilter:
    """DailyReportScheduler 가 자기 계좌만 집계하는지 검증.

    SPLIT-1 부터 거래/포지션 row 가 실제 account_id 를 갖기 시작하므로,
    단일 계좌 바인딩된 스케줄러가 cross-account 데이터를 끌어오면
    DailyReportEvent 에 타 계좌 거래/포지션이 섞이게 된다. 이를 회귀로
    차단한다.
    """

    async def test_daily_report_run_once_filters_other_account_trades(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
        treasury,
    ):
        """run_once 가 ``account_id=self._account_id`` 를 모든 집계 호출에
        명시 전달한다.

        ``trade_recorder.get_trades``, ``performance_tracker.get_realized_pnl``,
        ``position_history.get_all_positions`` 호출에 자기 계좌만 명시되어야
        타 계좌의 거래/포지션이 DailyReportEvent 에 섞이지 않는다.
        """
        # trade_recorder/performance/position 모두 빈 리스트 반환 — 필터링
        # 자체가 호출 인자로 잘 전달되는지가 핵심 검증 포인트.
        trade_recorder.get_trades.return_value = [_make_trade("buy")]
        performance_tracker.get_realized_pnl.return_value = 0.0
        position_history.get_all_positions.return_value = []

        await scheduler.run_once(target_date=date(2026, 3, 19))

        # get_trades: account_id 키워드로 자기 계좌(acc-1) 가 명시 전달됨.
        get_trades_kwargs = trade_recorder.get_trades.await_args.kwargs
        assert get_trades_kwargs.get("account_id") == "acc-1"

        # get_realized_pnl: 자기 계좌와 보고 날짜의 KST 하루가 명시 전달됨.
        pnl_kwargs = performance_tracker.get_realized_pnl.await_args.kwargs
        assert pnl_kwargs == {
            "account_id": "acc-1",
            "start": datetime(2026, 3, 19, tzinfo=KST),
            "end": datetime(2026, 3, 20, tzinfo=KST),
        }

        # get_all_positions: account_id 키워드로 자기 계좌가 명시 전달됨.
        gap_kwargs = position_history.get_all_positions.await_args.kwargs
        assert gap_kwargs.get("account_id") == "acc-1"


# ── _loop target date ────────────────────────────────


class _AdjustableClock:
    """Test clock whose wall time can jump in either direction."""

    def __init__(self, start: datetime) -> None:
        self.current = start
        self._mono = 0.0

    def now(self, tz):
        return self.current.astimezone(tz)

    def monotonic(self) -> float:
        return self._mono


class TestLoopDate:
    """The loop reports the date of the target it slept toward (#2787)."""

    async def _run_loop(self, monkeypatch, scheduler, eventbus, start, wake_at):
        fake_clock = _AdjustableClock(start)
        original_sleep = asyncio.sleep
        delays: list[float] = []

        async def fake_sleep(delay, *args, **kwargs):
            if delay <= 0:
                return await original_sleep(delay, *args, **kwargs)
            delays.append(delay)
            if len(delays) > 1:
                raise asyncio.CancelledError
            fake_clock.current = wake_at

        monkeypatch.setattr("ante.trade.daily_report.asyncio.sleep", fake_sleep)
        report_events: list[DailyReportEvent] = []
        eventbus.subscribe(DailyReportEvent, lambda e: report_events.append(e))

        with clock.use_clock(fake_clock), pytest.raises(asyncio.CancelledError):
            await scheduler._loop()
        return report_events, delays, fake_clock

    @pytest.fixture
    def make_scheduler(
        self, performance_tracker, trade_recorder, position_history, eventbus, treasury
    ):
        def _make(report_time: time) -> DailyReportScheduler:
            return DailyReportScheduler(
                performance_tracker=performance_tracker,
                trade_recorder=trade_recorder,
                position_history=position_history,
                eventbus=eventbus,
                account_id="acc-1",
                report_time=report_time,
                currency="KRW",
                treasury=treasury,
            )

        return _make

    async def test_wall_clock_jumps_forward_past_midnight(
        self, monkeypatch, make_scheduler, eventbus
    ):
        """Waking after midnight still reports the target's date."""
        sched = make_scheduler(time(23, 59))
        events, delays, _ = await self._run_loop(
            monkeypatch,
            sched,
            eventbus,
            start=datetime(2026, 3, 19, 23, 58, 0, tzinfo=KST),
            wake_at=datetime(2026, 3, 20, 0, 0, 10, tzinfo=KST),
        )

        assert delays[0] == 60.0
        assert [e.report_date for e in events] == ["2026-03-19"]

    async def test_wall_clock_jumps_back_before_midnight(
        self, monkeypatch, make_scheduler, eventbus
    ):
        """Waking before midnight still reports the next-day target's date."""
        sched = make_scheduler(time(0, 40))
        events, delays, _ = await self._run_loop(
            monkeypatch,
            sched,
            eventbus,
            start=datetime(2026, 3, 19, 0, 41, 0, tzinfo=KST),
            wake_at=datetime(2026, 3, 19, 23, 59, 0, tzinfo=KST),
        )

        assert delays[0] == 86_340.0
        assert [e.report_date for e in events] == ["2026-03-20"]

    async def test_no_adjustment_reports_wall_clock_date(
        self, monkeypatch, make_scheduler, eventbus
    ):
        """Without an adjustment the date equals the wall-clock date on waking."""
        sched = make_scheduler(time(23, 59))
        events, _, fake_clock = await self._run_loop(
            monkeypatch,
            sched,
            eventbus,
            start=datetime(2026, 3, 19, 23, 58, 0, tzinfo=KST),
            wake_at=datetime(2026, 3, 19, 23, 59, 0, tzinfo=KST),
        )

        assert [e.report_date for e in events] == [
            fake_clock.now(KST).date().isoformat()
        ]

    def _record_trades_until_now(self, trade_recorder, trades):
        async def get_trades(*, from_date, to_date, **kwargs):
            now = clock.now(KST)
            return [t for t in trades if from_date <= t.timestamp <= min(to_date, now)]

        trade_recorder.get_trades = AsyncMock(side_effect=get_trades)

    async def test_report_after_midnight_covers_the_closing_day(
        self, monkeypatch, make_scheduler, eventbus, trade_recorder, treasury
    ):
        """A 23:59 close reports the closing day at 00:29 the next day (#3093)."""
        trade = replace(
            _make_trade(side="buy", price=50000.0, quantity=10.0),
            timestamp=datetime(2026, 11, 24, 12, 0, tzinfo=KST),
        )
        self._record_trades_until_now(trade_recorder, [trade])
        notifications: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: notifications.append(e))
        sched = make_scheduler(compute_report_time("23:59"))
        events, delays, _ = await self._run_loop(
            monkeypatch,
            sched,
            eventbus,
            start=datetime(2026, 11, 24, 0, 30, tzinfo=KST),
            wake_at=datetime(2026, 11, 25, 0, 29, tzinfo=KST),
        )

        window = trade_recorder.get_trades.await_args.kwargs
        assert window["from_date"] == datetime(2026, 11, 24, tzinfo=KST)
        assert window["to_date"] == datetime.combine(
            date(2026, 11, 24), time.max, tzinfo=KST
        )
        assert delays[0] == 86_340.0
        assert [e.report_date for e in events] == ["2026-11-24"]
        assert events[0].trade_count == 1
        assert events[0].net_trade_amount == 500_000.0
        assert [n.title for n in notifications] == ["일일 성과 요약 (2026-11-24)"]
        treasury.get_daily_snapshot.assert_awaited_once_with("2026-11-23")
        treasury.save_daily_snapshot.assert_awaited_once_with("2026-11-24")

    async def test_report_before_midnight_keeps_the_same_day(
        self, monkeypatch, make_scheduler, eventbus, trade_recorder, treasury
    ):
        """A 15:30 close still reports the same day at 16:00."""
        sched = make_scheduler(compute_report_time("15:30"))
        events, _, _ = await self._run_loop(
            monkeypatch,
            sched,
            eventbus,
            start=datetime(2026, 11, 24, 15, 0, tzinfo=KST),
            wake_at=datetime(2026, 11, 24, 16, 0, tzinfo=KST),
        )

        window = trade_recorder.get_trades.await_args.kwargs
        assert window["from_date"] == datetime(2026, 11, 24, tzinfo=KST)
        assert window["to_date"] == datetime.combine(
            date(2026, 11, 24), time.max, tzinfo=KST
        )
        assert [e.report_date for e in events] == ["2026-11-24"]
        treasury.get_daily_snapshot.assert_awaited_once_with("2026-11-23")
        treasury.save_daily_snapshot.assert_awaited_once_with("2026-11-24")
