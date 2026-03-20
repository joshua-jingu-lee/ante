"""Bot — 전략을 실행하는 개별 봇."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ante.bot.config import BotConfig, BotStatus

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.strategy.base import Signal, Strategy
    from ante.strategy.context import StrategyContext

logger = logging.getLogger(__name__)


class Bot:
    """전략을 실행하는 개별 봇.

    각 봇은 독립 asyncio.Task로 실행되며,
    주기적으로 on_step()을 호출하여 Signal을 수집하고
    OrderRequestEvent로 변환하여 EventBus에 발행한다.
    """

    def __init__(
        self,
        config: BotConfig,
        strategy_cls: type[Strategy],
        ctx: StrategyContext,
        eventbus: EventBus,
        exchange: str = "",
    ) -> None:
        self.config = config
        self.bot_id = config.bot_id
        self.exchange = exchange
        self._strategy_cls = strategy_cls
        self._ctx = ctx
        self._eventbus = eventbus

        self.status = BotStatus.CREATED
        self.strategy: Strategy | None = None
        self._task: asyncio.Task[None] | None = None
        self.started_at: datetime | None = None
        self.stopped_at: datetime | None = None
        self.error_message: str | None = None
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 3

    async def start(self) -> None:
        """봇 시작. 전략 인스턴스화 + 실행 루프 Task 생성."""
        from ante.eventbus.events import BotStartedEvent

        self.strategy = self._strategy_cls(ctx=self._ctx)
        self.strategy.on_start()

        self.status = BotStatus.RUNNING
        self.started_at = datetime.now(UTC)
        self._task = asyncio.create_task(
            self._run_loop(),
            name=f"bot_{self.bot_id}",
        )

        await self._eventbus.publish(
            BotStartedEvent(bot_id=self.bot_id, account_id=self.config.account_id)
        )
        logger.info("봇 시작: %s", self.bot_id)

    async def stop(self) -> None:
        """봇 중지. 실행 루프 취소 + 전략 정리."""
        from ante.eventbus.events import BotStoppedEvent

        if self.status != BotStatus.RUNNING:
            return

        self.status = BotStatus.STOPPING

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self.strategy:
            self.strategy.on_stop()

        self.status = BotStatus.STOPPED
        self.stopped_at = datetime.now(UTC)

        await self._eventbus.publish(
            BotStoppedEvent(bot_id=self.bot_id, account_id=self.config.account_id)
        )
        logger.info("봇 중지: %s", self.bot_id)

    async def _run_loop(self) -> None:
        """메인 실행 루프."""
        from ante.eventbus.events import BotErrorEvent

        try:
            while self.status == BotStatus.RUNNING:
                step_context = {
                    "timestamp": datetime.now(UTC),
                    "portfolio": self._ctx.get_positions(),
                    "balance": self._ctx.get_balance(),
                }

                # on_step 타임아웃 적용
                try:
                    signals = await asyncio.wait_for(
                        self.strategy.on_step(step_context),  # type: ignore[union-attr]
                        timeout=self.config.step_timeout_seconds,
                    )
                except TimeoutError:
                    self._consecutive_failures += 1
                    logger.warning(
                        "on_step 타임아웃: %s (%d/%d)",
                        self.bot_id,
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                    )
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        logger.error(
                            "연속 타임아웃 한도 초과 — 봇 중지: %s",
                            self.bot_id,
                        )
                        await self.stop()
                        return
                    await asyncio.sleep(self.config.interval_seconds)
                    continue

                # Signal 수 상한 검증
                max_signals = self.config.max_signals_per_step
                if len(signals) > max_signals:
                    self._consecutive_failures += 1
                    logger.warning(
                        "Signal 수 초과: %s (%d > %d, 연속 %d/%d)",
                        self.bot_id,
                        len(signals),
                        max_signals,
                        self._consecutive_failures,
                        self._max_consecutive_failures,
                    )
                    msg = f"Signal count exceeded: {len(signals)} > {max_signals}"
                    await self._eventbus.publish(
                        BotErrorEvent(
                            bot_id=self.bot_id,
                            account_id=self.config.account_id,
                            error_message=msg,
                        )
                    )
                    if self._consecutive_failures >= self._max_consecutive_failures:
                        logger.error(
                            "연속 Signal 초과 한도 — 봇 중지: %s",
                            self.bot_id,
                        )
                        await self.stop()
                        return
                    await asyncio.sleep(self.config.interval_seconds)
                    continue

                # 정상 실행 — 카운터 리셋
                self._consecutive_failures = 0

                await self._publish_signals(signals)

                actions = self._ctx._drain_actions()
                await self._publish_actions(actions)

                await asyncio.sleep(self.config.interval_seconds)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            self.status = BotStatus.ERROR
            self.error_message = str(e)
            logger.exception("봇 오류: %s", self.bot_id)
            await self._eventbus.publish(
                BotErrorEvent(
                    bot_id=self.bot_id,
                    account_id=self.config.account_id,
                    error_message=str(e),
                )
            )

    async def on_order_filled(self, event: object) -> None:
        """체결 통보를 전략에 전달."""
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return
        if not self.strategy or event.bot_id != self.bot_id:
            return

        follow_up = await self.strategy.on_fill(
            {
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "price": event.price,
                "timestamp": event.timestamp,
            }
        )
        await self._publish_signals(follow_up or [])

    async def on_order_update(self, event: object) -> None:
        """주문 상태 변경 통보를 전략에 전달."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
        )

        bot_id = getattr(event, "bot_id", None)
        if not self.strategy or bot_id != self.bot_id:
            return

        update: dict[str, Any] = {}
        if isinstance(event, OrderSubmittedEvent):
            update = {
                "order_id": event.order_id,
                "status": "submitted",
                "symbol": event.symbol,
                "side": event.side,
            }
        elif isinstance(event, OrderRejectedEvent):
            update = {
                "order_id": event.order_id,
                "status": "rejected",
                "symbol": event.symbol,
                "side": event.side,
                "reason": event.reason,
            }
        elif isinstance(event, OrderCancelledEvent):
            update = {
                "order_id": event.order_id,
                "status": "cancelled",
                "symbol": event.symbol,
                "side": event.side,
                "reason": event.reason,
            }
        elif isinstance(event, OrderFailedEvent):
            update = {
                "order_id": event.order_id,
                "status": "failed",
                "symbol": event.symbol,
                "side": event.side,
                "reason": event.error_message,
            }
        elif isinstance(event, OrderCancelFailedEvent):
            update = {
                "order_id": event.order_id,
                "status": "cancel_failed",
                "symbol": "",
                "side": "",
                "reason": event.error_message,
            }

        if update:
            await self.strategy.on_order_update(update)

    async def on_external_signal(self, event: object) -> None:
        """외부 시그널 수신 → 전략의 on_data()로 전달.

        accepts_external_signals=False인 전략은 시그널을 무시한다.
        """
        from ante.eventbus.events import ExternalSignalEvent

        if not isinstance(event, ExternalSignalEvent):
            return
        if not self.strategy or event.bot_id != self.bot_id:
            return

        if not self.strategy.meta.accepts_external_signals:
            logger.warning(
                "외부 시그널 거부: 봇 %s 전략 %s — accepts_external_signals=False",
                self.bot_id,
                self.strategy.meta.name,
            )
            return

        follow_up = await self.strategy.on_data(
            {
                "signal_id": event.signal_id,
                "symbol": event.symbol,
                "action": event.action,
                "reason": event.reason,
                "confidence": event.confidence,
                "metadata": event.metadata,
                "timestamp": event.timestamp,
            }
        )
        await self._publish_signals(follow_up or [])

    async def _publish_signals(self, signals: list[Signal]) -> None:
        """Signal → OrderRequestEvent 변환 + EventBus 발행."""
        from ante.eventbus.events import OrderRequestEvent

        for signal in signals:
            await self._eventbus.publish(
                OrderRequestEvent(
                    bot_id=self.bot_id,
                    account_id=self.config.account_id,
                    strategy_id=self.config.strategy_id,
                    symbol=signal.symbol,
                    side=signal.side,
                    quantity=signal.quantity,
                    order_type=signal.order_type,
                    price=signal.price,
                    stop_price=signal.stop_price,
                    reason=signal.reason,
                    exchange=self.exchange,
                )
            )

    async def _publish_actions(self, actions: list[Any]) -> None:
        """OrderAction → EventBus 이벤트 변환."""
        from ante.eventbus.events import OrderCancelEvent, OrderModifyEvent

        for action in actions:
            if action.action == "cancel":
                await self._eventbus.publish(
                    OrderCancelEvent(
                        bot_id=self.bot_id,
                        account_id=self.config.account_id,
                        order_id=action.order_id,
                        reason=action.reason,
                    )
                )
            elif action.action == "modify":
                await self._eventbus.publish(
                    OrderModifyEvent(
                        bot_id=self.bot_id,
                        account_id=self.config.account_id,
                        order_id=action.order_id,
                        quantity=action.quantity or 0.0,
                        price=action.price,
                        reason=action.reason,
                    )
                )

    def get_info(self) -> dict[str, Any]:
        """봇 상태 정보 반환."""
        return {
            "bot_id": self.bot_id,
            "name": self.config.name,
            "status": self.status.value,
            "account_id": self.config.account_id,
            "strategy_id": self.config.strategy_id,
            "interval_seconds": self.config.interval_seconds,
            "started_at": (self.started_at.isoformat() if self.started_at else None),
            "stopped_at": (self.stopped_at.isoformat() if self.stopped_at else None),
            "error_message": self.error_message,
        }
