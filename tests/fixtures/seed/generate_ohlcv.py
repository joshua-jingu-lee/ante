"""E2E 테스트용 샘플 OHLCV Parquet 데이터 생성기.

5일치 일봉 데이터를 생성하여 지정 경로에 저장한다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

import polars as pl


def generate_sample_ohlcv(
    symbol: str = "005930",
    days: int = 5,
    base_price: float = 70_000.0,
) -> pl.DataFrame:
    """샘플 OHLCV DataFrame 생성."""
    rows = []
    price = base_price
    now = datetime(2026, 3, 10, 9, 0, 0)

    for i in range(days):
        ts = now + timedelta(days=i)
        open_p = price
        high_p = price * 1.02
        low_p = price * 0.98
        close_p = price * (1.01 if i % 2 == 0 else 0.99)
        volume = 1_000_000 + i * 100_000

        rows.append(
            {
                "timestamp": ts,
                "symbol": symbol,
                "open": open_p,
                "high": high_p,
                "low": low_p,
                "close": close_p,
                "volume": volume,
                "source": "seed",
            }
        )
        price = close_p

    return pl.DataFrame(rows).cast(
        {
            "timestamp": pl.Datetime("ns"),
            "symbol": pl.Utf8,
            "open": pl.Float64,
            "high": pl.Float64,
            "low": pl.Float64,
            "close": pl.Float64,
            "volume": pl.Int64,
            "source": pl.Utf8,
        }
    )


def write_sample_parquet(output_dir: Path, symbol: str = "005930") -> Path:
    """샘플 OHLCV Parquet 파일을 생성하고 경로를 반환한다."""
    df = generate_sample_ohlcv(symbol=symbol)
    parquet_dir = output_dir / "ohlcv" / "1d" / symbol
    parquet_dir.mkdir(parents=True, exist_ok=True)
    filepath = parquet_dir / "2026-03.parquet"
    df.write_parquet(filepath, compression="snappy")
    return filepath
