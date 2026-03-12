"""Data Pipeline — 다양한 소스의 데이터를 통일된 스키마로 정규화."""

from __future__ import annotations

import logging

import polars as pl

from ante.data.schemas import OHLCV_COLUMNS

logger = logging.getLogger(__name__)

# 소스별 컬럼 매핑 규칙
COLUMN_MAPPINGS: dict[str, dict[str, str]] = {
    "kis": {
        "stck_bsop_date": "date",
        "stck_clpr": "close",
        "stck_oprc": "open",
        "stck_hgpr": "high",
        "stck_lwpr": "low",
        "acml_vol": "volume",
    },
    "yahoo": {
        "Date": "timestamp",
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    },
    "default": {
        "date": "timestamp",
        "datetime": "timestamp",
        "time": "timestamp",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
        "vol": "volume",
    },
}


class DataNormalizer:
    """다양한 소스의 DataFrame을 OHLCV 공통 스키마로 정규화."""

    def normalize(
        self,
        df: pl.DataFrame,
        source: str = "external",
        format_hint: str | None = None,
    ) -> pl.DataFrame:
        """DataFrame을 OHLCV 스키마로 정규화.

        Args:
            df: 원본 DataFrame
            source: 데이터 소스 식별자 ("kis", "yahoo", "external" 등)
            format_hint: 소스별 컬럼 매핑 힌트. None이면 자동 감지.

        Returns:
            OHLCV 스키마에 맞춰 정규화된 DataFrame.
        """
        mapping_key = format_hint or source
        mapping = COLUMN_MAPPINGS.get(mapping_key, COLUMN_MAPPINGS["default"])

        # 컬럼 이름 매핑 적용
        rename_map: dict[str, str] = {}
        for src_col, dst_col in mapping.items():
            if src_col in df.columns:
                rename_map[src_col] = dst_col

        if rename_map:
            df = df.rename(rename_map)

        # timestamp 컬럼 처리
        df = self._normalize_timestamp(df)

        # 숫자 컬럼 타입 변환
        for col in ["open", "high", "low", "close"]:
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))

        if "volume" in df.columns:
            df = df.with_columns(pl.col("volume").cast(pl.Int64))

        # source 컬럼 추가
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(source).alias("source"))

        # symbol 컬럼 없으면 빈 문자열 (호출자가 채움)
        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit("").alias("symbol"))

        # 필요한 컬럼만 선택 (존재하는 것만)
        available = [c for c in OHLCV_COLUMNS if c in df.columns]
        df = df.select(available)

        return df.sort("timestamp")

    def _normalize_timestamp(self, df: pl.DataFrame) -> pl.DataFrame:
        """timestamp 컬럼을 Datetime[ns]로 정규화."""
        if "timestamp" not in df.columns:
            raise ValueError("DataFrame에 timestamp 컬럼이 없습니다.")

        ts_dtype = df["timestamp"].dtype
        if ts_dtype == pl.Utf8:
            # 문자열 → datetime 변환 시도
            df = df.with_columns(pl.col("timestamp").str.to_datetime(time_zone="UTC"))
        elif ts_dtype == pl.Date:
            df = df.with_columns(
                pl.col("timestamp").cast(pl.Datetime("ns")).dt.replace_time_zone("UTC")
            )
        elif isinstance(ts_dtype, pl.Datetime):
            if ts_dtype.time_zone is None:
                df = df.with_columns(pl.col("timestamp").dt.replace_time_zone("UTC"))
        else:
            raise ValueError(f"지원하지 않는 timestamp 타입: {ts_dtype}")

        return df
