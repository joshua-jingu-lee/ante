"""PriceSimulator — GBM 기반 가격 시뮬레이션 엔진.

Test 브로커에서 사용할 현실적 가격 변동 엔진.
시드 생성기의 GBM 로직을 재활용하되, 틱 단위(초 단위) 변동을 지원한다.
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# KRX 하루 거래 시간: 09:00~15:30 = 6.5시간 = 23,400초
KRX_TRADING_SECONDS = 23_400


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
