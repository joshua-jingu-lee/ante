"""Virtual 계좌 봇용 Provider 구현체 + VirtualExecutor.

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


class VirtualPortfolioView(PortfolioView):
    """Virtual 계좌 봇용 PortfolioView. 인메모리 가상 잔고/포지션 관리."""

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


class VirtualOrderView(OrderView):
    """Virtual 계좌 봇용 OrderView. VirtualPortfolioView의 미체결 주문 추적.

    #1948: VirtualExecutor 는 ``OrderApprovedEvent`` 를 즉시 가상 체결하고
    ``OrderSubmittedEvent`` 를 발행하지 않으므로(발행처는 live gateway 단독),
    virtual 주문은 OrderTracker 에 들어가지 않는다 → OrderTracker 백엔드 미사용.
    virtual 은 즉시 체결로 open window 가 사실상 없어
    ``_pending_orders`` (프로덕션 대개 빈)를 **통일 OpenOrder dict 스키마**로
    best-effort 매핑한다. amount(예약 금액)는 OrderView 스키마에서 제외한다.
    """

    def __init__(self, portfolio: VirtualPortfolioView) -> None:
        self._portfolio = portfolio

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회 (통일 OpenOrder dict 스키마)."""
        result: list[dict[str, Any]] = []
        for oid, info in self._portfolio._pending_orders.items():
            ordered_qty = float(info.get("ordered_qty", 0.0))
            recorded = float(info.get("recorded_filled_qty", 0.0))
            remaining = ordered_qty - recorded
            result.append(
                {
                    "order_id": oid,
                    "symbol": info.get("symbol", ""),
                    "side": info.get("side", ""),
                    "ordered_qty": ordered_qty,
                    "recorded_filled_qty": recorded,
                    "remaining_qty": remaining if remaining > 0 else 0.0,
                    "status": info.get("status", "open"),
                    "submitted_at": info.get("submitted_at"),
                }
            )
        return result


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
    ) -> None:
        self._eventbus = eventbus
        self._gateway = gateway
        self._commission_info = CommissionInfo(
            buy_commission_rate=commission_rate,
            sell_commission_rate=commission_rate + sell_tax_rate,
        )
        self._slippage_rate = slippage_rate
        self._portfolios: dict[str, VirtualPortfolioView] = {}
        self._bot_configs: dict[str, Any] = {}

    def register_bot(self, bot_id: str, portfolio: VirtualPortfolioView) -> None:
        """Virtual 계좌 봇의 PortfolioView 등록."""
        self._portfolios[bot_id] = portfolio
        logger.info("VirtualExecutor: 봇 등록 %s", bot_id)

    def unregister_bot(self, bot_id: str) -> None:
        """Virtual 계좌 봇 등록 해제."""
        self._portfolios.pop(bot_id, None)
        logger.info("VirtualExecutor: 봇 해제 %s", bot_id)

    def subscribe(self) -> None:
        """EventBus에 OrderApprovedEvent 구독."""
        from ante.eventbus.events import OrderApprovedEvent

        self._eventbus.subscribe(
            OrderApprovedEvent, self._on_order_approved, priority=50
        )
        logger.info("VirtualExecutor 구독 완료")

    async def _on_order_approved(self, event: object) -> None:
        """OrderApprovedEvent 처리. virtual 계좌 봇의 주문만 처리."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderFilledEvent,
        )

        if not isinstance(event, OrderApprovedEvent):
            return

        # 등록 단계의 stop / stop_limit 주문은 가상 체결하지 않는다.
        # StopOrderManager가 trigger 시 변환된 OrderRequestEvent를 발행하면
        # 그 변환 주문이 일반 limit/market로 다시 RuleEngine → Treasury →
        # OrderApprovedEvent 경로를 타고 들어와 정상 체결된다.
        if event.order_type in ("stop", "stop_limit"):
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
            # APIGateway.get_current_price 가 account_id 를 required 로 받으
            # 므로 OrderApprovedEvent.account_id 를 명시 전달.
            if self._gateway:
                try:
                    current_price = await self._gateway.get_current_price(
                        symbol, account_id=account_id
                    )
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

        # OrderFilledEvent 발행.
        #
        # #1949 fill_dedup_key 빈키 정책: VirtualProvider 는 가상 체결을 즉시 1회
        # 직접 발행하는 경로로, FillApplier/OrderTracker(CAS) 와 outbox 를 거치지
        # 않는다. 따라서 결정적 fill_dedup_key(= order_id:confirmed_cumulative)의
        # 산출 기반(CAS 확정 누적값)이 없다. at-least-once 재전달도 없으므로(outbox
        # 미경유, 단발 in-memory 발행) dedup 대상이 아니다 → fill_dedup_key 는
        # **빈키("")** 로 둔다. (default 이므로 명시 생략 가능하나, 정책을 코드로
        # 못박기 위해 명시한다.) 소비자(#1957)는 빈키를 "dedup 비대상" 으로 본다.
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
                timestamp=datetime.now(UTC),
                fill_dedup_key="",
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
