"""Backtest 시뮬레이션 실행기."""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, Any

from ante.backtest.context import BacktestStrategyContext
from ante.backtest.result import BacktestResult, BacktestTrade

if TYPE_CHECKING:
    from ante.backtest.data_provider import BacktestDataProvider
    from ante.strategy.base import Signal, Strategy

logger = logging.getLogger(__name__)

# 라이브 preflight가 허용하는 side vocabulary. RuleEngine이 OrderRequestEvent를
# 검증할 때와 동일하게 case-sensitive로 buy/sell만 허용한다(#1991).
_ALLOWED_SIDES = ("buy", "sell")


def _is_valid_quantity(value: object) -> bool:
    """``value``가 finite한 ``int``/``float`` quantity인지 판정.

    RuleEngine ``_is_finite_quantity``와 동일 정책 (cross-module import 회피):
    private helper를 import하면 backtest가 rule 모듈 내부 구현에 결합되므로,
    같은 정책을 backtest 안에 작은 local mirror로 둔다(#1991, codex 지시).

    - ``bool``은 제외한다(``True``/``False``를 수량으로 보지 않음).
      ``isinstance(True, int) == True`` 이므로 명시적으로 잠근다.
    - ``int``/``float``만 허용하고, ``math.isfinite``로 ``NaN``/``inf``를 차단한다.
    - Python ``int``는 임의 정밀도라 ``10**10000`` 같은 거대 정수는 ``float``
      변환 시 ``OverflowError`` (또는 ``ValueError``/``TypeError``)를 던진다.
      이때도 finite-호환이 아니므로 ``False``로 떨어뜨린다(overflow guard).
    - 본 helper는 절대 raise하지 않는 invariant를 유지한다.
    """
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
    ) -> None:
        self._strategy_cls = strategy_cls
        self._data = data_provider
        self._initial_balance = initial_balance
        self._buy_commission_rate = buy_commission_rate
        self._sell_commission_rate = sell_commission_rate
        self._slippage_rate = slippage_rate
        self._exchange = exchange

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

        # 루프 종료 후 advance()가 커서를 1칸 더 올린 상태이므로
        # 여기서 _calculate_equity()/get_current_price()를 재호출하면
        # 다음 봉(미래) 가격을 보는 lookahead가 된다. 마지막 시뮬레이션 봉의
        # equity를 재사용한다.
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

    async def _execute_signal(self, signal: Signal, timestamp: Any) -> None:
        """Signal을 가상 체결.

        체결 수량(``executed_qty``)을 분기별로 먼저 확정한 뒤, 수수료/슬리피지/
        거래 기록을 모두 체결 수량 기준으로 계산한다. 보유 수량을 초과하는 매도는
        보유분만 체결되므로, 초과 요청 수량이 수수료·슬리피지·거래 수량에
        반영되지 않는다(#1989).

        가격 조회/분기 이전에 Signal을 검증한다(#1991, #2066 포괄). 라이브
        ``RuleEngine`` preflight와 동일하게 ``side ∈ {"buy","sell"}`` 와 finite
        양수 ``quantity`` 만 허용한다. 무효 Signal은 거래를 발행하지 않고 진단
        로그만 남긴 뒤 skip한다(라이브 OrderRejectedEvent와 달리 backtest는
        이벤트 없음). 특히 ``hold`` 등 buy/sell 이외 side는 **절대 sell 분기로
        라우팅하지 않는다**(unknown side가 매도로 처리되던 회귀 차단).
        """
        # ── Signal 검증 (가격 조회/분기 이전) ──────────────────────────
        # side 검증: case-sensitive로 buy/sell만 허용. hold/unknown은 skip하여
        # sell 분기 라우팅을 차단한다. 진단 로그는 hold(전략 작성 가이드)와
        # unknown side(잘못된 값 경고)를 문구로 구분한다.
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
            return

        # quantity 검증: finite numeric이 아니거나(NaN/inf/non-number/bool/거대
        # 정수) <= 0(음수/0)이면 skip. 음수 buy는 cost가 음수가 되어 잔고
        # 검사를 통과하므로 여기서 fail-closed로 막는다.
        if not _is_valid_quantity(signal.quantity) or signal.quantity <= 0:
            logger.warning(
                "Signal skip(invalid quantity): symbol=%s side=%r quantity=%r — "
                "quantity는 finite한 양수여야 함(거래 미발행)",
                signal.symbol,
                signal.side,
                signal.quantity,
            )
            return

        price = await self._data.get_current_price(signal.symbol)

        if signal.side == "buy":
            exec_price = price * (1 + self._slippage_rate)
            executed_qty = signal.quantity
            commission = exec_price * executed_qty * self._buy_commission_rate
            cost = exec_price * executed_qty + commission
            if self._balance < cost:
                return
            self._balance -= cost
            self._update_position(signal.symbol, executed_qty, exec_price)
        else:
            exec_price = price * (1 - self._slippage_rate)
            pos = self._positions.get(signal.symbol, {})
            executed_qty = min(signal.quantity, pos.get("quantity", 0))
            if executed_qty <= 0:
                return
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

    async def _calculate_equity(self) -> float:
        """현재 bar 시점의 자산 가치 (mark-to-market).

        미청산 포지션을 현재 bar 종가로 평가한다. 가격 조회가 실패
        (None/<=0/예외)하면 해당 포지션은 avg_price(원가)로 fallback하되
        symbol을 포함한 경고를 남긴다(조용히 숨기지 않는다).

        Note: 현재 bar 가격이 SSOT이므로 반드시 run 루프 안에서만 호출한다.
        루프 종료 후 호출하면 advance()가 올린 미래 봉을 보는 lookahead가 된다.
        """
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
        """성과 지표 계산.

        Args:
            final_equity: 마지막 시뮬레이션 봉의 mark-to-market equity.
                run()에서 equity_curve[-1] 기반으로 전달한다(재계산하지 않음).
        """
        from ante.backtest.metrics import calculate_metrics

        if not self._trades:
            return {}

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

    def get_trade_history(
        self,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """백테스트 중 누적된 가상 거래 이력을 최신순으로 반환.

        라이브 ``StrategyContext.get_trade_history`` 와 동일한 full dict shape
        (``trade_id``/``symbol``/``side``/``quantity``/``price``/``status``/
        ``order_type``/``reason``/``commission``/``timestamp``)를 제공해, 같은
        전략 코드가 라이브/백테스트에서 동일하게 동작하도록 parity를 맞춘다(#2075).

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
        # 원본 인덱스를 보존한 채 최신순(역순)으로 정렬한다. enumerate를 정렬
        # 전에 수행해 정렬/필터 후에도 trade_id가 결정적으로 유지되게 한다.
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
