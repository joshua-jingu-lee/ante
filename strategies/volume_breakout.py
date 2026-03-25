"""거래량 돌파 전략.

당일 거래량이 20일 평균 거래량의 2배를 초과하고
종가가 전일 대비 상승하면 매수 시그널을 발생시킨다.
"""

from __future__ import annotations

from typing import Any

from ante.strategy.base import Signal, Strategy, StrategyMeta

STRATEGY_VERSION = "0.2.0"


class VolumeBreakoutStrategy(Strategy):
    """거래량 급증 돌파 전략."""

    meta = StrategyMeta(
        name="volume_breakout",
        version=STRATEGY_VERSION,
        description="거래량 2배 돌파 + 가격 상승 시 매수",
        author_name="test-agent-001",
        author_id="test-agent-001",
        symbols=["005930", "000660", "035420"],
        timeframe="1d",
        exchange="KRX",
    )

    LOOKBACK = 20
    VOLUME_MULTIPLIER = 2.0

    def get_params(self) -> dict[str, Any]:
        """백테스트 최적화 파라미터 반환."""
        return {
            "lookback": self.LOOKBACK,
            "volume_multiplier": self.VOLUME_MULTIPLIER,
        }

    def get_param_schema(self) -> dict[str, str]:
        """파라미터 설명 반환."""
        return {
            "lookback": "평균 거래량 계산 기간 (일)",
            "volume_multiplier": "거래량 돌파 배수 기준",
        }

    def get_rationale(self) -> str:
        """투자 근거 반환."""
        return (
            "거래량이 평균 대비 급증하면서 가격이 상승하는 종목은 "
            "기관/외국인 등 큰 손의 매집 신호일 가능성이 높다. "
            "거래량 돌파와 가격 상승이 동시에 발생하는 시점을 포착하여 매수한다."
        )

    def get_risks(self) -> list[str]:
        """리스크 항목 반환."""
        return [
            "거래량 급증이 단발성 이벤트(뉴스 등)일 경우 후속 상승 부재",
            "매수 전용 전략으로 하락장 대응 수단 부재",
            "대량 매도에 의한 거래량 급증을 매수 신호로 오인할 가능성",
        ]

    async def on_step(self, context: dict[str, Any]) -> list[Signal]:
        """거래량 돌파 시그널 생성."""
        signals: list[Signal] = []

        for symbol in self.meta.symbols:
            ohlcv = await self.ctx.get_ohlcv(symbol, "1d", limit=self.LOOKBACK + 2)
            if ohlcv.is_empty() or len(ohlcv) < self.LOOKBACK + 1:
                continue

            volumes = ohlcv["volume"].to_list()
            closes = ohlcv["close"].to_list()

            avg_volume = sum(volumes[-self.LOOKBACK - 1 : -1]) / self.LOOKBACK
            current_volume = volumes[-1]
            price_change = closes[-1] - closes[-2]

            if avg_volume == 0:
                continue

            volume_ratio = current_volume / avg_volume

            if volume_ratio >= self.VOLUME_MULTIPLIER and price_change > 0:
                signals.append(
                    Signal(
                        symbol=symbol,
                        side="buy",
                        quantity=1.0,
                        order_type="market",
                        reason=(
                            f"거래량 돌파 {volume_ratio:.1f}x"
                            f" (>{self.VOLUME_MULTIPLIER}x)"
                            " + 가격 상승"
                        ),
                    )
                )

        return signals
