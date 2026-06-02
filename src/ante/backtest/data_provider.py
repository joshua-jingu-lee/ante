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

    미래 데이터 참조를 방지하기 위해 통합 timeline(전 심볼 timestamp의 union)을
    기준으로 현재 시각까지만 노출한다(as-of 관측, #2098). 심볼별 거래 달력이
    달라도 같은 step에서 모든 심볼이 동일한 wall-clock 시각(current_ts) 이하만
    보므로, 공유 row-index가 유발하던 미래 데이터 노출(lookahead)이 발생하지
    않는다.

    Note: DataProvider 인터페이스 준수를 위해 get_ohlcv 등은 async def를 유지한다.
    """

    def __init__(
        self,
        store: ParquetStore,
        start_date: str,
        end_date: str,
        exchange: str = "KRX",
    ) -> None:
        self._store = store
        self._start = start_date
        self._end = end_date
        self._exchange = exchange
        self._cache: dict[str, pl.DataFrame] = {}
        # 초기 커서는 첫 row 이전(-1)에 위치한다. 첫 advance()가 timeline 0으로
        # 전진하여 첫 시각을 처리한다(#2061). pre-advance 상태(idx=-1)에서는
        # OHLCV가 empty, current timestamp는 None, current price는 unavailable이다.
        self._current_idx: int = -1
        # 전 캐시 DataFrame의 timestamp를 union·정렬·dedupe한 통합 시간축(#2098).
        # 심볼마다 거래 달력이 다를 수 있으므로 공유 row-index 대신 wall-clock
        # 시각을 SSOT로 삼아 as-of 관측을 한다. None이면 다음 접근 시 lazy-build.
        # load()/reset()에서 무효화한다.
        self._timeline: list[datetime] | None = None
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
        df = self._store.read(
            symbol,
            timeframe,
            start=self._start,
            end=self._end,
            exchange=self._exchange,
        )
        self._cache[key] = df
        # 새 데이터가 캐시에 들어오면 통합 timeline을 무효화한다(#2098). 다음
        # advance()/get_total_steps()/get_current_timestamp() 접근 시 lazy-build.
        self._timeline = None

        data_dir = self._store.resolve_path(symbol, timeframe, exchange=self._exchange)
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

    def _build_timeline(self) -> list[datetime]:
        """전 캐시 DataFrame의 timestamp를 union·오름차순 정렬·dedupe한 통합 시간축.

        심볼마다 거래 달력이 달라도 모든 심볼이 동일한 wall-clock 시각 기준으로
        전진하도록, 캐시된 모든 timestamp 컬럼을 합쳐 중복 제거 후 정렬한다.
        tz-aware datetime을 그대로 유지한다(#2098).
        """
        if not self._cache:
            return []
        seen: set[datetime] = set()
        for df in self._cache.values():
            if df.is_empty():
                continue
            for ts in df["timestamp"].to_list():
                if isinstance(ts, datetime):
                    seen.add(ts)
        return sorted(seen)

    def _ensure_timeline(self) -> list[datetime]:
        """timeline이 무효화(None)되어 있으면 lazy-build 후 반환한다(#2098)."""
        if self._timeline is None:
            self._timeline = self._build_timeline()
        return self._timeline

    async def get_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> pl.DataFrame:
        """현재 시점(current_ts)까지의 OHLCV 데이터 반환(as-of 관측, #2098).

        공유 row-index 슬라이스 대신 통합 timeline의 current_ts 이하 행만
        노출한다. current_ts가 None(pre-advance/끝)이면 empty를 반환한다.
        """
        key = f"{symbol}:{timeframe}"
        if key not in self._cache:
            self.load(symbol, timeframe)

        df = self._cache[key]
        current_ts = self.get_current_timestamp()
        # 데이터가 없는 심볼은 store가 컬럼 없는 빈 df를 줄 수 있으므로,
        # timestamp 컬럼 참조 전에 empty를 먼저 가드한다(존재하지 않는 심볼).
        if current_ts is None or df.is_empty():
            return df.head(0)
        visible = df.filter(pl.col("timestamp") <= current_ts)
        return visible.tail(limit)

    async def get_current_price(self, symbol: str) -> float:
        """현재 시점까지의 최근 종가(as-of, mark-to-market/지표/전략 관측용).

        current_ts 이하의 가장 최근 봉 종가를 반환한다. 심볼이 current_ts에
        봉이 없어도(gap day) 그 이전 최근 봉가를 쓰므로, 보유 포지션의 mark-
        to-market 평가가 끊기지 않는다. visible이 empty면(미시작/pre-advance)
        BacktestDataError를 raise한다.

        체결 가능 가격은 ``get_current_bar_price``(현재 봉 정확 일치)를 별도로
        쓴다. 이 메서드의 as-of 가격으로 비거래일에 체결하면 안 된다(#2098).
        """
        df = await self.get_ohlcv(symbol, limit=1)
        if df.is_empty():
            msg = f"No data for {symbol} at step {self._current_idx}"
            raise BacktestDataError(msg)
        return float(df["close"][-1])

    def get_current_bar_price(self, symbol: str, timeframe: str = "1d") -> float | None:
        """현재 시각(current_ts)에 정확히 일치하는 봉의 종가(체결 가능가, #2098).

        current_ts가 None이면 None. 심볼 df에서 ``timestamp == current_ts`` 인
        행을 정확 일치 조회한다. 없으면(해당 심볼이 current_ts에 봉이 없음 =
        gap day/미시작) None을 반환하고, 있으면 그 행의 close(float)를 반환한다.

        as-of(get_current_price)와 달리 stale 가격을 쓰지 않으므로, 호출부는
        None을 "이번 step에 거래 불가"로 해석해 체결을 skip해야 한다.
        """
        key = f"{symbol}:{timeframe}"
        if key not in self._cache:
            self.load(symbol, timeframe)

        current_ts = self.get_current_timestamp()
        if current_ts is None:
            return None
        df = self._cache[key]
        # 데이터가 없는 심볼은 timestamp 컬럼이 없는 빈 df일 수 있으므로 가드.
        if df.is_empty():
            return None
        match = df.filter(pl.col("timestamp") == current_ts)
        if match.is_empty():
            return None
        return float(match["close"][-1])

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
        """시뮬레이션 1스텝 전진. False면 데이터 끝.

        통합 timeline(전 심볼 timestamp union) 위에서 전진한다(#2098). 캐시가
        비어 있으면 False. 그 외에는 다음 timeline 인덱스가 범위 안인지로 판정.
        """
        self._current_idx += 1
        if not self._cache:
            return False
        timeline = self._ensure_timeline()
        return self._current_idx < len(timeline)

    def get_current_timestamp(self) -> datetime | None:
        """현재 시뮬레이션 시각(통합 timeline의 current_idx 위치, #2098)."""
        if self._current_idx < 0:
            # pre-advance 상태(첫 advance() 이전). 음수 인덱스로 마지막 행을
            # 잘못 반환하지 않도록 명시적으로 None을 반환한다(#2061).
            return None
        if not self._cache:
            return None
        timeline = self._ensure_timeline()
        if self._current_idx >= len(timeline):
            return None
        return timeline[self._current_idx]

    def get_total_steps(self) -> int:
        """전체 시뮬레이션 스텝 수(통합 timeline의 distinct 시각 개수, #2098)."""
        if not self._cache:
            return 0
        return len(self._ensure_timeline())

    def reset(self) -> None:
        """인덱스 초기화. 커서를 첫 row 이전(-1)으로 되돌린다.

        통합 timeline도 무효화해 다음 접근 시 재빌드한다(#2098).
        """
        self._current_idx = -1
        self._timeline = None
        self._loaded_datasets.clear()
