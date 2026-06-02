"""Data Pipeline — 정규화된 데이터 스키마 정의."""

from __future__ import annotations

import polars as pl

from ante.core.market_data_vocab import CANONICAL_TIMEFRAMES

# 모든 시세 데이터의 공통 스키마 (OHLCV)
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

# 틱 데이터 스키마 (선택적 수집)
TICK_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "timestamp": pl.Datetime("ns"),
    "symbol": pl.Utf8,
    "price": pl.Float64,
    "volume": pl.Int64,
    "side": pl.Utf8,
}

# 재무 데이터 스키마 (DART, data.go.kr 등)
#
# `date`는 보고 기간말일(period_end, 분기말 3/31·6/30·9/30·12/31)이고,
# `available_date`는 그 데이터가 실제로 **알 수 있게 된 시점**(point-in-time,
# DART 공시 접수일 rcept_dt)이다(#2010). lookahead bias를 피하려면 소비자가
# `available_date` 기준 as-of join을 해야 하지만, consumer 전환은 별도 이슈
# (#2067)이며 본 스키마는 producer가 `available_date`를 **저장**만 한다.
# `available_date`는 nullable이다 — 소스(rcept_no)가 없거나 접수일 파싱이
# 실패한 행은 null로 강등되고, data.go.kr 등 DART가 아닌 소스 행에서도 null이다.
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

# 지원되는 타임프레임 — 코드 레벨 SSOT(`ante.core.market_data_vocab`)에
# 위임한다. 타입(`list`)·순서는 위임 전과 동일하다 — 순서 의존 소비자
# (`src/ante/cli/commands/data.py` iteration)를 위해 계약상 고정 순서를
# 보존한다(#1613 narrow-scope: behavior-preserving).
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
