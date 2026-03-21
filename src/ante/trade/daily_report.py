"""DailyReportScheduler -- Account 기반 일일 성과 리포트 발행.

Account의 trading_hours_end + 30분 시각에 매일 실행하여,
DailyReportEvent를 무조건 발행하고 (거래 0건이어도),
거래 1건 이상일 때만 NotificationEvent를 추가 발행한다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.trade.performance import PerformanceTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DEFAULT_REPORT_TIME = time(16, 0)  # 16:00 KST

# 통화 기호 매핑
_CURRENCY_SYMBOLS: dict[str, str] = {
    "KRW": "원",
    "USD": "$",
}


def compute_report_time(trading_hours_end: str) -> time:
    """trading_hours_end(HH:MM) + 30분을 report_time으로 변환.

    Args:
        trading_hours_end: "HH:MM" 형식 문자열.

    Returns:
        report_time (time).
    """
    h, m = trading_hours_end.split(":")
    dt = datetime(2000, 1, 1, int(h), int(m)) + timedelta(minutes=30)
    return dt.time()


def format_currency(value: float, currency: str) -> str:
    """통화 단위를 적용하여 금액 포맷팅.

    Args:
        value: 금액.
        currency: 통화 코드 (KRW, USD 등).

    Returns:
        포맷된 문자열.
    """
    symbol = _CURRENCY_SYMBOLS.get(currency, currency)
    if value >= 0:
        sign = "+"
    else:
        sign = "-"
        value = abs(value)
    if currency == "USD":
        return f"{sign}{symbol}{value:,.2f}"
    return f"{sign}{value:,.0f}{symbol}"


class DailyReportScheduler:
    """Account 기반 일일 성과 리포트 스케줄러.

    매일 report_time에 실행하여:
    1. DailyReportEvent를 무조건 발행 (성과 데이터 포함)
    2. NotificationEvent는 거래 1건 이상일 때만 발행

    Args:
        performance_tracker: 일별 성과 집계 조회용.
        trade_recorder: 당일 거래 건수(매수/매도) 조회용.
        position_history: 보유 포지션 현황 조회용.
        eventbus: 이벤트 발행용.
        report_time: 리포트 발행 시각 (KST). 기본 16:00.
        account_id: 계좌 ID.
        currency: 통화 코드 (KRW, USD 등).
        treasury: Treasury 인스턴스 (성과 산출용). Optional.
    """

    def __init__(
        self,
        performance_tracker: PerformanceTracker,
        trade_recorder: TradeRecorder,
        position_history: PositionHistory,
        eventbus: EventBus,
        report_time: time = DEFAULT_REPORT_TIME,
        account_id: str = "",
        currency: str = "KRW",
        treasury: Treasury | None = None,
    ) -> None:
        self._performance = performance_tracker
        self._recorder = trade_recorder
        self._positions = position_history
        self._eventbus = eventbus
        self._report_time = report_time
        self._account_id = account_id
        self._currency = currency
        self._treasury = treasury
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the scheduler."""
        if self._task and not self._task.done():
            logger.warning("DailyReportScheduler already running")
            return

        logger.info(
            "DailyReportScheduler start (report_time: %s KST)",
            self._report_time.strftime("%H:%M"),
        )
        self._task = asyncio.create_task(
            self._loop(),
            name="daily-report-scheduler",
        )

    async def stop(self) -> None:
        """Stop the scheduler."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("DailyReportScheduler stopped")

    async def run_once(self, target_date: date | None = None) -> bool:
        """Execute daily report for the given date.

        Always publishes DailyReportEvent.
        Publishes NotificationEvent only when there are trades.

        Args:
            target_date: Target date. Defaults to today (KST).

        Returns:
            True if there were trades (NotificationEvent published),
            False if no trades (only DailyReportEvent published).
        """
        today = target_date or datetime.now(KST).date()
        today_str = today.isoformat()
        yesterday = today - timedelta(days=1)
        yesterday_str = yesterday.isoformat()

        # 1) Query today's filled trades
        from ante.trade.models import TradeStatus

        trades = await self._recorder.get_trades(
            status=TradeStatus.FILLED,
            from_date=datetime.combine(today, time.min, tzinfo=KST),
            to_date=datetime.combine(today, time.max, tzinfo=KST),
            limit=10000,
        )

        total_count = len(trades)
        has_trades = total_count > 0
        buy_count = sum(1 for t in trades if t.side == "buy")
        sell_count = sum(1 for t in trades if t.side == "sell")

        # 2) Compute performance metrics
        net_trade_amount = 0.0
        for t in trades:
            if t.side == "buy":
                net_trade_amount += t.price * t.quantity
            else:
                net_trade_amount -= t.price * t.quantity

        # Get today's ante_eval_amount from Treasury
        today_ante_eval = 0.0
        ante_purchase_amount = 0.0
        yesterday_ante_eval = 0.0

        if self._treasury:
            summary = self._treasury.get_summary()
            today_ante_eval = summary.get("ante_eval_amount", 0.0)
            ante_purchase_amount = summary.get("ante_purchase_amount", 0.0)

            # Get yesterday's snapshot
            prev_snapshot = await self._treasury.get_daily_snapshot(yesterday_str)
            if prev_snapshot:
                yesterday_ante_eval = prev_snapshot["ante_eval_amount"]

        # daily_pnl = today_eval - net_trade_amount - yesterday_eval
        daily_pnl = today_ante_eval - net_trade_amount - yesterday_ante_eval
        # daily_return = daily_pnl / yesterday_eval (0 if no prev)
        daily_return = (
            daily_pnl / yesterday_ante_eval if yesterday_ante_eval != 0 else 0.0
        )
        # unrealized_pnl = ante_eval_amount - ante_purchase_amount
        unrealized_pnl = today_ante_eval - ante_purchase_amount

        # 3) Save today's snapshot for tomorrow's reference
        if self._treasury:
            await self._treasury.save_daily_snapshot(today_str)

        # 4) Always publish DailyReportEvent
        from ante.eventbus.events import DailyReportEvent

        await self._eventbus.publish(
            DailyReportEvent(
                account_id=self._account_id,
                report_date=today_str,
                trade_count=total_count,
                has_trades=has_trades,
                daily_pnl=daily_pnl,
                daily_return=daily_return,
                net_trade_amount=net_trade_amount,
                unrealized_pnl=unrealized_pnl,
            )
        )

        # 5) Publish NotificationEvent only when trades exist
        if not has_trades:
            logger.debug(
                "DailyReport: no trades on %s — DailyReportEvent only",
                today_str,
            )
            return False

        # Realized PnL from performance tracker (existing logic)
        summaries = await self._performance.get_daily_summary(
            start_date=today_str,
            end_date=today_str,
        )
        realized_pnl = summaries[0].realized_pnl if summaries else 0.0

        # Position count
        all_positions = await self._positions.get_all_positions()
        position_count = len(all_positions)

        pnl_formatted = format_currency(realized_pnl, self._currency)
        message = (
            f"거래: {total_count}건 (매수 {buy_count} / 매도 {sell_count})\n"
            f"실현 손익: {pnl_formatted}\n"
            f"보유 포지션: {position_count}종목"
        )

        from ante.eventbus.events import NotificationEvent

        await self._eventbus.publish(
            NotificationEvent(
                level="info",
                title=f"일일 성과 요약 ({today_str})",
                message=message,
                category="trade",
            )
        )

        logger.info("DailyReport published (%s): %d trades", today_str, total_count)
        return True

    async def _loop(self) -> None:
        """Execute run_once() daily at report_time."""
        while True:
            now = datetime.now(KST)
            target = datetime.combine(now.date(), self._report_time, tzinfo=KST)
            if now >= target:
                target += timedelta(days=1)

            delay = (target - now).total_seconds()
            logger.debug(
                "DailyReportScheduler next run in %.0f seconds",
                delay,
            )
            await asyncio.sleep(delay)

            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DailyReportScheduler execution error")
