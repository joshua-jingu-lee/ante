"""FillApplier — 단일 멱등 choke point."""

from __future__ import annotations

import asyncio
import logging
import math
import uuid
from datetime import UTC
from typing import TYPE_CHECKING, ClassVar
from uuid import uuid4

from ante.account.scoping import require_account_id
from ante.core import clock
from ante.trade.models import TradeRecord, TradeStatus

if TYPE_CHECKING:
    from datetime import datetime

    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.fill_outbox import FillOutbox, FillOutboxPublisher
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.position import PositionHistory

logger = logging.getLogger(__name__)

_VIRTUAL_TRADE_NAMESPACE = uuid.UUID("5b0c7f3e-2611-4a5e-9d1c-7f3a2b8e6c41")


class InsufficientHoldingsError(Exception):
    """가상 매도 수량이 그 봇의 포지션 보유를 넘는다."""


class FillApplier:
    """체결 반영 단일 권위자. 단일 인스턴스로 운영한다."""

    InsufficientHoldingsError: ClassVar[type[InsufficientHoldingsError]] = (
        InsufficientHoldingsError
    )

    def __init__(
        self,
        *,
        db: Database,
        order_tracker: OrderTracker,
        position_history: PositionHistory,
        eventbus: EventBus,
        outbox: FillOutbox | None = None,
        publisher: FillOutboxPublisher | None = None,
    ) -> None:
        self._db = db
        self._tracker = order_tracker
        self._position_history = position_history
        self._eventbus = eventbus
        self._outbox = outbox
        self._publisher = publisher
        self._lock = asyncio.Lock()

    async def apply_cumulative(
        self,
        *,
        account_id: str,
        broker_order_id: str,
        observed_cumulative: float,
        avg_price: float,
        submitted_date: str,
    ) -> float:
        """관측 누적 체결량을 멱등 적용. 적용된 delta 를 반환 (no-op이면 0).

        1. ``lookup_order_id`` 로 추적 주문 확인 — 없으면 무시(self/external 경계).
        2. 단일 트랜잭션: CAS advance → delta>0 이면 TradeRecord + position 적용 +
           OrderFilledEvent payload 를 outbox 에 INSERT(동일 원자 커밋).
        3. commit 이후 publisher 워커가 outbox 미발행분을 at-least-once 발행한다
           (outbox 미주입 fallback 경로는 commit 직후 직접 1회 발행).
        """
        validated = require_account_id(
            account_id, context="fill_applier.apply_cumulative"
        )

        async with self._lock:
            order_id = await self._tracker.lookup_order_id(
                validated, broker_order_id, submitted_date
            )
            if order_id is None:
                logger.debug(
                    "추적되지 않는 체결 무시: account=%s odno=%s date=%s",
                    validated,
                    broker_order_id,
                    submitted_date,
                )
                return 0.0

            record = await self._tracker.get(order_id)
            if record is None:
                return 0.0

            return await self._apply_locked(
                record=record,
                order_id=order_id,
                broker_order_id=broker_order_id,
                observed_cumulative=observed_cumulative,
                avg_price=avg_price,
                account_id=validated,
            )

    async def apply_stream_increment(
        self,
        *,
        account_id: str,
        broker_order_id: str,
        increment: float,
        avg_price: float,
        submitted_date: str,
    ) -> float:
        """스트림(빠른 경로)의 per-execution 증분을 누적으로 환산해 적용.

        실시간 체결 통보(``H0STCNI0``)는 누적이 아닌 per-execution 증분을 준다.
        Lock 안에서 추적 주문의 현재 ``recorded_filled_qty`` 를 읽어
        ``observed_cumulative = recorded + increment`` 로 환산한 뒤 백스톱과 동일한
        누적 멱등 모델(``apply_cumulative`` 코어)로 수렴시킨다.
        """
        validated = require_account_id(
            account_id, context="fill_applier.apply_stream_increment"
        )
        if increment <= 0:
            return 0.0
        async with self._lock:
            order_id = await self._tracker.lookup_order_id(
                validated, broker_order_id, submitted_date
            )
            if order_id is None:
                return 0.0
            record = await self._tracker.get(order_id)
            if record is None:
                return 0.0
            observed_cumulative = record.recorded_filled_qty + increment
            return await self._apply_locked(
                record=record,
                order_id=order_id,
                broker_order_id=broker_order_id,
                observed_cumulative=observed_cumulative,
                avg_price=avg_price,
                account_id=validated,
            )

    async def _apply_locked(
        self,
        *,
        record: object,
        order_id: str,
        broker_order_id: str,
        observed_cumulative: float,
        avg_price: float,
        account_id: str,
    ) -> float:
        """Lock 보유 상태의 공통 코어: 단일 트랜잭션 적용, delta 반환(0 이하면 0.0)."""
        from ante.trade.fill_outbox import make_fill_dedup_key
        from ante.trade.order_tracker import OrderTrackerRecord

        assert isinstance(record, OrderTrackerRecord)
        fill_dedup_key = ""
        with self._position_history.defer_cache():
            async with self._db.transaction():
                result = await self._tracker.record_fill(
                    order_id, observed_cumulative, avg_price
                )
                delta = result.delta
                if delta <= 0:
                    return 0.0
                trade = TradeRecord(
                    trade_id=uuid4(),
                    bot_id=record.bot_id,
                    strategy_id=record.strategy_id,
                    symbol=record.symbol,
                    side=record.side,
                    quantity=delta,
                    price=avg_price,
                    status=TradeStatus.FILLED,
                    order_type=record.order_type,
                    timestamp=clock.now(UTC),
                    order_id=order_id,
                    account_id=account_id,
                    exchange=record.exchange or "KRX",
                )
                await self._save_trade(trade)
                await self._position_history.on_trade(trade)

                if self._outbox is not None:
                    fill_dedup_key = make_fill_dedup_key(
                        order_id, result.confirmed_cumulative
                    )
                    payload = self._build_payload(
                        record, order_id, delta, avg_price, fill_dedup_key
                    )
                    await self._outbox.enqueue(
                        fill_dedup_key=fill_dedup_key, payload=payload
                    )

        self._tracker.mirror_fill_to_cache(
            order_id, result.confirmed_cumulative, result.new_status
        )

        if self._outbox is not None:
            if self._publisher is not None:
                self._publisher.notify()
        else:
            await self._publish_filled(record, order_id, delta, avg_price)
        logger.info(
            "체결 반영: order=%s odno=%s %s %s delta=%s @ %s (cumulative=%s)",
            order_id,
            broker_order_id,
            record.side,
            record.symbol,
            delta,
            avg_price,
            observed_cumulative,
        )
        return delta

    async def _save_trade(self, trade: TradeRecord) -> None:
        """trades 테이블에 체결 기록 insert (트랜잭션 내)."""
        await self._db.execute(
            """INSERT OR IGNORE INTO trades
                   (trade_id, bot_id, strategy_id, symbol, side, quantity, price,
                    status, order_type, reason, commission, timestamp, order_id,
                    account_id, currency, exchange)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(trade.trade_id),
                trade.bot_id,
                trade.strategy_id,
                trade.symbol,
                trade.side,
                trade.quantity,
                trade.price,
                trade.status.value,
                trade.order_type,
                trade.reason,
                trade.commission,
                trade.timestamp.isoformat() if trade.timestamp else None,
                trade.order_id,
                trade.account_id,
                trade.currency,
                trade.exchange,
            ),
        )

    def _build_payload(
        self,
        record: object,
        order_id: str,
        delta: float,
        avg_price: float,
        fill_dedup_key: str,
    ) -> dict[str, object]:
        """outbox 에 저장할 ``OrderFilledEvent`` 생성자 인자 payload."""
        from ante.trade.order_tracker import OrderTrackerRecord

        assert isinstance(record, OrderTrackerRecord)
        return {
            "account_id": record.account_id,
            "order_id": order_id,
            "broker_order_id": record.broker_order_id,
            "bot_id": record.bot_id,
            "strategy_id": record.strategy_id,
            "symbol": record.symbol,
            "side": record.side,
            "quantity": delta,
            "price": avg_price,
            "order_type": record.order_type,
            "fill_dedup_key": fill_dedup_key,
            "exchange": record.exchange or "KRX",
        }

    async def _publish_filled(
        self,
        record: object,
        order_id: str,
        delta: float,
        avg_price: float,
    ) -> None:
        """``OrderFilledEvent`` 직접 발행 (outbox 미주입 legacy fallback)."""
        from ante.eventbus.events import OrderFilledEvent
        from ante.trade.order_tracker import OrderTrackerRecord

        assert isinstance(record, OrderTrackerRecord)
        await self._eventbus.publish(
            OrderFilledEvent(
                account_id=record.account_id,
                order_id=order_id,
                broker_order_id=record.broker_order_id,
                bot_id=record.bot_id,
                strategy_id=record.strategy_id,
                symbol=record.symbol,
                side=record.side,
                quantity=delta,
                price=avg_price,
                order_type=record.order_type,
                exchange=record.exchange or "KRX",
            )
        )

    async def apply_direct_fill(
        self,
        *,
        account_id: str,
        order_id: str,
        bot_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float,
        order_type: str,
        exchange: str,
        timestamp: datetime,
    ) -> bool:
        validated = require_account_id(
            account_id, context="fill_applier.apply_direct_fill"
        )
        if not order_id:
            raise ValueError("apply_direct_fill: order_id must not be empty")
        if not (math.isfinite(quantity) and quantity > 0) or not (
            math.isfinite(price) and price > 0
        ):
            raise ValueError(
                f"apply_direct_fill: quantity and price must be finite and positive "
                f"(quantity={quantity}, price={price})"
            )
        trade = TradeRecord(
            trade_id=uuid.uuid5(_VIRTUAL_TRADE_NAMESPACE, f"virtual:{order_id}"),
            bot_id=bot_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            price=price,
            status=TradeStatus.FILLED,
            order_type=order_type,
            commission=commission,
            timestamp=timestamp,
            order_id=order_id,
            account_id=validated,
            exchange=exchange or "KRX",
        )
        async with self._lock:
            with self._position_history.defer_cache():
                async with self._db.transaction():
                    inserted = await self._db.execute_fetch_one(
                        """INSERT INTO trades
                               (trade_id, bot_id, strategy_id, symbol, side,
                                quantity, price, status, order_type, reason,
                                commission, timestamp, order_id, account_id,
                                currency, exchange)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                           ON CONFLICT DO NOTHING
                           RETURNING trade_id""",
                        (
                            str(trade.trade_id),
                            trade.bot_id,
                            trade.strategy_id,
                            trade.symbol,
                            trade.side,
                            trade.quantity,
                            trade.price,
                            trade.status.value,
                            trade.order_type,
                            trade.reason,
                            trade.commission,
                            timestamp.isoformat(),
                            trade.order_id,
                            trade.account_id,
                            trade.currency,
                            trade.exchange,
                        ),
                    )
                    if inserted is None:
                        return False
                    if side == "sell":
                        position = await self._position_history.get_current(
                            bot_id, symbol, account_id=validated
                        )
                        if quantity > position["quantity"]:
                            raise InsufficientHoldingsError(
                                f"apply_direct_fill: sell quantity {quantity} exceeds "
                                f"holdings {position['quantity']} "
                                f"(bot={bot_id}, symbol={symbol})"
                            )
                    await self._position_history.on_trade(trade)
        logger.info(
            "가상 체결 기록: order=%s %s %s qty=%s @ %s commission=%s",
            order_id,
            side,
            symbol,
            quantity,
            price,
            commission,
        )
        return True
