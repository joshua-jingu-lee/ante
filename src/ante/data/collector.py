"""Data Pipeline — 봇 운영 중 실시간 시세 데이터 수집."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

from ante.core.market_data_vocab import is_krx_symbol, is_valid_timeframe

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

    def _is_valid_ingress(self, symbol: object, timeframe: object) -> bool:
        """canonical symbol/timeframe ingress 검증 (#1613 SSOT 위임).

        통과 조건:
        - ``timeframe`` 이 ``str`` 이고 (#1613 ``is_valid_timeframe``)
          canonical OHLCV bar timeframe 5종 중 하나이며
          (unhashable timeframe → ``is_valid_timeframe`` 호출 전 차단으로
          TypeError 방지),
        - ``timeframe != "1d"`` (``1d`` 는 DataFeed write-ownership 소유,
          data-pipeline/02 — vocabulary regex가 아닌 write-ownership 경계
          literal 비교. ``tick``/``oracle`` 등은 ``is_valid_timeframe``
          이 False),
        - exchange 가 KRX면 ``symbol`` 이 ``str`` 이고 신규 입력 KRX
          symbol shape (#1613 ``is_krx_symbol``). ``isinstance(symbol,
          str)`` 선검사는 ``is_krx_symbol`` 내장 ``isinstance(str)``
          가드와 동일 결과(비-str symbol → KRX 거부)이며 #1613 SSOT
          시그니처(``value: str``)와의 타입 정합을 위한 것이다.
          비-KRX exchange 는 symbol-shape 미적용 (core.md
          ``### KRX symbol shape`` 1.0 비목표).
        """
        return (
            isinstance(timeframe, str)
            and is_valid_timeframe(timeframe)
            and timeframe != "1d"
            and (
                self._exchange != "KRX"
                or (isinstance(symbol, str) and is_krx_symbol(symbol))
            )
        )

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
        if not self._is_valid_ingress(symbol, timeframe):
            logger.warning(
                "DataCollector ingress reject (add_data): symbol=%r tf=%r — skip",
                symbol,
                timeframe,
            )
            return
        key = f"{symbol}:{timeframe}"
        if key not in self._buffer:
            self._buffer[key] = []
        self._buffer[key].append(row)

        if len(self._buffer[key]) >= self._buffer_size:
            self._flush(key)

    def flush_all(self) -> int:
        """모든 버퍼 데이터를 Parquet에 flush.

        반환값 = "이번 호출에서 실제 append 성공한 row 수". invalid/
        malformed key drop 과 append-exception(재버퍼링 retry 보존)은
        둘 다 0 으로 집계되어 합산에서 자동 제외된다 (drop 된 invalid
        rows·재버퍼링된 append-fail rows 미포함).
        """
        total = 0
        for key in list(self._buffer.keys()):
            total += self._flush(key)
        return total

    async def _collect_loop(self) -> None:
        """주기적으로 시세 데이터 수집."""
        while self._running:
            if self._data_callback:
                for symbol in self._symbols:
                    for tf in self._timeframes:
                        if not self._is_valid_ingress(symbol, tf):
                            logger.warning(
                                "DataCollector ingress reject (collect): "
                                "symbol=%r tf=%r — skip",
                                symbol,
                                tf,
                            )
                            continue
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

    def _flush(self, key: object) -> int:
        """버퍼의 데이터를 Parquet에 적재. 실제 append 성공 row 수 반환.

        반환 계약:
        - **append 성공** → ``len(rows)``
        - **invalid/malformed key drop** (non-str key / ``rsplit(":",1)``
          len != 2 / ``_is_valid_ingress`` False) → ``0`` (이미 pop된
          rows 는 의도된 invalid drop — **retry 안 함**)
        - **``_store.append`` 예외** → 기존 재버퍼링 동작 보존
          (``rows + self._buffer[key]`` — 같은 key 에 되돌려 다음 flush
          재시도, rows 미유실) + ``return 0`` (이번 회차 append 0)

        invalid/malformed key drop(retry 안 함)과 append-exception
        (재버퍼링 retry 보존)을 명확히 구분한다. public ``buffer``
        프로퍼티 직접 주입(임의 malformed/invalid key)에도 raise 없이
        drop 하여 out-of-vocab ``ohlcv/<bad>/`` 경로를 만들지 않고
        ``flush_all``/``stop`` 을 중단시키지 않는다.
        """
        # ``key`` 는 public ``buffer`` 직접 주입으로 non-str 일 수 있어
        # ``object`` 로 받는다. ``dict.pop`` 은 hashable key 면 안전하며
        # (정상 경로는 항상 str key), non-str 우회 주입분은 아래
        # ``isinstance`` guard 가 drop 한다. cast 는 런타임 무동작.
        buffer = cast("dict[object, list[dict]]", self._buffer)
        rows = buffer.pop(key, [])
        if not rows:
            return 0
        if not isinstance(key, str):
            logger.warning(
                "DataCollector flush guard: drop non-str buffered key %r",
                key,
            )
            return 0
        parts = key.rsplit(":", 1)
        if len(parts) != 2:
            logger.warning(
                "DataCollector flush guard: drop malformed buffered key %r",
                key,
            )
            return 0
        symbol, tf = parts
        if not self._is_valid_ingress(symbol, tf):
            logger.warning(
                "DataCollector flush guard: drop invalid buffered key %r",
                key,
            )
            return 0
        try:
            self._store.append(symbol, tf, rows, exchange=self._exchange)
            logger.debug("Flushed %d rows for %s/%s", len(rows), symbol, tf)
            return len(rows)
        except Exception as e:
            logger.error("Failed to flush data for %s/%s: %s", symbol, tf, e)
            # 실패 시 버퍼에 다시 넣기 (rows 미유실 — 다음 flush 재시도)
            if key not in self._buffer:
                self._buffer[key] = []
            self._buffer[key] = rows + self._buffer[key]
            return 0
