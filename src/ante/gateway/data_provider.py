"""LiveDataProvider — 라이브 모드에서 전략에 데이터를 제공."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import polars as pl

from ante.strategy.base import DataProvider

if TYPE_CHECKING:
    from ante.data.store import ParquetStore
    from ante.gateway.gateway import APIGateway

logger = logging.getLogger(__name__)

# OHLCV DataFrame 표준 컬럼 (DataProvider 프로토콜)
_OHLCV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


def _dicts_to_ohlcv_df(records: list[dict[str, Any]]) -> pl.DataFrame:
    """list[dict] → Polars DataFrame 변환 (OHLCV 표준 컬럼만 추출)."""
    if not records:
        return pl.DataFrame(schema={col: pl.Float64 for col in _OHLCV_COLUMNS})
    return pl.DataFrame(records)


class LiveDataProvider(DataProvider):
    """라이브 모드 DataProvider. ParquetStore + APIGateway 조합.

    과거 봉 데이터는 ParquetStore에서 읽고, 현재가는 APIGateway 캐시를 활용한다.
    ParquetStore에 데이터가 없으면 APIGateway 경유로 폴백한다.

    Note: DataProvider 인터페이스 준수를 위해 async def를 유지한다.
    """

    def __init__(
        self,
        gateway: APIGateway,
        parquet_store: ParquetStore | None = None,
    ) -> None:
        self._gateway = gateway
        self._store = parquet_store

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> pl.DataFrame:
        """OHLCV 데이터 조회 (ParquetStore 우선, APIGateway 폴백).

        1. ParquetStore가 주입되어 있으면 과거 봉 데이터를 읽는다.
        2. ParquetStore에 데이터가 없으면 APIGateway 경유로 폴백한다.
        3. 둘 다 데이터가 없으면 빈 DataFrame을 반환한다.

        Returns:
            Polars DataFrame with columns: timestamp, open, high, low, close, volume.
        """
        if self._store is not None:
            try:
                df = self._store.read(symbol, timeframe, limit=limit)
                if not df.is_empty():
                    return df
                logger.warning(
                    "ParquetStore 데이터 없음 — APIGateway 폴백: %s %s",
                    symbol,
                    timeframe,
                )
            except Exception:
                logger.warning(
                    "ParquetStore 읽기 실패 — APIGateway 폴백: %s %s",
                    symbol,
                    timeframe,
                    exc_info=True,
                )

        records = await self._gateway.get_ohlcv(
            symbol, timeframe=timeframe, limit=limit
        )
        return _dicts_to_ohlcv_df(records)

    async def get_current_price(self, symbol: str) -> float:
        """현재가 조회 (APIGateway 캐시 활용)."""
        return await self._gateway.get_current_price(symbol)

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """기술 지표 계산.

        OHLCV 데이터를 조회한 뒤 IndicatorCalculator로 지표를 계산한다.
        pandas-ta는 정규 의존성이므로 항상 사용 가능하다.
        OHLCV 데이터가 없으면 빈 딕셔너리를 반환한다.
        """
        from ante.strategy.indicators import IndicatorCalculator, ohlcv_to_dataframe

        ohlcv_data = await self.get_ohlcv(symbol, limit=500)
        if ohlcv_data.is_empty():
            logger.warning(
                "OHLCV 데이터 없음 — 지표 계산 불가: %s %s", symbol, indicator
            )
            return {}

        arrays = ohlcv_to_dataframe(ohlcv_data)
        return IndicatorCalculator.compute(indicator, arrays, **(params or {}))
