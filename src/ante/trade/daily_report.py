"""DailyReportScheduler — 장 마감 후 일일 성과 요약 알림 발행.

KRX 장 마감(15:30) 이후 지정 시각(기본 16:00)에 1회 실행하여,
당일 거래 요약을 NotificationEvent로 발행한다.
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

logger = logging.getLogger(__name__)

KST = timezone(timedelta(hours=9))
DEFAULT_REPORT_TIME = time(16, 0)  # 16:00 KST


class DailyReportScheduler:
    """장 마감 후 당일 거래 요약을 NotificationEvent로 발행한다.

    ReconcileScheduler와 동일한 asyncio 루프 패턴을 사용한다.

    Args:
        performance_tracker: 일별 성과 집계 조회용.
        trade_recorder: 당일 거래 건수(매수/매도) 조회용.
        position_history: 보유 포지션 현황 조회용.
        eventbus: NotificationEvent 발행용.
        report_time: 리포트 발행 시각 (KST). 기본 16:00.
    """

    def __init__(
        self,
        performance_tracker: PerformanceTracker,
        trade_recorder: TradeRecorder,
        position_history: PositionHistory,
        eventbus: EventBus,
        report_time: time = DEFAULT_REPORT_TIME,
    ) -> None:
        self._performance = performance_tracker
        self._recorder = trade_recorder
        self._positions = position_history
        self._eventbus = eventbus
        self._report_time = report_time
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """스케줄러를 시작한다."""
        if self._task and not self._task.done():
            logger.warning("DailyReportScheduler 이미 실행 중")
            return

        logger.info(
            "DailyReportScheduler 시작 (발행 시각: %s KST)",
            self._report_time.strftime("%H:%M"),
        )
        self._task = asyncio.create_task(
            self._loop(),
            name="daily-report-scheduler",
        )

    async def stop(self) -> None:
        """스케줄러를 중지한다."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
            logger.info("DailyReportScheduler 종료")

    async def run_once(self, target_date: date | None = None) -> bool:
        """수동 실행 (테스트/CLI용).

        Args:
            target_date: 대상 날짜. None이면 오늘(KST).

        Returns:
            True: 알림 발행됨, False: 당일 거래 0건으로 스킵.
        """
        today = target_date or datetime.now(KST).date()
        today_str = today.isoformat()

        # 1) 당일 체결 거래 조회 (매수/매도 건수)
        from ante.trade.models import TradeStatus

        trades = await self._recorder.get_trades(
            status=TradeStatus.FILLED,
            from_date=datetime.combine(today, time.min, tzinfo=KST),
            to_date=datetime.combine(today, time.max, tzinfo=KST),
            limit=10000,
        )

        if not trades:
            logger.debug("일일 리포트 스킵 — 당일 거래 0건 (%s)", today_str)
            return False

        total_count = len(trades)
        buy_count = sum(1 for t in trades if t.side == "buy")
        sell_count = sum(1 for t in trades if t.side == "sell")

        # 2) 일별 실현 손익 조회
        summaries = await self._performance.get_daily_summary(
            start_date=today_str,
            end_date=today_str,
        )
        realized_pnl = summaries[0].realized_pnl if summaries else 0.0

        # 3) 보유 포지션 현황
        all_positions = await self._positions.get_all_positions()
        position_count = len(all_positions)

        # 4) NotificationEvent 발행
        pnl_sign = "+" if realized_pnl >= 0 else ""
        message = (
            f"거래: {total_count}건 (매수 {buy_count} / 매도 {sell_count})\n"
            f"실현 손익: {pnl_sign}{realized_pnl:,.0f}원\n"
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

        logger.info("일일 성과 요약 발행 완료 (%s): 거래 %d건", today_str, total_count)
        return True

    async def _loop(self) -> None:
        """매일 report_time에 run_once()를 실행한다."""
        while True:
            now = datetime.now(KST)
            target = datetime.combine(now.date(), self._report_time, tzinfo=KST)
            if now >= target:
                # 오늘 시각을 지났으면 내일로
                target += timedelta(days=1)

            delay = (target - now).total_seconds()
            logger.debug(
                "DailyReportScheduler 다음 실행까지 %.0f초 대기",
                delay,
            )
            await asyncio.sleep(delay)

            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("DailyReportScheduler 실행 오류")
