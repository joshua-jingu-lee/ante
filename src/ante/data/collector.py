"""Data Pipeline — 봇 운영 중 실시간 시세 데이터 수집."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.data.store import ParquetStore
    from ante.eventbus import EventBus

DataCallback = Callable[[str, str], Awaitable[list[dict]]]

logger = logging.getLogger(__name__)


class DataCollector:
    """봇 운영 중 실시간 시세 데이터를 수집하여 Parquet에 적재.

    APIGateway를 통해 주기적으로 시세를 조회하고,
    메모리 버퍼에 쌓은 뒤 일정 건수/시간마다 Parquet에 flush한다.
    """

    def __init__(
        self,
        store: ParquetStore,
        eventbus: EventBus,
        buffer_size: int = 100,
        flush_interval: float = 300.0,
        collect_interval: float = 60.0,
        exchange: str = "KRX",
    ) -> None:
        self._store = store
        self._eventbus = eventbus
        self._buffer: dict[str, list[dict]] = {}  # "symbol:timeframe" → rows
        self._buffer_size = buffer_size
        self._flush_interval = flush_interval
        self._collect_interval = collect_interval
        self._exchange = exchange
        self._symbols: list[str] = []
        self._timeframes: list[str] = []
        self._collect_task: asyncio.Task | None = None
        self._flush_task: asyncio.Task | None = None
        self._running = False
        self._data_callback: DataCallback | None = None

    @property
    def running(self) -> bool:
        return self._running

    @property
    def buffer(self) -> dict[str, list[dict]]:
        return self._buffer

    def set_data_callback(self, callback: DataCallback) -> None:
        """데이터 수집 콜백 설정. 시그니처: async (symbol, tf) -> list[dict]."""
        self._data_callback = callback

    def start(self, symbols: list[str], timeframes: list[str]) -> None:
        """데이터 수집 시작."""
        if self._running:
            logger.warning("DataCollector is already running")
            return

        self._symbols = symbols
        self._timeframes = timeframes
        self._running = True
        self._collect_task = asyncio.create_task(self._collect_loop())
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.info(
            "DataCollector started: symbols=%s, timeframes=%s",
            symbols,
            timeframes,
        )

    def stop(self) -> None:
        """데이터 수집 중지. 남은 버퍼를 flush."""
        self._running = False
        if self._collect_task:
            self._collect_task.cancel()
            self._collect_task = None
        if self._flush_task:
            self._flush_task.cancel()
            self._flush_task = None

        # 남은 데이터 flush
        self.flush_all()
        logger.info("DataCollector stopped")

    def add_data(self, symbol: str, timeframe: str, row: dict) -> None:
        """외부에서 직접 데이터를 추가 (이벤트 기반 수집 시 사용)."""
        key = f"{symbol}:{timeframe}"
        if key not in self._buffer:
            self._buffer[key] = []
        self._buffer[key].append(row)

        if len(self._buffer[key]) >= self._buffer_size:
            self._flush(key)

    def flush_all(self) -> int:
        """모든 버퍼 데이터를 Parquet에 flush. flush된 총 건수 반환."""
        total = 0
        for key in list(self._buffer.keys()):
            if self._buffer[key]:
                count = len(self._buffer[key])
                self._flush(key)
                total += count
        return total

    async def _collect_loop(self) -> None:
        """주기적으로 시세 데이터 수집."""
        while self._running:
            if self._data_callback:
                for symbol in self._symbols:
                    for tf in self._timeframes:
                        try:
                            rows = await self._data_callback(symbol, tf)
                            for row in rows:
                                self.add_data(symbol, tf, row)
                        except Exception as e:
                            logger.warning(
                                "Data collection failed for %s/%s: %s",
                                symbol,
                                tf,
                                e,
                            )
            try:
                await asyncio.sleep(self._collect_interval)
            except asyncio.CancelledError:
                raise

    async def _flush_loop(self) -> None:
        """주기적 버퍼 flush."""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
            except asyncio.CancelledError:
                raise
            self.flush_all()

    def _flush(self, key: str) -> None:
        """버퍼의 데이터를 Parquet에 적재."""
        rows = self._buffer.pop(key, [])
        if not rows:
            return
        symbol, tf = key.split(":")
        try:
            self._store.append(symbol, tf, rows, exchange=self._exchange)
            logger.debug("Flushed %d rows for %s/%s", len(rows), symbol, tf)
        except Exception as e:
            logger.error("Failed to flush data for %s/%s: %s", symbol, tf, e)
            # 실패 시 버퍼에 다시 넣기
            if key not in self._buffer:
                self._buffer[key] = []
            self._buffer[key] = rows + self._buffer[key]
