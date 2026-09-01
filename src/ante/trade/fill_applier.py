"""FillApplier — 단일 멱등 choke point (#1946).

빠른 경로(실시간 체결 통보 스트림)와 백스톱 경로(REST ``get_order_history`` 폴)가
모두 ``apply_cumulative`` 로 수렴한다. 같은 체결을 몇 번 관측하든 포지션은 정확히
한 번 반영된다.

crash 원자성: ``recorded_filled_qty`` advance(CAS) + ``TradeRecord`` insert +
``PositionHistory.on_trade`` 를 ``Database.transaction()`` 단일 트랜잭션으로 묶는다.
적용 도중 crash 하면 rollback 되어 recorded 가 advance 되지 않고, 재기동 후 다음
폴이 동일 delta 를 재적용한다 → positions/trades crash-safe exactly-once.

이벤트 durability (#1949): outbox 가 주입되면 같은 트랜잭션 안에서
``OrderFilledEvent`` payload 를 ``fill_outbox`` 에 INSERT 한다. commit 성공 =
이벤트 영속 보장이므로, commit↔publish 사이 crash window 가 닫힌다(이벤트 무손실).
실제 발행은 ``FillOutboxPublisher`` 워커가 트랜잭션 밖에서 at-least-once 로 한다.
(소비자 멱등화는 #1957 범위. #1949 는 무손실 전달 + 결정적 키 제공까지.)

``asyncio.Lock`` 은 read → delta → txn(outbox insert 포함) 전체를 감싸 프로세스
내 동시 관측을 직렬화한다.

상세 설계: ``docs/specs/trade/03-08-fill-recovery.md``,
``docs/specs/broker-adapter/18-fill-recovery.md``(§5.2),
``docs/specs/eventbus/eventbus.md``(전달 시맨틱).
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
    from ante.trade.fill_outbox import FillOutbox, FillOutboxPublisher
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
        outbox: FillOutbox | None = None,
        publisher: FillOutboxPublisher | None = None,
    ) -> None:
        self._db = db
        self._tracker = order_tracker
        self._position_history = position_history
        self._eventbus = eventbus
        # #1949: outbox 가 주입되면 체결 적용 txn 안에서 이벤트 payload 를 함께
        # 커밋하고(durability), publisher 워커가 commit↔publish crash window 밖에서
        # at-least-once 로 발행한다. 미주입(legacy/단위 테스트 partial wiring)이면
        # 기존처럼 commit 직후 직접 발행(crash window 잔존 — 본 이슈 이전 동작).
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
           (#1949) OrderFilledEvent payload 를 outbox 에 INSERT(동일 원자 커밋).
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

        #1949 durability: outbox 가 주입되면 recorded advance + trade insert +
        position update **와 동일 트랜잭션** 안에서 OrderFilledEvent payload 를
        outbox 에 INSERT 한다(원자 커밋). commit 성공 = 이벤트 영속 보장이므로
        commit↔publish 사이 crash window 가 닫힌다. 발행은 트랜잭션 밖에서
        publisher 워커(at-least-once)에 위임한다.

        #1948 open 캐시 미러: ``record_fill`` 은 트랜잭션 내부 호출이라 캐시를
        건드리지 않는다(rollback 시 stale 방지). LIVE ``get_open_orders`` 의 sync
        캐시는 트랜잭션 블록이 **정상 COMMIT 된 직후** ``mirror_fill_to_cache`` 로만
        갱신한다. rollback(``_save_trade``/position/outbox 실패) 시 commit 이후
        지점에 도달하지 못해 캐시는 불변 — DB(원복)와 일관된다. 스트림/폴 양
        경로의 공통 코어라 미러 호출은 이 한 지점뿐이다.
        """
        from ante.trade.fill_outbox import make_fill_dedup_key
        from ante.trade.order_tracker import OrderTrackerRecord

        assert isinstance(record, OrderTrackerRecord)
        fill_dedup_key = ""
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
                timestamp=datetime.now(UTC),
                order_id=order_id,
                account_id=account_id,
                # #2487: 주문 거래소는 tracker record 가 단일 소스다. v007 이전
                # legacy row(exchange NULL)는 "KRX" 폴백 — 종전 관측값과 동일.
                exchange=record.exchange or "KRX",
            )
            await self._save_trade(trade)
            await self._position_history.on_trade(trade)

            if self._outbox is not None:
                # 결정적 키는 CAS RETURNING 확정 누적값으로 산출(입력값 아님).
                fill_dedup_key = make_fill_dedup_key(
                    order_id, result.confirmed_cumulative
                )
                payload = self._build_payload(
                    record, order_id, delta, avg_price, fill_dedup_key
                )
                await self._outbox.enqueue(
                    fill_dedup_key=fill_dedup_key, payload=payload
                )

        # commit 성공 (rollback 시 이 지점 미도달). #1948: LIVE get_open_orders 의
        # sync open 캐시를 CAS 확정값(confirmed_cumulative)/확정 status 로 미러링.
        # delta>0 경로만 도달하므로 항상 유효한 advance 다.
        self._tracker.mirror_fill_to_cache(
            order_id, result.confirmed_cumulative, result.new_status
        )

        # outbox 경유면 워커가 발행(crash window 닫힘), 미주입이면
        # 기존처럼 commit 직후 직접 발행한다.
        if self._outbox is not None:
            if self._publisher is not None:
                # enqueue 직후 즉시 드레인 트리거. 누락돼도 워커 주기 백스톱.
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

    def _build_payload(
        self,
        record: object,
        order_id: str,
        delta: float,
        avg_price: float,
        fill_dedup_key: str,
    ) -> dict[str, object]:
        """outbox 에 저장할 ``OrderFilledEvent`` 생성자 인자 payload (#1949).

        ``event_id``/``timestamp`` 는 발행 시점에 새로 생성되도록 제외한다(재전달
        시 새 event_id 가 부여돼도 dedup 은 결정적 ``fill_dedup_key`` 로 한다).
        키 집합은 ``FillOutboxPublisher._publish_row`` 의
        ``OrderFilledEvent(**payload)`` 와 정확히 호응해야 한다.
        """
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
            # #2487: legacy tracker row(exchange NULL)는 "KRX" 폴백.
            "exchange": record.exchange or "KRX",
        }

    async def _publish_filled(
        self,
        record: object,
        order_id: str,
        delta: float,
        avg_price: float,
    ) -> None:
        """``OrderFilledEvent`` 직접 발행 (outbox 미주입 legacy fallback).

        outbox 가 주입되지 않은 경로(단위 테스트 partial wiring 등)에서만 쓰인다.
        이 경로는 commit↔publish crash window 가 잔존하며(#1949 이전 동작),
        ``fill_dedup_key`` 를 채우지 않는다(빈키).
        """
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
                # #2487: legacy tracker row(exchange NULL)는 "KRX" 폴백.
                exchange=record.exchange or "KRX",
            )
        )
