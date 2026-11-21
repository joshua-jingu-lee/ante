"""Backtest Service — 메인 프로세스에서 백테스트를 관리."""

from __future__ import annotations

import asyncio
import datetime
import json
import logging
import math
import re
import sys
import uuid
from dataclasses import replace
from typing import TYPE_CHECKING, Any

from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.exceptions import BacktestConfigError, BacktestError
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult
from ante.core.exchange import CANONICAL_EXCHANGES, is_canonical
from ante.core.market_data_vocab import (
    CANONICAL_TIMEFRAMES,
    is_krx_symbol,
    is_valid_timeframe,
)
from ante.data.store import ParquetStore
from ante.strategy.loader import StrategyLoader
from ante.strategy.validator import StrategyValidator

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

BACKTEST_RESULT_SENTINEL = "__ANTE_BACKTEST_RESULT__"

_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


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

        strategy_path = Path(validated.strategy_path)
        val_result = StrategyValidator().validate(strategy_path)
        if not val_result.valid:
            msg = f"전략 검증 실패: {'; '.join(val_result.errors)}"
            raise BacktestConfigError(msg)

        strategy_cls = StrategyLoader.load(strategy_path)

        meta = strategy_cls.meta
        eff_symbols = validated.symbols or list(meta.symbols or [])
        cfg_timeframe = config.get("timeframe", "1d")
        eff_timeframe = cfg_timeframe if cfg_timeframe is not None else meta.timeframe

        self._validate_timeframe_vocab(eff_timeframe)
        self._validate_symbols_vocab(eff_symbols, validated.exchange)

        effective = replace(
            validated,
            symbols=eff_symbols,
            timeframe=eff_timeframe,
        )

        if not effective.symbols:
            logger.warning(
                "백테스트 대상 종목이 없습니다(CLI --symbols 생략 + "
                "StrategyMeta.symbols 미설정 '%s'): 데이터셋 0개·0-step 으로 "
                "종료될 수 있습니다.",
                meta.name,
            )

        store = ParquetStore(
            base_path=effective.data_paths[0],
        )
        data_provider = BacktestDataProvider(
            store=store,
            start_date=effective.start_date,
            end_date=effective.end_date,
            exchange=effective.exchange,
            timeframe=effective.timeframe,
        )

        for symbol in effective.symbols:
            data_provider.load(symbol, effective.timeframe)

        executor = BacktestExecutor(
            strategy_cls=strategy_cls,
            data_provider=data_provider,
            initial_balance=effective.initial_balance,
            buy_commission_rate=effective.buy_commission_rate,
            sell_commission_rate=effective.sell_commission_rate,
            slippage_rate=effective.slippage_rate,
            exchange=effective.exchange,
            symbols=effective.symbols,
        )

        result = await executor.run(progress_callback=progress_callback)
        result.config = effective
        result.datasets = data_provider.loaded_datasets

        result.result_path = self._save_result_artifact(result, effective)

        await self._publish_complete_event(result)

        return result

    def _save_result_artifact(
        self,
        result: BacktestResult,
        effective: BacktestConfig,
    ) -> str:
        """결과를 durable JSON artifact 로 저장하고 경로를 반환한다."""
        from pathlib import Path

        try:
            artifact_dir = Path(effective.data_paths[0]) / ".backtest" / "results"
            artifact_dir.mkdir(parents=True, exist_ok=True)
            name = (
                f"{result.strategy_name}_v{result.strategy_version}_"
                f"{uuid.uuid4().hex}.json"
            )
            path = artifact_dir / name
            path.write_text(json.dumps(result.to_dict(), default=str))
        except OSError as e:
            logger.warning(
                "백테스트 결과 artifact 저장 실패(자동 리포트 초안 skip): %s",
                e,
            )
            return ""
        else:
            logger.info("백테스트 결과 artifact 저장: %s", path)
            return str(path)

    async def run_subprocess(self, config: dict[str, Any]) -> dict:
        """백테스트를 subprocess로 격리 실행 (D-004).

        ``ante backtest run`` CLI 의 격리 실행 경로다. ``python -m
        ante.backtest.runner`` 자식 프로세스를 띄워 stdin 으로 JSON config 를
        전달하고, stdout 의 ``BACKTEST_RESULT_SENTINEL`` 라인만 파싱한 dict 를
        반환한다. returncode≠0 또는 sentinel 라인 부재는 ``BacktestError`` 다.
        """
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

        stdout_text = stdout.decode()
        for line in stdout_text.splitlines():
            if line.startswith(BACKTEST_RESULT_SENTINEL):
                payload = line[len(BACKTEST_RESULT_SENTINEL) :]
                return json.loads(payload)
        msg = "Backtest subprocess did not emit a result line"
        raise BacktestError(msg)

    async def _publish_complete_event(
        self,
        result: BacktestResult,
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
            result_path=result.result_path,
        )
        await self._eventbus.publish(event)
        logger.info("BacktestCompleteEvent 발행: %s", strategy_id)

    def _validate_timeframe_vocab(self, timeframe: object) -> None:
        """timeframe vocabulary 검증. invalid → BacktestConfigError."""
        if not isinstance(timeframe, str) or not is_valid_timeframe(timeframe):
            msg = (
                f"Invalid timeframe: {timeframe!r}. "
                f"Allowed: {', '.join(CANONICAL_TIMEFRAMES)}"
            )
            raise BacktestConfigError(msg)

    def _validate_symbols_vocab(
        self,
        symbols: object,
        exchange: str,
        *,
        raw: object | None = None,
    ) -> None:
        """symbols 구조/빈/KRX-shape 검증 (공유 helper)."""
        shown = symbols if raw is None else raw
        if not isinstance(symbols, list) or not all(
            isinstance(s, str) for s in symbols
        ):
            msg = f"Invalid symbols (expected list[str]): {shown!r}"
            raise BacktestConfigError(msg)
        if any(not s.strip() for s in symbols):
            msg = f"Invalid symbols (empty/blank segment): {shown!r}"
            raise BacktestConfigError(msg)
        if exchange == "KRX":
            for s in symbols:
                if not is_krx_symbol(s):
                    msg = (
                        f"Invalid KRX symbol: {s!r}. "
                        "Expected 6-digit canonical KRX symbol shape."
                    )
                    raise BacktestConfigError(msg)

    def _validate_config(self, config: dict[str, Any]) -> BacktestConfig:
        """설정 검증 후 BacktestConfig를 반환."""
        required = ["strategy_path", "start_date", "end_date"]
        missing = [k for k in required if k not in config]
        if missing:
            msg = f"Missing required config keys: {missing}"
            raise BacktestConfigError(msg)

        for label in ("start_date", "end_date"):
            value = config[label]
            if not isinstance(value, str) or _ISO_DATE_RE.fullmatch(value) is None:
                msg = f"Invalid {label} (expected YYYY-MM-DD): {value!r}"
                raise BacktestConfigError(msg)
            try:
                datetime.date.fromisoformat(value)
            except ValueError as e:
                msg = f"Invalid {label}: {value!r}"
                raise BacktestConfigError(msg) from e
        start = datetime.date.fromisoformat(config["start_date"])
        end = datetime.date.fromisoformat(config["end_date"])
        if start > end:
            msg = (
                f"start_date {config['start_date']!r} is after "
                f"end_date {config['end_date']!r}"
            )
            raise BacktestConfigError(msg)

        timeframe = config.get("timeframe", "1d")
        if timeframe is not None:
            self._validate_timeframe_vocab(timeframe)

        symbols_raw = config.get("symbols", [])
        normalized_symbols = [] if symbols_raw is None else symbols_raw

        exchange = config.get("exchange", "KRX")
        if not isinstance(exchange, str) or not is_canonical(exchange):
            msg = (
                f"Invalid exchange: {exchange!r}. "
                f"Allowed: {', '.join(sorted(CANONICAL_EXCHANGES))}"
            )
            raise BacktestConfigError(msg)

        self._validate_symbols_vocab(normalized_symbols, exchange, raw=symbols_raw)

        def _check_number(label: str, value: object, *, allow_zero: bool) -> None:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                msg = f"Invalid {label} (expected number): {value!r}"
                raise BacktestConfigError(msg)
            if math.isnan(value) or math.isinf(value):
                msg = f"Invalid {label} (NaN/Infinity not allowed): {value!r}"
                raise BacktestConfigError(msg)
            if allow_zero and value < 0:
                msg = f"Invalid {label} (must be >= 0): {value!r}"
                raise BacktestConfigError(msg)
            if not allow_zero and value <= 0:
                msg = f"Invalid {label} (must be > 0): {value!r}"
                raise BacktestConfigError(msg)

        if "initial_balance" in config:
            _check_number(
                "initial_balance", config["initial_balance"], allow_zero=False
            )
        for _rate in ("buy_commission_rate", "sell_commission_rate", "slippage_rate"):
            if _rate in config:
                _check_number(_rate, config[_rate], allow_zero=True)

        data_paths = config.get(
            "data_paths",
            [config.get("data_path", self._data_path)],
        )

        cfg_timeframe = config.get("timeframe", "1d")
        return BacktestConfig(
            strategy_path=config["strategy_path"],
            symbols=normalized_symbols,
            timeframe="1d" if cfg_timeframe is None else cfg_timeframe,
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
