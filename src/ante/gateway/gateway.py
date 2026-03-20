"""APIGateway — 증권사 API 호출 중앙 관리."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.gateway.cache import ResponseCache
from ante.gateway.rate_limiter import RateLimitConfig, RateLimiter

if TYPE_CHECKING:
    from ante.account.service import AccountService
    from ante.broker.base import BrokerAdapter
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class _SingleBrokerAccountService:
    """AccountService 미초기화 시 단일 브로커를 감싸는 폴백 래퍼.

    모든 account_id에 대해 동일한 BrokerAdapter를 반환한다.
    AccountService 통합 완료 후 제거 예정.
    """

    def __init__(self, broker: BrokerAdapter) -> None:
        self._broker = broker

    async def get_broker(self, account_id: str) -> BrokerAdapter:
        """어떤 account_id든 동일 브로커 반환."""
        return self._broker


class APIGateway:
    """증권사 API 호출 중앙 관리.

    AccountService를 통해 계좌별 BrokerAdapter를 라우팅한다.
    - 계좌별 독립 Rate limit 준수
    - 계좌별 네임스페이스 캐시 (시세, 잔고 등)
    - EventBus 이벤트 기반 주문 처리
    - Stop order 라우팅 (StopOrderManager 연동)
    """

    def __init__(
        self,
        account_service: AccountService,
        eventbus: EventBus,
        rate_config: RateLimitConfig | None = None,
        stop_order_manager: Any | None = None,
    ) -> None:
        self._account_service = account_service
        self._eventbus = eventbus
        self._default_rate_config = rate_config or RateLimitConfig(
            max_requests=20, window_seconds=60
        )
        self._rate_limiters: dict[str, RateLimiter] = {}
        self._cache = ResponseCache()
        self._running = False
        self._stop_order_manager = stop_order_manager

    async def _get_broker(self, account_id: str) -> BrokerAdapter:
        """AccountService에서 브로커 인스턴스를 획득한다."""
        return await self._account_service.get_broker(account_id)

    def _get_rate_limiter(self, account_id: str) -> RateLimiter:
        """계좌별 독립 Rate Limiter를 반환한다."""
        if account_id not in self._rate_limiters:
            self._rate_limiters[account_id] = RateLimiter(self._default_rate_config)
        return self._rate_limiters[account_id]

    def start(self) -> None:
        """이벤트 구독 시작."""
        self._subscribe_events()
        self._running = True
        logger.info("APIGateway 시작")

    def stop(self) -> None:
        """중지."""
        self._running = False
        logger.info("APIGateway 중지")

    def _subscribe_events(self) -> None:
        """EventBus 이벤트 구독."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderCancelEvent,
            OrderFilledEvent,
            OrderModifyEvent,
        )

        self._eventbus.subscribe(
            OrderApprovedEvent, self._on_order_approved, priority=50
        )
        self._eventbus.subscribe(OrderCancelEvent, self._on_order_cancel, priority=50)
        self._eventbus.subscribe(OrderModifyEvent, self._on_order_modify, priority=50)
        self._eventbus.subscribe(OrderFilledEvent, self._on_order_filled)

    # ── 공개 API ──────────────────────────────────

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
        exchange: str = "KRX",
        account_id: str = "",
    ) -> list[dict[str, Any]]:
        """과거 봉 데이터 조회 (캐시 우선).

        OHLCV 캐시 키는 exchange 기반을 유지한다 (동일 거래소 데이터 공유).
        BrokerAdapter.get_ohlcv()가 미구현이면 빈 리스트를 반환한다.
        """
        cache_key = f"ohlcv:{exchange}:{symbol}:{timeframe}:{limit}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        get_ohlcv = getattr(broker, "get_ohlcv", None)
        if get_ohlcv is None:
            return []
        data: list[dict[str, Any]] = await get_ohlcv(
            symbol, timeframe=timeframe, limit=limit
        )
        self._cache.set(cache_key, data, ttl=60)
        return data

    async def get_current_price(
        self, symbol: str, account_id: str = "", exchange: str = "KRX"
    ) -> float:
        """현재가 조회 (캐시 우선). account_id로 브로커 라우팅."""
        cache_key = f"{account_id}:price:{symbol}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        price = await broker.get_current_price(symbol)
        self._cache.set(cache_key, price, ttl=5)
        return price

    async def get_positions(self, account_id: str = "") -> list[dict[str, Any]]:
        """포지션 조회 (캐시 우선). account_id로 브로커 라우팅."""
        cache_key = f"{account_id}:positions"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        positions = await broker.get_positions()
        self._cache.set(cache_key, positions, ttl=30)
        return positions

    async def get_account_balance(self, account_id: str = "") -> dict[str, float]:
        """잔고 조회 (캐시 우선). account_id로 브로커 라우팅."""
        cache_key = f"{account_id}:balance"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        balance = await broker.get_account_balance()
        self._cache.set(cache_key, balance, ttl=30)
        return balance

    async def submit_order(
        self,
        bot_id: str,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        account_id: str = "",
    ) -> str:
        """주문 제출. 캐시 없이 rate limit만 적용. account_id로 브로커 라우팅."""
        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        broker_order_id = await broker.place_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            order_type=order_type,
            price=price,
        )
        logger.info(
            "주문 제출: %s %s %s %.0f주 → %s (account=%s)",
            bot_id,
            side,
            symbol,
            quantity,
            broker_order_id,
            account_id,
        )
        return broker_order_id

    async def cancel_order(self, order_id: str, account_id: str = "") -> bool:
        """주문 취소. account_id로 브로커 라우팅."""
        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        return await broker.cancel_order(order_id)

    # ── EventBus 핸들러 ──────────────────────────────

    async def _on_order_approved(self, event: object) -> None:
        """Treasury 자금 확보 완료 → 증권사에 주문 제출.

        event.account_id로 올바른 BrokerAdapter를 라우팅한다.
        stop/stop_limit 주문은 StopOrderManager로 라우팅한다.
        """
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderFailedEvent,
            OrderSubmittedEvent,
        )

        if not isinstance(event, OrderApprovedEvent):
            return

        # stop/stop_limit → StopOrderManager로 라우팅
        if event.order_type in ("stop", "stop_limit") and self._stop_order_manager:
            try:
                await self._stop_order_manager.register(
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    order_type=event.order_type,
                    stop_price=event.stop_price or 0.0,
                    limit_price=event.price,
                    exchange=event.exchange,
                )
                return
            except Exception as e:
                logger.error("스탑 주문 등록 실패: %s — %s", event.order_id, e)
                await self._eventbus.publish(
                    OrderFailedEvent(
                        account_id=event.account_id,
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=event.symbol,
                        side=event.side,
                        quantity=event.quantity,
                        price=event.price or 0.0,
                        order_type=event.order_type,
                        error_message=str(e),
                        exchange=event.exchange,
                    )
                )
                return

        try:
            broker_order_id = await self.submit_order(
                bot_id=event.bot_id,
                symbol=event.symbol,
                side=event.side,
                quantity=event.quantity,
                order_type=event.order_type,
                price=event.price,
                account_id=event.account_id,
            )
            await self._eventbus.publish(
                OrderSubmittedEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    broker_order_id=broker_order_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    order_type=event.order_type,
                    exchange=event.exchange,
                )
            )
        except Exception as e:
            from ante.broker.exceptions import APIError

            error_code = ""
            if isinstance(e, APIError):
                error_code = e.error_code

            logger.error("주문 제출 실패: %s — %s", event.order_id, e)
            await self._eventbus.publish(
                OrderFailedEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=event.symbol,
                    side=event.side,
                    quantity=event.quantity,
                    price=event.price or 0.0,
                    order_type=event.order_type,
                    error_message=str(e),
                    error_code=error_code,
                    exchange=event.exchange,
                )
            )

    async def _on_order_cancel(self, event: object) -> None:
        """주문 취소 요청 → BrokerAdapter 전달 (룰 검증 생략).

        event.account_id로 브로커를 선택한다.
        """
        from ante.eventbus.events import (
            OrderCancelEvent,
            OrderCancelFailedEvent,
            OrderCancelledEvent,
        )

        if not isinstance(event, OrderCancelEvent):
            return

        try:
            await self.cancel_order(event.order_id, account_id=event.account_id)
            await self._eventbus.publish(
                OrderCancelledEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol="",
                    side="",
                    quantity=0.0,
                    price=0.0,
                    reason=event.reason,
                )
            )
        except Exception as e:
            logger.error("주문 취소 실패: %s — %s", event.order_id, e)
            await self._eventbus.publish(
                OrderCancelFailedEvent(
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    error_message=str(e),
                )
            )

    async def _on_order_modify(self, event: object) -> None:
        """주문 정정 요청 → 로깅만 (정정은 추후 구현).

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        from ante.eventbus.events import OrderModifyEvent

        if not isinstance(event, OrderModifyEvent):
            return
        logger.warning("주문 정정은 추후 구현: %s", event.order_id)

    async def _on_order_filled(self, event: object) -> None:
        """체결 시 해당 account_id 범위 내 캐시 무효화.

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return
        account_id = event.account_id
        self._cache.invalidate(f"{account_id}:balance")
        self._cache.invalidate(f"{account_id}:positions")
        self._cache.invalidate(f"{account_id}:price:{event.symbol}")
