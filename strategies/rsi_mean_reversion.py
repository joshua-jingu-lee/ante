"""RSI 평균회귀 전략.

RSI(14)가 과매도(30 이하) 구간에서 매수,
과매수(70 이상) 구간에서 매도 시그널을 발생시킨다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.2.0"


class RsiMeanReversionStrategy(Strategy):
    """RSI 기반 평균회귀 전략."""

    meta = StrategyMeta(
        name="rsi_mean_reversion",
        version=STRATEGY_VERSION,
        description="RSI(14) 과매도 매수 / 과매수 매도 평균회귀",
        author_name="test-agent-001",
        author_id="test-agent-001",
        symbols=["005930", "000660"],
        timeframe="1d",
        exchange="KRX",
    )

    RSI_PERIOD = 14
    OVERSOLD = 30.0
    OVERBOUGHT = 70.0

    def get_params(self) -> dict[str, Any]:
        """백테스트 최적화 파라미터 반환."""
        return {
            "rsi_period": self.RSI_PERIOD,
            "oversold": self.OVERSOLD,
            "overbought": self.OVERBOUGHT,
        }

    def get_param_schema(self) -> dict[str, str]:
        """파라미터 설명 반환."""
        return {
            "rsi_period": "RSI 계산 기간",
            "oversold": "과매도 판단 RSI 임계값",
            "overbought": "과매수 판단 RSI 임계값",
        }

    def get_rationale(self) -> str:
        """투자 근거 반환."""
        return (
            "RSI가 극단적 과매도/과매수 영역에 도달하면 "
            "평균으로 회귀하는 경향을 이용한 역추세 전략. "
            "단기 과매도 반등과 과매수 조정을 포착한다."
        )

    def get_risks(self) -> list[str]:
        """리스크 항목 반환."""
        return [
            "강한 추세장에서 역추세 진입으로 손실 확대 가능",
            "RSI 단일 지표 의존으로 거짓 신호 발생 가능",
            "급락장에서 과매도 매수 후 추가 하락 위험",
        ]

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """RSI 기반 시그널 생성."""
        signals: list[Signal] = []

        for symbol in self.meta.symbols:
            ohlcv = await self.ctx.get_ohlcv(symbol, "1d", limit=self.RSI_PERIOD + 5)
            if ohlcv.is_empty() or len(ohlcv) < self.RSI_PERIOD + 1:
                continue

            closes = ohlcv["close"].to_list()
            rsi = self._calc_rsi(closes, self.RSI_PERIOD)
            if rsi is None:
                continue

            if rsi <= self.OVERSOLD:
                signals.append(
                    Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=1.0,
                        order_type="market",
                        reason=f"RSI {rsi:.1f} <= {self.OVERSOLD} 과매도 매수",
                    )
                )
            elif rsi >= self.OVERBOUGHT:
                signals.append(
                    Signal(
                        symbol=symbol,
                        side="sell",
                        quantity=1.0,
                        order_type="market",
                        reason=f"RSI {rsi:.1f} >= {self.OVERBOUGHT} 과매수 매도",
                    )
                )

        return signals

    @staticmethod
    def _calc_rsi(prices: list[float], period: int) -> float | None:
        """단순 RSI 계산."""
        if len(prices) < period + 1:
            return None

        changes = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
        recent = changes[-period:]

        gains = [c for c in recent if c > 0]
        losses = [-c for c in recent if c < 0]

        avg_gain = sum(gains) / period if gains else 0.0
        avg_loss = sum(losses) / period if losses else 0.0

        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
