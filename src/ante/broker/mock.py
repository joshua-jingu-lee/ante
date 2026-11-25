"""Mock Broker Adapter — E2E 테스트용 가상 브로커."""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, NoReturn

from ante.broker.base import BrokerAdapter, ensure_order_side
from ante.broker.exceptions import BrokerError, OrderNotFoundError
from ante.broker.models import CommissionInfo
from ante.core import clock
from ante.core.price import is_valid_price

logger = logging.getLogger(__name__)

_PRICES_FILE_KEYS = frozenset({"prices", "default_price"})


def _valid_delay_polls(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise BrokerError(f"delay_polls는 1 이상의 정수여야 함: {value!r}")
    return value


def _reject_json_constant(name: str) -> NoReturn:
    raise ValueError(f"허용하지 않는 JSON 상수: {name}")


def _valid_price(value: object, where: str, prices_file: str) -> float:
    if not is_valid_price(value):
        raise BrokerError(
            f"Mock 가격 파일의 {where} 값은 0보다 큰 유한한 수여야 함: "
            f"{value!r} ({prices_file})"
        )
    return float(value)


def _load_prices_file(config: dict[str, Any]) -> tuple[dict[str, float], float | None]:
    conflicting = sorted(_PRICES_FILE_KEYS & config.keys())
    if conflicting:
        raise BrokerError(
            f"prices_file과 {conflicting}를 함께 줄 수 없음. 가격은 파일에만 둔다"
        )
    prices_file = config["prices_file"]
    if not isinstance(prices_file, str) or not Path(prices_file).is_absolute():
        raise BrokerError(f"prices_file은 절대 경로 문자열이어야 함: {prices_file!r}")
    try:
        text = Path(prices_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise BrokerError(
            f"Mock 가격 파일을 읽을 수 없음: {prices_file} ({exc})"
        ) from exc
    try:
        data = json.loads(text, parse_constant=_reject_json_constant)
    except ValueError as exc:
        raise BrokerError(
            f"Mock 가격 파일이 JSON이 아님: {prices_file} ({exc})"
        ) from exc
    if not isinstance(data, dict):
        raise BrokerError(f"Mock 가격 파일은 JSON 객체여야 함: {prices_file}")
    unknown = sorted(data.keys() - _PRICES_FILE_KEYS)
    if unknown:
        raise BrokerError(
            f"Mock 가격 파일에 허용하지 않는 키: {unknown} ({prices_file})"
        )
    if "prices" not in data:
        raise BrokerError(f"Mock 가격 파일에 prices 키가 없음: {prices_file}")
    raw_prices = data["prices"]
    if not isinstance(raw_prices, dict):
        raise BrokerError(f"Mock 가격 파일의 prices는 JSON 객체여야 함: {prices_file}")
    prices = {
        symbol: _valid_price(value, f"prices[{symbol!r}]", prices_file)
        for symbol, value in raw_prices.items()
    }
    default_price = (
        _valid_price(data["default_price"], "default_price", prices_file)
        if "default_price" in data
        else None
    )
    return prices, default_price


class FillMode(StrEnum):
    """체결 시뮬레이션 모드."""

    IMMEDIATE = "immediate"
    PARTIAL = "partial"
    DELAYED = "delayed"
    REJECT = "reject"


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
    status: str
    created_at: datetime = field(default_factory=lambda: clock.now(UTC))


class MockBrokerAdapter(BrokerAdapter):
    """E2E 테스트용 가상 브로커 어댑터.

    설정 옵션:
        fill_mode: "immediate" | "partial" | "delayed" | "reject"
        partial_fill_ratio: 부분 체결 비율 (0.0~1.0, 기본 0.5)
        delay_polls: 지연 모드에서 주문 뒤 체결되는 주문 이력 조회 차례 (기본 2)
        initial_cash: 초기 현금 (기본 100_000_000)
        default_price: prices에 없는 종목의 현재가 (기본 50_000)
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
        self._delay_polls = _valid_delay_polls(config.get("delay_polls", 2))
        self._polls_left: dict[str, int] = {}

        self._cash: float = config.get("initial_cash", 100_000_000.0)
        self._positions: dict[str, MockPosition] = {}
        self._orders: dict[str, MockOrder] = {}

        self._prices: dict[str, float]
        self._default_price: float | None
        if "prices_file" in config:
            self._prices, self._default_price = _load_prices_file(config)
        else:
            self._prices = config.get("prices", {})
            self._default_price = config.get("default_price", 50_000.0)

        self._commission = CommissionInfo(
            buy_commission_rate=config.get("buy_commission_rate", 0.00015),
            sell_commission_rate=config.get("sell_commission_rate", 0.00195),
        )

    async def connect(self) -> None:
        """Mock 연결 (항상 성공). 멱등: 이미 연결됐으면 no-op."""
        if self.is_connected:
            return
        self.is_connected = True
        logger.info("Mock Broker 연결됨")

    async def disconnect(self) -> None:
        """Mock 연결 해제."""
        self.is_connected = False
        logger.info("Mock Broker 연결 해제")

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

    async def get_buyable(
        self,
        symbol: str,
        price: float | None = None,
        order_type: str = "market",
    ) -> dict[str, float]:
        """매수가능 조회 — 보유 현금(``cash``) 기반 가상 산정.

        브로커 호출 없이 보유 현금으로 산정한다. ``price=None``이면 내부
        현재가를 단가로 사용하며, 단가 0이면 수량은 0.0이다.
        """
        cash = self._cash
        unit_price = price if price is not None else self._get_price(symbol)
        qty = float(int(cash // unit_price)) if unit_price > 0 else 0.0
        return {
            "order_buyable_amount": cash,
            "max_buyable_amount": cash,
            "order_cash": cash,
            "order_buyable_qty": qty,
            "max_buyable_qty": qty,
        }

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
        ensure_order_side(side)
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

        if self._fill_mode == FillMode.DELAYED:
            self._orders[order_id] = order
            self._polls_left[order_id] = self._delay_polls
            logger.info("Mock 주문 접수(지연): %s %s %s", order_id, side, symbol)
            return order_id

        fill_qty = self._calculate_fill_quantity(quantity)
        self._execute_fill(order, fill_qty, exec_price)
        self._orders[order_id] = order

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
        self._polls_left.pop(order_id, None)
        return True

    async def modify_order(
        self,
        order_id: str,
        *,
        quantity: float | None = None,
        price: float | None = None,
        order_type: str = "limit",
    ) -> bool:
        """주문 정정 (v1=price-only). 미체결 주문 가격만 갱신."""
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"주문을 찾을 수 없음: {order_id}")
        if order.status in ("filled", "cancelled", "rejected"):
            return False
        if price is not None:
            order.price = price
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

    async def get_account_positions(self) -> list[dict[str, Any]]:
        """증권사 실제 보유 잔고 (대사용)."""
        return await self.get_positions()

    async def get_order_history(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """주문/체결 이력 조회. 지연 모드의 주문은 정해진 차례의 조회에서 체결된다."""
        self._advance_delayed()
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

    def get_commission_info(self) -> CommissionInfo:
        """수수료율 정보."""
        return self._commission

    def _get_price(self, symbol: str) -> float:
        """종목 현재가 반환."""
        price = self._prices.get(symbol, self._default_price)
        if price is None:
            raise BrokerError(f"Mock 가격 파일에 종목 가격이 없음: {symbol}")
        return price

    def set_price(self, symbol: str, price: float) -> None:
        """테스트용: 종목 현재가 설정."""
        self._prices[symbol] = price

    def set_fill_mode(self, mode: FillMode) -> None:
        """테스트용: 체결 모드 변경."""
        self._fill_mode = mode

    def _advance_delayed(self) -> None:
        """지연 주문마다 남은 조회 수를 줄이고, 0이 된 주문을 체결한다."""
        for order_id, remaining in list(self._polls_left.items()):
            if remaining > 1:
                self._polls_left[order_id] = remaining - 1
                continue
            del self._polls_left[order_id]
            order = self._orders[order_id]
            self._execute_fill(order, order.quantity, order.price)

    def _calculate_fill_quantity(self, quantity: float) -> float:
        """체결 모드에 따른 체결 수량 계산."""
        if self._fill_mode == FillMode.PARTIAL:
            return quantity * self._partial_fill_ratio
        return quantity

    def _execute_fill(
        self, order: MockOrder, fill_qty: float, exec_price: float
    ) -> None:
        """체결 처리: 매도 보유를 먼저 검증한 뒤 잔고 및 포지션 업데이트."""
        if order.side != "buy":
            self._check_sellable(order.symbol, fill_qty)
        order.filled_quantity = fill_qty
        filled_value = fill_qty * exec_price
        commission = self._commission.calculate(order.side, filled_value)

        if order.side == "buy":
            self._cash -= filled_value + commission
            self._update_position_buy(order.symbol, fill_qty, exec_price)
        else:
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

    def _check_sellable(self, symbol: str, quantity: float) -> MockPosition:
        """매도할 보유가 충분한지 검증하고 그 포지션을 돌려준다."""
        pos = self._positions.get(symbol)
        if pos is None:
            msg = f"매도할 포지션 없음: {symbol}"
            raise BrokerError(msg)
        if pos.quantity < quantity:
            msg = f"보유 수량 부족: {symbol} (보유: {pos.quantity}, 매도: {quantity})"
            raise BrokerError(msg)
        return pos

    def _update_position_sell(self, symbol: str, quantity: float) -> None:
        """매도 시 포지션 업데이트."""
        self._check_sellable(symbol, quantity).quantity -= quantity
