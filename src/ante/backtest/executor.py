"""Backtest 시뮬레이션 실행기."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.backtest.context import BacktestStrategyContext
from ante.backtest.result import BacktestResult, BacktestTrade

if TYPE_CHECKING:
    from ante.backtest.data_provider import BacktestDataProvider
    from ante.strategy.base import Signal, Strategy

logger = logging.getLogger(__name__)


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
        commission_rate: float = 0.00015,
        slippage_rate: float = 0.001,
    ) -> None:
        self._strategy_cls = strategy_cls
        self._data = data_provider
        self._initial_balance = initial_balance
        self._commission_rate = commission_rate
        self._slippage_rate = slippage_rate

        self._balance = initial_balance
        self._positions: dict[str, dict[str, float]] = {}
        self._trades: list[BacktestTrade] = []
        self._equity_curve: list[dict] = []

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
        )
        strategy = self._strategy_cls(ctx)
        strategy.on_start()

        step = 0
        while self._data.advance():
            timestamp = self._data.get_current_timestamp()
            if timestamp is None:
                break

            context = {
                "timestamp": timestamp,
                "portfolio": self.get_positions("backtest"),
                "balance": self.get_balance("backtest"),
            }

            signals = await strategy.on_step(context)

            for signal in signals:
                await self._execute_signal(signal, timestamp)

            equity = self._calculate_equity()
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

        final_equity = self._calculate_equity()
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
            metrics=self._calculate_metrics(),
        )

    async def _execute_signal(self, signal: Signal, timestamp: Any) -> None:
        """Signal을 가상 체결."""
        price = await self._data.get_current_price(signal.symbol)

        if signal.side == "buy":
            exec_price = price * (1 + self._slippage_rate)
        else:
            exec_price = price * (1 - self._slippage_rate)

        commission = exec_price * signal.quantity * self._commission_rate

        if signal.side == "buy":
            cost = exec_price * signal.quantity + commission
            if self._balance < cost:
                return
            self._balance -= cost
            self._update_position(signal.symbol, signal.quantity, exec_price)
        else:
            pos = self._positions.get(signal.symbol, {})
            sell_qty = min(signal.quantity, pos.get("quantity", 0))
            if sell_qty <= 0:
                return
            proceeds = exec_price * sell_qty - commission
            self._balance += proceeds
            self._update_position(signal.symbol, -sell_qty, exec_price)

        self._trades.append(
            BacktestTrade(
                timestamp=timestamp,
                symbol=signal.symbol,
                side=signal.side,
                quantity=signal.quantity,
                price=exec_price,
                commission=commission,
                slippage=abs(exec_price - price) * signal.quantity,
                reason=signal.reason,
            )
        )

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

    def _calculate_equity(self) -> float:
        """현재 자산 가치."""
        equity = self._balance
        for pos in self._positions.values():
            equity += pos["quantity"] * pos["avg_price"]
        return equity

    def _calculate_metrics(self) -> dict:
        """성과 지표 계산."""
        from ante.backtest.metrics import calculate_metrics

        if not self._trades:
            return {}

        final_equity = self._calculate_equity()
        metrics = calculate_metrics(
            trades=self._trades,
            equity_curve=self._equity_curve,
            initial_balance=self._initial_balance,
            final_balance=final_equity,
        )

        # 기존 호환 필드 추가
        metrics["buy_trades"] = sum(1 for t in self._trades if t.side == "buy")
        metrics["sell_trades"] = sum(1 for t in self._trades if t.side == "sell")
        metrics["total_slippage"] = round(sum(t.slippage for t in self._trades), 2)

        return metrics

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """PortfolioView 인터페이스."""
        return {
            s: {"quantity": p["quantity"], "avg_price": p["avg_price"]}
            for s, p in self._positions.items()
        }

    def get_balance(self, bot_id: str) -> dict[str, float]:
        """PortfolioView 인터페이스."""
        return {
            "total": self._balance,
            "available": self._balance,
            "reserved": 0,
        }
