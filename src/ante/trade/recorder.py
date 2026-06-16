"""TradeRecorder — 이벤트 기반 거래 자동 기록."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ante.account.errors import InvalidAccountIdError
from ante.account.scoping import require_account_id
from ante.eventbus.fill_dedup_guard import FillDedupGuard
from ante.trade.models import TradeRecord, TradeStatus

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService
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
    account_id     TEXT NOT NULL,
    currency       TEXT DEFAULT 'KRW',
    exchange       TEXT DEFAULT 'KRX'
);
CREATE INDEX IF NOT EXISTS idx_trades_account ON trades(account_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol, timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_status ON trades(status);
"""


class TradeRecorder:
    """EventBus 이벤트를 구독하여 거래를 자동 기록."""

    def __init__(
        self,
        db: Database,
        position_history: PositionHistory,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._db = db
        self._position_history = position_history
        # #2377: 체결 알림 종목명 병기용. 미주입(None)이면 종목코드만 표기하는
        # 기존 경로를 유지한다(CLI 생성 경로는 미주입 — 알림 미발행).
        self._instrument_service = instrument_service
        self._eventbus: EventBus | None = None
        # #1957: 체결 이벤트 bounded 멱등 가드. trades 는 INSERT OR IGNORE 로
        # 이미 DB-멱등이나, NotificationEvent 재발행은 effect 비멱등이라 outbox
        # at-least-once 재전달 시 중복 알림이 난다. 비빈키 재전달을 가드로
        # early-return 해 중복 알림을 차단한다(best-effort — 재기동/maxlen 초과는
        # known-limitation).
        self._fill_dedup_guard = FillDedupGuard()

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
            OrderModifyExecutedEvent,
            OrderRejectedEvent,
        )

        self._eventbus = eventbus
        eventbus.subscribe(OrderFilledEvent, self._on_filled, priority=10)
        eventbus.subscribe(OrderRejectedEvent, self._on_rejected, priority=10)
        eventbus.subscribe(OrderFailedEvent, self._on_failed, priority=10)
        eventbus.subscribe(OrderCancelledEvent, self._on_cancelled, priority=10)
        eventbus.subscribe(OrderCancelFailedEvent, self._on_cancel_failed, priority=10)
        eventbus.subscribe(OrderModifyExecutedEvent, self._on_modified, priority=10)

    async def _on_filled(self, event: object) -> None:
        """체결 이벤트 → 체결 알림 발행.

        #1946: fill 의 durable 적용(trades insert + ``positions``)은 **FillApplier
        단일 권위자**가 단일 트랜잭션으로 수행한다. ``OrderFilledEvent`` 는 commit
        이후 발행되므로, 본 핸들러(priority=10, 가장 늦게 실행)가 호출될 때는 이미
        trades/positions 가 반영된 상태다. 따라서 TradeRecorder 는 fill 경로에서
        trades insert·position 갱신을 **다시 하지 않는다**(이중 적용 방지). 갱신된
        포지션을 읽어 체결 알림만 발행한다. rejected/failed/cancelled 등 비-fill
        상태 기록은 별도 핸들러에서 유지한다.

        #1957: trades insert(``_save``, INSERT OR IGNORE) 는 DB-멱등이지만 아래
        ``NotificationEvent`` publish 는 effect 비멱등이다(NotificationService 의
        60s in-memory content dedup 만 거쳐 재기동/catch_up 재전달 시 중복 알림).
        따라서 비빈키 ``fill_dedup_key`` 가 이미 처리됐으면 **early-return** 해
        중복 NotificationEvent 재발행을 차단한다. 빈키(재전달 없는 단발 경로)는
        가드 비대상으로 항상 처리한다.
        """
        from ante.eventbus.events import NotificationEvent, OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return

        # 비빈키만 dedup. seen_or_add 는 await 없는 동기 원자 구간(#1957).
        if event.fill_dedup_key and self._fill_dedup_guard.seen_or_add(
            event.fill_dedup_key
        ):
            return

        side_label = "매수" if event.side == "buy" else "매도"
        if self._eventbus:
            position = await self._position_history.get_current(
                event.bot_id, event.symbol, account_id=event.account_id
            )
            # #2377: 종목코드만 노출하던 라인에 종목명 병기. 미주입/조회 불가 시
            # symbol-only 로 폴백한다(format_label 이 폴백을 내장 — 무예외·무IO).
            #
            # known-limitation(#2377): OrderFilledEvent.exchange 는 일부
            # producer(durable fill 의 FillApplier._build_filled_payload,
            # VirtualProvider)에서 기본값 KRX 로 들어올 수 있다. 이 경우 비-KRX
            # 종목은 instrument cache((symbol, exchange) 키) 미스로 symbol-only
            # 폴백된다(병기 누락이지 오표기 아님 — 다른 종목명 표기 안 함, #2377
            # 불변식 보존). producer exchange 전파(account_id 기반 역추적)는
            # plan 의 "schema 확장 금지"·"비-KRX 거래소 이름 소스 확장 비목표"에
            # 따라 후속 이슈 영역.
            symbol_label = (
                self._instrument_service.format_label(
                    event.symbol, event.exchange, markdown=True
                )
                if self._instrument_service is not None
                else f"`{event.symbol}`"
            )
            base_msg = (
                f"봇 `{event.bot_id}`\n"
                f"종목: {symbol_label}\n"
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
            account_id=event.account_id,
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
            account_id=event.account_id,
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
            account_id=event.account_id,
        )
        await self._save(record)

    async def _on_modified(self, event: object) -> None:
        """정정 완료 이벤트 → 정정 기록 저장 (#2391, v1=price-only).

        ``OrderModifyExecutedEvent.price`` 는 신규 정정 가격이며, ``quantity`` 는
        원주문 수량(불변)이다. ``event_id`` 를 trade_id PK 로 써 멱등(INSERT OR
        IGNORE)하게 별도 row 를 남긴다(취소 기록 _on_cancelled 와 동형).
        """
        from ante.eventbus.events import OrderModifyExecutedEvent

        if not isinstance(event, OrderModifyExecutedEvent):
            return

        record = TradeRecord(
            trade_id=event.event_id,
            bot_id=event.bot_id,
            strategy_id=event.strategy_id,
            symbol=event.symbol,
            side=event.side,
            quantity=event.quantity,
            price=event.price or 0.0,
            status=TradeStatus.MODIFIED,
            order_type="",
            reason=event.reason,
            timestamp=event.timestamp,
            order_id=event.order_id,
            account_id=event.account_id,
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
        account_id = require_account_id(
            record.account_id, context="trade_recorder._save"
        )
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
                account_id,
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
        *,
        account_id: str,
    ) -> None:
        """대사 보정 이력 기록."""
        from ante.account.scoping import require_account_id

        account_id = require_account_id(
            account_id, context="trade_recorder.save_adjustment"
        )
        # #2371: timestamp 는 save_trade/_save_trade 와 동일한 UTC-aware isoformat 으로
        # 저장한다(과거 SQLite ``datetime('now')`` 공백 구분 포맷 금지). lexical
        # 비교에서 공백(0x20) < 'T'(0x54) 라 ``trade list --from`` 당일 경계에서
        # 보정 행이 누락되던 단일-포맷 invariant 위반을 닫는다.
        timestamp = datetime.now(UTC).isoformat()
        await self._db.execute(
            """INSERT INTO trades
               (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                status, order_type, reason, timestamp, account_id)
               VALUES (?, ?, '', ?, 'adjustment', ?, 0.0, 'adjusted', '', ?,
                       ?, ?)""",
            (
                str(uuid4()),
                bot_id,
                symbol,
                abs(new_quantity - old_quantity),
                reason,
                timestamp,
                account_id,
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
        from ante.account.scoping import INVALID_RUNTIME_ACCOUNT_IDS

        conditions: list[str] = []
        params: list[Any] = []
        validated_account_id: str | None = None
        if account_id is not None:
            validated_account_id = require_account_id(
                account_id, context="trade_recorder.get_trades"
            )

        # Refs #1240 review (P2-3): legacy invalid account_id row를 SQL 단계에서
        # 제외해야 LIMIT/OFFSET 페이지네이션이 정확해진다. Python 단계 skip만으로는
        # legacy default row가 첫 페이지를 가득 채울 때 유효 거래가 다음 페이지에
        # 묻혀 underflow 가 발생한다. SSOT (``INVALID_RUNTIME_ACCOUNT_IDS``) 와
        # 빈 문자열/NULL을 함께 제외한다.
        invalid_ids = sorted(INVALID_RUNTIME_ACCOUNT_IDS)
        invalid_placeholders = ", ".join("?" for _ in invalid_ids)
        conditions.append(
            f"account_id IS NOT NULL AND account_id != '' "
            f"AND account_id NOT IN ({invalid_placeholders})"
        )
        params.extend(invalid_ids)

        if validated_account_id is not None:
            conditions.append("account_id = ?")
            params.append(validated_account_id)
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

        where = " AND ".join(conditions)
        query = f"""SELECT * FROM trades
                    WHERE {where}
                    ORDER BY timestamp DESC
                    LIMIT ? OFFSET ?"""
        params.extend([limit, offset])

        rows = await self._db.fetch_all(query, tuple(params))
        return self._rows_to_records(rows, context="get_trades")

    @classmethod
    def _rows_to_records(cls, rows: list[dict], *, context: str) -> list[TradeRecord]:
        """rows → TradeRecord 목록, legacy invalid account_id row는 skip."""
        records: list[TradeRecord] = []
        for row in rows:
            record = cls._row_to_record_safe(row, context=context)
            if record is not None:
                records.append(record)
        return records

    @classmethod
    def _row_to_record_safe(cls, row: dict, *, context: str) -> TradeRecord | None:
        """DB row → TradeRecord, legacy invalid account_id row는 skip.

        legacy ``account_id='default'`` (또는 기타 invalid) 값을 가진 row는
        :class:`InvalidAccountIdError` 로 skip하고 warning만 남긴다.
        스키마/데이터 마이그레이션(#1219 등)이 완료되기 전에도 trade read
        경로(get_trades, DailyReport 등)가 실패하지 않도록 하기 위함이다.
        """
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
            account_id=row["account_id"],
            currency=row.get("currency", "KRW"),
        )
