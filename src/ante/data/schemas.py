"""Data Pipeline — 정규화된 데이터 스키마 정의."""

from __future__ import annotations

import polars as pl

# 모든 시세 데이터의 공통 스키마 (OHLCV)
OHLCV_SCHEMA: dict[str, type[pl.DataType]] = {
    "timestamp": pl.Datetime("ns"),
    "symbol": pl.Utf8,
    "open": pl.Float64,
    "high": pl.Float64,
    "low": pl.Float64,
    "close": pl.Float64,
    "volume": pl.Int64,
    "amount": pl.Int64,
    "source": pl.Utf8,
}

OHLCV_COLUMNS: list[str] = list(OHLCV_SCHEMA.keys())

# 틱 데이터 스키마 (선택적 수집)
TICK_SCHEMA: dict[str, type[pl.DataType]] = {
    "timestamp": pl.Datetime("ns"),
    "symbol": pl.Utf8,
    "price": pl.Float64,
    "volume": pl.Int64,
    "side": pl.Utf8,
}

# 지원되는 타임프레임
TIMEFRAMES: list[str] = ["1m", "5m", "15m", "1h", "1d"]


def validate_ohlcv(df: pl.DataFrame) -> bool:
    """OHLCV DataFrame이 스키마에 부합하는지 검증."""
    required = {
        "timestamp",
        "symbol",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source",
    }
    return required.issubset(set(df.columns))
