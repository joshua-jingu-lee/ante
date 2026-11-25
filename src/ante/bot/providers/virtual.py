"""Virtual 계좌 봇용 Provider 구현체 + VirtualExecutor."""

from __future__ import annotations

import logging
import math
from datetime import UTC
from typing import TYPE_CHECKING, Any

from ante.bot.providers.live import LivePortfolioView
from ante.broker.models import CommissionInfo
from ante.core import clock
from ante.strategy.base import OrderView

if TYPE_CHECKING:
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.gateway.gateway import APIGateway
    from ante.trade.fill_applier import FillApplier

logger = logging.getLogger(__name__)


def _is_valid_market_price(x: object) -> bool:
    """불리언이 아닌 유한한 수이고 0보다 큰지 — 예외 무전파."""
    if isinstance(x, bool) or not isinstance(x, int | float):
        return False
    try:
        return math.isfinite(x) and x > 0
    except (OverflowError, TypeError, ValueError):
        return False


class VirtualPortfolioView(LivePortfolioView):
    """Virtual 계좌 봇용 PortfolioView. live 와 같이 Treasury + Trade 경유.

    가상 체결도 ``FillApplier.apply_direct_fill`` 이 positions 표에, Treasury 가
    봇 예산에 정산하므로 재시작·재조립 뒤에도 같은 값을 본다.
    """


class VirtualOrderView(OrderView):
    """Virtual 계좌 봇용 OrderView. 가상 주문은 즉시 체결되므로 늘 빈 목록."""

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회 (즉시 체결이라 늘 빈 목록)."""
        return []


class VirtualExecutor:
    """Virtual 계좌 봇의 주문을 가상 체결하는 실행기.

    EventBus에서 OrderApprovedEvent를 구독하여 virtual 계좌 봇의 주문만 처리한다.
    RuleEngine → Treasury 파이프라인을 거친 승인된 주문만 체결한다.
    """

    def __init__(
        self,
        eventbus: EventBus,
        gateway: APIGateway | None = None,
        commission_rate: float = 0.00015,
        sell_tax_rate: float = 0.0023,
        slippage_rate: float = 0.0,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
        account_service: AccountService | None = None,
        fill_applier: FillApplier | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._gateway = gateway
        self._commission_info = CommissionInfo(
            buy_commission_rate=commission_rate,
            sell_commission_rate=commission_rate + sell_tax_rate,
        )
        self._slippage_rate = slippage_rate
        self._bot_ids: set[str] = set()
        self._bot_configs: dict[str, Any] = {}
        self._runtime_readiness = runtime_readiness
        self._account_service = account_service
        self._fill_applier = fill_applier

    def register_bot(self, bot_id: str) -> None:
        """Virtual 계좌 봇을 체결 대상으로 등록."""
        self._bot_ids.add(bot_id)
        logger.info("VirtualExecutor: 봇 등록 %s", bot_id)

    def unregister_bot(self, bot_id: str) -> None:
        """Virtual 계좌 봇 등록 해제."""
        self._bot_ids.discard(bot_id)
        logger.info("VirtualExecutor: 봇 해제 %s", bot_id)

    _ORDER_APPROVED_PRIORITY = 60

    def subscribe(self) -> None:
        """EventBus에 OrderApprovedEvent 구독.

        priority 는 ``_ORDER_APPROVED_PRIORITY``(=60)로 APIGateway(=50)보다
        높게 둔다 — 구독 삽입 순서와 무관하게 gateway 보다 먼저 실행돼
        ``_virtual_handled`` 마커를 set 한다(위 invariant 주석 참조).
        """
        from ante.eventbus.events import OrderApprovedEvent

        self._eventbus.subscribe(
            OrderApprovedEvent,
            self._on_order_approved,
            priority=self._ORDER_APPROVED_PRIORITY,
        )
        logger.info("VirtualExecutor 구독 완료")

    async def _gate_blocked_reason(self, account_id: str) -> str | None:
        """G9 + G7 backstop — virtual 경로 최종 차단 사유 토큰(fail-closed)."""
        from ante.account.gate import (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
            ACCOUNT_SUSPENDED_REASON,
            STATUS_UNAVAILABLE,
            active_trading_blocked,
            derive_account_status,
        )
        from ante.account.models import AccountStatus

        if self._runtime_readiness is None or self._account_service is None:
            return ACCOUNT_NOT_READY_REASON

        fetched: Any | None = None
        fetch_failed = False
        try:
            fetched = await self._account_service.get(account_id)
        except Exception:
            fetch_failed = True

        status = derive_account_status(
            self._account_service, fetched, fetch_failed=fetch_failed
        )
        if status == AccountStatus.SUSPENDED:
            return ACCOUNT_SUSPENDED_REASON
        if status is STATUS_UNAVAILABLE:
            return ACCOUNT_STATUS_UNAVAILABLE_REASON

        broker_type = getattr(fetched, "broker_type", None)
        trading_mode = getattr(fetched, "trading_mode", None)
        if not isinstance(broker_type, str) or trading_mode is None:
            return ACCOUNT_NOT_READY_REASON
        if active_trading_blocked(
            self._runtime_readiness,
            account_id,
            broker_type=broker_type,
            trading_mode=trading_mode,
        ):
            return ACCOUNT_NOT_READY_REASON
        return None

    async def _fail_order(self, event: Any, *, error_message: str) -> None:
        """virtual 주문을 OrderFailedEvent 로 종결한다(fill 금지)."""
        from ante.account.gate import (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
            ACCOUNT_SUSPENDED_REASON,
            build_not_ready_notification,
            is_liquidation_reason,
        )
        from ante.eventbus.events import OrderFailedEvent

        gate_reasons = (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_SUSPENDED_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
        )
        is_gate_block = error_message in gate_reasons
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
                error_message=error_message,
                error_code=(error_message if is_gate_block else ""),
                exchange=event.exchange,
            )
        )
        if is_gate_block:
            await self._eventbus.publish(
                build_not_ready_notification(
                    account_id=event.account_id,
                    reason=error_message,
                    side=getattr(event, "side", ""),
                    is_liquidation=is_liquidation_reason(getattr(event, "reason", "")),
                )
            )

    async def _on_order_approved(self, event: object) -> None:
        """OrderApprovedEvent 처리. virtual 계좌 봇의 주문만 처리."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderFilledEvent,
        )

        if not isinstance(event, OrderApprovedEvent):
            return

        if event.order_type in ("stop", "stop_limit"):
            return

        if event.bot_id not in self._bot_ids:
            return

        object.__setattr__(event, "_virtual_handled", True)

        order_id = event.order_id
        account_id = event.account_id
        symbol = event.symbol
        side = event.side
        quantity = event.quantity
        order_type = event.order_type

        blocked_reason = await self._gate_blocked_reason(account_id)
        if blocked_reason is not None:
            await self._fail_order(event, error_message=blocked_reason)
            return

        if order_type == "limit" and event.price is not None:
            fill_price = event.price
        else:
            current_price: float | None = None
            if self._gateway:
                try:
                    current_price = await self._gateway.get_current_price(
                        symbol, account_id=account_id
                    )
                except Exception:
                    logger.warning("현재가 조회 실패: %s — 주문 실패 종결", symbol)
                    current_price = None
            elif event.price is not None:
                current_price = event.price

            if current_price is None or not _is_valid_market_price(current_price):
                logger.error(
                    "Virtual 시장가 체결가 미상 — 0원 체결 금지, 주문 실패 종결 "
                    "(order_id=%s, symbol=%s)",
                    order_id,
                    symbol,
                )
                await self._fail_order(
                    event, error_message="virtual_market_price_unavailable"
                )
                return

            if self._slippage_rate > 0:
                if side == "buy":
                    fill_price = current_price * (1 + self._slippage_rate)
                else:
                    fill_price = current_price * (1 - self._slippage_rate)
            else:
                fill_price = current_price

        trade_amount = fill_price * quantity
        commission = self._commission_info.calculate(side, trade_amount)
        filled_at = clock.now(UTC)

        if self._fill_applier is None:
            logger.warning(
                "VirtualExecutor: fill_applier 미주입 — 가상 체결을 trades·positions에 "
                "기록하지 않는다 (order_id=%s)",
                order_id,
            )
        else:
            try:
                recorded = await self._fill_applier.apply_direct_fill(
                    account_id=account_id,
                    order_id=order_id,
                    bot_id=event.bot_id,
                    strategy_id=event.strategy_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    price=fill_price,
                    commission=commission,
                    order_type=order_type,
                    exchange=event.exchange,
                    timestamp=filled_at,
                )
            except self._fill_applier.InsufficientHoldingsError:
                logger.warning(
                    "Virtual 매도 보유 초과 — 주문 실패 종결 (order_id=%s)", order_id
                )
                await self._fail_order(
                    event, error_message="virtual_insufficient_holdings"
                )
                return
            except Exception:
                logger.exception(
                    "Virtual 체결 기록 실패 — 주문 실패 종결 (order_id=%s)", order_id
                )
                await self._fail_order(
                    event, error_message="virtual_fill_record_failed"
                )
                return
            if not recorded:
                logger.warning(
                    "Virtual 체결 중복 — 발행 생략 (order_id=%s)",
                    order_id,
                )
                return

        await self._eventbus.publish(
            OrderFilledEvent(
                order_id=order_id,
                broker_order_id=f"virtual-{order_id[:8]}",
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                account_id=account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                order_type=order_type,
                timestamp=filled_at,
                fill_dedup_key="",
                exchange=event.exchange,
            )
        )
        logger.info(
            "Virtual 체결: %s %s %s qty=%s price=%s commission=%s",
            event.bot_id,
            side,
            symbol,
            quantity,
            fill_price,
            commission,
        )
