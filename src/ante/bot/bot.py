"""Bot — 전략을 실행하는 개별 봇."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ante.bot.config import BOT_STATUS_TRANSITIONS, BotConfig, BotStatus
from ante.bot.exceptions import BotError, BotStateConflict
from ante.core import clock
from ante.eventbus.fill_dedup_guard import FillDedupGuard

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.strategy.base import Signal, Strategy
    from ante.strategy.context import StrategyContext

logger = logging.getLogger(__name__)


def _transition_status(bot: Bot, target: BotStatus) -> BotStatus:
    if target not in BOT_STATUS_TRANSITIONS.get(bot.status, set()):
        raise BotStateConflict(
            f"봇 상태를 바꿀 수 없습니다: {bot.bot_id} "
            f"({bot.status.value} → {target.value})"
        )
    bot.status = target
    return target


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
        trading_mode: str = "",
        currency: str = "",
        signal_lock: asyncio.Lock | None = None,
    ) -> None:
        self.config = config
        self.bot_id = config.bot_id
        self.exchange = exchange
        self.trading_mode = trading_mode
        self.currency = currency
        self._strategy_cls = strategy_cls
        self._bound_strategy_id = config.strategy_id
        self._ctx = ctx
        self._eventbus = eventbus
        self._signal_lock = signal_lock or asyncio.Lock()

        self.status = BotStatus.CREATED
        self.strategy: Strategy | None = None
        self._task: asyncio.Task[None] | None = None
        self.started_at: datetime | None = None
        self.stopped_at: datetime | None = None
        self.error_message: str | None = None
        self._consecutive_failures: int = 0
        self._max_consecutive_failures: int = 3
        self._fill_dedup_guard = FillDedupGuard()
        self._generation: int = 0
        self._orders_closed: bool = False

    async def start(self) -> None:
        """봇 시작. 전략 인스턴스화 + 실행 루프 Task 생성."""
        from ante.eventbus.events import BotStartedEvent

        if self._bound_strategy_id != self.config.strategy_id:
            raise BotError(
                f"봇에 묶인 전략과 설정의 전략이 다릅니다: {self.bot_id} "
                f"(묶인 전략: {self._bound_strategy_id}, "
                f"설정: {self.config.strategy_id})"
            )
        self.strategy = self._strategy_cls(ctx=self._ctx)
        self.strategy.on_start()

        self._generation += 1
        self._orders_closed = False
        _transition_status(self, BotStatus.RUNNING)
        self.started_at = clock.now(UTC)
        self._task = asyncio.create_task(
            self._run_loop(),
            name=f"bot_{self.bot_id}",
        )

        await self._eventbus.publish(
            BotStartedEvent(bot_id=self.bot_id, account_id=self.config.account_id)
        )
        logger.info("봇 시작: %s", self.bot_id)

    def rebind_strategy(self, strategy_id: str, strategy_cls: type[Strategy]) -> None:
        """전략 클래스와 묶인 전략 ID를 함께 바꾸고 전략 인스턴스를 비운다."""
        if self.status in (BotStatus.RUNNING, BotStatus.STOPPING):
            raise BotStateConflict(
                f"실행 중인 봇의 전략은 바꿀 수 없습니다: {self.bot_id} "
                f"(현재: {self.status.value})"
            )
        self._strategy_cls = strategy_cls
        self._bound_strategy_id = strategy_id
        self.strategy = None

    async def stop(self) -> None:
        """봇 중지. 실행 루프 취소 + 전략 정리."""
        from ante.eventbus.events import BotStoppedEvent

        if self.status not in (BotStatus.RUNNING, BotStatus.ERROR):
            return

        _transition_status(self, BotStatus.STOPPING)
        self._orders_closed = True

        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

        if self.strategy:
            self.strategy.on_stop()

        _transition_status(self, BotStatus.STOPPED)
        self.stopped_at = clock.now(UTC)

        await self._eventbus.publish(
            BotStoppedEvent(bot_id=self.bot_id, account_id=self.config.account_id)
        )
        logger.info("봇 중지: %s", self.bot_id)

    async def _run_loop(self) -> None:
        """메인 실행 루프."""
        from ante.eventbus.events import BotErrorEvent, BotStepCompletedEvent

        generation = self._generation
        step_start: float | None = None
        try:
            while self.status == BotStatus.RUNNING and self._generation == generation:
                step_start = None
                should_sleep = False
                should_return = False
                step_context = {
                    "timestamp": clock.now(UTC),
                    "portfolio": self._ctx.get_positions(),
                    "balance": self._ctx.get_balance(),
                }

                async with self._signal_lock:
                    if (
                        self.status != BotStatus.RUNNING
                        or self._generation != generation
                    ):
                        should_return = True
                    else:
                        try:
                            step_start = clock.monotonic()
                            signals = await asyncio.wait_for(
                                self.strategy.on_step(step_context),  # type: ignore[union-attr]
                                timeout=self.config.step_timeout_seconds,
                            )
                            step_duration_ms = int(
                                (clock.monotonic() - step_start) * 1000
                            )
                        except TimeoutError:
                            assert step_start is not None
                            timeout_duration_ms = int(
                                (clock.monotonic() - step_start) * 1000
                            )
                            self._consecutive_failures += 1
                            timeout_msg = (
                                f"on_step timeout "
                                f"({self._consecutive_failures}/{self._max_consecutive_failures})"
                            )
                            logger.warning(
                                "on_step 타임아웃: %s (%d/%d)",
                                self.bot_id,
                                self._consecutive_failures,
                                self._max_consecutive_failures,
                            )
                            await self._eventbus.publish(
                                BotStepCompletedEvent(
                                    bot_id=self.bot_id,
                                    account_id=self.config.account_id,
                                    result="timeout",
                                    message=timeout_msg,
                                    signal_count=0,
                                    duration_ms=timeout_duration_ms,
                                )
                            )
                            if (
                                self._consecutive_failures
                                >= self._max_consecutive_failures
                            ):
                                msg = (
                                    f"연속 타임아웃 한도 초과 "
                                    f"({self._consecutive_failures}/{self._max_consecutive_failures})"
                                )
                                logger.error(
                                    "연속 타임아웃 한도 초과 — 봇 ERROR 전이: %s",
                                    self.bot_id,
                                )
                                _transition_status(self, BotStatus.ERROR)
                                self._orders_closed = True
                                self.error_message = msg
                                await self._eventbus.publish(
                                    BotErrorEvent(
                                        bot_id=self.bot_id,
                                        account_id=self.config.account_id,
                                        error_message=msg,
                                    )
                                )
                                should_return = True
                            else:
                                should_sleep = True
                        else:
                            max_signals = self.config.max_signals_per_step
                            if len(signals) > max_signals:
                                self._consecutive_failures += 1
                                overflow_msg = (
                                    "Signal count exceeded: "
                                    f"{len(signals)} > {max_signals}"
                                )
                                logger.warning(
                                    "Signal 수 초과: %s (%d > %d, 연속 %d/%d)",
                                    self.bot_id,
                                    len(signals),
                                    max_signals,
                                    self._consecutive_failures,
                                    self._max_consecutive_failures,
                                )
                                await self._eventbus.publish(
                                    BotStepCompletedEvent(
                                        bot_id=self.bot_id,
                                        account_id=self.config.account_id,
                                        result="signal_overflow",
                                        message=overflow_msg,
                                        signal_count=len(signals),
                                        duration_ms=step_duration_ms,
                                    )
                                )
                                await self._eventbus.publish(
                                    BotErrorEvent(
                                        bot_id=self.bot_id,
                                        account_id=self.config.account_id,
                                        error_message=overflow_msg,
                                    )
                                )
                                if (
                                    self._consecutive_failures
                                    >= self._max_consecutive_failures
                                ):
                                    logger.error(
                                        "연속 Signal 초과 한도 — 봇 중지: %s",
                                        self.bot_id,
                                    )
                                    await self.stop()
                                    should_return = True
                                else:
                                    should_sleep = True
                            else:
                                self._consecutive_failures = 0

                                await self._publish_signals(
                                    signals, generation=generation
                                )
                                if self._generation != generation:
                                    should_return = True
                                else:
                                    actions = self._ctx._drain_actions()
                                    await self._publish_actions(actions)

                                    await self._eventbus.publish(
                                        BotStepCompletedEvent(
                                            bot_id=self.bot_id,
                                            account_id=self.config.account_id,
                                            result="success",
                                            message=f"signals={len(signals)}",
                                            signal_count=len(signals),
                                            duration_ms=step_duration_ms,
                                        )
                                    )
                                    should_sleep = True

                if should_return:
                    return
                if should_sleep:
                    await asyncio.sleep(self.config.interval_seconds)
                    continue

        except asyncio.CancelledError:
            raise
        except Exception as e:
            if self._generation != generation:
                logger.warning(
                    "옛 세대 루프 예외 무시: 봇 %s 세대 %d → %d — %s",
                    self.bot_id,
                    generation,
                    self._generation,
                    e,
                    exc_info=True,
                )
                return
            if self.status in (BotStatus.STOPPED, BotStatus.DELETED):
                logger.warning(
                    "루프 예외 무시: 봇 %s 상태 %s (정지 완료) — %s",
                    self.bot_id,
                    self.status.value,
                    e,
                    exc_info=True,
                )
                return
            _transition_status(self, BotStatus.ERROR)
            self._orders_closed = True
            self.error_message = str(e)
            logger.exception("봇 오류: %s", self.bot_id)
            await self._eventbus.publish(
                BotStepCompletedEvent(
                    bot_id=self.bot_id,
                    account_id=self.config.account_id,
                    result="error",
                    message=str(e),
                    signal_count=0,
                    duration_ms=(
                        int((clock.monotonic() - step_start) * 1000)
                        if step_start is not None
                        else 0
                    ),
                )
            )
            await self._eventbus.publish(
                BotErrorEvent(
                    bot_id=self.bot_id,
                    account_id=self.config.account_id,
                    error_message=str(e),
                )
            )

    async def on_order_filled(self, event: object) -> None:
        """체결 통보를 전략에 전달.

        outbox at-least-once 재전달 시 같은 fill 의 전략 follow-up 이
        이중 발행되지 않도록 bounded dedup 한다. 비빈키 ``fill_dedup_key`` 가
        이미 처리됐으면 follow-up 을 skip(early-return). 빈키(VirtualProvider
        직접발행 등 재전달 없는 단발 경로)는 가드 비대상으로 항상 처리한다.
        ``fill_dedup_key`` 를 ``strategy.on_fill`` dict 로 전달해 전략이 자체
        dedup 할 수 있게 한다(보장은 사용자 코드 책임 = known-limitation).
        """
        from ante.eventbus.events import OrderFilledEvent

        if not isinstance(event, OrderFilledEvent):
            return
        if not self.strategy or event.bot_id != self.bot_id:
            return

        if event.fill_dedup_key and self._fill_dedup_guard.seen_or_add(
            event.fill_dedup_key
        ):
            return

        follow_up = await self.strategy.on_fill(
            {
                "order_id": event.order_id,
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "price": event.price,
                "timestamp": event.timestamp,
                "fill_dedup_key": event.fill_dedup_key,
            }
        )
        await self._publish_signals(follow_up or [], generation=None)

    async def on_order_update(self, event: object) -> None:
        """주문 상태 변경 통보를 전략에 전달."""
        from ante.eventbus.events import (
            OrderCancelFailedEvent,
            OrderCancelledEvent,
            OrderFailedEvent,
            OrderModifyExecutedEvent,
            OrderModifyRejectedEvent,
            OrderRejectedEvent,
            OrderSubmittedEvent,
            StopOrderExpiredEvent,
            StopOrderRegisteredEvent,
            StopOrderTriggeredEvent,
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
                "symbol": event.symbol,
                "side": event.side,
                "reason": event.error_message,
            }
        elif isinstance(event, OrderModifyExecutedEvent):
            update = {
                "order_id": event.order_id,
                "status": "modified",
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "reason": event.reason,
            }
        elif isinstance(event, OrderModifyRejectedEvent):
            update = {
                "order_id": event.order_id,
                "status": "modify_rejected",
                "symbol": event.symbol,
                "side": event.side,
                "reason": event.reason,
            }
        elif isinstance(event, StopOrderRegisteredEvent):
            update = {
                "order_id": event.stop_order_id,
                "stop_order_id": event.stop_order_id,
                "status": "stop_registered",
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "stop_price": event.stop_price,
                "limit_price": event.limit_price,
            }
        elif isinstance(event, StopOrderTriggeredEvent):
            update = {
                "order_id": event.stop_order_id,
                "stop_order_id": event.stop_order_id,
                "status": "stop_triggered",
                "symbol": event.symbol,
                "side": event.side,
                "quantity": event.quantity,
                "trigger_price": event.trigger_price,
                "converted_order_type": event.converted_order_type,
            }
        elif isinstance(event, StopOrderExpiredEvent):
            update = {
                "order_id": event.stop_order_id,
                "stop_order_id": event.stop_order_id,
                "status": "stop_expired",
                "symbol": event.symbol,
                "reason": event.reason,
            }

        if update:
            await self.strategy.on_order_update(update)

    async def on_external_signal(self, event: object) -> None:
        """외부 시그널 수신 → 전략의 on_data()로 전달.

        accepts_external_signals=False인 전략은 시그널을 무시한다.

        **non-reentrancy 감사(asyncio.Lock 은 non-reentrant)**: lock 보유 중
        ``_publish_signals`` 가 publish 하는 ``OrderRequestEvent`` 의 핸들러가
        동일 bot ``ExternalSignalEvent`` 를 재발행하지 않는다(재발행하면
        deadlock). ``ExternalSignalEvent`` 는 ``SignalChannel._handle_signal``
        에서만 publish 된다(grep invariant).
        """
        from ante.eventbus.events import ExternalSignalEvent

        if not isinstance(event, ExternalSignalEvent):
            return
        generation = self._generation
        if not self.strategy or event.bot_id != self.bot_id:
            return

        if not self.strategy.meta.accepts_external_signals:
            logger.warning(
                "외부 시그널 거부: 봇 %s 전략 %s — accepts_external_signals=False"
                " signal_id=%s",
                self.bot_id,
                self.strategy.meta.name,
                event.signal_id,
            )
            return

        if self.status != BotStatus.RUNNING:
            logger.warning(
                "외부 시그널 거부: 봇 %s 상태 %s (RUNNING 아님) signal_id=%s",
                self.bot_id,
                self.status.value,
                event.signal_id,
            )
            return

        async with self._signal_lock:
            if self.status != BotStatus.RUNNING:
                logger.warning(
                    "외부 시그널 거부: 봇 %s 상태 %s (잠금 대기 중 RUNNING 이탈)"
                    " signal_id=%s",
                    self.bot_id,
                    self.status.value,
                    event.signal_id,
                )
                return
            if self._generation != generation:
                logger.warning(
                    "외부 시그널 거부: 봇 %s 세대 %d → %d (잠금 대기 중 재시작)"
                    " signal_id=%s",
                    self.bot_id,
                    generation,
                    self._generation,
                    event.signal_id,
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
            await self._publish_signals(follow_up or [], generation=generation)

    async def _publish_signals(
        self, signals: list[Signal], *, generation: int | None
    ) -> None:
        """Signal → OrderRequestEvent 변환 + EventBus 발행."""
        from ante.eventbus.events import OrderRequestEvent

        for index, signal in enumerate(signals):
            if generation is not None and (
                self._orders_closed or self._generation != generation
            ):
                logger.warning(
                    "주문 요청 버림: 봇 %s 시그널 %d건 (주문 닫힘 %s, 세대 %d → %d)",
                    self.bot_id,
                    len(signals) - index,
                    self._orders_closed,
                    generation,
                    self._generation,
                )
                return
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
                        strategy_id=self.config.strategy_id,
                        order_id=action.order_id,
                        reason=action.reason,
                    )
                )
            elif action.action == "modify":
                await self._eventbus.publish(
                    OrderModifyEvent(
                        bot_id=self.bot_id,
                        account_id=self.config.account_id,
                        strategy_id=self.config.strategy_id,
                        order_id=action.order_id,
                        quantity=action.quantity or 0.0,
                        price=action.price,
                        reason=action.reason,
                    )
                )

    def get_info(self) -> dict[str, Any]:
        """봇 상태 정보 반환.

        ``config`` nested object 는 ``BotConfig`` 의 runtime control 6 필드
        (SSOT: ``src/ante/bot/config.py``) 를 상세 조회 prefill 용도로
        노출한다. top-level ``interval_seconds`` 는 backward compatibility
        용으로 유지된다 (기존 list/detail 호출자의 flat key 의존성). 다른
        runtime control 필드는 top-level 에 추가하지 않는다 (계약 중복
        방지).
        """
        return {
            "bot_id": self.bot_id,
            "name": self.config.name,
            "status": self.status.value,
            "account_id": self.config.account_id,
            "strategy_id": self.config.strategy_id,
            "interval_seconds": self.config.interval_seconds,
            "trading_mode": self.trading_mode,
            "exchange": self.exchange,
            "currency": self.currency,
            "started_at": (self.started_at.isoformat() if self.started_at else None),
            "stopped_at": (self.stopped_at.isoformat() if self.stopped_at else None),
            "error_message": self.error_message,
            "config": {
                "interval_seconds": self.config.interval_seconds,
                "auto_restart": self.config.auto_restart,
                "max_restart_attempts": self.config.max_restart_attempts,
                "restart_cooldown_seconds": self.config.restart_cooldown_seconds,
                "step_timeout_seconds": self.config.step_timeout_seconds,
                "max_signals_per_step": self.config.max_signals_per_step,
            },
        }
