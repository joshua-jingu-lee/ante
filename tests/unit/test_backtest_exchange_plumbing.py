"""non-CLI backtest exchange plumbing 테스트 (#1585).

CLI 검증과 분리 — service/provider가 exchange를 무시해도 CLI 테스트는
통과하므로 별도 고정한다:

- `_validate_config`: exchange 미지정 → KRX 기본 / 명시 → 그대로 (default plumbing).
- `BacktestService.run()`: `BacktestDataProvider`를 `exchange=<config.exchange>`로 생성.
- `BacktestDataProvider.load()`: store.read() **및** store.resolve_path() 양쪽에
  동일 exchange 전달 (resolve_path 메타 hop 회귀 고정).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

from ante.backtest.config import BacktestConfig
from ante.backtest.data_provider import BacktestDataProvider
from ante.backtest.result import BacktestResult
from ante.backtest.service import BacktestService


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
