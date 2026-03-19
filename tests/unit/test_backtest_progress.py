"""백테스트 진행률 표시 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.backtest.executor import BacktestExecutor


class TestProgressCallback:
    @pytest.mark.asyncio
    async def test_callback_called_each_step(self):
        """진행률 콜백이 매 스텝 호출된다."""
        from datetime import datetime

        mock_strategy_cls = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.on_start = MagicMock()
        mock_strategy.on_stop = MagicMock()
        mock_strategy.on_step = AsyncMock(return_value=[])
        mock_meta = MagicMock()
        mock_meta.name = "test"
        mock_meta.version = "1.0"
        mock_strategy.meta = mock_meta
        mock_strategy_cls.return_value = mock_strategy

        mock_data = MagicMock()
        mock_data.get_total_steps.return_value = 3
        mock_data.advance = MagicMock(side_effect=[True, True, True, False])
        mock_data.get_current_timestamp.return_value = datetime(2025, 1, 1)
        mock_data.start = "2025-01-01"
        mock_data.end = "2025-12-31"

        progress_calls = []

        def callback(current: int, total: int) -> None:
            progress_calls.append((current, total))

        executor = BacktestExecutor(
            strategy_cls=mock_strategy_cls,
            data_provider=mock_data,
        )
        await executor.run(progress_callback=callback)

        assert len(progress_calls) == 3
        assert progress_calls[0] == (1, 3)
        assert progress_calls[1] == (2, 3)
        assert progress_calls[2] == (3, 3)

    @pytest.mark.asyncio
    async def test_no_callback_works(self):
        """콜백 없이도 정상 동작한다."""
        from datetime import datetime

        mock_strategy_cls = MagicMock()
        mock_strategy = MagicMock()
        mock_strategy.on_start = MagicMock()
        mock_strategy.on_stop = MagicMock()
        mock_strategy.on_step = AsyncMock(return_value=[])
        mock_meta = MagicMock()
        mock_meta.name = "test"
        mock_meta.version = "1.0"
        mock_strategy.meta = mock_meta
        mock_strategy_cls.return_value = mock_strategy

        mock_data = MagicMock()
        mock_data.get_total_steps.return_value = 2
        mock_data.advance = MagicMock(side_effect=[True, True, False])
        mock_data.get_current_timestamp.return_value = datetime(2025, 1, 1)
        mock_data.start = "2025-01-01"
        mock_data.end = "2025-12-31"

        executor = BacktestExecutor(
            strategy_cls=mock_strategy_cls,
            data_provider=mock_data,
        )
        result = await executor.run()

        assert result is not None
        assert result.strategy_name == "test"


class TestBacktestServiceProgress:
    @pytest.mark.asyncio
    async def test_service_passes_callback(self):
        """BacktestService가 progress_callback을 전달한다."""
        with (
            patch("ante.backtest.service.StrategyLoader.load") as mock_load,
            patch("ante.backtest.service.BacktestDataProvider") as mock_dp_cls,
            patch("ante.backtest.service.BacktestExecutor") as mock_exec_cls,
        ):
            mock_load.return_value = MagicMock()
            mock_dp = AsyncMock()
            mock_dp.load = MagicMock(return_value=100)
            mock_dp_cls.return_value = mock_dp

            mock_exec = AsyncMock()
            mock_result = MagicMock()
            mock_exec.run = AsyncMock(return_value=mock_result)
            mock_exec_cls.return_value = mock_exec

            from ante.backtest.service import BacktestService

            service = BacktestService()
            cb = MagicMock()
            config = {
                "strategy_path": "test.py",
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
                "symbols": ["005930"],
            }
            await service.run(config, progress_callback=cb)

            mock_exec.run.assert_called_once_with(
                progress_callback=cb,
            )
