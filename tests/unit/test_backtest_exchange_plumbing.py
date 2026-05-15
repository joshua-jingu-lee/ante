"""non-CLI backtest exchange plumbing 테스트 (#1585).

CLI 검증과 분리 — service/provider가 exchange를 무시해도 CLI 테스트는
통과하므로 별도 고정한다:

- `_validate_config`: exchange 미지정 → KRX 기본 / 명시 → 그대로 (default plumbing).
- `BacktestService.run()`: `BacktestDataProvider`를 `exchange=<config.exchange>`로 생성.
- `BacktestDataProvider.load()`: store.read() **및** store.resolve_path() 양쪽에
  동일 exchange 전달 (resolve_path 메타 hop 회귀 고정).
- `BacktestExecutor`: `exchange=` ctor 인자를 받아 `_execute_signal`이 만든
  `BacktestTrade.exchange`에 그대로 라벨링 (executor→trade hop 회귀 고정).
- `BacktestService.run()`: `BacktestExecutor`를 `exchange=<config.exchange>`로
  생성 (service→executor hop 회귀 고정).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.executor import BacktestExecutor
from ante.backtest.result import BacktestResult
from ante.backtest.service import BacktestService
from ante.strategy.base import Signal, Strategy, StrategyMeta


class TestValidateConfigExchangeDefault:
    """_validate_config exchange default plumbing (검증 아님)."""

    def test_exchange_missing_defaults_to_krx(self):
        svc = BacktestService()
        validated = svc._validate_config(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
            }
        )
        assert isinstance(validated, BacktestConfig)
        assert validated.exchange == "KRX"

    def test_explicit_exchange_preserved(self):
        svc = BacktestService()
        validated = svc._validate_config(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "exchange": "NYSE",
            }
        )
        assert validated.exchange == "NYSE"

    def test_validate_config_does_not_canonical_validate(self):
        """_validate_config는 canonical 검증을 하지 않는다 (CLI 경계 단일 검증).

        서비스/config 이중검증 금지 — 비-canonical 값도 plumbing은 그대로
        통과시킨다 (게이트는 CLI ingress).
        """
        svc = BacktestService()
        validated = svc._validate_config(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "exchange": "ORACLE_INVALID_EXCHANGE",
            }
        )
        assert validated.exchange == "ORACLE_INVALID_EXCHANGE"


class TestServicePassesExchangeToProvider:
    """BacktestService.run() → BacktestDataProvider(exchange=...) ctor 전달."""

    @pytest.mark.asyncio
    async def test_run_constructs_provider_with_config_exchange(self):
        config = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "symbols": ["005930"],
            "exchange": "NYSE",
        }

        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []

        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore") as mock_store_cls,
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ) as mock_provider_cls,
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ),
        ):
            mock_loader.load.return_value = MagicMock()
            mock_store_cls.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_provider_cls.call_args
        assert kwargs["exchange"] == "NYSE"

    @pytest.mark.asyncio
    async def test_run_defaults_provider_exchange_to_krx(self):
        config = {
            "strategy_path": "s.py",
            "start_date": "2026-01-01",
            "end_date": "2026-01-02",
            "symbols": [],
        }

        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []
        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore"),
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ) as mock_provider_cls,
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ),
        ):
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_provider_cls.call_args
        assert kwargs["exchange"] == "KRX"


class TestDataProviderForwardsExchangeToStore:
    """BacktestDataProvider.load() → store.read() + store.resolve_path() 양쪽 hop."""

    def _make_store(self):
        store = MagicMock()
        store.read.return_value = pl.DataFrame({"timestamp": [], "close": []})
        store.resolve_path.return_value = Path("/nonexistent/dir")
        return store

    def test_load_forwards_explicit_exchange_to_read_and_resolve_path(self):
        store = self._make_store()
        provider = BacktestDataProvider(
            store=store,
            start_date="2026-01-01",
            end_date="2026-01-02",
            exchange="NYSE",
        )

        provider.load("AAPL", "1d")

        # store.read() hop
        _, read_kwargs = store.read.call_args
        assert read_kwargs["exchange"] == "NYSE"
        # store.resolve_path() 메타 hop (read와 동일 exchange)
        _, resolve_kwargs = store.resolve_path.call_args
        assert resolve_kwargs["exchange"] == "NYSE"

    def test_load_defaults_exchange_krx_to_both_hops(self):
        store = self._make_store()
        provider = BacktestDataProvider(
            store=store,
            start_date="2026-01-01",
            end_date="2026-01-02",
        )

        provider.load("005930", "1d")

        _, read_kwargs = store.read.call_args
        assert read_kwargs["exchange"] == "KRX"
        _, resolve_kwargs = store.resolve_path.call_args
        assert resolve_kwargs["exchange"] == "KRX"


class _SingleBuyStrategy(Strategy):
    """첫 스텝에 buy 1건만 내는 최소 전략 (executor hop fixture)."""

    meta = StrategyMeta(name="single_buy", version="1", description="t")

    def __init__(self, ctx):  # noqa: D107
        super().__init__(ctx)
        self._fired = False

    async def on_step(self, context) -> list[Signal]:  # noqa: D102
        if self._fired:
            return []
        self._fired = True
        return [Signal(symbol="TEST", side="buy", quantity=1.0, reason="r")]


class _FakeDataProvider:
    """2스텝짜리 인메모리 data_provider (실제 store/API 호출 없음)."""

    def __init__(self) -> None:
        self._idx = 0
        self._ts = [datetime(2026, 1, 1), datetime(2026, 1, 2)]
        self.start = "2026-01-01"
        self.end = "2026-01-02"
        self.loaded_datasets: list = []

    def get_total_steps(self) -> int:
        return len(self._ts)

    def advance(self) -> bool:
        self._idx += 1
        return self._idx < len(self._ts)

    def get_current_timestamp(self):
        if self._idx >= len(self._ts):
            return None
        return self._ts[self._idx]

    async def get_current_price(self, symbol: str) -> float:
        return 100.0


def _make_executor(exchange: str | None) -> BacktestExecutor:
    kwargs = {"exchange": exchange} if exchange is not None else {}
    return BacktestExecutor(
        strategy_cls=_SingleBuyStrategy,
        data_provider=_FakeDataProvider(),
        initial_balance=1_000_000.0,
        **kwargs,
    )


class TestExecutorLabelsTradeWithExchange:
    """BacktestExecutor(exchange=) → BacktestTrade.exchange (executor→trade hop)."""

    @pytest.mark.asyncio
    async def test_explicit_exchange_labels_result_trades(self):
        executor = _make_executor("NYSE")

        result = await executor.run()

        assert result.trades, "1건의 거래가 체결되어야 한다"
        assert all(t.exchange == "NYSE" for t in result.trades)

    @pytest.mark.asyncio
    async def test_default_exchange_labels_result_trades_krx(self):
        executor = _make_executor(None)

        result = await executor.run()

        assert result.trades
        assert all(t.exchange == "KRX" for t in result.trades)


class TestServicePassesExchangeToExecutor:
    """BacktestService.run() → BacktestExecutor(exchange=...) ctor 전달.

    end-to-end에 가깝게: `_validate_config(exchange=...)`가 만든
    `validated.exchange`가 executor 생성 인자로 흐르는지 고정.
    """

    async def _run_capture_executor_kwargs(self, config: dict) -> dict:
        provider_instance = MagicMock()
        provider_instance.loaded_datasets = []
        executor_instance = MagicMock()

        async def _fake_run(progress_callback=None):
            return BacktestResult(
                strategy_name="S",
                strategy_version="1",
                start_date="2026-01-01",
                end_date="2026-01-02",
                initial_balance=1.0,
                final_balance=1.0,
                total_return=0.0,
            )

        executor_instance.run = _fake_run

        with (
            patch("ante.backtest.service.StrategyLoader") as mock_loader,
            patch("ante.backtest.service.ParquetStore"),
            patch(
                "ante.backtest.service.BacktestDataProvider",
                return_value=provider_instance,
            ),
            patch(
                "ante.backtest.service.BacktestExecutor",
                return_value=executor_instance,
            ) as mock_executor_cls,
        ):
            mock_loader.load.return_value = MagicMock()
            svc = BacktestService()
            await svc.run(config)

        _, kwargs = mock_executor_cls.call_args
        return kwargs

    @pytest.mark.asyncio
    async def test_run_constructs_executor_with_config_exchange(self):
        kwargs = await self._run_capture_executor_kwargs(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "symbols": [],
                "exchange": "NYSE",
            }
        )
        assert kwargs["exchange"] == "NYSE"

    @pytest.mark.asyncio
    async def test_run_defaults_executor_exchange_to_krx(self):
        kwargs = await self._run_capture_executor_kwargs(
            {
                "strategy_path": "s.py",
                "start_date": "2026-01-01",
                "end_date": "2026-01-02",
                "symbols": [],
            }
        )
        assert kwargs["exchange"] == "KRX"
