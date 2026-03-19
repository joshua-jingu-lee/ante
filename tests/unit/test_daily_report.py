"""DailyReportScheduler 단위 테스트."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from ante.eventbus.bus import EventBus
from ante.eventbus.events import NotificationEvent
from ante.trade.daily_report import DEFAULT_REPORT_TIME, DailyReportScheduler
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
def scheduler(performance_tracker, trade_recorder, position_history, eventbus):
    return DailyReportScheduler(
        performance_tracker=performance_tracker,
        trade_recorder=trade_recorder,
        position_history=position_history,
        eventbus=eventbus,
    )


def _make_trade(side: str = "buy") -> TradeRecord:
    """테스트용 체결 거래 레코드 생성."""
    return TradeRecord(
        trade_id=uuid4(),
        bot_id="bot-1",
        strategy_id="strat-1",
        symbol="005930",
        side=side,
        quantity=10.0,
        price=50000.0,
        status=TradeStatus.FILLED,
        timestamp=datetime.now(KST),
    )


# ── run_once 테스트 ──────────────────────────────────


class TestRunOnce:
    async def test_skip_when_no_trades(self, scheduler, trade_recorder):
        """당일 거래 0건이면 False를 반환하고 알림을 발행하지 않는다."""
        trade_recorder.get_trades.return_value = []

        result = await scheduler.run_once(target_date=date(2026, 3, 19))

        assert result is False

    async def test_publishes_notification_with_trades(
        self,
        scheduler,
        trade_recorder,
        performance_tracker,
        position_history,
        eventbus,
    ):
        """당일 거래가 있으면 NotificationEvent를 발행한다."""
        # 거래 7건 매수, 5건 매도
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
        """음수 손익은 부호 없이 표시된다."""
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
        """일별 요약이 없으면(매수만 있는 날) 실현 손익을 0으로 표시한다."""
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
        """알림 카테고리가 trade이다."""
        trade_recorder.get_trades.return_value = [_make_trade("buy")]

        received: list[NotificationEvent] = []
        eventbus.subscribe(NotificationEvent, lambda e: received.append(e))

        await scheduler.run_once(target_date=date(2026, 3, 19))

        assert received[0].category == "trade"


# ── start/stop 테스트 ────────────────────────────────


class TestStartStop:
    async def test_start_creates_task(self, scheduler):
        """start() 시 태스크가 생성된다."""
        await scheduler.start()
        try:
            assert scheduler._task is not None
            assert not scheduler._task.done()
        finally:
            await scheduler.stop()

    async def test_stop_cancels_task(self, scheduler):
        """stop() 시 태스크가 취소된다."""
        await scheduler.start()
        await scheduler.stop()

        assert scheduler._task is None

    async def test_double_start_ignored(self, scheduler):
        """이미 실행 중인데 다시 start() 하면 무시된다."""
        await scheduler.start()
        first_task = scheduler._task

        await scheduler.start()  # 두 번째 호출

        assert scheduler._task is first_task
        await scheduler.stop()

    async def test_stop_without_start(self, scheduler):
        """start() 없이 stop() 해도 오류 없음."""
        await scheduler.stop()  # 예외 없이 완료


# ── 설정 테스트 ──────────────────────────────────────


class TestConfiguration:
    def test_default_report_time(
        self, performance_tracker, trade_recorder, position_history, eventbus
    ):
        """기본 발행 시각은 16:00이다."""
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
        """report_time으로 발행 시각을 변경할 수 있다."""
        custom_time = time(17, 30)
        sched = DailyReportScheduler(
            performance_tracker=performance_tracker,
            trade_recorder=trade_recorder,
            position_history=position_history,
            eventbus=eventbus,
            report_time=custom_time,
        )
        assert sched._report_time == custom_time
