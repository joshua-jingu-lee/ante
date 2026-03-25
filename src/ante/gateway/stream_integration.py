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
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.bot.manager import BotManager
    from ante.broker.kis_stream import KISStreamClient
    from ante.eventbus.bus import EventBus
    from ante.gateway.cache import ResponseCache
    from ante.gateway.gateway import APIGateway
    from ante.gateway.stop_order import StopOrderManager

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
        account_id: str = "",
        stop_order_manager: StopOrderManager | None = None,
        gateway: APIGateway | None = None,
        bot_manager: BotManager | None = None,
        fallback_poll_interval: float = DEFAULT_FALLBACK_POLL_INTERVAL,
        sync_interval: float = DEFAULT_SYNC_INTERVAL,
    ) -> None:
        self._stream = stream_client
        self._cache = cache
        self._eventbus = eventbus
        self._account_id = account_id
        self._stop_order_manager = stop_order_manager
        self._gateway = gateway
        self._bot_manager = bot_manager
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
        if self._stop_order_manager:
            try:
                await self._stop_order_manager.on_price_update(symbol, price)
            except Exception:
                logger.exception("StopOrderManager 시세 전달 오류: %s", symbol)

    # ── 체결 콜백 ──────────────────────────────────

    async def _on_execution(self, execution: dict[str, Any]) -> None:
        """실시간 체결 통보 콜백.

        캐시 무효화 + OrderFilledEvent 발행.
        """
        symbol = execution.get("symbol", "")
        account_id = execution.get("account_id", self._account_id)

        # 캐시 무효화: account_id 범위 내 balance, positions, 해당 종목 시세
        self._cache.invalidate(f"{account_id}:balance")
        self._cache.invalidate(f"{account_id}:positions")
        if symbol:
            self._cache.invalidate(f"{account_id}:price:{symbol}")

        # 체결 이벤트 발행
        from ante.eventbus.events import OrderFilledEvent

        await self._eventbus.publish(
            OrderFilledEvent(
                account_id=account_id,
                order_id=execution.get("order_id", ""),
                symbol=symbol,
                side=execution.get("side", ""),
                quantity=execution.get("quantity", 0.0),
                price=execution.get("price", 0.0),
                exchange="KRX",
            )
        )

        logger.debug("체결 통보 처리: %s %s", symbol, execution.get("side", ""))

    # ── 스트림 연결/해제 이벤트 ──────────────────────

    async def _on_stream_connected(self, event: object) -> None:
        """스트림 연결 성공 시 폴백 중지."""
        await self._stop_fallback()
        logger.info("스트림 연결됨 — REST 폴링 폴백 중지")

    async def _on_stream_disconnected(self, event: object) -> None:
        """스트림 연결 해제 시 REST 폴링 폴백 시작."""
        if not self._running:
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
                            await self._stop_order_manager.on_price_update(
                                symbol, price
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
        """모니터링 대상 종목 수집 (활성 봇 + StopOrderManager)."""
        symbols: set[str] = set()

        # 활성 봇의 종목 (봇 info에서 추출 가능한 경우)
        if self._bot_manager:
            for bot_info in self._bot_manager.list_bots():
                if bot_info.get("status") == "running":
                    bot = self._bot_manager.get_bot(bot_info["bot_id"])
                    if bot and hasattr(bot, "monitored_symbols"):
                        symbols.update(bot.monitored_symbols)

        # StopOrderManager의 모니터링 종목
        if self._stop_order_manager:
            symbols.update(self._stop_order_manager.monitored_symbols)

        return symbols
