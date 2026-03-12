"""Backtest Service — 메인 프로세스에서 백테스트를 관리."""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.exceptions import BacktestConfigError, BacktestError
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult
from ante.data.store import ParquetStore
from ante.strategy.loader import StrategyLoader

logger = logging.getLogger(__name__)


class BacktestService:
    """백테스트 실행 관리.

    in-process 실행과 subprocess 격리 실행 두 모드를 지원한다.
    """

    def __init__(self, data_path: str = "data/") -> None:
        self._data_path = data_path
        self._running: dict[str, asyncio.Task] = {}

    async def run(self, config: dict[str, Any]) -> BacktestResult:
        """백테스트를 in-process로 실행."""
        self._validate_config(config)

        from pathlib import Path

        strategy_cls = StrategyLoader.load(Path(config["strategy_path"]))

        store = ParquetStore(base_path=config.get("data_path", self._data_path))
        data_provider = BacktestDataProvider(
            store=store,
            start_date=config["start_date"],
            end_date=config["end_date"],
        )

        symbols = config.get("symbols", [])
        timeframe = config.get("timeframe", "1d")
        for symbol in symbols:
            await data_provider.load(symbol, timeframe)

        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=data_provider,
            initial_balance=config.get("initial_balance", 10_000_000),
            commission_rate=config.get("commission_rate", 0.00015),
            slippage_rate=config.get("slippage_rate", 0.001),
        )

        return await executor.run()

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

    def _validate_config(self, config: dict[str, Any]) -> None:
        """설정 검증."""
        required = ["strategy_path", "start_date", "end_date"]
        missing = [k for k in required if k not in config]
        if missing:
            msg = f"Missing required config keys: {missing}"
            raise BacktestConfigError(msg)
