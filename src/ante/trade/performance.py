"""PerformanceTracker — 봇/전략 성과 지표 산출."""

from __future__ import annotations

import logging
import statistics
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ante.account.errors import InvalidAccountIdError
from ante.core.database import OperationalError, is_missing_table
from ante.trade.models import (
    DailySummary,
    MonthlySummary,
    PerformanceMetrics,
    TradeRecord,
    TradeStatus,
    WeeklySummary,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ante.core.database import Database

logger = logging.getLogger(__name__)


def _stored_form(value: datetime) -> str:
    """aware 경계는 저장값처럼 UTC isoformat으로, naive는 그대로 isoformat."""
    if value.tzinfo is None:
        return value.isoformat()
    return value.astimezone(UTC).isoformat()


_COND_STATUS_FILLED = "t.status = ?"
_COND_SIDE_SELL = "t.side = 'sell'"
_COND_BOT_ID = "t.bot_id = ?"
_COND_STRATEGY_ID = "t.strategy_id = ?"
_JOIN_POSITION_HISTORY = """LEFT JOIN position_history ph
                ON ph.trade_id = CAST(t.trade_id AS TEXT)
                AND ph.action = 'sell'"""


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
        allocated_budgets: Mapping[str, float] | None = None,
    ) -> PerformanceMetrics:
        """성과 지표 계산.

        account_id는 필수. allocated_budgets(봇별 할당 예산)는 MDD의 시작 자본이다.
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

        max_drawdown, max_drawdown_amount = self._calculate_mdd(
            pnl_list, self._starting_capital(trades, allocated_budgets)
        )

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
        *,
        account_id: str | None = None,
        strategy_id: str | None = None,
    ) -> list[DailySummary]:
        """일별 성과 집계.

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            account_id: 계좌 ID 필터. ``None`` 이면 모든 계좌의 거래를
                집계한다 (read query 정책). 단일 계좌에
                바인딩된 호출자(DailyReportScheduler 등)는 자기 계좌만
                집계되도록 명시적으로 전달해야 한다.
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)
        if account_id:
            conditions.append("t.account_id = ?")
            params.append(account_id)
        if strategy_id:
            conditions.append(_COND_STRATEGY_ID)
            params.append(strategy_id)
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
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
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

    async def get_realized_pnl(
        self, *, account_id: str, start: datetime, end: datetime
    ) -> float:
        """계좌의 ``[start, end)`` 매도 실현 손익 합. naive면 ``ValueError``."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("get_realized_pnl needs aware datetimes")
        try:
            row = await self._db.fetch_one(
                """SELECT COALESCE(SUM(pnl), 0.0) AS realized_pnl
                   FROM position_history
                   WHERE account_id = ? AND action = 'sell'
                     AND timestamp >= ? AND timestamp < ?""",
                (
                    account_id,
                    start.astimezone(UTC).isoformat(),
                    end.astimezone(UTC).isoformat(),
                ),
            )
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
            return 0.0
        return 0.0 if row is None else float(row["realized_pnl"])

    async def count_filled_orders(
        self, *, account_id: str, since: datetime, strategy_id: str | None = None
    ) -> int:
        """``since`` 이후 체결 행이 있는 주문 수. naive면 ``ValueError``."""
        if since.tzinfo is None:
            raise ValueError("count_filled_orders needs an aware datetime")
        sql = """SELECT COUNT(DISTINCT COALESCE(NULLIF(order_id, ''), trade_id))
                    AS order_count
                 FROM trades
                 WHERE account_id = ? AND status = ? AND timestamp >= ?"""
        params: list[Any] = [
            account_id,
            TradeStatus.FILLED.value,
            since.astimezone(UTC).isoformat(),
        ]
        if strategy_id is not None:
            sql += " AND strategy_id = ?"
            params.append(strategy_id)
        try:
            row = await self._db.fetch_one(sql, tuple(params))
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
            return 0
        return 0 if row is None else int(row["order_count"])

    async def get_weekly_summary(
        self,
        bot_id: str | None = None,
        *,
        strategy_id: str | None = None,
    ) -> list[WeeklySummary]:
        """주별 성과 집계.

        ISO 주 단위(월요일 시작)로 거래를 그룹화하여 집계한다.

        Args:
            strategy_id: 전략 ID 필터. ``None`` 이면 전략 무관 전체.
                지정 시 ``trades.strategy_id`` 로 전략 전체 거래를
                집계하며 봇 멤버십/상태와 무관하다. ``bot_id`` 와
                함께 전달되면 AND 로 결합된다.
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)
        if strategy_id:
            conditions.append(_COND_STRATEGY_ID)
            params.append(strategy_id)

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
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
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
        *,
        strategy_id: str | None = None,
    ) -> list[MonthlySummary]:
        """월별 성과 집계.

        Args:
            bot_id: 봇 ID 필터 (None이면 전체)
            year: 연도 필터 (None이면 전체)
            strategy_id: 전략 ID 필터. ``None`` 이면 전략 무관 전체.
                지정 시 ``trades.strategy_id`` 로 전략 전체 거래를
                집계하며 봇 멤버십/상태와 무관하다. ``bot_id``/
                ``year`` 와 함께 전달되면 AND 로 결합된다.
        """
        conditions: list[str] = [
            _COND_STATUS_FILLED,
            _COND_SIDE_SELL,
        ]
        params: list[Any] = [TradeStatus.FILLED.value]

        if bot_id:
            conditions.append(_COND_BOT_ID)
            params.append(bot_id)
        if strategy_id:
            conditions.append(_COND_STRATEGY_ID)
            params.append(strategy_id)
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
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
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
    def _starting_capital(
        trades: list[TradeRecord],
        allocated_budgets: Mapping[str, float] | None,
    ) -> float | None:
        """거래한 봇들의 할당 예산 합. 예산 없는 봇이 끼거나 합이 0 이하면 None."""
        if allocated_budgets is None:
            return None
        bot_ids = {t.bot_id for t in trades}
        if not bot_ids.issubset(allocated_budgets):
            return None
        total = sum(allocated_budgets[b] for b in bot_ids)
        return total if total > 0 else None

    @staticmethod
    def _calculate_mdd(
        pnl_list: list[float],
        starting_capital: float | None,
    ) -> tuple[float | None, float]:
        """MDD를 (비율, 금액) 튜플로 계산한다."""
        if not pnl_list:
            return 0.0, 0.0

        capital = (
            starting_capital if starting_capital and starting_capital > 0 else None
        )
        value = capital if capital is not None else 0.0
        peak = value
        max_dd_amount = 0.0
        max_dd_rate = 0.0

        for pnl in pnl_list:
            value += pnl
            peak = max(peak, value)
            max_dd_amount = max(max_dd_amount, peak - value)
            if peak > 0:
                max_dd_rate = max(max_dd_rate, (peak - value) / peak)

        return (max_dd_rate if capital is not None else None), max_dd_amount

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
            params.append(_stored_form(from_date))
        if to_date:
            conditions.append("timestamp <= ?")
            params.append(_stored_form(to_date))

        where = " AND ".join(conditions)
        query = f"SELECT * FROM trades WHERE {where} ORDER BY timestamp ASC"

        try:
            rows = await self._db.fetch_all(query, tuple(params))
        except OperationalError as exc:
            if not is_missing_table(exc):
                raise
            logger.debug("trades 테이블 없음 — 빈 목록 반환")
            return []
        return self._rows_to_records(rows, context="_get_filled_trades")

    async def _calculate_pnl_per_trade(
        self,
        sell_trades: list[TradeRecord],
        bot_id: str | None,
    ) -> list[float]:
        """매도 거래별 실현 손익(position_history pnl, 행이 없으면 -수수료 또는 0.0)."""
        pnl_list: list[float] = []
        for trade in sell_trades:
            try:
                row = await self._db.fetch_one(
                    """SELECT pnl FROM position_history
                       WHERE trade_id = ? AND action = 'sell'
                       LIMIT 1""",
                    (str(trade.trade_id),),
                )
            except OperationalError as exc:
                if not is_missing_table(exc):
                    raise
                row = None
            if row:
                pnl_list.append(float(row["pnl"]))
            else:
                pnl_list.append(-trade.commission if trade.commission else 0.0)
        return pnl_list

    @classmethod
    def _rows_to_records(
        cls, rows: list[dict[str, Any]], *, context: str
    ) -> list[TradeRecord]:
        """rows → TradeRecord 목록, legacy invalid account_id row는 skip."""
        records: list[TradeRecord] = []
        for row in rows:
            record = cls._row_to_record_safe(row, context=context)
            if record is not None:
                records.append(record)
        return records

    @classmethod
    def _row_to_record_safe(
        cls, row: dict[str, Any], *, context: str
    ) -> TradeRecord | None:
        """DB row → TradeRecord, legacy invalid account_id row는 skip."""
        try:
            return cls._row_to_record(row)
        except InvalidAccountIdError as e:
            logger.warning(
                "%s: invalid account_id trade row skip "
                "(legacy migration 필요): %s, row=%s",
                context,
                e,
                dict(row),
            )
            return None

    @staticmethod
    def _row_to_record(row: dict[str, Any]) -> TradeRecord:
        """DB row → TradeRecord."""
        from uuid import UUID

        raw_id = row["trade_id"]
        try:
            trade_id = UUID(raw_id)
        except (ValueError, AttributeError):
            logger.warning("trade_id UUID 파싱 실패, 문자열 그대로 사용: %s", raw_id)
            trade_id = raw_id

        ts = row.get("timestamp")
        return TradeRecord(
            trade_id=trade_id,
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
            exchange=row.get("exchange") or "KRX",
            account_id=row["account_id"],
            currency=row.get("currency", "KRW"),
        )

    @staticmethod
    def _empty_metrics() -> PerformanceMetrics:
        """거래 없을 때 빈 지표."""
        return PerformanceMetrics()
