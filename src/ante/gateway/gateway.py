"""APIGateway — 증권사 API 호출 중앙 관리."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.gateway.cache import ResponseCache
from ante.gateway.rate_limiter import RateLimitConfig, RateLimiter

if TYPE_CHECKING:
    from ante.account.readiness import RuntimeReadinessRegistry
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
        runtime_readiness: RuntimeReadinessRegistry | None = None,
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
        # #2398 D-ACC-09 축 ii: active-order readiness gate(계층3, 최후보루)
        # reader. 미주입(None)이면 fail-closed — submit_order 가 차단한다(G2).
        # main(s.runtime_readiness) pass-through.
        self._runtime_readiness = runtime_readiness

    async def _get_broker(self, account_id: str) -> BrokerAdapter:
        """AccountService에서 브로커 인스턴스를 획득한다."""
        return await self._account_service.get_broker(account_id)

    async def _get_account(self, account_id: str) -> tuple[Any | None, bool]:
        """account_id 의 Account 메타 조회 — ``(account, fetch_failed)`` 반환.

        ``_on_order_approved`` 가 non-LIVE silent skip 라우팅 판정으로 호출한다.
        ``AccountService.get`` 은 ``AccountNotFoundError`` 를 raise 하므로 예외를
        흡수하되, **조회 실패 여부**(``fetch_failed``)를 별도로 반환해 호출자/계층3
        gate 가 "조회 예외(검증 불가)"와 "정상 None"을 구별할 수 있게 한다(G7 status
        축 STATUS_UNAVAILABLE 도출에 필요). 예외 = fail-closed(virtual fall-open
        금지, G2).
        """
        get = getattr(self._account_service, "get", None)
        if get is None:
            return None, False
        try:
            return await get(account_id), False
        except Exception:  # noqa: BLE001 — 조회 실패 = fail-closed(G2)·검증 불가.
            return None, True

    async def _readiness_gate(self, account_id: str, *, side: object) -> None:
        """계층3 active-order gate — ``broker.place_order`` **직전** 단일 재확인.

        **위치(#2398 attempt4-a, P1)**: ``rate_limiter.acquire()``(최대 ~60s await)
        + ``_get_broker()`` await **이후**, ``place_order`` 직전에 호출된다(spec
        broker-adapter/11-order-flow.md). acquire/get_broker 대기 중 ``mark_not_ready``/
        suspend 가 끼어도 그 직후 단일 재확인으로 TOCTOU 윈도우를 닫는다(재확인
        직후 ``place_order`` 가 동기 시작하므로 각 await 후 중복 체크 불요).

        **단일 fresh fetch(중복 get 금지)**: 이 gate 가 **한 번** account 를 fetch
        해(``_get_account``) readiness(broker_type/trading_mode) + status(SUSPENDED)
        **둘 다** 평가한다. routing 단계(``_on_order_approved``)의 fetch 를 재사용하지
        **않고** 여기서 fresh fetch 하는 이유는, status 가 런타임 가변 kill-switch 라
        acquire/get_broker await 중 in-flight suspend 를 잡으려면 await **이후** 최신
        status 를 읽어야 하기 때문이다(stale routing 스냅샷 금지).

        평가 축(둘 중 하나라도 막으면 거부 — D-ACC-09 §8 effect 일관성):

        - **status 축(Fix 2, in-flight kill-switch backstop)**: verified SUSPENDED →
          ``account_suspended``; ``STATUS_UNAVAILABLE``(소스 present + 조회 예외/미상)
          → ``account_status_unavailable`` fail-closed; ``None``(소스 미구성)/verified
          non-SUSPENDED → status 축 통과. 계층1 통과 후 await 중 발생한 suspend 를
          계층3 final backstop 이 잡는다(D-ACC-09 §8 계층1 primary + 계층3 backstop).
        - **readiness 축**: account 메타 미상/non-LIVE/registry 미주입/not_ready →
          ``account_not_ready``(missing-flag suffix). non-LIVE fail-closed 는 직접
          ``submit_order`` 호출 경로의 virtual 주문이 실 broker 로 새는 것을 막는다.

        차단 시 G6 운영자 알림(error/system) 정확히 1회 + ``APIError`` raise →
        ``_on_order_approved`` except → OrderFailedEvent(reserve 정확 해제, G3).
        OrderApprovedEvent 는 ``reason`` 필드가 없어 청산 marker 미운반(generic 문구).
        매 주문 시점 registry/status 조회(상태 캐시 금지, G5).
        """
        from ante.account.gate import (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
            ACCOUNT_SUSPENDED_REASON,
            STATUS_UNAVAILABLE,
            active_trading_blocked,
            build_not_ready_notification,
            derive_account_status,
            not_ready_reason,
        )
        from ante.account.models import AccountStatus, TradingMode
        from ante.broker.exceptions import APIError

        # 단일 fresh fetch(await 이후 최신 status 확보 — in-flight suspend 검출).
        account, fetch_failed = await self._get_account(account_id)

        # status 축(Fix 2) — kill-switch in-flight backstop. account_service 는
        # gateway 생성자 필수 인자라 소스가 항상 present → status 축 활성.
        status = derive_account_status(
            self._account_service, account, fetch_failed=fetch_failed
        )
        reason: str | None = None
        if status == AccountStatus.SUSPENDED:
            reason = ACCOUNT_SUSPENDED_REASON
        elif status is STATUS_UNAVAILABLE:
            # 소스 present + 조회 예외/미상 = 검증 불가 → fail-closed(in-flight
            # suspend 를 stale 통과시키지 않는다). account=None(조회 실패)도 여기로
            # 귀결돼 readiness 축의 account_metadata_unavailable 보다 우선 차단한다.
            reason = ACCOUNT_STATUS_UNAVAILABLE_REASON

        # readiness 축 — status 축이 통과했을 때만 평가(둘 중 하나라도 막으면 거부).
        if reason is None:
            broker_type = getattr(account, "broker_type", "")
            trading_mode = getattr(account, "trading_mode", None)
            if not isinstance(broker_type, str) or trading_mode is None:
                reason = f"{ACCOUNT_NOT_READY_REASON}: account_metadata_unavailable"
            elif trading_mode != TradingMode.LIVE:
                # 안전장치(G2): non-LIVE 가 마커 skip 을 뚫고 여기까지 도달하면
                # 실 broker.place_order 호출 직전이다 — fail-closed 차단한다.
                reason = f"{ACCOUNT_NOT_READY_REASON}: non_live_broker_call_blocked"
            elif active_trading_blocked(
                self._runtime_readiness,
                account_id,
                broker_type=broker_type,
                trading_mode=trading_mode,
            ):
                reason = not_ready_reason(
                    self._runtime_readiness,
                    account_id,
                    broker_type=broker_type,
                    trading_mode=trading_mode,
                )

        if reason is None:
            return
        # G6: 계층3 운영자 가시성 — generic 문구(청산 marker 미운반). 정확히 1회.
        await self._eventbus.publish(
            build_not_ready_notification(
                account_id=account_id,
                reason=reason,
                side=side,
                is_liquidation=False,
            )
        )
        # error_code 는 status 축이면 해당 토큰, readiness 축이면 account_not_ready.
        error_code = (
            reason
            if reason in (ACCOUNT_SUSPENDED_REASON, ACCOUNT_STATUS_UNAVAILABLE_REASON)
            else ACCOUNT_NOT_READY_REASON
        )
        raise APIError(reason, error_code=error_code)

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

        # ── #2398 계층3: active-order gate — rate-limit/broker 획득 **이후**, ──
        # ``place_order`` **직전** 단일 재확인(attempt4-a, P1).
        #
        # **위치(spec 11-order-flow.md)**: ``rate_limiter.acquire()``(최대 ~60s
        # await) + ``_get_broker()`` await **뒤**, ``place_order`` 직전. gate 를
        # 이 await 들 **앞**에 두면 대기 중 ``mark_not_ready``/suspend 가 끼어
        # stale 통과로 실 주문이 나가므로(TOCTOU), 비가역 시점 직전 단일 재확인으로
        # 윈도우를 닫는다. 재확인 직후 ``place_order`` 가 동기 시작한다.
        #
        # not_ready/suspended/status-unavailable 면 broker 를 호출하지 않고
        # ``APIError`` 를 raise → 호출자 ``_on_order_approved`` 의 except 가
        # OrderFailedEvent(bot_id/order_id/account_id 보존)로 변환 → Treasury
        # ``_on_order_failed`` → ``release_reservation`` 정확 해제(G3, [must_fix I]).
        #
        # **G3 critical**: 이 gate 를 ``_on_order_approved`` 의 isinstance 직후에서
        # raise 하면 EventBus(bus.py:96)가 예외를 swallow 하여 OrderFailedEvent 가
        # 미발행되고 reserve 가 영구 고착된다. 따라서 gate 는 반드시
        # ``submit_order`` 내부에서 실행해 실패가 except→OrderFailedEvent 로
        # 귀결되게 한다.
        rate_limiter = self._get_rate_limiter(account_id)
        await rate_limiter.acquire()
        broker = await self._get_broker(account_id)
        await self._readiness_gate(account_id, side=side)
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

        # ── #2398 Virtual 라우팅: account 메타 기반 non-LIVE silent skip(Fix A) ──
        # 위치: stop/stop_limit StopOrderManager 분기 **뒤**, submit try **前**
        # (spec api-gateway.md:161 normative).
        #
        # **메타 기반 결정적 라우팅(구독 순서 비의존)**: gateway 는 account 메타를
        # **단일** fetch 해(``_get_account``) ``trading_mode`` 로 routing 을
        # **결정적으로** 판정한다 — main 의 EventBus 구독 순서에 의존하지 않는다.
        # 과거 attempt1 의 ``_virtual_handled`` 마커-only skip 은 VirtualExecutor 가
        # gateway 보다 먼저 구독됐다는 가정에 의존했고, gateway 가 먼저 실행되면
        # 마커 미설정 상태로 virtual 주문이 ``submit_order``→``_readiness_gate`` 의
        # ``trading_mode != LIVE`` 분기로 들어가 ``non_live_broker_call_blocked``
        # OrderFailedEvent 를 발행 → 뒤이어 VirtualExecutor 가 같은 주문을 체결/실패
        # 처리해 동일 order_id terminal 이 중복됐다(finding 1). 메타 기반 silent
        # skip 으로 이 race 를 봉쇄한다.
        #
        # - 메타 성공 + ``trading_mode != LIVE`` → **silent skip**(terminal 발행
        #   없음). virtual 주문은 VirtualExecutor 가 소유 처리(체결/실패 종결).
        # - 메타 성공 + LIVE → ``submit_order``. 내부 계층3 gate 가 ``place_order``
        #   직전 단일 fresh fetch 로 readiness + status(SUSPENDED) 재확인 후 broker
        #   호출(routing fetch 재사용 금지 — in-flight suspend 검출 위해 await 이후
        #   최신 status 필요, attempt4-a/b).
        # - 메타 **실패**(None) → fail-closed. 단 ``_virtual_handled`` 마커가 set
        #   이면 skip(VirtualExecutor 가 소유 처리 — finding 1 메타 실패 잔여
        #   코너의 중복 terminal 봉쇄, defense-in-depth). 마커 미설정이면 live
        #   경로로 보고 ``submit_order``→계층3 gate 가 메타 실패를 G6 알림
        #   + APIError 로 처리 → except → OrderFailedEvent(alert 누락 방지).
        from ante.account.models import TradingMode

        account, _ = await self._get_account(event.account_id)
        if account is not None:
            trading_mode = getattr(account, "trading_mode", None)
            is_non_live = (
                isinstance(trading_mode, TradingMode)
                and trading_mode != TradingMode.LIVE
            )
            if is_non_live:
                # 메타 결정적 non-LIVE(VIRTUAL) → broker.place_order 경로 silent
                # skip. virtual 주문은 VirtualExecutor 가 소유 처리(terminal 없음).
                # trading_mode 가 None/비-TradingMode(메타 손상)면 silent skip 하지
                # 않고 아래 live 경로로 떨어뜨려 ``_readiness_gate`` 가 fail-closed
                # (account_metadata_unavailable) 차단하게 한다(G2 — 손상 메타를
                # virtual 로 오인해 fall-open 하지 않는다).
                return
        elif getattr(event, "_virtual_handled", False):
            # 메타 실패 잔여 코너 — VirtualExecutor 가 소유 마커를 set 했으므로
            # (priority 60 > gateway 50, 구독 순서 비의존) virtual 주문이다 →
            # VirtualExecutor 가 체결/실패 종결한다. gateway 는 skip 하여 동일
            # order_id terminal 중복(finding 1)을 막는다.
            return
        # 메타 성공+LIVE 또는 메타 실패(마커 미설정)=live 경로. 계층3 gate 가
        # ``place_order`` 직전 fresh fetch 로 readiness + status 를 재확인한다(routing
        # 의 stale account 를 재사용하지 않음 — in-flight suspend/저하 검출).

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

        def _is_finite_number(x: object) -> bool:
            """비-bool 유한 숫자 여부 — 예외 무전파(terminal 보장).

            비숫자·bool·NaN/Inf 는 False. float 로 표현 불가한 큰 정수
            (``math.isfinite`` 가 ``OverflowError`` raise — #1412 P2-2 동형)도
            예외를 삼켜 False 로 본다(핸들러 예외로 terminal update 가 소실되지
            않도록 fail-closed).
            """
            if isinstance(x, bool) or not isinstance(x, (int, float)):
                return False
            try:
                return math.isfinite(x)
            except (OverflowError, TypeError, ValueError):
                return False

        def _safe_repr(x: object) -> str:
            """로그용 안전 repr — 거대 정수 repr 시 ValueError(int→str 4300자
            한도) 등을 삼키고 타입명으로 대체(로깅이 terminal 거부를 깨지 않도록)."""
            try:
                r = repr(x)
            except (ValueError, OverflowError):
                return f"<{type(x).__name__}>"
            return r if len(r) <= 80 else r[:77] + "..."

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
        # (_is_finite_number 가 비숫자·NaN/Inf·큰 정수 OverflowError 를 예외 없이
        # False 로 처리 → terminal 보장.)
        new_price = event.price
        if new_price is None or not _is_finite_number(new_price) or new_price <= 0:
            logger.warning(
                "주문 정정 거부(무효 가격): %s — %s",
                event.order_id,
                _safe_repr(new_price),
            )
            await _reject("modify_invalid_args")
            return

        # (b) 수량 finite 검증 + sentinel — 비숫자/bool/비유한(NaN/Inf)/음수 무효.
        # NaN 은 <0·>0 모두 false 라 검증 없이는 price-only 로 브로커까지 통과하고,
        # str/None 은 비교에서 TypeError, 큰 정수는 OverflowError → terminal 이벤트
        # 소실되므로 비교 전에 _is_finite_number 로 fail-closed.
        new_qty = event.quantity
        if not _is_finite_number(new_qty) or new_qty < 0:
            logger.warning(
                "주문 정정 거부(무효 수량): %s — %s",
                event.order_id,
                _safe_repr(new_qty),
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

        # (b0) 봇 소유권 — 같은 계좌 내 타 봇 주문 정정 차단(봇 격리). 성공 시
        # 요청 봇/전략으로 기록·이벤트가 남으므로, record 의 bot_id 가 이벤트와
        # 다르면 broker 호출 전에 fail-closed.
        if record.bot_id != event.bot_id:
            logger.warning(
                "주문 정정 거부(봇 소유권 불일치): %s — record_bot=%s req_bot=%s",
                event.order_id,
                record.bot_id,
                event.bot_id,
            )
            await _reject("modify_not_owner", symbol=sym, side=sd)
            return

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

        # (c') v1 은 지정가(limit) price-only 정정만 — 비지정가(market 등) 주문은
        # 정정 시 order_type="limit" 강제로 주문구분이 바뀌므로 fail-closed(#2393).
        if record.order_type != "limit":
            logger.warning(
                "주문 정정 거부(비지정가 주문): %s — order_type=%s",
                event.order_id,
                record.order_type,
            )
            await _reject("modify_unsupported_order_type", symbol=sym, side=sd)
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
        # broker 조회/레이트리밋 대기도 try 안에 둔다 — broker 미캐시·connect/auth
        # 실패 예외가 핸들러 밖으로 새면 EventBus 가 에러만 로깅하고 전략에
        # terminal(OrderModifyRejectedEvent)이 전달되지 않으므로(정정은 성공/거부
        # 중 하나의 terminal update 보장 필요).
        try:
            rate_limiter = self._get_rate_limiter(account_id)
            await rate_limiter.acquire()
            broker = await self._get_broker(account_id)
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
