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
    """스탑 주문 내부 표현.

    SPLIT-3 (#1242): ``account_id`` 는 runtime 시점부터 ``require_account_id``
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
    order_type: str  # "stop" | "stop_limit"
    stop_price: float
    limit_price: float | None
    trading_session: str  # "regular" | "extended"
    account_id: str  # required — trigger 시 OrderRequestEvent에 전파
    registered_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    triggered: bool = False
    expired: bool = False
    exchange: str = "KRX"
    # #2405 (A2 세션만료): 이 주문이 거래 세션 안에 한 번이라도 진입했는지 여부.
    # ``check_session_expiry`` sweep 은 ``entered_session AND not _is_in_session``
    # 인 주문만 ``session_ended`` 로 만료한다. 세션에 한 번도 안 들어간 주문(예:
    # 장 전 미리 등록분)은 만료되지 않아, "세션 외 등록 즉시 만료"(A1) 부작용을
    # 제거한다.
    #
    # #2405 (attempt1 P2-1): 마킹 신호를 **실제 시장 활동(price-update 틱)** 으로
    # 잡는다. src/ante 에 거래일/휴장일 캘린더가 없어서 ``_is_in_session`` 은
    # 시각(09:00–15:30 KST)만 보므로, sweep/register 에서 시각만으로 마킹하면
    # 주말·공휴일의 "시장 시간대"에도 entered_session=True 가 되어 사전 등록분이
    # session_ended 로 오만료(월요일 개장 전 사망)된다. 실제 틱은 거래일 개장
    # 중에만 흐르므로, ``on_price_update`` 의 in-session 경로에서만 True 로
    # 마킹한다(휴장일엔 무틱 → 미마킹 → 비만료). register/sweep 은 더 이상
    # 마킹하지 않는다.
    entered_session: bool = False

    def __post_init__(self) -> None:
        from ante.account.scoping import require_account_id

        # SPLIT-3 (#1242): account_id fallback 차단. invalid 값으로
        # StopOrder 가 만들어지면 이후 OrderRequestEvent 발행 시 실패한다.
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
        *,
        account_id: str,
        limit_price: float | None = None,
        trading_session: str = "regular",
        exchange: str = "KRX",
    ) -> str:
        """스탑 주문 등록.

        Returns:
            stop_order_id

        Raises:
            InvalidAccountIdError: account_id 가 invalid 일 때.

        #2405 (attempt1 P2-2): 매니저가 stopped(``_running=False``) 상태면
        등록을 거부한다(빈 문자열 반환). shutdown 진행 중 in-flight IPC/봇이
        OrderApprovedEvent 로 stop 주문을 보내도, 그 주문은 manager_stopped
        sweep 을 이미 놓쳤고 이후 price update 도 ``_running=False`` 라 무시되어
        영구 inert 로 남는다. 따라서 stopped 상태에서는 받지 않는다(등록 거부,
        StopOrderRegisteredEvent 미발행, _orders 미추가). shutdown 순서와 무관하게
        결정적.
        """
        # account_id invalid 는 stopped 가드보다 먼저 거부한다(StopOrder
        # __post_init__ 의 require_account_id 와 동형 — invalid 입력은 stopped
        # 여부와 무관하게 거부되어야 한다).
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stop_order.register")

        if not self._running:
            logger.warning(
                "StopOrderManager stopped 상태 — stop 주문 등록 거부: %s %s stop=%.0f",
                side,
                symbol,
                stop_price,
            )
            return ""

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
            account_id=account_id,
        )
        # #2405 (attempt1 P2-1): register-time 마킹 제거. 휴장일 시장 시간대
        # 등록도 마킹되는 오만료를 방지하기 위해, entered_session 은 첫 in-session
        # **틱**(on_price_update)에서만 set 한다. 등록은 항상 False 로 시작한다.
        self._orders[stop_order_id] = order

        logger.info(
            "스탑 주문 등록: %s %s %s stop=%.0f",
            stop_order_id,
            side,
            symbol,
            stop_price,
        )

        from ante.eventbus.events import StopOrderRegisteredEvent

        # Refs #1336: ``account_id`` 를 명시 전달하여 BotManager /
        # SignalChannel 이 account-scoped 통보 경로로 전달할 수 있도록 한다.
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
        self, symbol: str, price: float, *, account_id: str
    ) -> None:
        """실시간 시세 수신 시 트리거 판단.

        매수 스탑: 현재가 >= stop_price → 트리거
        매도 스탑: 현재가 <= stop_price → 트리거

        SPLIT-3 (#1242): ``account_id`` 는 호출자가 명시 전달해야 한다.
        multi-account 환경에서는 각 계좌마다 별도의 ``KISStreamClient``
        인스턴스를 가지므로, tick 이 들어온 stream 의 ``account_id`` 만
        매칭되는 stop order 를 평가한다. 다른 계좌의 stop order 는 같은
        symbol 이라도 무시된다.
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stop_order.on_price_update")

        if not self._running:
            return

        active_for_symbol = [
            o
            for o in self.active_orders
            if o.symbol == symbol
            and o.account_id == account_id
            and self._is_in_session(o)
        ]

        for order in active_for_symbol:
            # #2405 (attempt1 P2-1): 실제 틱 + in-session = 시장이 실제로 개장한
            # 신호다(휴장일엔 틱이 흐르지 않아 마킹되지 않는다). 이 마킹이
            # check_session_expiry sweep 의 session_ended 만료 자격 게이트가 된다.
            order.entered_session = True
            if self._should_trigger(order, price):
                await self._trigger_order(order, price)

    async def check_session_expiry(self) -> None:
        """세션 종료 시 미트리거 주문 만료 처리.

        #2405 (A2 의미론): **세션에 한 번이라도 진입했고**(``entered_session``)
        **현재 세션 밖**(``not _is_in_session``)인 주문만 ``session_ended`` 로
        만료한다. 세션에 한 번도 들어간 적 없는 주문(예: 장 전 미리 등록분)은
        만료되지 않는다 — "세션 외 등록 stop 즉시 만료"(A1) 부작용을 제거한다.

        #2405 (attempt1 P2-1): sweep 은 더 이상 ``entered_session`` 을 마킹하지
        않는다(만료만 수행). 시각만 보는 ``_is_in_session`` 으로 마킹하면 휴장일
        시장 시간대에도 마킹되어 사전 등록분이 오만료되기 때문이다. 마킹은
        실제 시장 틱(``on_price_update`` in-session 경로)에서만 일어난다.
        결과적으로 휴장일(무틱)에는 ``entered_session=False`` 가 유지되어 사전
        등록 stop 이 보존되고, 거래일에는 in-session 틱으로 마킹된 뒤 세션 종료
        sweep 에서 정상 만료된다.
        """
        for order in self.active_orders:
            if order.entered_session and not self._is_in_session(order):
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
        # Refs #1336: ``account_id`` 보존. 변환된 ``OrderRequestEvent`` 는
        # 자체 라이프사이클 이벤트를 발행하지만, stop 식별 단위 (stop_order_id)
        # 가 다르므로 stop 트리거 통보를 별도로 보존한다.
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

        # 변환된 주문을 기존 흐름에 주입
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
        """스탑 주문 만료 처리."""
        order.expired = True

        logger.info(
            "스탑 주문 만료: %s (%s)",
            order.stop_order_id,
            reason,
        )

        from ante.eventbus.events import StopOrderExpiredEvent

        # Refs #1336: ``account_id`` 보존. ``reason`` 은 호출 위치에서
        # ``"session_ended"`` (세션 종료) 또는 ``"manager_stopped"``
        # (매니저 stop()) 로 분류되어 들어온다.
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
