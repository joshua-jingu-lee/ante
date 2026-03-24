"""Backtest 데이터 프로바이더 — Parquet 기반 과거 데이터."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import polars as pl

from ante.backtest.config import DatasetInfo
from ante.backtest.exceptions import BacktestDataError
from ante.strategy.base import DataProvider

if TYPE_CHECKING:
    from ante.data.store import ParquetStore

logger = logging.getLogger(__name__)


class BacktestDataProvider(DataProvider):
    """백테스트용 DataProvider. 과거 데이터를 시간순으로 제공.

    미래 데이터 참조를 방지하기 위해 current_idx까지만 노출한다.

    Note: DataProvider 인터페이스 준수를 위해 get_ohlcv 등은 async def를 유지한다.
    """

    def __init__(
        self,
        store: ParquetStore,
        start_date: str,
        end_date: str,
    ) -> None:
        self._store = store
        self._start = start_date
        self._end = end_date
        self._cache: dict[str, pl.DataFrame] = {}
        self._current_idx: int = 0
        self._loaded_datasets: list[DatasetInfo] = []

    @property
    def current_idx(self) -> int:
        return self._current_idx

    @property
    def start(self) -> str:
        return self._start

    @property
    def end(self) -> str:
        return self._end

    @property
    def loaded_datasets(self) -> list[DatasetInfo]:
        """로드된 데이터셋 메타정보 목록."""
        return list(self._loaded_datasets)

    def load(self, symbol: str, timeframe: str) -> int:
        """데이터를 캐시에 로드. 로드된 행 수 반환."""
        key = f"{symbol}:{timeframe}"
        df = self._store.read(symbol, timeframe, start=self._start, end=self._end)
        self._cache[key] = df

        data_dir = self._store.resolve_path(symbol, timeframe)
        file_count = len(list(data_dir.glob("*.parquet"))) if data_dir.exists() else 0
        info = DatasetInfo(
            symbol=symbol,
            timeframe=timeframe,
            row_count=len(df),
            start_date=str(df["timestamp"][0]) if len(df) > 0 else "",
            end_date=str(df["timestamp"][-1]) if len(df) > 0 else "",
            data_dir=str(data_dir),
            file_count=file_count,
        )
        self._loaded_datasets.append(info)

        return len(df)

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> pl.DataFrame:
        """현재 시점까지의 OHLCV 데이터 반환."""
        key = f"{symbol}:{timeframe}"
        if key not in self._cache:
            self.load(symbol, timeframe)

        df = self._cache[key]
        visible = df.head(self._current_idx + 1)
        return visible.tail(limit)

    async def get_current_price(self, symbol: str) -> float:
        """현재 시점의 종가."""
        df = await self.get_ohlcv(symbol, limit=1)
        if df.is_empty():
            msg = f"No data for {symbol} at step {self._current_idx}"
            raise BacktestDataError(msg)
        return float(df["close"][-1])

    async def get_indicator(
        self,
        symbol: str,
        indicator: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """기술 지표 계산.

        OHLCV 데이터를 가져와 IndicatorCalculator로 지표를 계산한다.
        라이브(StrategyContext)와 동일한 로직을 사용하여
        백테스트-라이브 패리티를 보장한다.
        """
        from ante.strategy.indicators import IndicatorCalculator, ohlcv_to_dataframe

        ohlcv_data = await self.get_ohlcv(symbol, limit=500)
        arrays = ohlcv_to_dataframe(ohlcv_data)
        return IndicatorCalculator.compute(indicator, arrays, **(params or {}))

    def advance(self) -> bool:
        """시뮬레이션 1스텝 전진. False면 데이터 끝."""
        self._current_idx += 1
        if not self._cache:
            return False
        max_len = min(len(df) for df in self._cache.values())
        return self._current_idx < max_len

    def get_current_timestamp(self) -> datetime | None:
        """현재 시뮬레이션 시각."""
        if not self._cache:
            return None
        first_df = next(iter(self._cache.values()))
        if self._current_idx >= len(first_df):
            return None
        ts = first_df["timestamp"][self._current_idx]
        if isinstance(ts, datetime):
            return ts
        return None

    def get_total_steps(self) -> int:
        """전체 시뮬레이션 스텝 수."""
        if not self._cache:
            return 0
        return min(len(df) for df in self._cache.values())

    def reset(self) -> None:
        """인덱스 초기화."""
        self._current_idx = 0
        self._loaded_datasets.clear()
