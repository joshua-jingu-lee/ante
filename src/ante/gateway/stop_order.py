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

# #2405 (A2 세션만료): 세션 종류 SSOT. ``StopOrder.trading_session`` 의 허용 값.
SESSION_TYPES = ("regular", "extended")


class StopOrderManagerStoppedError(RuntimeError):
    """매니저가 stopped(``_running=False``) 상태에서 register 가 호출됐을 때.

    #2405 (attempt2 P2): stopped/pre-start 상태의 등록은 silent loss(빈 문자열
    반환)가 아니라 예외로 거부한다. 호출자(gateway ``_on_order_approved``)가
    이를 잡아 ``OrderFailedEvent`` 로 terminal 종결하므로, in-flight 주문이
    영구 inert 로 남지 않는다.

    class-level ``code`` 로 안정 fault code 를 부여한다 — error taxonomy drift
    guard(#1841) 가 모든 ``*Error`` 에 code/registry/allowlist 중 하나를
    요구하며, 본 예외는 internal lifecycle 가드라 class-level code 가 적합하다.
    """

    code = "STOP_ORDER_MANAGER_STOPPED"


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
    # #2405 (A2 세션만료, attempt3 P1/P2): 이 주문이 자신의 거래 세션 안에서
    # 한 번이라도 in-session 틱(``on_price_update``)을 받은 적이 있는지. tick 은
    # 거래일 개장의 proxy 이므로(휴장일엔 무틱), 이 플래그가 True 인 주문만 세션
    # 종료 시 ``session_ended`` 로 만료된다. per-order 멤버십이라 세션 경계
    # race(일부 주문이 한 sweep 에서 미만료)·세션 종료 후 등록(in-session 틱
    # 부재)의 오만료를 구조적으로 배제한다(manager-level 플래그의 타이밍 엣지 교정).
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
            StopOrderManagerStoppedError: 매니저가 stopped(``_running=False``)
                상태일 때.

        #2405 (attempt2 P2): 매니저가 stopped(``_running=False``) 상태면 등록을
        ``StopOrderManagerStoppedError`` 로 거부한다. shutdown 진행 중 in-flight
        IPC/봇이 OrderApprovedEvent 로 stop 주문을 보내도, 그 주문은
        manager_stopped sweep 을 이미 놓쳤고 이후 price update 도
        ``_running=False`` 라 무시되어 영구 inert 로 남는다. 이전(attempt1)에는
        빈 문자열을 반환했으나, 그 경우 호출자가 silent loss 를 인지하지 못해
        주문이 terminal 이벤트 없이 사라졌다(P1). 예외로 거부하면 호출자
        (gateway ``_on_order_approved``)의 try/except 가 이를 잡아
        ``OrderFailedEvent`` 로 결정적 종결한다(api-gateway.md:187 정합). shutdown
        순서와 무관하게 결정적.
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
            raise StopOrderManagerStoppedError(
                f"StopOrderManager stopped — register 거부: {side} {symbol} "
                f"stop={stop_price:.0f}"
            )

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

        SPLIT-3 (#1242): ``account_id`` 는 호출자가 명시 전달해야 한다.
        multi-account 환경에서는 각 계좌마다 별도의 ``KISStreamClient``
        인스턴스를 가지므로, tick 이 들어온 stream 의 ``account_id`` 만
        매칭되는 stop order 를 평가한다. 다른 계좌의 stop order 는 같은
        symbol 이라도 무시된다.

        #2405 (A2 source chokepoint, attempt5 P2): ``is_exchange_tick`` 은
        이 가격이 **실 WebSocket 틱**(``True``)인지 **REST fallback poll**
        (``False``)인지 호출자가 구분해 전달한다. 거래일 멤버십 마킹은
        ``is_exchange_tick=True`` 일 때만 수행한다 — KIS ``inquire-price`` 는
        휴장일에도 직전 종가를 성공 반환하므로, 스트림 끊김 중 휴장일의
        시계상 세션 시간에 fallback poll 이 성공해도 그것이 거래일을
        보증하지 못한다(휴장일 사전등록 stop 의 오만료 차단). 반면 트리거
        평가는 출처와 무관하게 항상 수행한다(아래 ``active_for_symbol``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stop_order.on_price_update")

        if not self._running:
            return

        # #2405 (A2 세션만료, attempt3 P1/P2 · attempt5 P2 source chokepoint):
        # market-wide per-order 마킹. **실 WebSocket 틱**(``is_exchange_tick=
        # True``)이 흐른다는 것만을 거래일 개장 중 신호로 신뢰한다(휴장일엔
        # 실 틱 무수신). REST fallback poll(``is_exchange_tick=False``)은 KIS
        # ``inquire-price`` 가 휴장일에도 직전 종가를 성공 반환하므로 거래일을
        # 보증하지 못해 마킹을 유발하지 않는다 — 이 게이트가 없으면 휴장일
        # 시계상 세션 시간의 fallback 성공이 사전등록 stop 을 마킹해 장종료
        # sweep 에서 오만료시킨다. 실 틱이면 이 틱의 종목·계좌와 **무관하게**,
        # 그 시점 자신의 세션 안에 있는 **모든** active order 의
        # ``entered_session`` 을 True 로 표시한다 — 이 틱이 들어온 종목뿐 아니라
        # 같은 세션의 무틱 종목까지 세션 멤버십을 부여한다(아래 트리거용
        # ``active_for_symbol`` 루프는 per-symbol·출처 무관 그대로). per-order
        # 멤버십이라 세션 경계 race·세션 종료 후 등록의 오만료 엣지가 없다.
        if is_exchange_tick:
            for order in self.active_orders:
                if self._is_in_session(order):
                    order.entered_session = True

        # #2405 (attempt5 P2): 트리거 평가는 출처(실 틱/fallback poll)와
        # **무관하게** 항상 수행한다. 스트림 hiccup 중에도 실거래일이면
        # fallback 가격으로 stop 이 발동돼야 하므로 게이트하지 않는다(#2405
        # scope=만료, 트리거 아님). fallback poll 가격의 거래일 staleness 는
        # bounded known-limitation 으로 api-gateway.md 에 명시.
        active_for_symbol = [
            o
            for o in self.active_orders
            if o.symbol == symbol
            and o.account_id == account_id
            and self._is_in_session(o)
        ]

        for order in active_for_symbol:
            if self._should_trigger(order, price):
                await self._trigger_order(order, price)

    async def check_session_expiry(self) -> None:
        """세션 종료 시 미트리거 주문 만료 처리.

        #2405 (A2 의미론): **자신의 세션에 진입했던**(``entered_session``)
        미트리거 주문만 그 세션 종료 시 ``session_ended`` 로 만료한다. 세션에 한
        번도 진입한 적 없는 주문(예: 장 전 미리 등록분, 휴장일 사전 등록분,
        세션 종료 후 등록분)은 만료되지 않는다 — "세션 외 등록 stop 즉시
        만료"(A1) 부작용을 제거한다.

        #2405 (attempt3 P1/P2): 멤버십을 per-order ``entered_session`` 으로
        추적한다. ``on_price_update`` 가 market-wide(틱의 종목·계좌 무관)로 그
        시점 in-session 인 **모든** active order 를 마킹하므로, 거래일에 한
        종목이라도 틱이 흐르면 그 세션의 무틱 종목까지 멤버십을 얻어 함께
        만료된다. ``entered_session`` 은 per-order 1회 set 이고 ``_expire_order``
        가 만료 주문을 ``active_orders`` 에서 제외(소비)하므로 별도 reset 이
        필요 없다. 이 per-order 멤버십이 manager-level 플래그의 타이밍 엣지를
        교정한다:

        - 세션 경계 race: 한 sweep 에서 경계 통과로 미만료된 주문도
          ``entered_session=True`` 를 유지하므로 다음(완전 세션 밖) sweep 에서
          만료된다(누락 없음).
        - 세션 종료 후 등록: 세션 밖에 등록된 주문엔 in-session 틱이 오지 않아
          ``entered_session=False`` → 미만료(보존). 사전 등록분도 동일 보존.

        #2405 (bounded known-limitation): src/ante 에 거래일/휴장일 캘린더가
        없으므로 "거래일인데 전 모니터 종목이 세션 내내 무틱"(전종목 거래정지 등)
        이면 어떤 주문도 마킹되지 않아 미만료된다(다음 세션 생존). 캘린더
        부재의 구조적 하한 — api-gateway.md normative 선언.
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
        return self._is_session_type_active_now(order.trading_session)

    def _is_session_type_active_now(self, session_type: str) -> bool:
        """현재 시각이 주어진 세션 종류의 윈도우 안인지(시각 기준)."""
        now = datetime.now(UTC)
        current_minutes = now.hour * 60 + now.minute

        if session_type == "extended":
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
