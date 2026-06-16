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
        order_tracker: Any | None = None,
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
        self._order_tracker = order_tracker

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
        *,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """과거 봉 데이터 조회 (캐시 우선).

        OHLCV 캐시 키는 exchange 기반을 유지한다 (동일 거래소 데이터 공유).
        BrokerAdapter.get_ohlcv()가 미구현이면 빈 리스트를 반환한다.

        SPLIT-3 (#1242): ``account_id`` 는 broker 라우팅과 rate limiter
        bucket 결정에 사용되므로 fallback 금지 (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.get_ohlcv")

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
        self, symbol: str, *, account_id: str, exchange: str = "KRX"
    ) -> float:
        """현재가 조회 (캐시 우선). account_id로 브로커 라우팅.

        SPLIT-3 (#1242): ``account_id`` required (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.get_current_price")

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

    async def get_positions(self, *, account_id: str) -> list[dict[str, Any]]:
        """포지션 조회 (캐시 우선). account_id로 브로커 라우팅.

        SPLIT-3 (#1242): ``account_id`` required (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.get_positions")

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

    async def get_account_balance(self, *, account_id: str) -> dict[str, float]:
        """잔고 조회 (캐시 우선). account_id로 브로커 라우팅.

        SPLIT-3 (#1242): ``account_id`` required (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.get_account_balance")

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
        *,
        account_id: str,
    ) -> str:
        """주문 제출. 캐시 없이 rate limit만 적용. account_id로 브로커 라우팅.

        SPLIT-3 (#1242): ``account_id`` required (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.submit_order")

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

    async def cancel_order(self, order_id: str, *, account_id: str) -> bool:
        """주문 취소. account_id로 브로커 라우팅.

        취소 대상은 **내부 order_id** 로 들어오지만 BrokerAdapter 는
        broker_order_id(증권사 주문번호, KIS ``odno`` 등)를 요구한다. #2134:
        OrderTracker 로 ``order_id → broker_order_id`` 를 변환한 뒤 broker 에
        전달한다. 변환 불가/검증 실패 시 **fail-closed** 로 ``False`` 를 반환하고
        broker 를 호출하지 않는다 (내부 order_id 를 broker 로 passthrough 하지
        않는다 — P1 재발 방지).

        SPLIT-3 (#1242): ``account_id`` required (``require_account_id``).
        """
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="gateway.cancel_order")

        # #2134: fail-closed broker_order_id 변환 — broker 호출 전에 검증.
        if self._order_tracker is None:
            logger.error(
                "order_tracker 미주입 — broker_order_id 변환 불가, 취소 차단 "
                "(order_id=%s, account=%s)",
                order_id,
                account_id,
            )
            return False

        record = await self._order_tracker.get(order_id)
        if record is None:
            logger.warning(
                "취소 대상 주문 미발견 — broker_order_id 변환 불가, 취소 차단 "
                "(order_id=%s, account=%s)",
                order_id,
                account_id,
            )
            return False

        if record.account_id != account_id:
            logger.warning(
                "cross-account 취소 시도 차단 "
                "(order_id=%s, record.account=%s, 요청 account=%s)",
                order_id,
                record.account_id,
                account_id,
            )
            return False

        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        return await broker.cancel_order(record.broker_order_id)

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
                    account_id=event.account_id,
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
                    # #2391: 원주문 지정가 단가를 전파 → OrderTracker.order_price seed.
                    # market/미지정 주문은 None(OrderApprovedEvent.price 그대로).
                    price=event.price,
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

        # #2044: 전략 on_order_update(cancelled/cancel_failed) 스펙의 필수 키
        # symbol/side 를 OrderTracker record 에서 채운다. cross-account leak
        # 방지를 위해 record.account_id == event.account_id 일 때만 채우고,
        # order_tracker 미주입 / record 미발견 / account 불일치 시에는 ""
        # 로 graceful 하게 비운다 (예외 없음).
        sym, sd = "", ""
        if self._order_tracker is not None:
            record = await self._order_tracker.get(event.order_id)
            if record is not None and record.account_id == event.account_id:
                sym, sd = record.symbol, record.side

        try:
            ok = await self.cancel_order(event.order_id, account_id=event.account_id)
            if not ok:
                # 브로커가 예외 없이 False(취소 실패)를 반환한 경우.
                # 성공 이벤트를 발행하지 않고 실패 이벤트로 전환한다 (#2142).
                logger.warning("주문 취소 실패(broker False 반환): %s", event.order_id)
                await self._eventbus.publish(
                    OrderCancelFailedEvent(
                        account_id=event.account_id,
                        order_id=event.order_id,
                        bot_id=event.bot_id,
                        strategy_id=event.strategy_id,
                        symbol=sym,
                        side=sd,
                        error_message="브로커가 취소 실패(False)를 반환함",
                    )
                )
                return
            await self._eventbus.publish(
                OrderCancelledEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=sym,
                    side=sd,
                    quantity=0.0,
                    price=0.0,
                    reason=event.reason,
                )
            )
        except Exception as e:
            logger.error("주문 취소 실패: %s — %s", event.order_id, e)
            await self._eventbus.publish(
                OrderCancelFailedEvent(
                    account_id=event.account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=sym,
                    side=sd,
                    error_message=str(e),
                )
            )

    async def _on_order_modify(self, event: object) -> None:
        """주문 정정 요청 → broker 위임 (#2391, v1=price-only).

        RuleEngine이 이미 정정 요청을 거부하면 ``_consumed=True`` transient
        marker를 set한다(``object.__setattr__``). 본 핸들러는 그 경우 추가
        terminal event를 발행하지 않고 바로 반환하여, 동일 정정 요청에 대해
        terminal event가 중복 발행되지 않도록 한다 (#1331).

        v1(price-only) 정정 흐름 (broker 호출 **전** fail-closed):

        (a) finite ``price > 0`` 아니면 ``modify_invalid_args``.
        (b) 수량 변경 판정 — Bot이 ``action.quantity or 0.0`` 로 접으므로
            (``bot.py``) ``event.quantity == 0.0`` 은 미지정(price-only 허용),
            ``> 0 && != record.ordered_qty`` 는 수량 변경 →
            ``modify_qty_change_unsupported`` (#2393), ``< 0`` 은 무효
            → ``modify_invalid_args``.
        (c) OrderTracker record status가 ``open`` 이 아니면(부분체결/터미널/미발견)
            ``modify_partial_or_terminal_unsupported``.
        (d) buy면 ``new_price <= record.order_price`` 가 아니면(예산 증가)
            ``modify_budget_increase_unsupported`` (``order_price`` 부재/None
            시 buy fail-closed). sell은 통과.
        (e) ``ModifyOrgnoUnavailableError`` → ``modify_orgno_unavailable``.

        broker 성공 → ``OrderModifyExecutedEvent``(quantity=record.ordered_qty
        유지, price=신규). broker False → ``modify_failed``. 기타 예외 → str(e).
        OrderTracker ``ordered_qty`` 는 변경하지 않는다(price-only).

        Note: EventBus 핸들러 — isawaitable 패턴을 위해 async def 유지.
        """
        import math

        from ante.broker.exceptions import ModifyOrgnoUnavailableError
        from ante.eventbus.events import (
            OrderModifyEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
        )

        if not isinstance(event, OrderModifyEvent):
            return

        # rule engine 거부 흐름이 이미 terminal event를 발행했으면 skip (#1331).
        if getattr(event, "_consumed", False):
            return

        account_id = event.account_id

        async def _reject(reason: str, *, symbol: str = "", side: str = "") -> None:
            await self._eventbus.publish(
                OrderModifyRejectedEvent(
                    account_id=account_id,
                    order_id=event.order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=symbol or event.symbol,
                    side=side or event.side,
                    quantity=event.quantity,
                    price=event.price,
                    reason=reason,
                )
            )

        # (a) 신규 가격 finite & 양수 — broker 호출 전 fail-closed.
        new_price = event.price
        if (
            new_price is None
            or not isinstance(new_price, (int, float))
            or isinstance(new_price, bool)
            or not math.isfinite(new_price)
            or new_price <= 0
        ):
            logger.warning(
                "주문 정정 거부(무효 가격): %s — %r", event.order_id, new_price
            )
            await _reject("modify_invalid_args")
            return

        # (b) 수량 sentinel 판정 — quantity<0 무효.
        if event.quantity < 0:
            logger.warning(
                "주문 정정 거부(무효 수량): %s — %r", event.order_id, event.quantity
            )
            await _reject("modify_invalid_args")
            return

        # OrderTracker record 조회 — broker_order_id 변환 + status/order_price 판정.
        if self._order_tracker is None:
            logger.error(
                "order_tracker 미주입 — 주문 정정 차단 (order_id=%s, account=%s)",
                event.order_id,
                account_id,
            )
            await _reject("modify_partial_or_terminal_unsupported")
            return

        record = await self._order_tracker.get(event.order_id)
        if record is None or record.account_id != account_id:
            logger.warning(
                "주문 정정 거부(record 미발견/cross-account): %s (account=%s)",
                event.order_id,
                account_id,
            )
            await _reject("modify_partial_or_terminal_unsupported")
            return

        sym, sd = record.symbol, record.side

        # (b') 수량 변경(미지정 0.0 제외) → #2393 deferred.
        if event.quantity > 0 and event.quantity != record.ordered_qty:
            logger.warning(
                "주문 정정 거부(수량 변경 미지원): %s — req=%s ordered=%s",
                event.order_id,
                event.quantity,
                record.ordered_qty,
            )
            await _reject("modify_qty_change_unsupported", symbol=sym, side=sd)
            return

        # (c) open 상태만 정정 허용 (부분체결/터미널 미지원).
        if record.status != "open":
            logger.warning(
                "주문 정정 거부(부분체결/터미널): %s — status=%s",
                event.order_id,
                record.status,
            )
            await _reject("modify_partial_or_terminal_unsupported", symbol=sym, side=sd)
            return

        # (d) buy 예산 증가 차단 — 신규가격 ≤ 원주문가격. order_price 부재 시 buy
        # fail-closed. sell 은 reserve 없음 → 통과.
        if record.side == "buy":
            if record.order_price is None or new_price > record.order_price:
                logger.warning(
                    "주문 정정 거부(예산 증가 buy): %s — new=%s order=%s",
                    event.order_id,
                    new_price,
                    record.order_price,
                )
                await _reject("modify_budget_increase_unsupported", symbol=sym, side=sd)
                return

        # broker 위임 — ordered_qty 불변(price-only), order_type="limit".
        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        try:
            ok = await broker.modify_order(
                record.broker_order_id,
                quantity=record.ordered_qty,
                price=new_price,
                order_type="limit",
            )
        except ModifyOrgnoUnavailableError as e:
            logger.warning("주문 정정 거부(orgno 미상): %s — %s", event.order_id, e)
            await _reject("modify_orgno_unavailable", symbol=sym, side=sd)
            return
        except Exception as e:
            logger.error("주문 정정 실패: %s — %s", event.order_id, e)
            await _reject(str(e), symbol=sym, side=sd)
            return

        if not ok:
            logger.warning("주문 정정 실패(broker False 반환): %s", event.order_id)
            await _reject("modify_failed", symbol=sym, side=sd)
            return

        # broker 성공 → 정정 완료 이벤트. quantity=record.ordered_qty(불변),
        # price=신규. OrderTracker ordered_qty 는 변경하지 않는다(price-only).
        logger.info("주문 정정 완료: %s → 신규가격 %s", event.order_id, new_price)
        await self._eventbus.publish(
            OrderModifyExecutedEvent(
                account_id=account_id,
                order_id=event.order_id,
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                symbol=sym,
                side=sd,
                quantity=record.ordered_qty,
                price=new_price,
                reason=event.reason,
            )
        )

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
