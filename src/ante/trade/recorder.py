"""TradeRecorder — 이벤트 기반 거래 자동 기록."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ante.trade.models import TradeRecord, TradeStatus

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.position import PositionHistory

logger = logging.getLogger(__name__)

TRADE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    trade_id       TEXT PRIMARY KEY,
    bot_id         TEXT NOT NULL,
    strategy_id    TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    side           TEXT NOT NULL,
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    status         TEXT NOT NULL,
    order_type     TEXT DEFAULT '',
    reason         TEXT DEFAULT '',
    commission     REAL DEFAULT 0.0,
    timestamp      TEXT,
    order_id       TEXT,
    created_at     TEXT DEFAULT (datetime('now')),
    account_id     TEXT NOT NULL DEFAULT 'default',
    currency       TEXT DEFAULT 'KRW',
    exchange       TEXT DEFAULT 'KRX'
);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
"""


class TradeRecorder:
    """EventBus 이벤트를 구독하여 거래를 자동 기록."""

    def __init__(self, db: Database, position_history: PositionHistory) -> None:
        self._db = db
        self._position_history = position_history
        self._eventbus: EventBus | None = None

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(TRADE_SCHEMA)
        logger.info("TradeRecorder 초기화 완료")

    def subscribe(self, eventbus: EventBus) -> None:
        """이벤트 구독 등록."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderFilledEvent,
            OrderRejectedEvent,
        )

        self._eventbus = eventbus
        eventbus.subscribe(OrderFilledEvent, self._on_filled, priority=10)
        eventbus.subscribe(OrderRejectedEvent, self._on_rejected, priority=10)
        eventbus.subscribe(OrderFailedEvent, self._on_failed, priority=10)
        eventbus.subscribe(OrderCancelledEvent, self._on_cancelled, priority=10)
        eventbus.subscribe(OrderCancelFailedEvent, self._on_cancel_failed, priority=10)

    async def _on_filled(self, event: object) -> None:
        """체결 이벤트 → 거래 기록 + 포지션 갱신 + 알림 발행."""
        from ante.eventbus.events import NotificationEvent, OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return

        record = TradeRecord(
            trade_id=event.event_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=event.price,
            status=TradeStatus.FILLED,
            order_type=event.order_type,
            reason=event.reason,
            commission=event.commission,
            timestamp=event.timestamp,
            order_id=event.order_id,
            exchange=event.exchange,
        )
        await self._save(record)
        await self._position_history.on_trade(record)

        side_label = "매수" if event.side == "buy" else "매도"
        if self._eventbus:
            position = await self._position_history.get_current(
                event.bot_id, event.symbol
            )
            base_msg = (
                f"봇 `{event.bot_id}`\n"
                f"종목: `{event.symbol}`\n"
                f"{side_label} {event.quantity}주 @ {event.price:,.0f}원"
            )
            if event.side == "buy":
                base_msg += (
                    f"\n누적 {position['quantity']:.0f}주"
                    f" · 평단가 {position['avg_entry_price']:,.0f}원"
                )
            else:
                pnl = position["realized_pnl"]
                pnl_sign = "+" if pnl >= 0 else ""
                base_msg += (
                    f"\n잔여 {position['quantity']:.0f}주"
                    f" · 평단가 {position['avg_entry_price']:,.0f}원"
                    f"\n실현 손익 {pnl_sign}{pnl:,.0f}원"
                )
            await self._eventbus.publish(
                NotificationEvent(
                    level="info",
                    title=f"체결 완료 ({side_label})",
                    message=base_msg,
                    category="trade",
                )
            )

    async def _on_rejected(self, event: object) -> None:
        """거부 이벤트 → 거부 기록 저장."""
        from ante.eventbus.events import OrderRejectedEvent

        if not isinstance(event, OrderRejectedEvent):
            return

        record = TradeRecord(
            trade_id=event.event_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=event.price or 0.0,
            status=TradeStatus.REJECTED,
            order_type=event.order_type,
            reason=event.reason,
            timestamp=event.timestamp,
        )
        await self._save(record)

    async def _on_failed(self, event: object) -> None:
        """실패 이벤트 → 실패 기록 저장."""
        from ante.eventbus.events import OrderFailedEvent

        if not isinstance(event, OrderFailedEvent):
            return

        record = TradeRecord(
            trade_id=event.event_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=0.0,
            status=TradeStatus.FAILED,
            order_type=event.order_type,
            reason=event.error_message,
            timestamp=event.timestamp,
        )
        await self._save(record)

    async def _on_cancelled(self, event: object) -> None:
        """취소 완료 이벤트 → 취소 기록 저장."""
        from ante.eventbus.events import OrderCancelledEvent

        if not isinstance(event, OrderCancelledEvent):
            return

        record = TradeRecord(
            trade_id=event.event_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=0.0,
            status=TradeStatus.CANCELLED,
            order_type="",
            reason=event.reason,
            timestamp=event.timestamp,
            order_id=event.order_id,
        )
        await self._save(record)

    async def _on_cancel_failed(self, event: object) -> None:
        """주문 취소 실패 알림 발행."""
        from ante.eventbus.events import NotificationEvent, OrderCancelFailedEvent

        if not isinstance(event, OrderCancelFailedEvent):
            return

        if self._eventbus:
            await self._eventbus.publish(
                NotificationEvent(
                    level="error",
                    title="주문 취소 실패",
                    message=(
                        f"봇 `{event.bot_id}` · 주문 `{event.order_id}`\n"
                        f"{event.error_message}"
                    ),
                    category="trade",
                )
            )

    async def _save(self, record: TradeRecord) -> None:
        """거래 기록을 SQLite에 저장."""
        await self._db.execute(
            """INSERT OR IGNORE INTO trades
               (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                status, order_type, reason, commission, timestamp, order_id,
                account_id, currency, exchange)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(record.trade_id),
                record.bot_id,
                record.strategy_id,
                record.symbol,
                record.side,
                record.quantity,
                record.price,
                record.status.value,
                record.order_type,
                record.reason,
                record.commission,
                record.timestamp.isoformat() if record.timestamp else None,
                record.order_id,
                record.account_id,
                record.currency,
                record.exchange,
            ),
        )

    async def save(self, record: TradeRecord) -> None:
        """거래 기록 저장 (public). Reconciler용."""
        await self._save(record)

    async def save_adjustment(
        self,
        bot_id: str,
        symbol: str,
        old_quantity: float,
        new_quantity: float,
        reason: str,
    ) -> None:
        """대사 보정 이력 기록."""
        await self._db.execute(
            """INSERT INTO trades
               (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                status, order_type, reason, timestamp)
               VALUES (?, ?, '', ?, 'adjustment', ?, 0.0, 'adjusted', '', ?,
                       datetime('now'))""",
            (
                str(uuid4()),
                bot_id,
                symbol,
                abs(new_quantity - old_quantity),
                reason,
            ),
        )

    async def get_trades(
        self,
        account_id: str | None = None,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: TradeStatus | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeRecord]:
        """거래 기록 조회."""
        conditions: list[str] = []
        params: list[Any] = []

        if account_id:
            conditions.append("account_id = ?")
            params.append(account_id)
        if bot_id:
            conditions.append("bot_id = ?")
            params.append(bot_id)
        if strategy_id:
            conditions.append("strategy_id = ?")
            params.append(strategy_id)
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        if from_date:
            conditions.append("timestamp >= ?")
            params.append(from_date.isoformat())
        if to_date:
            conditions.append("timestamp <= ?")
            params.append(to_date.isoformat())

        where = " AND ".join(conditions) if conditions else "1=1"
        query = f"""SELECT * FROM trades
                    WHERE {where}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?"""
        params.extend([limit, offset])

        rows = await self._db.fetch_all(query, tuple(params))
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: dict) -> TradeRecord:
        """DB row → TradeRecord 변환."""
        from uuid import UUID as _UUID

        raw_id = row["trade_id"]
        try:
            trade_id = _UUID(raw_id)
        except (ValueError, AttributeError):
            logger.warning("trade_id UUID 파싱 실패, 문자열 그대로 사용: %s", raw_id)
            trade_id = raw_id  # type: ignore[assignment]

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
            account_id=row.get("account_id", "default"),
            currency=row.get("currency", "KRW"),
        )
