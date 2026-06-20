"""StreamIntegration — KISStreamClient와 APIGateway 실시간 시세 연동.

KIS WebSocket 실시간 시세를 수신하여:
- ResponseCache에 가격 적재
- StopOrderManager에 가격 전달
- 체결 통보 시 캐시 무효화 및 이벤트 발행
- 활성 봇의 모니터링 종목 자동 구독/해제
- 스트림 연결 해제 시 REST 폴링 폴백
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.bot.manager import BotManager
    from ante.broker.kis_stream import KISStreamClient
    from ante.eventbus.bus import EventBus
    from ante.gateway.cache import ResponseCache
    from ante.gateway.gateway import APIGateway
    from ante.gateway.stop_order import StopOrderManager
    from ante.trade.fill_applier import FillApplier

logger = logging.getLogger(__name__)

# REST 폴링 폴백 주기 (초)
DEFAULT_FALLBACK_POLL_INTERVAL = 5.0

# 종목 구독 동기화 주기 (초)
DEFAULT_SYNC_INTERVAL = 10.0


class StreamIntegration:
    """KISStreamClient ↔ APIGateway 실시간 시세 연동 관리자.

    - 시세 콜백: cache.set + stop_order.on_price_update
    - 체결 콜백: 캐시 무효화 + 이벤트 발행
    - 활성 봇 종목 구독/해제 메커니즘
    - 스트림 해제 시 REST 폴백
    """

    def __init__(
        self,
        stream_client: KISStreamClient,
        cache: ResponseCache,
        eventbus: EventBus,
        *,
        account_id: str,
        stop_order_manager: StopOrderManager | None = None,
        gateway: APIGateway | None = None,
        bot_manager: BotManager | None = None,
        fill_applier: FillApplier | None = None,
        fallback_poll_interval: float = DEFAULT_FALLBACK_POLL_INTERVAL,
        sync_interval: float = DEFAULT_SYNC_INTERVAL,
    ) -> None:
        # SPLIT-3 (#1242): multi-account StreamIntegration pool 의 핵심 계약 —
        # 인스턴스마다 단일 KIS 계좌 lifecycle 에 묶이며, fallback / 캐시
        # 네임스페이스 / stop_order trigger 격리 모두 self._account_id 에 의존
        # 한다. fallback 금지 (``require_account_id``).
        from ante.account.scoping import require_account_id

        require_account_id(account_id, context="stream_integration.__init__")

        self._stream = stream_client
        self._cache = cache
        self._eventbus = eventbus
        self._account_id = account_id
        self._stop_order_manager = stop_order_manager
        self._gateway = gateway
        self._bot_manager = bot_manager
        self._fill_applier = fill_applier
        self._fallback_poll_interval = fallback_poll_interval
        self._sync_interval = sync_interval

        self._running = False
        self._fallback_task: asyncio.Task[None] | None = None
        self._sync_task: asyncio.Task[None] | None = None
        self._fallback_active = False

    @property
    def is_stream_connected(self) -> bool:
        """스트림 연결 상태."""
        return self._stream.is_connected

    @property
    def is_fallback_active(self) -> bool:
        """REST 폴링 폴백 활성 여부."""
        return self._fallback_active

    async def start(self) -> None:
        """연동 시작: 콜백 등록 → 스트림 연결 → 구독 동기화 시작."""
        if self._running:
            return

        self._running = True

        # 콜백 등록
        self._stream.on_price(self._on_price)
        self._stream.on_execution(self._on_execution)

        # 이벤트 구독 (연결/해제 감지)
        from ante.eventbus.events import StreamConnectedEvent, StreamDisconnectedEvent

        self._eventbus.subscribe(StreamConnectedEvent, self._on_stream_connected)
        self._eventbus.subscribe(StreamDisconnectedEvent, self._on_stream_disconnected)

        # 봇 시작/종료 이벤트 구독 (종목 구독 동기화용)
        from ante.eventbus.events import BotStartedEvent, BotStoppedEvent

        self._eventbus.subscribe(BotStartedEvent, self._on_bot_changed)
        self._eventbus.subscribe(BotStoppedEvent, self._on_bot_changed)

        # 스트림 연결
        await self._stream.connect()
        await self._stream.subscribe_execution()

        # 종목 구독 동기화 태스크 시작
        self._sync_task = asyncio.create_task(
            self._subscription_sync_loop(),
            name="stream-subscription-sync",
        )

        logger.info("StreamIntegration 시작")

    async def stop(self) -> None:
        """연동 중지: 폴백 중지 → 동기화 중지 → 스트림 해제."""
        if not self._running:
            return

        self._running = False

        # 폴백 태스크 정리
        await self._stop_fallback()

        # 동기화 태스크 정리
        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        # 스트림 해제
        await self._stream.disconnect()

        logger.info("StreamIntegration 중지")

    # ── 시세 콜백 ──────────────────────────────────

    async def _on_price(self, symbol: str, price: float) -> None:
        """실시간 시세 수신 콜백.

        KIS WebSocket ──시세수신──> 콜백
            +-> ResponseCache.set("{account_id}:price:{symbol}", ...)
            +-> StopOrderManager.on_price_update(symbol, price)
        """
        # 캐시 적재 (account_id 기반 네임스페이스)
        cache_key = f"{self._account_id}:price:{symbol}"
        self._cache.set(cache_key, price, ttl=5)

        # StopOrderManager 시세 전달
        # SPLIT-3 (#1242): 각 KISStreamClient 는 단일 계좌 lifecycle 에 묶인다.
        # tick 의 account_id 는 stream 인스턴스의 ``self._account_id`` 와 동일하다.
        if self._stop_order_manager:
            try:
                # #2405 (attempt5 P2): 실 WebSocket 틱은 거래일 개장 신호이므로
                # ``is_exchange_tick=True`` (default 이나 대칭·가독성 위해 명시).
                await self._stop_order_manager.on_price_update(
                    symbol,
                    price,
                    account_id=self._account_id,
                    is_exchange_tick=True,
                )
            except Exception:
                logger.exception("StopOrderManager 시세 전달 오류: %s", symbol)

    # ── 체결 콜백 ──────────────────────────────────

    async def _on_execution(self, execution: dict[str, Any]) -> None:
        """실시간 체결 통보 콜백 (빠른 경로 — #1946).

        캐시 무효화 + ``FillApplier`` 라우팅.

        직접 ``OrderFilledEvent`` 를 발행하지 않는다. 스트림(빠른 경로)과 REST
        백스톱 폴이 단일 멱등 choke point(``FillApplier``)로 수렴해 같은 체결을
        몇 번 관측하든 포지션이 정확히 한 번 반영되게 한다. 스트림 payload 의
        ``order_id`` 는 broker 주문번호(odno)이며, ``quantity`` 는 per-execution
        증분이므로 ``apply_stream_increment`` 로 누적 환산해 적용한다.

        ``account_id``는 broker payload 우선, 없으면 lifecycle에 묶인
        ``self._account_id``로 fallback한다. 둘 다 비어있으면 라우팅을 skip하고
        WARNING만 남긴다 (캐시 무효화는 best-effort 수행). 백스톱 폴이 체결을
        멱등 복구하므로 fast-path skip 은 정합성을 깨지 않는다.
        """
        from ante.broker.fill_scheduler import business_date_kst

        symbol = execution.get("symbol", "")
        account_id = execution.get("account_id", "") or self._account_id

        # 캐시 무효화: account_id 범위 내 balance, positions, 해당 종목 시세
        # account_id 가 비어 있으면 무효화 키가 의미 없으므로 skip.
        if account_id:
            self._cache.invalidate(f"{account_id}:balance")
            self._cache.invalidate(f"{account_id}:positions")
            if symbol:
                self._cache.invalidate(f"{account_id}:price:{symbol}")

        # account_id 가 비어 있으면 FillApplier 라우팅(account-scoped 조회)이
        # 불가능하다. 백스톱 폴이 복구하므로 skip + WARNING.
        if not account_id:
            logger.warning(
                "체결 통보에 account_id가 없어 FillApplier 라우팅을 skip합니다: "
                "symbol=%s order_id=%s side=%s",
                symbol,
                execution.get("order_id", ""),
                execution.get("side", ""),
            )
            return

        # FillApplier 미주입(REST 전용 모드 등)이면 백스톱 폴에 일임.
        if self._fill_applier is None:
            logger.debug(
                "FillApplier 미설정 — 스트림 체결은 백스톱 폴이 복구: %s %s",
                symbol,
                execution.get("order_id", ""),
            )
            return

        broker_order_id = str(execution.get("order_id", ""))
        increment = float(execution.get("quantity", 0.0) or 0.0)
        avg_price = float(execution.get("price", 0.0) or 0.0)
        if not broker_order_id or increment <= 0:
            return

        ts = execution.get("timestamp")
        submitted_date = (
            business_date_kst(ts) if isinstance(ts, datetime) else business_date_kst()
        )
        try:
            await self._fill_applier.apply_stream_increment(
                account_id=account_id,
                broker_order_id=broker_order_id,
                increment=increment,
                avg_price=avg_price,
                submitted_date=submitted_date,
            )
        except Exception:
            logger.exception(
                "스트림 체결 FillApplier 라우팅 실패: %s %s",
                symbol,
                broker_order_id,
            )

        logger.debug("체결 통보 처리: %s %s", symbol, execution.get("side", ""))

    # ── 스트림 연결/해제 이벤트 ──────────────────────

    async def _on_stream_connected(self, event: object) -> None:
        """스트림 연결 성공 시 폴백 중지.

        SPLIT-3 (#1242): multi-account StreamIntegration pool 에서 다른
        계좌의 stream 이벤트로 자기 fallback 을 토글하지 않도록
        ``event.account_id`` 가 ``self._account_id`` 와 일치할 때만 반응한다.
        """
        event_account_id = getattr(event, "account_id", "")
        if event_account_id != self._account_id:
            return
        await self._stop_fallback()
        logger.info("스트림 연결됨 — REST 폴링 폴백 중지")

    async def _on_stream_disconnected(self, event: object) -> None:
        """스트림 연결 해제 시 REST 폴링 폴백 시작.

        SPLIT-3 (#1242): account-scoped 필터. 자세한 내용은
        :meth:`_on_stream_connected` 참조.
        """
        if not self._running:
            return
        event_account_id = getattr(event, "account_id", "")
        if event_account_id != self._account_id:
            return
        await self._start_fallback()
        logger.warning("스트림 연결 해제 — REST 폴링 폴백 시작")

    # ── REST 폴링 폴백 ──────────────────────────────

    async def _start_fallback(self) -> None:
        """REST 폴링 폴백 시작."""
        if self._fallback_active:
            return
        if not self._gateway:
            logger.warning("APIGateway 미설정 — REST 폴링 폴백 불가")
            return

        self._fallback_active = True
        self._fallback_task = asyncio.create_task(
            self._fallback_poll_loop(),
            name="stream-fallback-poll",
        )

    async def _stop_fallback(self) -> None:
        """REST 폴링 폴백 중지."""
        self._fallback_active = False
        if self._fallback_task and not self._fallback_task.done():
            self._fallback_task.cancel()
            try:
                await self._fallback_task
            except asyncio.CancelledError:
                pass
            self._fallback_task = None

    async def _fallback_poll_loop(self) -> None:
        """스트림 해제 시 REST API로 시세 폴링."""
        if self._gateway is None:
            return
        gateway = self._gateway
        while self._fallback_active and self._running:
            try:
                symbols = self._get_monitored_symbols()
                for symbol in symbols:
                    if not self._fallback_active or not self._running:
                        return
                    try:
                        price = await gateway.get_current_price(
                            symbol, account_id=self._account_id
                        )
                        cache_key = f"{self._account_id}:price:{symbol}"
                        self._cache.set(cache_key, price, ttl=5)

                        if self._stop_order_manager:
                            # #2405 (attempt5 P2): REST fallback poll 은 KIS
                            # ``inquire-price`` 가 휴장일에도 직전 종가를 성공
                            # 반환하므로 거래일을 보증하지 못한다 →
                            # ``is_exchange_tick=False`` 로 거래일 멤버십 마킹을
                            # 유발하지 않게 한다(트리거 평가는 그대로 수행).
                            await self._stop_order_manager.on_price_update(
                                symbol,
                                price,
                                account_id=self._account_id,
                                is_exchange_tick=False,
                            )
                    except Exception:
                        logger.warning("REST 폴링 실패: %s", symbol, exc_info=True)

                await asyncio.sleep(self._fallback_poll_interval)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("REST 폴링 폴백 루프 오류")
                await asyncio.sleep(self._fallback_poll_interval)

    # ── 종목 구독 동기화 ──────────────────────────────

    async def _on_bot_changed(self, event: object) -> None:
        """봇 시작/종료 시 종목 구독 즉시 동기화."""
        await self._sync_subscriptions()

    async def _subscription_sync_loop(self) -> None:
        """주기적으로 활성 봇 종목과 스트림 구독 동기화."""
        while self._running:
            try:
                await asyncio.sleep(self._sync_interval)
                await self._sync_subscriptions()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("종목 구독 동기화 오류")

    async def _sync_subscriptions(self) -> None:
        """활성 봇 모니터링 종목을 스트림에 구독/해제."""
        desired = self._get_monitored_symbols()
        current = self._stream.subscribed_symbols

        # 새로 구독해야 할 종목
        to_subscribe = desired - current
        # 해제해야 할 종목
        to_unsubscribe = current - desired

        for symbol in to_subscribe:
            success = await self._stream.subscribe(symbol)
            if success:
                logger.debug("종목 구독 추가: %s", symbol)

        for symbol in to_unsubscribe:
            await self._stream.unsubscribe(symbol)
            logger.debug("종목 구독 해제: %s", symbol)

    def _get_monitored_symbols(self) -> set[str]:
        """모니터링 대상 종목 수집 (활성 봇 + StopOrderManager).

        SPLIT-3 (#1242): multi-account StreamIntegration pool 에서 각 인스턴스
        는 자신의 ``self._account_id`` 에 해당하는 봇만 선택한다. StopOrder
        역시 같은 account_id 의 active orders 만 모니터링 종목에 포함시켜
        다른 계좌의 KIS 40종목 한도를 잠식하지 않게 한다.
        """
        symbols: set[str] = set()

        # 활성 봇의 종목: 봇 config 의 account_id 가 일치하는 것만.
        if self._bot_manager:
            for bot_info in self._bot_manager.list_bots():
                if bot_info.get("status") != "running":
                    continue
                bot = self._bot_manager.get_bot(bot_info["bot_id"])
                if bot is None:
                    continue
                bot_account_id = ""
                bot_config = getattr(bot, "config", None)
                if bot_config is not None:
                    bot_account_id = getattr(bot_config, "account_id", "")
                if bot_account_id != self._account_id:
                    continue
                if hasattr(bot, "monitored_symbols"):
                    symbols.update(bot.monitored_symbols)

        # StopOrderManager의 모니터링 종목 — account_id 매칭만.
        if self._stop_order_manager:
            for order in self._stop_order_manager.active_orders:
                if order.account_id == self._account_id:
                    symbols.add(order.symbol)

        return symbols
