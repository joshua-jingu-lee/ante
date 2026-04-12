"""Paper 봇용 Provider 구현체 + PaperExecutor.

인메모리 가상 자금/포지션으로 실제 계좌 영향 없이 전략을 검증한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ante.broker.models import CommissionInfo
from ante.strategy.base import OrderView, PortfolioView

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.gateway.gateway import APIGateway

logger = logging.getLogger(__name__)


class PaperPortfolioView(PortfolioView):
    """Paper 봇용 PortfolioView. 인메모리 가상 잔고/포지션 관리."""

    def __init__(self, bot_id: str, initial_balance: float) -> None:
        self._bot_id = bot_id
        self._initial_balance = initial_balance
        self._balance = initial_balance
        self._reserved: float = 0.0
        self._positions: dict[str, dict[str, Any]] = {}
        self._pending_orders: dict[str, dict[str, Any]] = {}

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """현재 보유 포지션 조회."""
        return {
            symbol: dict(pos)
            for symbol, pos in self._positions.items()
            if pos["quantity"] > 0
        }

    def get_balance(self, bot_id: str) -> dict[str, float]:
        """가상 자금 현황 조회."""
        return {
            "allocated": self._initial_balance,
            "available": self._balance - self._reserved,
            "reserved": self._reserved,
        }

    def apply_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float,
    ) -> None:
        """가상 체결 결과를 포지션/잔고에 반영."""
        pos = self._positions.get(
            symbol,
            {
                "symbol": symbol,
                "quantity": 0.0,
                "avg_entry_price": 0.0,
                "realized_pnl": 0.0,
            },
        )

        if side == "buy":
            total_cost = pos["avg_entry_price"] * pos["quantity"]
            new_cost = price * quantity
            new_qty = pos["quantity"] + quantity
            new_avg = (total_cost + new_cost) / new_qty if new_qty > 0 else 0.0

            pos["quantity"] = new_qty
            pos["avg_entry_price"] = new_avg
            self._balance -= price * quantity + commission

        elif side == "sell":
            pnl = (price - pos["avg_entry_price"]) * quantity - commission
            new_qty = pos["quantity"] - quantity

            pos["quantity"] = max(new_qty, 0.0)
            if new_qty <= 0:
                pos["avg_entry_price"] = 0.0
            pos["realized_pnl"] += pnl
            self._balance += price * quantity - commission

        self._positions[symbol] = pos

    def check_balance(self, amount: float) -> bool:
        """잔고 충분 여부 확인."""
        return (self._balance - self._reserved) >= amount

    def reserve(self, order_id: str, amount: float) -> None:
        """주문용 자금 예약."""
        self._reserved += amount
        self._pending_orders[order_id] = {"amount": amount}

    def release_reservation(self, order_id: str) -> None:
        """예약 해제."""
        order = self._pending_orders.pop(order_id, None)
        if order:
            self._reserved -= order["amount"]


class PaperOrderView(OrderView):
    """Paper 봇용 OrderView. PaperPortfolioView의 미체결 주문 추적."""

    def __init__(self, portfolio: PaperPortfolioView) -> None:
        self._portfolio = portfolio

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회."""
        return [
            {"order_id": oid, **info}
            for oid, info in self._portfolio._pending_orders.items()
        ]


class PaperExecutor:
    """Paper 봇의 주문을 가상 체결하는 실행기.

    EventBus에서 OrderApprovedEvent를 구독하여 paper 봇의 주문만 처리한다.
    RuleEngine → Treasury 파이프라인을 거친 승인된 주문만 체결한다.
    """

    def __init__(
        self,
        eventbus: EventBus,
        gateway: APIGateway | None = None,
        commission_rate: float = 0.00015,
        sell_tax_rate: float = 0.0023,
        slippage_rate: float = 0.0,
    ) -> None:
        self._eventbus = eventbus
        self._gateway = gateway
        self._commission_info = CommissionInfo(
            buy_commission_rate=commission_rate,
            sell_commission_rate=commission_rate + sell_tax_rate,
        )
        self._slippage_rate = slippage_rate
        self._portfolios: dict[str, PaperPortfolioView] = {}
        self._bot_configs: dict[str, Any] = {}

    def register_bot(self, bot_id: str, portfolio: PaperPortfolioView) -> None:
        """Paper 봇의 PortfolioView 등록."""
        self._portfolios[bot_id] = portfolio
        logger.info("PaperExecutor: 봇 등록 %s", bot_id)

    def unregister_bot(self, bot_id: str) -> None:
        """Paper 봇 등록 해제."""
        self._portfolios.pop(bot_id, None)
        logger.info("PaperExecutor: 봇 해제 %s", bot_id)

    def subscribe(self) -> None:
        """EventBus에 OrderApprovedEvent 구독."""
        from ante.eventbus.events import OrderApprovedEvent

        self._eventbus.subscribe(
            OrderApprovedEvent, self._on_order_approved, priority=50
        )
        logger.info("PaperExecutor 구독 완료")

    async def _on_order_approved(self, event: object) -> None:
        """OrderApprovedEvent 처리. paper 봇의 주문만 처리."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderFilledEvent,
        )

        if not isinstance(event, OrderApprovedEvent):
            return

        portfolio = self._portfolios.get(event.bot_id)
        if portfolio is None:
            return  # live 봇의 주문 → 무시 (APIGateway가 처리)

        order_id = event.order_id
        account_id = event.account_id
        symbol = event.symbol
        side = event.side
        quantity = event.quantity
        order_type = event.order_type

        # 체결가 계산
        if order_type == "limit" and event.price is not None:
            fill_price = event.price
        else:
            # market 주문: 현재가 기반 + 슬리피지
            if self._gateway:
                try:
                    current_price = await self._gateway.get_current_price(symbol)
                except Exception:
                    logger.warning("현재가 조회 실패: %s, 기본가 사용", symbol)
                    current_price = event.price or 0.0
            else:
                current_price = event.price or 0.0

            if self._slippage_rate > 0:
                if side == "buy":
                    fill_price = current_price * (1 + self._slippage_rate)
                else:
                    fill_price = current_price * (1 - self._slippage_rate)
            else:
                fill_price = current_price

        # 수수료 계산
        trade_amount = fill_price * quantity
        commission = self._commission_info.calculate(side, trade_amount)

        # 가상 체결: 포지션/잔고 업데이트
        portfolio.apply_fill(symbol, side, quantity, fill_price, commission)

        # OrderFilledEvent 발행
        await self._eventbus.publish(
            OrderFilledEvent(
                order_id=order_id,
                broker_order_id=f"paper-{order_id[:8]}",
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                account_id=account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                order_type=order_type,
                timestamp=datetime.now(UTC),
            )
        )
        logger.info(
            "Paper 체결: %s %s %s qty=%s price=%s commission=%s",
            event.bot_id,
            side,
            symbol,
            quantity,
            fill_price,
            commission,
        )
