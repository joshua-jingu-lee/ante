"""PerformanceTracker — 봇/전략 성과 지표 산출."""

from __future__ import annotations

import logging
import sqlite3
import statistics
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ante.trade.models import (
    DailySummary,
    MonthlySummary,
    PerformanceMetrics,
    TradeRecord,
    TradeStatus,
    WeeklySummary,
)

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

# SQL query fragments reused in daily/weekly/monthly summary methods
_COND_STATUS_FILLED = "t.status = ?"
_COND_SIDE_SELL = "t.side = 'sell'"
_COND_BOT_ID = "t.bot_id = ?"
_JOIN_POSITION_HISTORY = """LEFT JOIN position_history ph
                ON ph.bot_id = t.bot_id
                AND ph.symbol = t.symbol
                AND ph.action = 'sell'
                AND ph.price = t.price
                AND ph.quantity = t.quantity"""


class PerformanceTracker:
    """봇/전략의 성과 지표를 조회 시 계산."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def calculate(
        self,
        account_id: str,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> PerformanceMetrics:
        """성과 지표 계산.

        account_id는 필수. 계좌를 섞어 계산한 성과 지표는 의미가 없다.
        """
        trades = await self._get_filled_trades(
            account_id=account_id,
            bot_id=bot_id,
            strategy_id=strategy_id,
            from_date=from_date,
            to_date=to_date,
        )

        if not trades:
            return self._empty_metrics()

        # 매도 거래 기준 승/패 판정
        sell_trades = [t for t in trades if t.side == "sell"]
        pnl_list = await self._calculate_pnl_per_trade(sell_trades, bot_id)

        winning = [p for p in pnl_list if p > 0]
        losing = [p for p in pnl_list if p < 0]

        total_trades = len(sell_trades)
        winning_trades = len(winning)
        losing_trades = len(losing)

        total_profit = sum(winning) if winning else 0.0
        total_loss = abs(sum(losing)) if losing else 0.0
        total_commission = sum(t.commission for t in trades)

        max_drawdown, max_drawdown_amount = self._calculate_mdd(pnl_list)

        return PerformanceMetrics(
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate=winning_trades / total_trades if total_trades > 0 else 0.0,
            total_pnl=total_profit - total_loss,
            total_commission=total_commission,
            net_pnl=total_profit - total_loss - total_commission,
            avg_profit=total_profit / winning_trades if winning_trades > 0 else 0.0,
            avg_loss=total_loss / losing_trades if losing_trades > 0 else 0.0,
            profit_factor=total_profit / total_loss if total_loss > 0 else float("inf"),
            max_drawdown=max_drawdown,
            max_drawdown_amount=max_drawdown_amount,
            sharpe_ratio=self._calculate_sharpe(pnl_list),
            first_trade_at=trades[0].timestamp,
            last_trade_at=trades[-1].timestamp,
            active_days=len({t.timestamp.date() for t in trades if t.timestamp}),
        )

    async def get_daily_summary(
        self,
        bot_id: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[DailySummary]:
        """일별 성과 집계.

        Args:
            bot_id: 봇 ID 필터 (None이면 전체)
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)
        if start_date:
            conditions.append("date(t.timestamp) >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("date(t.timestamp) <= ?")
            params.append(end_date)

        where = " AND ".join(conditions)
        query = f"""
            SELECT
                date(t.timestamp) AS trade_date,
                COALESCE(SUM(ph.pnl), 0.0) AS realized_pnl,
                COUNT(*) AS trade_count,
                SUM(CASE WHEN ph.pnl > 0 THEN 1 ELSE 0 END) AS win_count
            FROM trades t
            {_JOIN_POSITION_HISTORY}
            WHERE {where}
            GROUP BY trade_date
            ORDER BY trade_date ASC
        """

        try:
            rows = await self._db.fetch_all(query, tuple(params))
        except sqlite3.OperationalError:
            return []
        return [
            DailySummary(
                date=row["trade_date"],
                realized_pnl=float(row["realized_pnl"]),
                trade_count=int(row["trade_count"]),
                win_rate=(
                    int(row["win_count"]) / int(row["trade_count"])
                    if int(row["trade_count"]) > 0
                    else 0.0
                ),
            )
            for row in rows
        ]

    async def get_weekly_summary(
        self,
        bot_id: str | None = None,
    ) -> list[WeeklySummary]:
        """주별 성과 집계.

        ISO 주 단위(월요일 시작)로 거래를 그룹화하여 집계한다.

        Args:
            bot_id: 봇 ID 필터 (None이면 전체)
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)

        where = " AND ".join(conditions)
        query = f"""
            SELECT
                date(t.timestamp, 'weekday 0', '-6 days') AS week_start,
                date(t.timestamp, 'weekday 0') AS week_end,
                COALESCE(SUM(ph.pnl), 0.0) AS realized_pnl,
                COUNT(*) AS trade_count,
                SUM(CASE WHEN ph.pnl > 0 THEN 1 ELSE 0 END) AS win_count
            FROM trades t
            {_JOIN_POSITION_HISTORY}
            WHERE {where}
            GROUP BY week_start
            ORDER BY week_start ASC
        """

        try:
            rows = await self._db.fetch_all(query, tuple(params))
        except sqlite3.OperationalError:
            return []
        return [
            WeeklySummary(
                week_start=row["week_start"],
                week_end=row["week_end"],
                realized_pnl=float(row["realized_pnl"]),
                trade_count=int(row["trade_count"]),
                win_rate=(
                    int(row["win_count"]) / int(row["trade_count"])
                    if int(row["trade_count"]) > 0
                    else 0.0
                ),
            )
            for row in rows
        ]

    async def get_monthly_summary(
        self,
        bot_id: str | None = None,
        year: int | None = None,
    ) -> list[MonthlySummary]:
        """월별 성과 집계.

        Args:
            bot_id: 봇 ID 필터 (None이면 전체)
            year: 연도 필터 (None이면 전체)
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)
        if year:
            conditions.append("strftime('%Y', t.timestamp) = ?")
            params.append(str(year))

        where = " AND ".join(conditions)
        query = f"""
            SELECT
                CAST(strftime('%Y', t.timestamp) AS INTEGER) AS yr,
                CAST(strftime('%m', t.timestamp) AS INTEGER) AS mo,
                COALESCE(SUM(ph.pnl), 0.0) AS realized_pnl,
                COUNT(*) AS trade_count,
                SUM(CASE WHEN ph.pnl > 0 THEN 1 ELSE 0 END) AS win_count
            FROM trades t
            {_JOIN_POSITION_HISTORY}
            WHERE {where}
            GROUP BY yr, mo
            ORDER BY yr ASC, mo ASC
        """

        try:
            rows = await self._db.fetch_all(query, tuple(params))
        except sqlite3.OperationalError:
            return []
        return [
            MonthlySummary(
                year=int(row["yr"]),
                month=int(row["mo"]),
                realized_pnl=float(row["realized_pnl"]),
                trade_count=int(row["trade_count"]),
                win_rate=(
                    int(row["win_count"]) / int(row["trade_count"])
                    if int(row["trade_count"]) > 0
                    else 0.0
                ),
            )
            for row in rows
        ]

    @staticmethod
    def _calculate_mdd(pnl_list: list[float]) -> tuple[float, float]:
        """MDD 계산. 누적 손익의 고점 대비 최대 하락.

        Returns:
            (비율, 금액) 튜플
        """
        if not pnl_list:
            return 0.0, 0.0

        cumulative: list[float] = []
        running = 0.0
        for pnl in pnl_list:
            running += pnl
            cumulative.append(running)

        peak = cumulative[0]
        max_dd_amount = 0.0

        for value in cumulative:
            if value > peak:
                peak = value
            drawdown = peak - value
            if drawdown > max_dd_amount:
                max_dd_amount = drawdown

        max_dd_rate = max_dd_amount / peak if peak > 0 else 0.0
        return max_dd_rate, max_dd_amount

    @staticmethod
    def _calculate_sharpe(
        pnl_list: list[float],
        risk_free_rate: float = 0.035,
    ) -> float | None:
        """샤프 비율 계산. 거래 30건 미만이면 None."""
        if len(pnl_list) < 30:
            return None

        mean_return = statistics.mean(pnl_list)
        std_return = statistics.stdev(pnl_list)

        if std_return == 0:
            return None

        return (mean_return - risk_free_rate / 252) / std_return

    async def _get_filled_trades(
        self,
        account_id: str,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> list[TradeRecord]:
        """체결 완료 거래 조회."""
        conditions: list[str] = ["status = ?", "account_id = ?"]
        params: list[Any] = [TradeStatus.FILLED.value, account_id]

        if bot_id:
            conditions.append("bot_id = ?")
            params.append(bot_id)
        if strategy_id:
            conditions.append("strategy_id = ?")
            params.append(strategy_id)
        if from_date:
            conditions.append("timestamp >= ?")
            params.append(from_date.isoformat())
        if to_date:
            conditions.append("timestamp <= ?")
            params.append(to_date.isoformat())

        where = " AND ".join(conditions)
        query = f"SELECT * FROM trades WHERE {where} ORDER BY timestamp ASC"

        try:
            rows = await self._db.fetch_all(query, tuple(params))
        except sqlite3.OperationalError:
            logger.debug("trades 테이블 없음 — 빈 목록 반환")
            return []
        return [self._row_to_record(row) for row in rows]

    async def _calculate_pnl_per_trade(
        self,
        sell_trades: list[TradeRecord],
        bot_id: str | None,
    ) -> list[float]:
        """매도 거래별 실현 손익 계산.

        position_history의 pnl 데이터를 활용하되,
        간단하게 (매도가 - 매입가) * 수량 - 수수료로 계산.
        """
        pnl_list: list[float] = []
        for trade in sell_trades:
            # position_history에서 해당 거래의 pnl 조회
            try:
                row = await self._db.fetch_one(
                    """SELECT pnl FROM position_history
                       WHERE bot_id = ? AND symbol = ? AND action = 'sell'
                         AND price = ? AND quantity = ?
                       ORDER BY created_at DESC LIMIT 1""",
                    (trade.bot_id, trade.symbol, trade.price, trade.quantity),
                )
            except sqlite3.OperationalError:
                row = None
            if row:
                pnl_list.append(float(row["pnl"]))
            else:
                # fallback: 수수료 제외한 대략적 계산
                pnl_list.append(-trade.commission if trade.commission else 0.0)
        return pnl_list

    @staticmethod
    def _row_to_record(row: dict) -> TradeRecord:
        """DB row → TradeRecord."""
        from uuid import UUID

        ts = row.get("timestamp")
        return TradeRecord(
            trade_id=UUID(row["trade_id"]),
            bot_id=row["bot_id"],
            strategy_id=row["strategy_id"],
            symbol=row["symbol"],
            side=row["side"],
            quantity=float(row["quantity"]),
            price=float(row["price"]),
            status=TradeStatus(row["status"]),
            order_type=row.get("order_type", ""),
            reason=row.get("reason", ""),
            commission=float(row.get("commission", 0)),
            timestamp=datetime.fromisoformat(ts) if ts else None,
            order_id=row.get("order_id"),
            account_id=row.get("account_id", "default"),
            currency=row.get("currency", "KRW"),
        )

    @staticmethod
    def _empty_metrics() -> PerformanceMetrics:
        """거래 없을 때 빈 지표."""
        return PerformanceMetrics()
