"""FillApplier — 단일 멱등 choke point (#1946).

빠른 경로(실시간 체결 통보 스트림)와 백스톱 경로(REST ``get_order_history`` 폴)가
모두 ``apply_cumulative`` 로 수렴한다. 같은 체결을 몇 번 관측하든 포지션은 정확히
한 번 반영된다.

crash 원자성: ``recorded_filled_qty`` advance(CAS) + ``TradeRecord`` insert +
``PositionHistory.on_trade`` 를 ``Database.transaction()`` 단일 트랜잭션으로 묶는다.
적용 도중 crash 하면 rollback 되어 recorded 가 advance 되지 않고, 재기동 후 다음
폴이 동일 delta 를 재적용한다 → positions/trades crash-safe exactly-once.

``asyncio.Lock`` 은 read → delta → txn → publish 전체를 감싸 프로세스 내 동시
관측을 직렬화한다.

상세 설계: ``docs/specs/trade/03-08-fill-recovery.md``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ante.account.scoping import require_account_id
from ante.trade.models import TradeRecord, TradeStatus

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.position import PositionHistory

logger = logging.getLogger(__name__)


class FillApplier:
    """체결 반영 단일 권위자. 단일 인스턴스로 운영한다."""

    def __init__(
        self,
        *,
        db: Database,
        order_tracker: OrderTracker,
        position_history: PositionHistory,
        eventbus: EventBus,
    ) -> None:
        self._db = db
        self._tracker = order_tracker
        self._position_history = position_history
        self._eventbus = eventbus
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
        2. 단일 트랜잭션: CAS advance → delta>0 이면 TradeRecord + position 적용.
        3. commit 이후 ``OrderFilledEvent``(delta) 1회 발행.
        """
        validated = require_account_id(
            account_id, context="fill_applier.apply_cumulative"
        )

        async with self._lock:
            order_id = await self._tracker.lookup_order_id(
                validated, broker_order_id, submitted_date
            )
            if order_id is None:
                # 추적되지 않는 주문 — self/external 경계. 진짜 외부 포지션은
                # reconciler 영역. 멱등하게 무시한다.
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

        스트림은 fast-path 이며 정합성 SSOT 는 백스톱 폴이다. 드물게 스트림이
        같은 체결을 중복 통보하면 일시적으로 과다 환산될 수 있으나, 이는
        bounded fast-path 한계이며 누적 advance 의 단조성·정상 경로 정확성은
        유지된다.
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
        """Lock 보유 상태에서 단일 트랜잭션 적용 + 발행. delta 반환.

        ``apply_cumulative`` / ``apply_stream_increment`` 의 공통 코어. 호출자가
        이미 ``self._lock`` 을 보유하고 ``record`` 를 조회한 상태여야 한다.
        """
        from ante.trade.order_tracker import OrderTrackerRecord

        assert isinstance(record, OrderTrackerRecord)
        async with self._db.transaction():
            delta = await self._tracker.record_fill(
                order_id, observed_cumulative, avg_price
            )
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
                timestamp=datetime.now(UTC),
                order_id=order_id,
                account_id=account_id,
            )
            await self._save_trade(trade)
            await self._position_history.on_trade(trade)

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
        """trades 테이블에 체결 기록 insert (트랜잭션 내).

        TradeRecorder 와 동일 스키마. 본 호출은 FillApplier 의 ``transaction()``
        안에서 실행되므로 ``_db.execute`` 는 commit 하지 않고 한 트랜잭션에 묶인다.
        """
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

    async def _publish_filled(
        self,
        record: object,
        order_id: str,
        delta: float,
        avg_price: float,
    ) -> None:
        """``OrderFilledEvent`` 발행 (정체성은 tracker 에서 복원)."""
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
            )
        )
