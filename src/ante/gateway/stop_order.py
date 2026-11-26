"""StopOrderManager — 스탑 주문 에뮬레이션."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from ante.core import clock

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

REGULAR_SESSION_START = (0, 0)
REGULAR_SESSION_END = (6, 30)
EXTENDED_SESSION_START = (23, 30)
EXTENDED_SESSION_END = (9, 0)

SESSION_TYPES = ("regular", "extended")


class StopOrderManagerStoppedError(RuntimeError):
    """매니저가 stopped(``_running=False``) 상태에서 register 가 호출됐을 때.

    stopped/pre-start 상태의 등록은 silent loss(빈 문자열
    반환)가 아니라 예외로 거부한다. 호출자(gateway ``_on_order_approved``)가
    이를 잡아 ``OrderFailedEvent`` 로 terminal 종결하므로, in-flight 주문이
    영구 inert 로 남지 않는다.
    """

    code = "STOP_ORDER_MANAGER_STOPPED"


@dataclass
class StopOrder:
    """스탑 주문 내부 표현.

    ``account_id`` 는 runtime 시점부터 ``require_account_id``
    로 검증된다. multi-account 환경에서 같은 종목의 stop order 가 다른
    계좌의 시세 tick 으로 잘못 trigger 되지 않도록 격리한다.
    """

    stop_order_id: str
    order_id: str
    bot_id: str
    strategy_id: str
    symbol: str
    side: str
    quantity: float
    order_type: str
    stop_price: float
    limit_price: float | None
    trading_session: str
    account_id: str
    registered_at: datetime = field(default_factory=lambda: clock.now(UTC))
    triggered: bool = False
    expired: bool = False
    exchange: str = "KRX"
    entered_session: bool = False

    def __post_init__(self) -> None:
        from ante.account.scoping import require_account_id

        require_account_id(self.account_id, context="stop_order.register")


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
        self._session_tick_marked: set[str] = set()
        self._inflight_expires: set[asyncio.Task[None]] = set()

    @property
    def active_orders(self) -> list[StopOrder]:
        """활성 스탑 주문 목록."""
        return [o for o in self._orders.values() if not o.triggered and not o.expired]

    @property
    def monitored_symbols(self) -> set[str]:
        """모니터링 대상 종목."""
        return {o.symbol for o in self.active_orders}

    def start(self) -> None:
        """매니저 시작."""
        self._running = True
        logger.info("StopOrderManager 시작")

    async def stop(self) -> None:
        """매니저 중지. 활성 주문 모두 만료 처리.

        P2-A: ``active_orders`` 의 manager_stopped 정리 후,
        shutdown 중 sweep cancel 로 background 에 남은 in-flight
        ``_do_expire_order`` task 들을 loop teardown 전에 await 해 in-flight
        terminal(session_ended) 유실을 막는다. half-expired order 는 이미
        ``expired=True`` 라 ``active_orders`` 에서 빠져 manager_stopped 가
        재발행되지 않으므로 terminal 이 이중 발행되지 않는다.
        """
        self._running = False
        for order in self.active_orders:
            await self._expire_order(order, "manager_stopped")
        if self._inflight_expires:
            await asyncio.gather(*list(self._inflight_expires), return_exceptions=True)
        self._session_tick_marked.clear()
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
        *,
        account_id: str,
        limit_price: float | None = None,
        trading_session: str = "regular",
        exchange: str = "KRX",
    ) -> str:
        """스탑 주문 등록.

        Raises:
            InvalidAccountIdError: account_id 가 invalid 일 때.
            StopOrderManagerStoppedError: 매니저가 stopped(``_running=False``)
                상태일 때.
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stop_order.register")

        if not self._running:
            logger.warning(
                "StopOrderManager stopped 상태 — stop 주문 등록 거부: %s %s stop=%.0f",
                side,
                symbol,
                stop_price,
            )
            raise StopOrderManagerStoppedError(
                f"StopOrderManager stopped — register 거부: {side} {symbol} "
                f"stop={stop_price:.0f}"
            )

        stop_order_id = f"stop-{uuid4().hex[:12]}"
        now = clock.now(UTC)

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
            account_id=account_id,
            registered_at=now,
        )
        self._orders[stop_order_id] = order

        if self._is_in_session(order, now):
            if self._session_epoch_key(order.trading_session, now) in (
                self._session_tick_marked
            ):
                order.entered_session = True

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
                account_id=account_id,
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

    def cancel(self, stop_order_id: str) -> bool:
        """스탑 주문 취소."""
        order = self._orders.get(stop_order_id)
        if not order or order.triggered or order.expired:
            return False

        order.expired = True
        del self._orders[stop_order_id]
        logger.info("스탑 주문 취소: %s", stop_order_id)
        return True

    async def expire_for_bot(self, bot_id: str, reason: str) -> list[StopOrder]:
        """봇의 활성 스탑 주문을 첫 await 전에 모두 만료로 표시한 뒤 종결을 발행한다."""
        targets = self.get_orders_for_bot(bot_id)
        for order in targets:
            order.expired = True
        await self._shielded(self._publish_all_expired(targets, reason))
        return targets

    def get_order(self, stop_order_id: str) -> StopOrder | None:
        """스탑 주문 조회."""
        return self._orders.get(stop_order_id)

    def get_orders_for_bot(self, bot_id: str) -> list[StopOrder]:
        """봇의 활성 스탑 주문 목록."""
        return [o for o in self.active_orders if o.bot_id == bot_id]

    def get_orders_for_account(self, account_id: str) -> list[StopOrder]:
        """계좌의 활성 스탑 주문 목록."""
        return [o for o in self.active_orders if o.account_id == account_id]

    async def on_price_update(
        self,
        symbol: str,
        price: float,
        *,
        account_id: str,
        is_exchange_tick: bool = True,
    ) -> None:
        """실시간 시세 수신 시 트리거 판단.

        매수 스탑: 현재가 >= stop_price → 트리거
        매도 스탑: 현재가 <= stop_price → 트리거

        multi-account 환경에서는 각 계좌마다 별도의 ``KISStreamClient``
        인스턴스를 가지므로, tick 이 들어온 stream 의 ``account_id`` 만
        매칭되는 stop order 를 평가한다. 다른 계좌의 stop order 는 같은
        symbol 이라도 무시된다.
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stop_order.on_price_update")

        if not self._running:
            return

        now = clock.now(UTC)
        if is_exchange_tick:
            for order in self.active_orders:
                if self._is_in_session(order, now):
                    order.entered_session = True
            for session_type in SESSION_TYPES:
                if self._is_session_type_active_now(session_type, now):
                    self._session_tick_marked.add(
                        self._session_epoch_key(session_type, now)
                    )

        active_for_symbol = [
            o
            for o in self.active_orders
            if o.symbol == symbol
            and o.account_id == account_id
            and self._is_in_session(o, now)
        ]

        for order in active_for_symbol:
            if self._should_trigger(order, price):
                await self._trigger_order(order, price)

    async def check_session_expiry(self) -> None:
        """세션 종료 시 미트리거 주문 만료 처리.

        A2 의미론: **자신의 세션에 진입했던**(``entered_session``)
        미트리거 주문만 그 세션 종료 시 ``session_ended`` 로 만료한다. 세션에 한
        번도 진입한 적 없는 주문(예: 장 전 미리 등록분, 휴장일 사전 등록분,
        세션 종료 후 등록분)은 만료되지 않는다 — "세션 외 등록 stop 즉시
        만료"(A1) 부작용을 제거한다.
        """
        from ante.broker.fill_scheduler import business_date_kst

        now = clock.now(UTC)
        today = business_date_kst(now)
        self._session_tick_marked = {
            key for key in self._session_tick_marked if key.split(":", 1)[0] == today
        }

        for order in self.active_orders:
            if order.entered_session and not self._is_in_session(order, now):
                await self._expire_order(order, "session_ended")

    def _should_trigger(self, order: StopOrder, price: float) -> bool:
        """트리거 조건 판단."""
        if order.side == "buy":
            return price >= order.stop_price
        else:
            return price <= order.stop_price

    def _is_in_session(self, order: StopOrder, now: datetime) -> bool:
        """주어진 시각이 주문의 거래 세션 시간 내인지 확인."""
        return self._is_session_type_active_now(order.trading_session, now)

    def _session_epoch_key(self, session_type: str, now: datetime) -> str:
        """epoch 키 SSOT ``{KST 캘린더 날짜}:{세션종류}``(휴장일·주말도 roll 안 함)."""
        from ante.broker.fill_scheduler import business_date_kst

        return f"{business_date_kst(now)}:{session_type}"

    def _is_session_type_active_now(self, session_type: str, now: datetime) -> bool:
        """주어진 시각이 세션 종류의 윈도우 안인지(시각 기준)."""
        current_minutes = now.hour * 60 + now.minute

        if session_type == "extended":
            start = EXTENDED_SESSION_START[0] * 60 + EXTENDED_SESSION_START[1]
            end = EXTENDED_SESSION_END[0] * 60 + EXTENDED_SESSION_END[1]
            if start > end:
                return current_minutes >= start or current_minutes < end
            return start <= current_minutes < end
        else:
            start = REGULAR_SESSION_START[0] * 60 + REGULAR_SESSION_START[1]
            end = REGULAR_SESSION_END[0] * 60 + REGULAR_SESSION_END[1]
            return start <= current_minutes < end

    async def _trigger_order(self, order: StopOrder, trigger_price: float) -> None:
        """스탑 주문 트리거 → 시장가/지정가 주문으로 변환."""
        if order.triggered or order.expired:
            return
        order.triggered = True

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

        await self._eventbus.publish(
            StopOrderTriggeredEvent(
                account_id=order.account_id,
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

        await self._eventbus.publish(
            OrderRequestEvent(
                account_id=order.account_id,
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
        """스탑 주문 만료 처리(shield 보장)."""
        await self._shielded(self._do_expire_order(order, reason))

    async def _shielded(self, coro: Coroutine[Any, Any, None]) -> None:
        """종결 발행을 shield 된 inner 로 돌리고 in-flight 목록에 둔다."""
        inner = asyncio.ensure_future(coro)
        self._inflight_expires.add(inner)
        try:
            await asyncio.shield(inner)
        finally:
            if inner.done():
                self._inflight_expires.discard(inner)
            else:
                inner.add_done_callback(self._inflight_expires.discard)

    async def _do_expire_order(self, order: StopOrder, reason: str) -> None:
        """스탑 주문 만료 terminal 발행(shield 된 inner)."""
        if order.triggered or order.expired:
            return
        order.expired = True
        await self._publish_expired(order, reason)

    async def _publish_all_expired(self, orders: list[StopOrder], reason: str) -> None:
        """만료로 표시된 스탑 주문들의 종결 이벤트를 차례로 발행한다."""
        for order in orders:
            await self._publish_expired(order, reason)

    async def _publish_expired(self, order: StopOrder, reason: str) -> None:
        """만료로 표시된 스탑 주문의 종결 이벤트를 발행한다."""
        logger.info(
            "스탑 주문 만료: %s (%s)",
            order.stop_order_id,
            reason,
        )

        from ante.eventbus.events import StopOrderExpiredEvent

        await self._eventbus.publish(
            StopOrderExpiredEvent(
                account_id=order.account_id,
                stop_order_id=order.stop_order_id,
                bot_id=order.bot_id,
                strategy_id=order.strategy_id,
                symbol=order.symbol,
                reason=reason,
            )
        )
