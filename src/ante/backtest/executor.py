"""Backtest 시뮬레이션 실행기."""

from __future__ import annotations

import logging
import math
from collections import deque
from typing import TYPE_CHECKING, Any

from ante.backtest.context import BacktestStrategyContext
from ante.backtest.result import BacktestResult, BacktestTrade

if TYPE_CHECKING:
    from pathlib import Path

    from ante.backtest.data_provider import BacktestDataProvider
    from ante.strategy.base import Signal, Strategy

logger = logging.getLogger(__name__)

_ALLOWED_SIDES = ("buy", "sell")

_MAX_FOLLOW_UP_FILLS_PER_STEP = 1000


def _is_valid_quantity(value: object) -> bool:
    """``value``가 finite한 ``int``/``float`` quantity인지 판정."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except (OverflowError, ValueError, TypeError):
        return False


class BacktestExecutor:
    """백테스트 시뮬레이션 실행기.

    전략을 과거 데이터 위에서 실행하고, 가상 체결(슬리피지·수수료 포함)로
    성과를 측정한다.
    """

    def __init__(
        self,
        strategy_cls: type[Strategy],
        data_provider: BacktestDataProvider,
        initial_balance: float = 10_000_000,
        buy_commission_rate: float = 0.00015,
        sell_commission_rate: float = 0.00195,
        slippage_rate: float = 0.001,
        exchange: str = "KRX",
        strategies_dir: Path | None = None,
        symbols: list[str] | None = None,
    ) -> None:
        self._strategy_cls = strategy_cls
        self._data: BacktestDataProvider = data_provider
        self._allowed_symbols: frozenset[str] = frozenset(symbols or [])
        self._initial_balance = initial_balance
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        self._slippage_rate = slippage_rate
        self._exchange = exchange
        self._strategies_dir = strategies_dir

        self._balance = initial_balance
        self._positions: dict[str, dict[str, float]] = {}
        self._trades: list[BacktestTrade] = []
        self._equity_curve: list[dict] = []
        self._current_prices: dict[str, float] = {}
        self._order_seq = 0

    def _next_order_id(self) -> str:
        """체결마다 증가하는 결정적 order_id(``bt-{n}``)를 발급한다."""
        self._order_seq += 1
        return f"bt-{self._order_seq}"

    async def run(
        self,
        progress_callback: Any | None = None,
    ) -> BacktestResult:
        """백테스트 실행.

        Args:
            progress_callback: (current_step, total_steps)를 받는 콜백.
        """
        total_steps = self._data.get_total_steps()

        ctx = BacktestStrategyContext(
            bot_id="backtest",
            data_provider=self._data,
            portfolio=self,
            strategies_dir=self._strategies_dir,
        )
        strategy = self._strategy_cls(ctx)
        strategy.on_start()

        step = 0
        while self._data.advance():
            timestamp = self._data.get_current_timestamp()
            if timestamp is None:
                break

            await self._refresh_current_prices()

            context = {
                "timestamp": timestamp,
                "portfolio": self.get_positions("backtest"),
                "balance": self.get_balance("backtest"),
            }

            signals = await strategy.on_step(context)

            follow_up_queue: deque[Signal] = deque()
            for sig in signals:
                fill = await self._execute_signal(sig, timestamp)
                if fill is None:
                    continue
                follow_ups = await strategy.on_fill(fill)
                if follow_ups:
                    follow_up_queue.extend(follow_ups)

            follow_up_fills = 0
            while follow_up_queue:
                if follow_up_fills >= _MAX_FOLLOW_UP_FILLS_PER_STEP:
                    logger.warning(
                        "on_fill follow-up 한도(%d) 도달 — step %s truncate",
                        _MAX_FOLLOW_UP_FILLS_PER_STEP,
                        timestamp,
                    )
                    break
                sig = follow_up_queue.popleft()
                fill = await self._execute_signal(sig, timestamp)
                if fill is None:
                    continue
                follow_up_fills += 1
                follow_ups = await strategy.on_fill(fill)
                if follow_ups:
                    follow_up_queue.extend(follow_ups)

            equity = await self._calculate_equity()
            self._equity_curve.append(
                {
                    "timestamp": str(timestamp),
                    "equity": equity,
                    "balance": self._balance,
                }
            )
            step += 1
            if progress_callback:
                progress_callback(step, total_steps)

        strategy.on_stop()

        final_equity = (
            self._equity_curve[-1]["equity"] if self._equity_curve else self._balance
        )
        total_return = (
            (final_equity - self._initial_balance) / self._initial_balance * 100
            if self._initial_balance > 0
            else 0.0
        )

        return BacktestResult(
            strategy_name=strategy.meta.name,
            strategy_version=strategy.meta.version,
            start_date=self._data.start,
            end_date=self._data.end,
            initial_balance=self._initial_balance,
            final_balance=final_equity,
            total_return=total_return,
            trades=self._trades,
            equity_curve=self._equity_curve,
            metrics=self._calculate_metrics(final_equity),
        )

    async def _execute_signal(self, signal: Signal, timestamp: Any) -> dict | None:
        """Signal을 가상 체결."""
        if signal.side not in _ALLOWED_SIDES:
            if signal.side == "hold":
                logger.warning(
                    "Signal skip(hold): symbol=%s side=%r quantity=%r — "
                    "hold는 no-op이므로 Signal을 발행하지 말 것(거래 미발행)",
                    signal.symbol,
                    signal.side,
                    signal.quantity,
                )
            else:
                logger.warning(
                    "Signal skip(unknown side): symbol=%s side=%r quantity=%r — "
                    'side는 {"buy","sell"}만 허용(거래 미발행)',
                    signal.symbol,
                    signal.side,
                    signal.quantity,
                )
            return None

        if not _is_valid_quantity(signal.quantity) or signal.quantity <= 0:
            logger.warning(
                "Signal skip(invalid quantity): symbol=%s side=%r quantity=%r — "
                "quantity는 finite한 양수여야 함(거래 미발행)",
                signal.symbol,
                signal.side,
                signal.quantity,
            )
            return None

        if self._allowed_symbols and signal.symbol not in self._allowed_symbols:
            logger.warning(
                "Signal skip(symbol not in backtest universe): symbol=%s side=%r — "
                "config.symbols=%s 외 종목은 거래하지 않음(미체결)",
                signal.symbol,
                signal.side,
                sorted(self._allowed_symbols),
            )
            return None

        price = self._data.get_current_bar_price(signal.symbol)
        if price is None:
            logger.warning(
                "Signal skip(no current bar): symbol=%s side=%r quantity=%r ts=%s — "
                "해당 step에 봉 없음(gap day/미시작), 미체결",
                signal.symbol,
                signal.side,
                signal.quantity,
                timestamp,
            )
            return None

        if not self._order_triggered(signal, price):
            return None

        if signal.side == "buy":
            exec_price = self._apply_slippage_cap(signal, price, "buy")
            executed_qty = signal.quantity
            commission = exec_price * executed_qty * self._buy_commission_rate
            cost = exec_price * executed_qty + commission
            if self._balance < cost:
                return None
            self._balance -= cost
            self._update_position(signal.symbol, executed_qty, exec_price)
        else:
            exec_price = self._apply_slippage_cap(signal, price, "sell")
            pos = self._positions.get(signal.symbol, {})
            executed_qty = min(signal.quantity, pos.get("quantity", 0))
            if executed_qty <= 0:
                return None
            commission = exec_price * executed_qty * self._sell_commission_rate
            proceeds = exec_price * executed_qty - commission
            self._balance += proceeds
            self._update_position(signal.symbol, -executed_qty, exec_price)

        self._trades.append(
            BacktestTrade(
                timestamp=timestamp,
                symbol=signal.symbol,
                side=signal.side,
                quantity=executed_qty,
                price=exec_price,
                commission=commission,
                slippage=abs(exec_price - price) * executed_qty,
                reason=signal.reason,
                exchange=self._exchange,
            )
        )

        return {
            "order_id": self._next_order_id(),
            "symbol": signal.symbol,
            "side": signal.side,
            "quantity": executed_qty,
            "price": exec_price,
            "timestamp": timestamp,
            "fill_dedup_key": "",
        }

    def _order_triggered(self, signal: Signal, price: float) -> bool:
        """``signal.order_type`` 트리거가 현재 봉가(*price*)로 충족되는지 판정."""
        order_type = signal.order_type
        if order_type == "market":
            return True

        is_buy = signal.side == "buy"
        limit = signal.price
        stop = signal.stop_price

        if order_type == "limit":
            if limit is None:
                logger.warning(
                    "invalid limit order: missing price — symbol=%s side=%s (미체결)",
                    signal.symbol,
                    signal.side,
                )
                return False
            triggered = price <= limit if is_buy else price >= limit
        elif order_type == "stop":
            if stop is None:
                logger.warning(
                    "invalid stop order: missing stop_price — symbol=%s side=%s "
                    "(미체결)",
                    signal.symbol,
                    signal.side,
                )
                return False
            triggered = price >= stop if is_buy else price <= stop
        elif order_type == "stop_limit":
            if stop is None or limit is None:
                logger.warning(
                    "invalid stop_limit order: missing price/stop_price — "
                    "symbol=%s side=%s (미체결)",
                    signal.symbol,
                    signal.side,
                )
                return False
            triggered = (
                (price >= stop and price <= limit)
                if is_buy
                else (price <= stop and price >= limit)
            )
        else:
            logger.warning(
                "invalid order_type: unknown type=%r — symbol=%s side=%s (미체결)",
                order_type,
                signal.symbol,
                signal.side,
            )
            return False

        if not triggered:
            logger.debug(
                "order not triggered: type=%s side=%s price=%s limit=%s stop=%s",
                order_type,
                signal.side,
                price,
                limit,
                stop,
            )
        return triggered

    def _apply_slippage_cap(self, signal: Signal, price: float, side: str) -> float:
        """게이트 통과 후 order_type별 체결가(``exec_price``)를 산출한다."""
        limit = signal.price
        is_capped_limit = signal.order_type in ("limit", "stop_limit")
        if side == "buy":
            slipped = price * (1 + self._slippage_rate)
            if is_capped_limit and limit is not None:
                return min(slipped, limit)
            return slipped
        slipped = price * (1 - self._slippage_rate)
        if is_capped_limit and limit is not None:
            return max(slipped, limit)
        return slipped

    def _update_position(self, symbol: str, qty_delta: float, price: float) -> None:
        """포지션 업데이트."""
        if symbol not in self._positions:
            self._positions[symbol] = {"quantity": 0, "avg_price": 0.0}
        pos = self._positions[symbol]

        if qty_delta > 0:
            total_cost = pos["quantity"] * pos["avg_price"] + qty_delta * price
            pos["quantity"] += qty_delta
            if pos["quantity"] > 0:
                pos["avg_price"] = total_cost / pos["quantity"]
        else:
            pos["quantity"] += qty_delta
            if pos["quantity"] <= 0:
                del self._positions[symbol]

    async def _refresh_current_prices(self) -> None:
        """현재 봉 시점의 보유 심볼별 현재가 스냅샷을 새로 구성한다."""
        prices: dict[str, float] = {}
        for symbol, pos in self._positions.items():
            avg_price = pos["avg_price"]
            mark_price = avg_price
            try:
                current_price = await self._data.get_current_price(symbol)
                if current_price is not None and current_price > 0:
                    mark_price = current_price
                else:
                    logger.warning(
                        "현재가 조회 불가(symbol=%s, price=%r) — avg_price로 fallback",
                        symbol,
                        current_price,
                    )
            except Exception:
                logger.warning(
                    "현재가 조회 실패(symbol=%s) — avg_price로 fallback",
                    symbol,
                    exc_info=True,
                )
            prices[symbol] = mark_price
        self._current_prices = prices

    async def _calculate_equity(self) -> float:
        """현재 bar 시점의 자산 가치 (mark-to-market)."""
        equity = self._balance
        for symbol, pos in self._positions.items():
            mark_price = pos["avg_price"]
            try:
                current_price = await self._data.get_current_price(symbol)
                if current_price is not None and current_price > 0:
                    mark_price = current_price
                else:
                    logger.warning(
                        "현재가 평가 불가(symbol=%s, price=%r) — avg_price로 fallback",
                        symbol,
                        current_price,
                    )
            except Exception:
                logger.warning(
                    "현재가 조회 실패(symbol=%s) — avg_price로 fallback",
                    symbol,
                    exc_info=True,
                )
            equity += pos["quantity"] * mark_price
        return equity

    def _calculate_metrics(self, final_equity: float) -> dict:
        """성과 지표 계산."""
        from ante.backtest.metrics import calculate_metrics

        metrics = calculate_metrics(
            trades=self._trades,
            equity_curve=self._equity_curve,
            initial_balance=self._initial_balance,
            final_balance=final_equity,
        )

        metrics["buy_trades"] = sum(1 for t in self._trades if t.side == "buy")
        metrics["sell_trades"] = sum(1 for t in self._trades if t.side == "sell")
        metrics["total_slippage"] = round(sum(t.slippage for t in self._trades), 2)

        return metrics

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """PortfolioView 인터페이스.

        spec ``03-04-provider-and-views.md`` L29 PortfolioView 스키마대로
        ``{symbol: {"quantity","avg_price","current_price","unrealized_pnl"}}`` 를
        반환해 라이브와 parity를 맞춘다.

        provider를 재호출하지 않고 run 루프가 매 step 미리 채운
        ``self._current_prices`` 캐시만 읽는다(sync 유지). 캐시에 심볼이 없으면
        (예: run 루프 밖에서 호출되거나 가격 미조회) ``avg_price`` 로 fallback해
        ``unrealized_pnl == 0`` 이 된다.
        """
        result: dict[str, Any] = {}
        for symbol, p in self._positions.items():
            avg_price = p["avg_price"]
            current_price = self._current_prices.get(symbol, avg_price)
            result[symbol] = {
                "quantity": p["quantity"],
                "avg_price": avg_price,
                "current_price": current_price,
                "unrealized_pnl": (current_price - avg_price) * p["quantity"],
            }
        return result

    def get_balance(self, bot_id: str) -> dict[str, float]:
        """PortfolioView 인터페이스."""
        return {
            "total": self._balance,
            "available": self._balance,
            "reserved": 0,
        }

    def get_trade_history(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """백테스트 중 누적된 가상 거래 이력을 최신순으로 반환.

        라이브 ``StrategyContext.get_trade_history`` 와 동일한 full dict shape
        (``trade_id``/``symbol``/``side``/``quantity``/``price``/``status``/
        ``order_type``/``reason``/``commission``/``timestamp``)를 제공해, 같은
        전략 코드가 라이브/백테스트에서 동일하게 동작하도록 parity를 맞춘다.

        - ``self._trades`` (append 순 = 시간순)를 최신순(역순)으로 정렬한다.
        - *symbol* 이 주어지면 해당 symbol만 남긴 뒤 *limit* 개로 자른다
          (필터를 limit **이전에** 적용).
        - ``trade_id`` 는 원본 ``self._trades`` 인덱스 기반(``f"bt-{i}"``)으로
          합성해 결정적이다.
        - ``status`` 는 backtest 거래가 모두 체결되므로 ``"filled"``,
          ``order_type`` 은 시장가 체결이므로 ``"market"`` 으로 합성한다.
        - ``timestamp`` 는 ``datetime`` 이면 ``.isoformat()``, ``str`` 이면 그대로,
          ``None`` 이면 ``None`` (backtest timestamp 소스가 datetime/str 혼재 가능).
        """
        indexed = list(enumerate(self._trades))
        indexed.reverse()

        if symbol is not None:
            indexed = [(i, t) for i, t in indexed if t.symbol == symbol]

        indexed = indexed[:limit]

        return [
            {
                "trade_id": f"bt-{i}",
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "status": "filled",
                "order_type": "market",
                "reason": t.reason,
                "commission": t.commission,
                "timestamp": t.timestamp.isoformat()
                if hasattr(t.timestamp, "isoformat")
                else t.timestamp,
            }
            for i, t in indexed
        ]
