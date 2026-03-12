"""Data Pipeline — 외부 소스에서 과거 데이터를 Parquet에 주입."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

if TYPE_CHECKING:
    from ante.data.normalizer import DataNormalizer
    from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)


class DataInjector:
    """외부 소스(CSV, API 등)에서 과거 데이터를 정규화하여 Parquet에 주입."""

    def __init__(self, store: ParquetStore, normalizer: DataNormalizer) -> None:
        self._store = store
        self._normalizer = normalizer

    async def inject_csv(
        self,
        filepath: str | Path,
        symbol: str,
        timeframe: str,
        source: str = "external",
        format_hint: str | None = None,
    ) -> int:
        """CSV 파일에서 데이터 주입.

        Args:
            filepath: CSV 파일 경로
            symbol: 종목 코드
            timeframe: 타임프레임
            source: 데이터 소스 식별자
            format_hint: 소스별 컬럼 매핑 힌트

        Returns:
            주입된 행 수
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {filepath}")

        df = pl.read_csv(str(filepath))
        if df.is_empty():
            logger.warning("Empty CSV file: %s", filepath)
            return 0

        normalized = self._normalizer.normalize(
            df, source=source, format_hint=format_hint
        )
        normalized = normalized.with_columns(pl.lit(symbol).alias("symbol"))

        await self._store.write(symbol, timeframe, normalized)
        logger.info(
            "Injected %d rows from %s for %s/%s",
            len(normalized),
            filepath.name,
            symbol,
            timeframe,
        )
        return len(normalized)

    async def inject_dataframe(
        self,
        df: pl.DataFrame,
        symbol: str,
        timeframe: str,
        source: str = "external",
    ) -> int:
        """DataFrame을 직접 주입.

        Args:
            df: 정규화된 OHLCV DataFrame
            symbol: 종목 코드
            timeframe: 타임프레임
            source: 데이터 소스 식별자

        Returns:
            주입된 행 수
        """
        if df.is_empty():
            return 0

        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit(symbol).alias("symbol"))
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(source).alias("source"))

        await self._store.write(symbol, timeframe, df)
        logger.info("Injected %d rows for %s/%s", len(df), symbol, timeframe)
        return len(df)
