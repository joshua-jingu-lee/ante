"""DataGoKrCollector — data.go.kr 전종목 일별 수집."""

from __future__ import annotations

import logging
from typing import Any

import polars as pl

from ante.data.normalizer import DataGoKrNormalizer
from ante.data.store import ParquetStore
from ante.feed.transform.validate import validate_all

logger = logging.getLogger(__name__)

# OHLCV 필수 검증 필드
OHLCV_REQUIRED_FIELDS = [
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
]


class DataGoKrCollector:
    """data.go.kr에서 특정 날짜 전종목 데이터를 수집한다.

    책임: API 호출 -> 검증 -> 정규화 -> 심볼별 저장.
    """

    def __init__(
        self,
        source: Any,
        normalizer: DataGoKrNormalizer | None = None,
    ) -> None:
        self._source = source
        self._normalizer = normalizer or DataGoKrNormalizer()

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, set[str], list[dict]]:
        """특정 날짜의 전종목 데이터를 수집한다.

        Returns:
            (기록 행 수, 수집된 심볼 집합, 경고 목록).
        """
        raw_items = await self._source.fetch(target_date)
        if not raw_items:
            logger.debug("data.go.kr: date=%s 데이터 없음", target_date)
            return 0, set(), []

        warns = self._validate(raw_items, target_date)
        df = pl.DataFrame(raw_items)
        df = self._deduplicate(df)

        rows_written, symbols = await self._normalize_and_store(
            df,
            store,
            target_date,
        )

        return rows_written, symbols, warns

    @staticmethod
    def _validate(
        raw_items: list[dict],
        target_date: str,
    ) -> list[dict]:
        """데이터를 검증하고 경고 목록을 반환한다."""
        validation = validate_all(raw_items, OHLCV_REQUIRED_FIELDS)
        warns: list[dict] = []
        for w in validation.warnings:
            warns.append(
                {
                    "date": target_date,
                    "source": "data_go_kr",
                    "type": "business_rule",
                    "message": w,
                }
            )
        return warns

    @staticmethod
    def _deduplicate(df: pl.DataFrame) -> pl.DataFrame:
        """srtnCd + basDt 기준 중복을 제거한다."""
        if "srtnCd" in df.columns and "basDt" in df.columns:
            return df.unique(subset=["srtnCd", "basDt"])
        return df

    async def _normalize_and_store(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        target_date: str,
    ) -> tuple[int, set[str]]:
        """OHLCV와 fundamental을 정규화하고 저장한다."""
        rows_written = 0
        symbols: set[str] = set()

        rows_written += await self._store_ohlcv(df, store, symbols)
        rows_written += await self._store_fundamental(df, store, symbols)

        logger.info(
            "data.go.kr 수집 완료: date=%s symbols=%d rows=%d",
            target_date,
            len(symbols),
            rows_written,
        )
        return rows_written, symbols

    async def _store_ohlcv(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        symbols: set[str],
    ) -> int:
        """OHLCV 데이터를 정규화하여 심볼별로 저장한다."""
        ohlcv_df = self._normalizer.normalize_ohlcv(df)
        if ohlcv_df.is_empty() or "symbol" not in ohlcv_df.columns:
            return 0

        rows = 0
        for sym in ohlcv_df["symbol"].unique().to_list():
            sym_df = ohlcv_df.filter(pl.col("symbol") == sym)
            await store.write(sym, "1d", sym_df, data_type="ohlcv")
            rows += len(sym_df)
            symbols.add(sym)
        return rows

    async def _store_fundamental(
        self,
        df: pl.DataFrame,
        store: ParquetStore,
        symbols: set[str],
    ) -> int:
        """fundamental 데이터를 정규화하여 심볼별로 저장한다."""
        fund_df = self._normalizer.normalize_fundamental(df)
        if fund_df.is_empty() or "symbol" not in fund_df.columns:
            return 0

        rows = 0
        for sym in fund_df["symbol"].unique().to_list():
            sym_df = fund_df.filter(pl.col("symbol") == sym)
            await store.write(sym, "krx", sym_df, data_type="fundamental")
            rows += len(sym_df)
            symbols.add(sym)
        return rows
