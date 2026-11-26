"""StreamIntegration — KISStreamClient와 APIGateway 실시간 시세 연동."""

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

DEFAULT_FALLBACK_POLL_INTERVAL = 5.0

DEFAULT_SYNC_INTERVAL = 10.0


class StreamIntegration:
    """KISStreamClient ↔ APIGateway 실시간 시세 연동 관리자.

    - 시세 콜백: cache.set + stop_order.on_price_update
    - 체결 통보: 구독하지 않고 처리기도 등록하지 않는다(체결은 백스톱 폴)
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

        self._stream.on_price(self._on_price)

        from ante.eventbus.events import StreamConnectedEvent, StreamDisconnectedEvent

        self._eventbus.subscribe(StreamConnectedEvent, self._on_stream_connected)
        self._eventbus.subscribe(StreamDisconnectedEvent, self._on_stream_disconnected)

        from ante.eventbus.events import BotStartedEvent, BotStoppedEvent

        self._eventbus.subscribe(BotStartedEvent, self._on_bot_changed)
        self._eventbus.subscribe(BotStoppedEvent, self._on_bot_changed)

        await self._stream.connect()

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

        await self._stop_fallback()

        if self._sync_task and not self._sync_task.done():
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
            self._sync_task = None

        await self._stream.disconnect()

        logger.info("StreamIntegration 중지")

    async def _on_price(self, symbol: str, price: float) -> None:
        """실시간 시세 수신 콜백."""
        cache_key = f"{self._account_id}:price:{symbol}"
        self._cache.set(cache_key, price, ttl=5)

        if self._stop_order_manager:
            try:
                await self._stop_order_manager.on_price_update(
                    symbol,
                    price,
                    account_id=self._account_id,
                    is_exchange_tick=True,
                )
            except Exception:
                logger.exception("StopOrderManager 시세 전달 오류: %s", symbol)

    async def _on_execution(self, execution: dict[str, Any]) -> None:
        """실시간 체결 통보 콜백 (빠른 경로)."""
        from ante.broker.fill_scheduler import business_date_kst

        symbol = execution.get("symbol", "")
        account_id = execution.get("account_id", "") or self._account_id

        if account_id:
            self._cache.invalidate(f"{account_id}:balance")
            self._cache.invalidate(f"{account_id}:positions")
            if symbol:
                self._cache.invalidate(f"{account_id}:price:{symbol}")

        if not account_id:
            logger.warning(
                "체결 통보에 account_id가 없어 FillApplier 라우팅을 skip합니다: "
                "symbol=%s order_id=%s side=%s",
                symbol,
                execution.get("order_id", ""),
                execution.get("side", ""),
            )
            return

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

    async def _on_stream_connected(self, event: object) -> None:
        """자기 계좌(``self._account_id``)의 스트림 연결 성공 시 폴백 중지."""
        event_account_id = getattr(event, "account_id", "")
        if event_account_id != self._account_id:
            return
        await self._stop_fallback()
        logger.info("스트림 연결됨 — REST 폴링 폴백 중지")

    async def _on_stream_disconnected(self, event: object) -> None:
        """자기 계좌의 스트림 연결 해제 시 REST 폴링 폴백 시작(``_running`` 일 때만)."""
        if not self._running:
            return
        event_account_id = getattr(event, "account_id", "")
        if event_account_id != self._account_id:
            return
        await self._start_fallback()
        logger.warning("스트림 연결 해제 — REST 폴링 폴백 시작")

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

        to_subscribe = desired - current
        to_unsubscribe = current - desired

        for symbol in to_subscribe:
            success = await self._stream.subscribe(symbol)
            if success:
                logger.debug("종목 구독 추가: %s", symbol)

        for symbol in to_unsubscribe:
            await self._stream.unsubscribe(symbol)
            logger.debug("종목 구독 해제: %s", symbol)

    def _get_monitored_symbols(self) -> set[str]:
        """자기 계좌의 모니터링 대상 종목 수집 (running 봇 + StopOrderManager)."""
        symbols: set[str] = set()

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

        if self._stop_order_manager:
            for order in self._stop_order_manager.active_orders:
                if order.account_id == self._account_id:
                    symbols.add(order.symbol)

        return symbols
