"""Data Pipeline — 다양한 소스의 데이터를 통일된 스키마로 정규화.

소스별 Normalizer 클래스 패턴: BaseNormalizer ABC를 상속하여
각 데이터 소스(KIS, Yahoo 등)마다 정규화 로직을 캡슐화한다.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import polars as pl

from ante.data.schemas import OHLCV_COLUMNS

logger = logging.getLogger(__name__)


class BaseNormalizer(ABC):
    """데이터 정규화 인터페이스.

    모든 소스별 Normalizer가 구현해야 하는 ABC.
    """

    @property
    @abstractmethod
    def source_name(self) -> str:
        """데이터 소스 식별자 (예: 'kis', 'yahoo')."""
        ...

    @property
    @abstractmethod
    def column_mapping(self) -> dict[str, str]:
        """소스 컬럼명 → OHLCV 표준 컬럼명 매핑."""
        ...

    def normalize(self, df: pl.DataFrame) -> pl.DataFrame:
        """DataFrame을 OHLCV 스키마로 정규화.

        Args:
            df: 원본 DataFrame.

        Returns:
            OHLCV 스키마에 맞춰 정규화된 DataFrame.
        """
        # 컬럼 이름 매핑
        rename_map = {
            src: dst for src, dst in self.column_mapping.items() if src in df.columns
        }
        if rename_map:
            df = df.rename(rename_map)

        # 소스별 추가 변환 (서브클래스 오버라이드 가능)
        df = self.transform(df)

        # timestamp 정규화
        df = _normalize_timestamp(df)

        # 숫자 컬럼 타입 변환
        for col in ("open", "high", "low", "close"):
            if col in df.columns:
                df = df.with_columns(pl.col(col).cast(pl.Float64))
        if "volume" in df.columns:
            df = df.with_columns(pl.col("volume").cast(pl.Int64))

        # source 컬럼
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(self.source_name).alias("source"))

        # symbol 컬럼 (호출자가 채움)
        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit("").alias("symbol"))

        # 스키마 컬럼만 선택
        available = [c for c in OHLCV_COLUMNS if c in df.columns]
        return df.select(available).sort("timestamp")

    def transform(self, df: pl.DataFrame) -> pl.DataFrame:
        """소스별 추가 변환 훅. 기본은 무변환."""
        return df


class KISNormalizer(BaseNormalizer):
    """한국투자증권(KIS) API 응답 정규화."""

    @property
    def source_name(self) -> str:
        return "kis"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "stck_bsop_date": "date",
            "stck_clpr": "close",
            "stck_oprc": "open",
            "stck_hgpr": "high",
            "stck_lwpr": "low",
            "acml_vol": "volume",
        }

    def transform(self, df: pl.DataFrame) -> pl.DataFrame:
        """KIS date 컬럼을 timestamp로 변환."""
        if "date" in df.columns and "timestamp" not in df.columns:
            df = df.rename({"date": "timestamp"})
        return df


class YahooNormalizer(BaseNormalizer):
    """Yahoo Finance 데이터 정규화."""

    @property
    def source_name(self) -> str:
        return "yahoo"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "Date": "timestamp",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume",
        }


class DefaultNormalizer(BaseNormalizer):
    """범용 정규화. 일반적인 컬럼명(date, datetime 등)을 매핑."""

    @property
    def source_name(self) -> str:
        return "external"

    @property
    def column_mapping(self) -> dict[str, str]:
        return {
            "date": "timestamp",
            "datetime": "timestamp",
            "time": "timestamp",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
            "vol": "volume",
        }


# ── Normalizer 레지스트리 ────────────────────────────

NORMALIZER_REGISTRY: dict[str, type[BaseNormalizer]] = {
    "kis": KISNormalizer,
    "yahoo": YahooNormalizer,
    "default": DefaultNormalizer,
    "external": DefaultNormalizer,
}


def get_normalizer(source: str) -> BaseNormalizer:
    """소스명으로 Normalizer 인스턴스를 조회.

    Args:
        source: 데이터 소스 식별자 (예: "kis", "yahoo", "external").

    Returns:
        해당 소스의 Normalizer 인스턴스. 미등록 시 DefaultNormalizer.
    """
    cls = NORMALIZER_REGISTRY.get(source, DefaultNormalizer)
    return cls()


def register_normalizer(source: str, cls: type[BaseNormalizer]) -> None:
    """커스텀 Normalizer를 레지스트리에 등록.

    새 거래소 추가 시 이 함수로 등록하면 DataNormalizer가 자동 인식.
    """
    NORMALIZER_REGISTRY[source] = cls


# ── 하위 호환 DataNormalizer 파사드 ──────────────────

# 기존 COLUMN_MAPPINGS 유지 (하위 호환)
COLUMN_MAPPINGS: dict[str, dict[str, str]] = {
    "kis": KISNormalizer().column_mapping,
    "yahoo": YahooNormalizer().column_mapping,
    "default": DefaultNormalizer().column_mapping,
}


class DataNormalizer:
    """하위 호환 파사드. 내부적으로 소스별 Normalizer에 위임."""

    def normalize(
        self,
        df: pl.DataFrame,
        source: str = "external",
        format_hint: str | None = None,
    ) -> pl.DataFrame:
        """DataFrame을 OHLCV 스키마로 정규화.

        Args:
            df: 원본 DataFrame.
            source: 데이터 소스 식별자.
            format_hint: 소스별 컬럼 매핑 힌트. None이면 source 사용.

        Returns:
            OHLCV 스키마에 맞춰 정규화된 DataFrame.
        """
        has_source = "source" in df.columns
        key = format_hint or source
        normalizer = get_normalizer(key)
        result = normalizer.normalize(df)
        # source 값: 원본에 없었을 때만 source 파라미터로 덮어쓰기
        if not has_source and "source" in result.columns:
            result = result.with_columns(pl.lit(source).alias("source"))
        return result

    @staticmethod
    def _normalize_timestamp(df: pl.DataFrame) -> pl.DataFrame:
        """timestamp 컬럼을 Datetime[ns]로 정규화."""
        return _normalize_timestamp(df)


# ── 공통 유틸 ────────────────────────────────────────


def _normalize_timestamp(df: pl.DataFrame) -> pl.DataFrame:
    """timestamp 컬럼을 Datetime[ns, UTC]로 정규화."""
    if "timestamp" not in df.columns:
        raise ValueError("DataFrame에 timestamp 컬럼이 없습니다.")

    ts_dtype = df["timestamp"].dtype
    if ts_dtype == pl.Utf8:
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
