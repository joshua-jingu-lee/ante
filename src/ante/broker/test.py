"""TestBrokerAdapter 및 PriceSimulator — 개발/검증용 테스트 브로커.

KIS 실전 API 없이도 시스템 전체 흐름을 검증할 수 있는 테스트 브로커.
GBM 기반 가격 시뮬레이션, 현실적 체결(슬리피지/부분 체결),
인메모리 잔고/포지션 관리를 지원한다.
MockBrokerAdapter(E2E용)와는 목적이 다르며 유지한다.
"""

from __future__ import annotations

import logging
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ante.broker.base import BrokerAdapter
from ante.broker.exceptions import BrokerError, OrderNotFoundError
from ante.broker.models import CommissionInfo

logger = logging.getLogger(__name__)

# KRX 하루 거래 시간: 09:00~15:30 = 6.5시간 = 23,400초
KRX_TRADING_SECONDS = 23_400

# ── 슬리피지/부분 체결 기본값 ────────────────────────────────
_SLIPPAGE_MIN = 0.001  # 0.1%
_SLIPPAGE_MAX = 0.003  # 0.3%
_PARTIAL_FILL_THRESHOLD = 100  # 이 수량 이상이면 부분 체결 확률 적용
_PARTIAL_FILL_PROBABILITY = 0.3  # 부분 체결 발생 확률
_PARTIAL_FILL_RATIO_MIN = 0.3
_PARTIAL_FILL_RATIO_MAX = 0.9


@dataclass(frozen=True)
class StockPreset:
    """가상 종목 프리셋."""

    symbol: str
    name: str
    base_price: float
    daily_vol: float  # 일별 변동성 (0.018 = 1.8%)


# 가상 종목 프리셋 6종
VIRTUAL_STOCK_PRESETS: dict[str, StockPreset] = {
    "000001": StockPreset("000001", "알파전자", 72_000, 0.018),
    "000002": StockPreset("000002", "베타반도체", 160_000, 0.025),
    "000003": StockPreset("000003", "감마소프트", 210_000, 0.022),
    "000004": StockPreset("000004", "델타플랫폼", 48_000, 0.028),
    "000005": StockPreset("000005", "엡실론모터스", 230_000, 0.015),
    "000006": StockPreset("000006", "제타에너지", 390_000, 0.020),
}


def _tick_size(price: float) -> int:
    """KRX 호가 단위 반환."""
    if price < 2_000:
        return 1
    if price < 5_000:
        return 5
    if price < 20_000:
        return 10
    if price < 50_000:
        return 50
    if price < 200_000:
        return 100
    if price < 500_000:
        return 500
    return 1_000


def tick_round(price: float) -> float:
    """KRX 호가 단위로 반올림."""
    tick = _tick_size(price)
    return float(round(price / tick) * tick)


class PriceSimulator:
    """GBM 기반 실시간 가격 시뮬레이션 엔진.

    시드 생성기의 GBM 로직을 재활용하되, 일봉이 아닌 틱(초) 단위
    변동을 지원한다.

    일변동성 → 초단위 스케일링:
        σ_tick = σ_daily / √(KRX 거래초수)

    동일 시드로 초기화하면 동일한 가격 시퀀스를 재현할 수 있다.
    """

    def __init__(
        self,
        presets: dict[str, StockPreset] | None = None,
        seed: int = 42,
    ) -> None:
        self._presets = presets or VIRTUAL_STOCK_PRESETS
        self._seed = seed
        self._rng = random.Random(seed)
        self._prices: dict[str, float] = {}
        self._tick_vols: dict[str, float] = {}
        self._initialize()

    def _initialize(self) -> None:
        """프리셋 기반 초기 가격 및 틱 변동성 설정."""
        sqrt_trading_seconds = math.sqrt(KRX_TRADING_SECONDS)
        for symbol, preset in self._presets.items():
            self._prices[symbol] = tick_round(preset.base_price)
            self._tick_vols[symbol] = preset.daily_vol / sqrt_trading_seconds
        logger.info(
            "PriceSimulator 초기화: %d종목, seed=%d",
            len(self._presets),
            self._seed,
        )

    def tick(self, symbol: str) -> float:
        """한 틱(초 단위) 진행 — GBM 변동 적용 후 현재가 반환.

        Args:
            symbol: 종목코드.

        Returns:
            호가 단위로 반올림된 현재가.

        Raises:
            KeyError: 등록되지 않은 종목코드.
        """
        if symbol not in self._prices:
            msg = f"등록되지 않은 종목: {symbol}"
            raise KeyError(msg)

        current = self._prices[symbol]
        sigma = self._tick_vols[symbol]

        # GBM: dS = S * σ * dW  (drift ≈ 0 for tick-level)
        z = self._rng.gauss(0, 1)
        log_return = sigma * z
        new_price = current * math.exp(log_return)

        # 최소 가격 보장 (1 호가 단위 이상)
        new_price = max(new_price, _tick_size(new_price))

        rounded = tick_round(new_price)
        self._prices[symbol] = rounded
        return rounded

    def get_price(self, symbol: str) -> float:
        """현재가 조회 (tick 진행 없이).

        Args:
            symbol: 종목코드.

        Returns:
            현재가.

        Raises:
            KeyError: 등록되지 않은 종목코드.
        """
        if symbol not in self._prices:
            msg = f"등록되지 않은 종목: {symbol}"
            raise KeyError(msg)
        return self._prices[symbol]

    @property
    def symbols(self) -> list[str]:
        """등록된 종목코드 목록."""
        return list(self._presets.keys())

    @property
    def presets(self) -> dict[str, StockPreset]:
        """종목 프리셋 조회."""
        return dict(self._presets)


# ── TestBrokerAdapter 내부 모델 ──────────────────────────────


@dataclass
class _TestPosition:
    """인메모리 가상 포지션."""

    symbol: str
    quantity: float
    avg_price: float


@dataclass
class _TestOrder:
    """인메모리 주문 기록."""

    order_id: str
    symbol: str
    side: str
    quantity: float
    filled_quantity: float
    price: float
    order_type: str
    status: str  # "pending" | "filled" | "partially_filled" | "cancelled"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


# ── TestBrokerAdapter ────────────────────────────────────────


class TestBrokerAdapter(BrokerAdapter):
    """개발/검증용 테스트 브로커 어댑터.

    KIS와 동일한 BrokerAdapter 인터페이스로 현실적인 시뮬레이션 데이터를 반환한다.
    PriceSimulator(GBM) 기반 가격 변동, 슬리피지/부분 체결 시뮬레이션,
    인메모리 잔고/포지션/주문 이력 관리를 제공한다.

    설정 옵션:
        seed: 시뮬레이션 시드 (기본 42, 재현 가능)
        initial_cash: 초기 현금 (기본 100_000_000)
        tick_interval: 스트리밍 가격 변동 간격 초 (기본 1.0)
    """

    broker_id: str = "test"
    broker_name: str = "테스트 브로커"
    broker_short_name: str = "TEST"

    def __init__(self, config: dict[str, Any]) -> None:
        config.setdefault("exchange", "TEST")
        config.setdefault("currency", "KRW")
        super().__init__(config)

        self._seed: int = config.get("seed", 42)
        self._initial_cash: float = config.get("initial_cash", 100_000_000.0)
        self._tick_interval: float = config.get("tick_interval", 1.0)

        # 시뮬레이터
        self._simulator = PriceSimulator(seed=self._seed)
        self._rng = random.Random(self._seed)

        # 인메모리 상태
        self._cash: float = self._initial_cash
        self._positions: dict[str, _TestPosition] = {}
        self._orders: dict[str, _TestOrder] = {}

        # 수수료 (buy/sell 분리)
        self._commission = CommissionInfo(
            buy_commission_rate=config.get("buy_commission_rate", 0.0),
            sell_commission_rate=config.get("sell_commission_rate", 0.0),
        )

    # ── 연결 ──────────────────────────────────────────────

    async def connect(self) -> None:
        """Test 브로커 연결 (항상 성공)."""
        self.is_connected = True
        logger.info(
            "Test Broker 연결됨 (seed=%d, cash=%.0f)",
            self._seed,
            self._cash,
        )

    async def disconnect(self) -> None:
        """Test 브로커 연결 해제."""
        self.is_connected = False
        logger.info("Test Broker 연결 해제")

    # ── 시세 조회 ─────────────────────────────────────────

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회 — 매 호출마다 GBM 변동 적용."""
        return self._simulator.tick(symbol)

    # ── 계좌/포지션 ───────────────────────────────────────

    async def get_account_balance(self) -> dict[str, float]:
        """가상 계좌 잔고 조회."""
        total_stock_value = sum(
            pos.quantity * self._simulator.get_price(pos.symbol)
            for pos in self._positions.values()
        )
        return {
            "cash": self._cash,
            "total_assets": self._cash + total_stock_value,
            "stock_value": total_stock_value,
        }

    async def get_positions(self) -> list[dict[str, Any]]:
        """보유 포지션 조회 — 현재 시뮬레이션 가격으로 평가손익 계산."""
        return [
            {
                "symbol": pos.symbol,
                "quantity": pos.quantity,
                "avg_price": pos.avg_price,
                "current_price": self._simulator.get_price(pos.symbol),
                "pnl": (self._simulator.get_price(pos.symbol) - pos.avg_price)
                * pos.quantity,
            }
            for pos in self._positions.values()
            if pos.quantity > 0
        ]

    async def get_account_positions(self) -> list[dict[str, Any]]:
        """증권사 실제 보유 잔고 (대사용) — get_positions() 위임."""
        return await self.get_positions()

    # ── 주문/체결 ─────────────────────────────────────────

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "market",
        price: float | None = None,
        stop_price: float | None = None,
    ) -> str:
        """주문 접수 및 체결 시뮬레이션.

        시장가: 현재 시뮬레이션가 +/- 슬리피지로 즉시 체결.
        지정가: 지정가와 현재가를 비교하여 체결 가능 시 체결.
        대량 주문 시 부분 체결 확률 적용.
        """
        if symbol not in self._simulator.symbols:
            msg = f"등록되지 않은 종목: {symbol}"
            raise BrokerError(msg)

        order_id = str(uuid.uuid4())[:8]
        current_price = self._simulator.get_price(symbol)

        # 체결 가격 결정
        if order_type == "limit" and price is not None:
            # 지정가: 매수 시 현재가 <= 지정가여야 체결, 매도 시 현재가 >= 지정가
            if side == "buy" and current_price > price:
                # 지정가 미도달 → 미체결 보류
                order = _TestOrder(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    filled_quantity=0.0,
                    price=price,
                    order_type=order_type,
                    status="pending",
                )
                self._orders[order_id] = order
                logger.info(
                    "Test 지정가 미체결: %s %s %s qty=%.1f @ %.0f (현재=%.0f)",
                    order_id,
                    side,
                    symbol,
                    quantity,
                    price,
                    current_price,
                )
                return order_id
            if side == "sell" and current_price < price:
                order = _TestOrder(
                    order_id=order_id,
                    symbol=symbol,
                    side=side,
                    quantity=quantity,
                    filled_quantity=0.0,
                    price=price,
                    order_type=order_type,
                    status="pending",
                )
                self._orders[order_id] = order
                logger.info(
                    "Test 지정가 미체결: %s %s %s qty=%.1f @ %.0f (현재=%.0f)",
                    order_id,
                    side,
                    symbol,
                    quantity,
                    price,
                    current_price,
                )
                return order_id
            exec_price = tick_round(price)
        else:
            # 시장가: 슬리피지 적용
            exec_price = self._apply_slippage(current_price, side)

        # 체결 수량 결정 (부분 체결 확률)
        fill_qty = self._calculate_fill_quantity(quantity)

        # 잔고 검증
        if side == "buy":
            required = fill_qty * exec_price
            if required > self._cash:
                msg = f"자금 부족: 필요 {required:.0f}, 보유 {self._cash:.0f}"
                raise BrokerError(msg)
        elif side == "sell":
            pos = self._positions.get(symbol)
            if pos is None or pos.quantity < fill_qty:
                available = pos.quantity if pos else 0.0
                msg = f"보유 수량 부족: {symbol} (보유: {available}, 매도: {fill_qty})"
                raise BrokerError(msg)

        # 주문 생성
        order = _TestOrder(
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

        # 체결 실행
        self._execute_fill(order, fill_qty, exec_price)

        logger.info(
            "Test 주문 체결: %s %s %s qty=%.1f filled=%.1f @ %.0f",
            order_id,
            side,
            symbol,
            quantity,
            fill_qty,
            exec_price,
        )
        return order_id

    async def cancel_order(self, order_id: str) -> bool:
        """미체결 주문 취소."""
        order = self._orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"주문을 찾을 수 없음: {order_id}")
        if order.status in ("filled", "cancelled"):
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

    # ── 이력/마스터 ───────────────────────────────────────

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

    async def get_instruments(self, exchange: str = "KRX") -> list[dict[str, Any]]:
        """가상 종목 프리셋 목록 반환 (6종)."""
        return [
            {
                "symbol": preset.symbol,
                "name": preset.name,
                "name_en": "",
                "instrument_type": "stock",
                "listed": True,
            }
            for preset in self._simulator.presets.values()
        ]

    # ── 수수료 ────────────────────────────────────────────

    def get_commission_info(self) -> CommissionInfo:
        """수수료율 정보 (KIS 동일: 0.015%, 매도세 0.23%)."""
        return self._commission

    # ── 내부 헬퍼 ─────────────────────────────────────────

    def _apply_slippage(self, price: float, side: str) -> float:
        """슬리피지 적용 — 매수 +0.1~0.3%, 매도 -0.1~0.3%."""
        slippage_rate = self._rng.uniform(_SLIPPAGE_MIN, _SLIPPAGE_MAX)
        if side == "buy":
            slipped = price * (1 + slippage_rate)
        else:
            slipped = price * (1 - slippage_rate)
        return tick_round(slipped)

    def _calculate_fill_quantity(self, quantity: float) -> float:
        """부분 체결 수량 계산.

        대량 주문(>= 100주) 시 30% 확률로 부분 체결 발생.
        """
        if quantity >= _PARTIAL_FILL_THRESHOLD:
            if self._rng.random() < _PARTIAL_FILL_PROBABILITY:
                ratio = self._rng.uniform(
                    _PARTIAL_FILL_RATIO_MIN, _PARTIAL_FILL_RATIO_MAX
                )
                return float(max(1, int(quantity * ratio)))
        return quantity

    def _execute_fill(
        self, order: _TestOrder, fill_qty: float, exec_price: float
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
            self._positions[symbol] = _TestPosition(
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
