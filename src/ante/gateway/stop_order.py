"""StopOrderManager — 스탑 주문 에뮬레이션.

KRX는 네이티브 스탑 주문을 지원하지 않으므로,
실시간 시세를 모니터링하여 트리거 조건 충족 시
시장가/지정가 주문으로 변환하여 기존 주문 흐름에 주입한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

# 거래 세션 시간 (한국 시간 기준, UTC+9)
REGULAR_SESSION_START = (0, 0)  # 09:00 KST = 00:00 UTC
REGULAR_SESSION_END = (6, 30)  # 15:30 KST = 06:30 UTC
EXTENDED_SESSION_START = (23, 30)  # 08:30 KST (전일 23:30 UTC)
EXTENDED_SESSION_END = (9, 0)  # 18:00 KST = 09:00 UTC


@dataclass
class StopOrder:
    """스탑 주문 내부 표현."""

    stop_order_id: str
    order_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str  # "stop" | "stop_limit"
    stop_price: float
    limit_price: float | None
    trading_session: str  # "regular" | "extended"
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    triggered: bool = False
    expired: bool = False
    exchange: str = "KRX"


class StopOrderManager:
    """스탑 주문 에뮬레이션 매니저.

    - 스탑 주문 등록/취소/조회
    - 실시간 시세 기반 트리거 판단
    - 세션 종료 시 미트리거 주문 만료
    """

    def __init__(self, eventbus: EventBus) -> None:
        self._eventbus = eventbus
        self._orders: dict[str, StopOrder] = {}
        self._running = False

    @property
    def active_orders(self) -> list[StopOrder]:
        """활성 스탑 주문 목록."""
        return [o for o in self._orders.values() if not o.triggered and not o.expired]

    @property
    def monitored_symbols(self) -> set[str]:
        """모니터링 대상 종목."""
        return {o.symbol for o in self.active_orders}

    async def start(self) -> None:
        """매니저 시작."""
        self._running = True
        logger.info("StopOrderManager 시작")

    async def stop(self) -> None:
        """매니저 중지. 활성 주문 모두 만료 처리."""
        self._running = False
        for order in self.active_orders:
            await self._expire_order(order, "manager_stopped")
        logger.info("StopOrderManager 중지")

    async def register(
        self,
        order_id: str,
        bot_id: str,
        strategy_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        stop_price: float,
        limit_price: float | None = None,
        trading_session: str = "regular",
        exchange: str = "KRX",
    ) -> str:
        """스탑 주문 등록.

        Returns:
            stop_order_id
        """
        stop_order_id = f"stop-{uuid4().hex[:12]}"

        order = StopOrder(
            stop_order_id=stop_order_id,
            order_id=order_id,
            bot_id=bot_id,
            strategy_id=strategy_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            stop_price=stop_price,
            limit_price=limit_price,
            trading_session=trading_session,
            exchange=exchange,
        )
        self._orders[stop_order_id] = order

        logger.info(
            "스탑 주문 등록: %s %s %s stop=%.0f",
            stop_order_id,
            side,
            symbol,
            stop_price,
        )

        from ante.eventbus.events import StopOrderRegisteredEvent

        await self._eventbus.publish(
            StopOrderRegisteredEvent(
                stop_order_id=stop_order_id,
                bot_id=bot_id,
                strategy_id=strategy_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                order_type=order_type,
                stop_price=stop_price,
                limit_price=limit_price,
            )
        )

        return stop_order_id

    async def cancel(self, stop_order_id: str) -> bool:
        """스탑 주문 취소."""
        order = self._orders.get(stop_order_id)
        if not order or order.triggered or order.expired:
            return False

        order.expired = True
        del self._orders[stop_order_id]
        logger.info("스탑 주문 취소: %s", stop_order_id)
        return True

    def get_order(self, stop_order_id: str) -> StopOrder | None:
        """스탑 주문 조회."""
        return self._orders.get(stop_order_id)

    def get_orders_for_bot(self, bot_id: str) -> list[StopOrder]:
        """봇의 활성 스탑 주문 목록."""
        return [o for o in self.active_orders if o.bot_id == bot_id]

    async def on_price_update(self, symbol: str, price: float) -> None:
        """실시간 시세 수신 시 트리거 판단.

        매수 스탑: 현재가 >= stop_price → 트리거
        매도 스탑: 현재가 <= stop_price → 트리거
        """
        if not self._running:
            return

        active_for_symbol = [
            o
            for o in self.active_orders
            if o.symbol == symbol and self._is_in_session(o)
        ]

        for order in active_for_symbol:
            if self._should_trigger(order, price):
                await self._trigger_order(order, price)

    async def check_session_expiry(self) -> None:
        """세션 종료 시 미트리거 주문 만료 처리."""
        for order in self.active_orders:
            if not self._is_in_session(order):
                await self._expire_order(order, "session_ended")

    def _should_trigger(self, order: StopOrder, price: float) -> bool:
        """트리거 조건 판단."""
        if order.side == "buy":
            return price >= order.stop_price
        else:  # sell
            return price <= order.stop_price

    def _is_in_session(self, order: StopOrder) -> bool:
        """현재 시각이 주문의 거래 세션 시간 내인지 확인."""
        now = datetime.now(UTC)
        hour, minute = now.hour, now.minute
        current_minutes = hour * 60 + minute

        if order.trading_session == "extended":
            # 확장 세션: 08:30-18:00 KST (23:30-09:00 UTC, 자정 걸침)
            start = EXTENDED_SESSION_START[0] * 60 + EXTENDED_SESSION_START[1]
            end = EXTENDED_SESSION_END[0] * 60 + EXTENDED_SESSION_END[1]
            if start > end:  # 자정 걸침
                return current_minutes >= start or current_minutes < end
            return start <= current_minutes < end
        else:
            # 정규 세션: 09:00-15:30 KST (00:00-06:30 UTC)
            start = REGULAR_SESSION_START[0] * 60 + REGULAR_SESSION_START[1]
            end = REGULAR_SESSION_END[0] * 60 + REGULAR_SESSION_END[1]
            return start <= current_minutes < end

    async def _trigger_order(self, order: StopOrder, trigger_price: float) -> None:
        """스탑 주문 트리거 → 시장가/지정가 주문으로 변환."""
        order.triggered = True

        # stop → market, stop_limit → limit
        converted_type = "limit" if order.order_type == "stop_limit" else "market"
        converted_price = order.limit_price if converted_type == "limit" else None

        logger.info(
            "스탑 주문 트리거: %s %s %s trigger=%.0f → %s",
            order.stop_order_id,
            order.side,
            order.symbol,
            trigger_price,
            converted_type,
        )

        from ante.eventbus.events import OrderRequestEvent, StopOrderTriggeredEvent

        # 트리거 이벤트 발행
        await self._eventbus.publish(
            StopOrderTriggeredEvent(
                stop_order_id=order.stop_order_id,
                bot_id=order.bot_id,
                strategy_id=order.strategy_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                trigger_price=trigger_price,
                converted_order_type=converted_type,
            )
        )

        # 변환된 주문을 기존 흐름에 주입
        await self._eventbus.publish(
            OrderRequestEvent(
                bot_id=order.bot_id,
                strategy_id=order.strategy_id,
                symbol=order.symbol,
                side=order.side,
                quantity=order.quantity,
                order_type=converted_type,
                price=converted_price,
                reason=f"stop_triggered: {order.stop_order_id}",
                exchange=order.exchange,
            )
        )

    async def _expire_order(self, order: StopOrder, reason: str) -> None:
        """스탑 주문 만료 처리."""
        order.expired = True

        logger.info(
            "스탑 주문 만료: %s (%s)",
            order.stop_order_id,
            reason,
        )

        from ante.eventbus.events import StopOrderExpiredEvent

        await self._eventbus.publish(
            StopOrderExpiredEvent(
                stop_order_id=order.stop_order_id,
                bot_id=order.bot_id,
                strategy_id=order.strategy_id,
                symbol=order.symbol,
                reason=reason,
            )
        )
