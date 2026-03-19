"""Mock Broker Adapter — E2E 테스트용 가상 브로커.

외부 API 없이 주문 → 체결 → 잔고 변동 흐름을 시뮬레이션한다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from ante.broker.base import BrokerAdapter
from ante.broker.exceptions import BrokerError, OrderNotFoundError
from ante.broker.models import CommissionInfo

logger = logging.getLogger(__name__)


# ── 시뮬레이션 모드 ─────────────────────────────────────


class FillMode(StrEnum):
    """체결 시뮬레이션 모드."""

    IMMEDIATE = "immediate"  # 즉시 전량 체결
    PARTIAL = "partial"  # 부분 체결
    DELAYED = "delayed"  # 지연 체결
    REJECT = "reject"  # 주문 거부


@dataclass
class MockPosition:
    """메모리 기반 가상 포지션."""

    symbol: str
    quantity: float
    avg_price: float


@dataclass
class MockOrder:
    """Mock 주문 기록."""

    order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    price: float
    order_type: str
    status: str  # "pending" | "filled" | "partially_filled" | "cancelled" | "rejected"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class MockBrokerAdapter(BrokerAdapter):
    """E2E 테스트용 가상 브로커 어댑터.

    Note: BrokerAdapter 인터페이스 준수를 위해 async def를 유지한다.
    내부적으로 await를 사용하지 않지만, 호출부에서 await로 사용된다.

    설정 옵션:
        fill_mode: "immediate" | "partial" | "delayed" | "reject"
        partial_fill_ratio: 부분 체결 비율 (0.0~1.0, 기본 0.5)
        delay_seconds: 지연 체결 시 대기 시간 (기본 0.1)
        initial_cash: 초기 현금 (기본 100_000_000)
        default_price: 종목 기본 현재가 (기본 50_000)
        prices: 종목별 현재가 딕셔너리 (예: {"005930": 70000})
    """

    broker_id: str = "mock"
    broker_name: str = "모의 브로커"
    broker_short_name: str = "MOCK"

    def __init__(self, config: dict[str, Any]) -> None:
        config.setdefault("exchange", "KRX")
        super().__init__(config)

        self._fill_mode = FillMode(config.get("fill_mode", "immediate"))
        self._partial_fill_ratio: float = config.get("partial_fill_ratio", 0.5)
        self._delay_seconds: float = config.get("delay_seconds", 0.1)

        # 가상 잔고
        self._cash: float = config.get("initial_cash", 100_000_000.0)
        self._positions: dict[str, MockPosition] = {}
        self._orders: dict[str, MockOrder] = {}

        # 종목별 현재가
        self._prices: dict[str, float] = config.get("prices", {})
        self._default_price: float = config.get("default_price", 50_000.0)

        self._commission = CommissionInfo(
            commission_rate=config.get("commission_rate", 0.00015),
            sell_tax_rate=config.get("sell_tax_rate", 0.0023),
        )

    # ── 연결 ──────────────────────────────────────────

    async def connect(self) -> None:
        """Mock 연결 (항상 성공)."""
        self.is_connected = True
        logger.info("Mock Broker 연결됨")

    async def disconnect(self) -> None:
        """Mock 연결 해제."""
        self.is_connected = False
        logger.info("Mock Broker 연결 해제")

    # ── 조회 ──────────────────────────────────────────

    async def get_account_balance(self) -> dict[str, float]:
        """가상 계좌 잔고 조회."""
        total_stock_value = sum(
            pos.quantity * self._get_price(pos.symbol)
            for pos in self._positions.values()
        )
        return {
            "cash": self._cash,
            "total_assets": self._cash + total_stock_value,
            "stock_value": total_stock_value,
        }

    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회."""
        return [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": self._get_price(pos.symbol),
                "pnl": (self._get_price(pos.symbol) - pos.avg_price) * pos.quantity,
            }
            for pos in self._positions.values()
            if pos.quantity > 0
        ]

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회."""
        return self._get_price(symbol)

    # ── 주문 ──────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수 및 시뮬레이션 체결."""
        if self._fill_mode == FillMode.REJECT:
            msg = f"Mock 주문 거부: {symbol} {side} {quantity}"
            raise BrokerError(msg)

        order_id = str(uuid.uuid4())[:8]
        exec_price = price if price is not None else self._get_price(symbol)

        order = MockOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            quantity=quantity,
            filled_quantity=0.0,
            price=exec_price,
            order_type=order_type,
            status="pending",
        )
        self._orders[order_id] = order

        if self._fill_mode == FillMode.DELAYED:
            await asyncio.sleep(self._delay_seconds)

        fill_qty = self._calculate_fill_quantity(quantity)
        self._execute_fill(order, fill_qty, exec_price)

        logger.info(
            "Mock 주문 체결: %s %s %s qty=%.1f filled=%.1f @ %.0f",
            order_id,
            side,
            symbol,
            quantity,
            fill_qty,
            exec_price,
        )
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소."""
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"주문을 찾을 수 없음: {order_id}")
        if order.status in ("filled", "cancelled", "rejected"):
            return False
        order.status = "cancelled"
        return True

    async def get_order_status(self, order_id: str) -> dict[str, Any]:
        """주문 상태 조회."""
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"주문을 찾을 수 없음: {order_id}")
        return {
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "filled_quantity": order.filled_quantity,
            "price": order.price,
            "order_type": order.order_type,
            "status": order.status,
            "created_at": order.created_at.isoformat(),
        }

    async def get_pending_orders(self) -> list[dict[str, Any]]:
        """미체결 주문 목록."""
        results = []
        for order in self._orders.values():
            if order.status in ("pending", "partially_filled"):
                results.append(await self.get_order_status(order.order_id))
        return results

    # ── 대사(Reconciliation) 조회 ─────────────────────

    async def get_account_positions(self) -> list[dict[str, Any]]:
        """증권사 실제 보유 잔고 (대사용)."""
        return await self.get_positions()

    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회."""
        results = []
        for order in self._orders.values():
            results.append(
                {
                    "order_id": order.order_id,
                    "symbol": order.symbol,
                    "side": order.side,
                    "quantity": order.quantity,
                    "filled_quantity": order.filled_quantity,
                    "price": order.price,
                    "status": order.status,
                    "timestamp": order.created_at.isoformat(),
                }
            )
        return results

    # ── 종목 마스터 ───────────────────────────────────

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """Mock 종목 마스터."""
        return [
            {
                "symbol": "005930",
                "name": "삼성전자",
                "name_en": "Samsung Electronics",
                "instrument_type": "stock",
                "listed": True,
            },
            {
                "symbol": "000660",
                "name": "SK하이닉스",
                "name_en": "SK Hynix",
                "instrument_type": "stock",
                "listed": True,
            },
        ]

    # ── 수수료 ────────────────────────────────────────

    def get_commission_info(self) -> CommissionInfo:
        """수수료율 정보."""
        return self._commission

    # ── 내부 헬퍼 ─────────────────────────────────────

    def _get_price(self, symbol: str) -> float:
        """종목 현재가 반환."""
        return self._prices.get(symbol, self._default_price)

    def set_price(self, symbol: str, price: float) -> None:
        """테스트용: 종목 현재가 설정."""
        self._prices[symbol] = price

    def set_fill_mode(self, mode: FillMode) -> None:
        """테스트용: 체결 모드 변경."""
        self._fill_mode = mode

    def _calculate_fill_quantity(self, quantity: float) -> float:
        """체결 모드에 따른 체결 수량 계산."""
        if self._fill_mode == FillMode.PARTIAL:
            return quantity * self._partial_fill_ratio
        return quantity  # IMMEDIATE, DELAYED

    def _execute_fill(
        self, order: MockOrder, fill_qty: float, exec_price: float
    ) -> None:
        """체결 처리: 잔고 및 포지션 업데이트."""
        order.filled_quantity = fill_qty
        filled_value = fill_qty * exec_price
        commission = self._commission.calculate(order.side, filled_value)

        if order.side == "buy":
            self._cash -= filled_value + commission
            self._update_position_buy(order.symbol, fill_qty, exec_price)
        else:  # sell
            self._cash += filled_value - commission
            self._update_position_sell(order.symbol, fill_qty)

        if fill_qty >= order.quantity:
            order.status = "filled"
        else:
            order.status = "partially_filled"

    def _update_position_buy(self, symbol: str, quantity: float, price: float) -> None:
        """매수 시 포지션 업데이트."""
        pos = self._positions.get(symbol)
        if pos is None:
            self._positions[symbol] = MockPosition(
                symbol=symbol, quantity=quantity, avg_price=price
            )
        else:
            total_qty = pos.quantity + quantity
            pos.avg_price = (
                pos.avg_price * pos.quantity + price * quantity
            ) / total_qty
            pos.quantity = total_qty

    def _update_position_sell(self, symbol: str, quantity: float) -> None:
        """매도 시 포지션 업데이트."""
        pos = self._positions.get(symbol)
        if pos is None:
            msg = f"매도할 포지션 없음: {symbol}"
            raise BrokerError(msg)
        if pos.quantity < quantity:
            msg = f"보유 수량 부족: {symbol} (보유: {pos.quantity}, 매도: {quantity})"
            raise BrokerError(msg)
        pos.quantity -= quantity
