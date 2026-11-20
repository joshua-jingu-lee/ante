"""Data Pipeline — 정규화된 데이터 스키마 정의."""

from __future__ import annotations

import polars as pl

from ante.core.market_data_vocab import CANONICAL_TIMEFRAMES

OHLCV_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
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

TICK_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "timestamp": pl.Datetime("ns"),
    "symbol": pl.Utf8,
    "price": pl.Float64,
    "volume": pl.Int64,
    "side": pl.Utf8,
}

FUNDAMENTAL_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "date": pl.Date,
    "available_date": pl.Date,
    "symbol": pl.Utf8,
    "market_cap": pl.Int64,
    "shares_listed": pl.Int64,
    "shares_outstanding": pl.Int64,
    "foreign_ratio": pl.Float64,
    "foreign_shares": pl.Int64,
    "per": pl.Float64,
    "pbr": pl.Float64,
    "eps": pl.Float64,
    "bps": pl.Float64,
    "roe": pl.Float64,
    "debt_to_equity": pl.Float64,
    "revenue": pl.Int64,
    "net_income": pl.Int64,
    "div_yield": pl.Float64,
    "dps": pl.Float64,
    "source": pl.Utf8,
}

FUNDAMENTAL_COLUMNS: list[str] = list(FUNDAMENTAL_SCHEMA.keys())

TIMEFRAMES: list[str] = list(CANONICAL_TIMEFRAMES)


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


def validate_fundamental(df: pl.DataFrame) -> bool:
    """FUNDAMENTAL DataFrame이 스키마에 부합하는지 검증.

    필수 필드: date, symbol, source만 필수. 나머지는 null 허용.
    """
    required = {"date", "symbol", "source"}
    return required.issubset(set(df.columns))
