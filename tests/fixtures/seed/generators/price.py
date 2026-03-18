"""GBM(기하 브라운 운동) 기반 가상 주가 생성기.

고정 시드로 재현 가능한 일봉 데이터를 생성한다.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class PriceConfig:
    """종목별 주가 생성 설정."""

    symbol: str
    name: str
    base_price: float
    daily_vol: float  # 일별 변동성 (0.015 = 1.5%)
    trend: float  # 일별 추세 (0.0005 = +0.05%/일)


@dataclass(frozen=True)
class DailyPrice:
    """하루치 OHLCV 데이터."""

    date: date
    symbol: str
    open: float
    high: float
    low: float
    close: float
    volume: int


# 한국 대형주 프리셋
STOCK_PRESETS: dict[str, PriceConfig] = {
    "005930": PriceConfig("005930", "삼성전자", 72000, 0.012, 0.0003),
    "000660": PriceConfig("000660", "SK하이닉스", 155000, 0.018, 0.0005),
    "035420": PriceConfig("035420", "NAVER", 210000, 0.015, -0.0002),
    "035720": PriceConfig("035720", "카카오", 52000, 0.020, -0.0003),
    "005380": PriceConfig("005380", "현대차", 215000, 0.014, 0.0002),
    "006400": PriceConfig("006400", "삼성SDI", 350000, 0.022, 0.0001),
}

# 종목명 조회용
SYMBOL_NAMES: dict[str, str] = {cfg.symbol: cfg.name for cfg in STOCK_PRESETS.values()}


def _tick_round(price: float, symbol: str) -> float:
    """한국 주식 호가 단위로 반올림."""
    if price < 2000:
        tick = 1
    elif price < 5000:
        tick = 5
    elif price < 20000:
        tick = 10
    elif price < 50000:
        tick = 50
    elif price < 200000:
        tick = 100
    elif price < 500000:
        tick = 500
    else:
        tick = 1000
    return round(price / tick) * tick


def _is_trading_day(d: date) -> bool:
    """주말을 제외한 거래일 판정 (공휴일 미반영)."""
    return d.weekday() < 5


def generate_daily_prices(
    config: PriceConfig,
    days: int = 60,
    start_date: date | None = None,
    seed: int | None = None,
) -> list[DailyPrice]:
    """GBM으로 일봉 데이터를 생성한다.

    Args:
        config: 종목 설정.
        days: 생성할 거래일 수.
        start_date: 시작 날짜. None이면 오늘 기준 days만큼 이전.
        seed: 랜덤 시드 (고정 시 재현 가능).

    Returns:
        거래일 수만큼의 DailyPrice 리스트.
    """
    rng = random.Random(seed)

    if start_date is None:
        # 거래일 기준으로 역산
        start_date = date.today() - timedelta(days=int(days * 1.5))

    prices: list[DailyPrice] = []
    price = config.base_price
    current = start_date

    while len(prices) < days:
        if not _is_trading_day(current):
            current += timedelta(days=1)
            continue

        # GBM: dS = S * (mu*dt + sigma*dW)
        z = rng.gauss(0, 1)
        log_return = config.trend + config.daily_vol * z
        new_price = price * math.exp(log_return)

        open_p = _tick_round(price, config.symbol)
        close_p = _tick_round(new_price, config.symbol)

        # 고가/저가: open-close 범위 + 추가 변동
        intra_high = max(open_p, close_p) * (1 + rng.uniform(0, config.daily_vol * 0.5))
        intra_low = min(open_p, close_p) * (1 - rng.uniform(0, config.daily_vol * 0.5))
        high_p = _tick_round(intra_high, config.symbol)
        low_p = _tick_round(intra_low, config.symbol)

        # 거래량: 기본 100만 ± 30%
        volume = int(1_000_000 * (1 + rng.uniform(-0.3, 0.3)))

        prices.append(
            DailyPrice(
                date=current,
                symbol=config.symbol,
                open=open_p,
                high=high_p,
                low=low_p,
                close=close_p,
                volume=volume,
            )
        )

        price = new_price
        current += timedelta(days=1)

    return prices


def generate_multi_stock_prices(
    symbols: list[str],
    days: int = 60,
    start_date: date | None = None,
    seed: int = 42,
) -> dict[str, list[DailyPrice]]:
    """여러 종목의 주가를 일괄 생성한다.

    각 종목은 seed + 종목 인덱스를 시드로 사용하여 독립적이면서 재현 가능하다.
    """
    result: dict[str, list[DailyPrice]] = {}
    for i, symbol in enumerate(symbols):
        config = STOCK_PRESETS[symbol]
        result[symbol] = generate_daily_prices(
            config, days=days, start_date=start_date, seed=seed + i
        )
    return result
