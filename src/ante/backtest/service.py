"""Backtest Service — 메인 프로세스에서 백테스트를 관리."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import TYPE_CHECKING, Any

from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.exceptions import BacktestConfigError, BacktestError
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult
from ante.core.market_data_vocab import (
    CANONICAL_TIMEFRAMES,
    is_krx_symbol,
    is_valid_timeframe,
)
from ante.data.store import ParquetStore
from ante.strategy.loader import StrategyLoader

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)


class BacktestService:
    """백테스트 실행 관리.

    in-process 실행과 subprocess 격리 실행 두 모드를 지원한다.
    """

    def __init__(
        self,
        data_path: str = "data/",
        eventbus: EventBus | None = None,
    ) -> None:
        self._data_path = data_path
        self._eventbus = eventbus
        self._running: dict[str, asyncio.Task] = {}

    async def run(
        self,
        config: dict[str, Any],
        progress_callback: Any | None = None,
    ) -> BacktestResult:
        """백테스트를 in-process로 실행."""
        from pathlib import Path

        validated = self._validate_config(config)

        strategy_cls = StrategyLoader.load(Path(validated.strategy_path))

        store = ParquetStore(
            base_path=config.get("data_path", self._data_path),
        )
        data_provider = BacktestDataProvider(
            store=store,
            start_date=validated.start_date,
            end_date=validated.end_date,
            exchange=validated.exchange,
        )

        for symbol in validated.symbols:
            data_provider.load(symbol, validated.timeframe)

        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=data_provider,
            initial_balance=validated.initial_balance,
            buy_commission_rate=validated.buy_commission_rate,
            sell_commission_rate=validated.sell_commission_rate,
            slippage_rate=validated.slippage_rate,
            exchange=validated.exchange,
        )

        result = await executor.run(progress_callback=progress_callback)
        result.config = validated
        result.datasets = data_provider.loaded_datasets

        # BacktestCompleteEvent 발행
        await self._publish_complete_event(result, config)

        return result

    async def run_subprocess(self, config: dict[str, Any]) -> dict:
        """백테스트를 subprocess로 격리 실행 (D-004)."""
        self._validate_config(config)

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "ante.backtest.runner",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate(
            input=json.dumps(config).encode(),
        )

        if proc.returncode != 0:
            msg = f"Backtest subprocess failed: {stderr.decode()}"
            raise BacktestError(msg)

        return json.loads(stdout.decode())

    async def _publish_complete_event(
        self,
        result: BacktestResult,
        config: dict[str, Any],
    ) -> None:
        """BacktestCompleteEvent 발행."""
        if not self._eventbus:
            return

        from ante.eventbus.events import BacktestCompleteEvent

        strategy_id = f"{result.strategy_name}_v{result.strategy_version}"
        event = BacktestCompleteEvent(
            backtest_id=strategy_id,
            strategy_id=strategy_id,
            status="completed",
            result_path=config.get("result_path", ""),
        )
        await self._eventbus.publish(event)
        logger.info("BacktestCompleteEvent 발행: %s", strategy_id)

    def _validate_config(self, config: dict[str, Any]) -> BacktestConfig:
        """설정 검증 후 BacktestConfig를 반환."""
        required = ["strategy_path", "start_date", "end_date"]
        missing = [k for k in required if k not in config]
        if missing:
            msg = f"Missing required config keys: {missing}"
            raise BacktestConfigError(msg)

        # symbol/timeframe vocabulary 검증 (#1604, core.md ``## Canonical
        # Symbol/Timeframe Vocabulary``:286 — programmatic API 행이
        # "검증 에러"를 normative로 요구). CLI(#1603)는 Click이 타입을
        # 협소화하지만 programmatic ``dict[str, Any]`` 는 임의 타입이
        # 유입되므로 모든 분기에 명시적 타입 경계를 두어 invalid를
        # ``TypeError`` 가 아닌 ``BacktestConfigError`` 로 early-fail
        # 시킨다. SSOT(`is_krx_symbol`)의 non-str→False 가드를
        # 우회하지 않도록 ``str()`` 캐스팅은 쓰지 않는다.
        # precedence: required-key → ① timeframe → ② symbols 정규화/
        # 구조/빈 → ③ KRX shape.
        timeframe = config.get("timeframe", "1d")
        if not isinstance(timeframe, str) or not is_valid_timeframe(timeframe):
            msg = (
                f"Invalid timeframe: {timeframe!r}. "
                f"Allowed: {', '.join(CANONICAL_TIMEFRAMES)}"
            )
            raise BacktestConfigError(msg)

        symbols_raw = config.get("symbols", [])
        # None/누락/[] → [] (no-symbols backtest 정상, 미거부). 명시적
        # ``{"symbols": None}`` 도 여기서 ``[]`` 로 정규화하여 build
        # 라인이 ``BacktestConfig.symbols=None`` 으로 새지 않게 한다.
        normalized_symbols = [] if symbols_raw is None else symbols_raw
        if not isinstance(normalized_symbols, list) or not all(
            isinstance(s, str) for s in normalized_symbols
        ):
            msg = f"Invalid symbols (expected list[str]): {symbols_raw!r}"
            raise BacktestConfigError(msg)
        if any(not s.strip() for s in normalized_symbols):
            msg = f"Invalid symbols (empty/blank segment): {symbols_raw!r}"
            raise BacktestConfigError(msg)

        exchange = config.get("exchange", "KRX")
        if exchange == "KRX":
            # resolved exchange == KRX 신규 입력 한정 (core.md
            # ``### KRX symbol shape``). 비-KRX exchange의 symbol
            # shape은 미검증 (NYSE+AAPL 비거부). 원본 str 값을 그대로
            # 전달 — ② 에서 list[str] 보장, SSOT non-str 가드 보존.
            for s in normalized_symbols:
                if not is_krx_symbol(s):
                    msg = (
                        f"Invalid KRX symbol: {s!r}. "
                        "Expected 6-digit canonical KRX symbol shape."
                    )
                    raise BacktestConfigError(msg)

        data_paths = config.get(
            "data_paths",
            [config.get("data_path", self._data_path)],
        )

        return BacktestConfig(
            strategy_path=config["strategy_path"],
            symbols=normalized_symbols,
            timeframe=config.get("timeframe", "1d"),
            exchange=config.get("exchange", "KRX"),
            start_date=config.get("start_date", ""),
            end_date=config.get("end_date", ""),
            initial_balance=config.get("initial_balance", 10_000_000.0),
            buy_commission_rate=config.get(
                "buy_commission_rate",
                config.get("commission_rate", 0.00015),
            ),
            sell_commission_rate=config.get("sell_commission_rate", 0.00195),
            slippage_rate=config.get("slippage_rate", 0.001),
            data_paths=data_paths,
        )
