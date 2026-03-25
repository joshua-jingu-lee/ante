"""이동평균 크로스오버 전략.

단기(5일) 이동평균이 장기(20일) 이동평균을 상향 돌파하면 매수,
하향 돌파하면 매도 시그널을 발생시킨다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.2.0"


class MaCrossoverStrategy(Strategy):
    """이동평균 골든/데드 크로스 전략."""

    meta = StrategyMeta(
        name="ma_crossover",
        version=STRATEGY_VERSION,
        description="MA(5/20) 골든크로스 매수 / 데드크로스 매도",
        author_name="test-agent-001",
        author_id="test-agent-001",
        symbols=["005930"],
        timeframe="1d",
        exchange="KRX",
    )

    SHORT_PERIOD = 5
    LONG_PERIOD = 20

    def get_params(self) -> dict[str, Any]:
        """백테스트 최적화 파라미터 반환."""
        return {
            "short_period": self.SHORT_PERIOD,
            "long_period": self.LONG_PERIOD,
        }

    def get_param_schema(self) -> dict[str, str]:
        """파라미터 설명 반환."""
        return {
            "short_period": "단기 이동평균 기간",
            "long_period": "장기 이동평균 기간",
        }

    def get_rationale(self) -> str:
        """투자 근거 반환."""
        return (
            "단기 이동평균이 장기 이동평균을 상향 돌파(골든크로스)하면 "
            "상승 추세 전환으로 판단하여 매수하고, "
            "하향 돌파(데드크로스)하면 하락 추세 전환으로 "
            "판단하여 매도하는 추세추종 전략."
        )

    def get_risks(self) -> list[str]:
        """리스크 항목 반환."""
        return [
            "횡보장에서 잦은 크로스로 거짓 신호 다발 가능",
            "이동평균 후행 특성으로 진입/청산 타이밍 지연",
            "급등/급락 시 신호 발생이 늦어 수익 기회 일부 상실",
        ]

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """이동평균 크로스오버 시그널 생성."""
        signals: list[Signal] = []

        for symbol in self.meta.symbols:
            ohlcv = await self.ctx.get_ohlcv(symbol, "1d", limit=self.LONG_PERIOD + 2)
            if ohlcv.is_empty() or len(ohlcv) < self.LONG_PERIOD + 1:
                continue

            prices = ohlcv["close"].to_list()

            short_now = sum(prices[-self.SHORT_PERIOD :]) / self.SHORT_PERIOD
            short_prev = sum(prices[-self.SHORT_PERIOD - 1 : -1]) / self.SHORT_PERIOD
            long_now = sum(prices[-self.LONG_PERIOD :]) / self.LONG_PERIOD
            long_prev = sum(prices[-self.LONG_PERIOD - 1 : -1]) / self.LONG_PERIOD

            # 골든크로스: 단기가 장기를 상향 돌파
            if short_prev <= long_prev and short_now > long_now:
                signals.append(
                    Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=1.0,
                        order_type="market",
                        reason=(
                            f"골든크로스 MA{self.SHORT_PERIOD}={short_now:.0f}"
                            f" > MA{self.LONG_PERIOD}={long_now:.0f}"
                        ),
                    )
                )
            # 데드크로스: 단기가 장기를 하향 돌파
            elif short_prev >= long_prev and short_now < long_now:
                signals.append(
                    Signal(
                        symbol=symbol,
                        side="sell",
                        quantity=1.0,
                        order_type="market",
                        reason=(
                            f"데드크로스 MA{self.SHORT_PERIOD}={short_now:.0f}"
                            f" < MA{self.LONG_PERIOD}={long_now:.0f}"
                        ),
                    )
                )

        return signals
