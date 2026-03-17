"""CSV 파일에서 데이터를 수동 주입하는 모듈 (ante feed inject).

DataInjector(ante.data)에서 이관된 FeedInjector.
외부 파일(CSV)이나 DataFrame을 정규화 + 4계층 검증 후 ParquetStore에 저장한다.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from ante.feed.transform.validate import validate_business, validate_schema

if TYPE_CHECKING:
    from ante.data.normalizer import DataNormalizer
    from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)

# inject 시 스키마 검증에 사용할 OHLCV 필수 필드
_OHLCV_REQUIRED_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]


class FeedInjector:
    """외부 CSV 파일이나 DataFrame에서 과거 데이터를 DataStore에 주입한다.

    동작 순서:
      1. CSV 파일 로드 (또는 DataFrame 직접 수신)
      2. Normalizer로 스키마 정규화 (source에 따라 선택)
      3. 4계층 검증 (transform/validate.py) — 스키마 + 비즈니스 계층
      4. ParquetStore.write()로 저장
    """

    def __init__(self, store: ParquetStore, normalizer: DataNormalizer) -> None:
        self._store = store
        self._normalizer = normalizer

    async def inject_csv(
        self,
        path: str | Path,
        symbol: str,
        timeframe: str = "1d",
        source: str = "external",
        format_hint: str | None = None,
    ) -> int:
        """CSV 파일을 읽어 DataStore에 주입한다.

        Args:
            path: CSV 파일 경로.
            symbol: 종목 코드 (6자리).
            timeframe: 타임프레임 (기본값: '1d').
            source: 데이터 소스 식별자 (normalizer 선택에 사용).
            format_hint: 소스별 컬럼 매핑 힌트.

        Returns:
            주입된 행 수.

        Raises:
            FileNotFoundError: CSV 파일이 존재하지 않을 때.
            ValueError: 스키마 검증 실패 시.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV 파일을 찾을 수 없습니다: {path}")

        df = pl.read_csv(str(path))
        if df.is_empty():
            logger.warning("빈 CSV 파일: %s", path)
            return 0

        # 정규화
        normalized = self._normalizer.normalize(
            df, source=source, format_hint=format_hint
        )
        normalized = normalized.with_columns(pl.lit(symbol).alias("symbol"))

        # 4계층 검증 (스키마 + 비즈니스)
        self._validate(normalized)

        await self._store.write(symbol, timeframe, normalized)
        logger.info(
            "CSV 주입 완료: %d행, %s → %s/%s",
            len(normalized),
            path.name,
            symbol,
            timeframe,
        )
        return len(normalized)

    async def inject_dataframe(
        self,
        df: pl.DataFrame,
        symbol: str,
        timeframe: str = "1d",
        source: str = "external",
    ) -> int:
        """DataFrame을 직접 주입한다.

        Args:
            df: OHLCV DataFrame.
            symbol: 종목 코드.
            timeframe: 타임프레임 (기본값: '1d').
            source: 데이터 소스 식별자.

        Returns:
            주입된 행 수.

        Raises:
            ValueError: 스키마 검증 실패 시.
        """
        if df.is_empty():
            return 0

        if "symbol" not in df.columns:
            df = df.with_columns(pl.lit(symbol).alias("symbol"))
        if "source" not in df.columns:
            df = df.with_columns(pl.lit(source).alias("source"))

        # 4계층 검증 (스키마 + 비즈니스)
        self._validate(df)

        await self._store.write(symbol, timeframe, df)
        logger.info("DataFrame 주입 완료: %d행, %s/%s", len(df), symbol, timeframe)
        return len(df)

    def _validate(self, df: pl.DataFrame) -> None:
        """DataFrame에 대해 스키마 + 비즈니스 계층 검증을 수행한다.

        전송/구문 계층은 이미 CSV/DataFrame 로드 단계에서 통과했으므로
        스키마(3계층)와 비즈니스(4계층)만 적용한다.

        Args:
            df: 검증할 DataFrame.

        Raises:
            ValueError: 스키마 검증 실패 시.
        """
        records = df.to_dicts()

        # 스키마 계층 검증
        schema_result = validate_schema(records, _OHLCV_REQUIRED_FIELDS)
        if not schema_result.passed:
            raise ValueError(f"스키마 검증 실패: {'; '.join(schema_result.errors)}")

        # 비즈니스 계층 검증 (경고만, 저장은 허용)
        business_result = validate_business(records)
        for warning in business_result.warnings:
            logger.warning("비즈니스 검증 경고: %s", warning)
