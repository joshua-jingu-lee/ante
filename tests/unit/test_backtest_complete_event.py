"""BacktestCompleteEvent 발행 통합 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.backtest.service import BacktestService
from ante.eventbus.events import BacktestCompleteEvent


class TestBacktestCompleteEventPublish:
    @pytest.mark.asyncio
    async def test_run_publishes_complete_event(self):
        """BacktestService.run() 완료 시 BacktestCompleteEvent 발행."""
        mock_eventbus = MagicMock()
        mock_eventbus.publish = AsyncMock()

        service = BacktestService(data_path="data/", eventbus=mock_eventbus)

        # BacktestResult mock
        mock_result = MagicMock()
        mock_result.strategy_name = "momentum"
        mock_result.strategy_version = "1.0.0"

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        with patch.object(service, "_validate_config"):
            with patch(
                "ante.backtest.service.StrategyLoader.load",
                return_value=MagicMock,
            ):
                with patch(
                    "ante.backtest.service.BacktestDataProvider",
                    return_value=MagicMock(),
                ):
                    with patch(
                        "ante.backtest.service.BacktestExecutor"
                    ) as mock_executor_cls:
                        mock_executor = MagicMock()
                        mock_executor.run = AsyncMock(return_value=mock_result)
                        mock_executor_cls.return_value = mock_executor

                        await service.run(config)

        mock_eventbus.publish.assert_called_once()
        event = mock_eventbus.publish.call_args[0][0]
        assert isinstance(event, BacktestCompleteEvent)
        assert event.strategy_id == "momentum_v1.0.0"
        assert event.status == "completed"

    @pytest.mark.asyncio
    async def test_run_without_eventbus(self):
        """EventBus 미설정 시 이벤트 발행 건너뜀."""
        service = BacktestService(data_path="data/", eventbus=None)

        mock_result = MagicMock()
        mock_result.strategy_name = "test"
        mock_result.strategy_version = "1.0.0"

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        with patch.object(service, "_validate_config"):
            with patch(
                "ante.backtest.service.StrategyLoader.load",
                return_value=MagicMock,
            ):
                with patch(
                    "ante.backtest.service.BacktestDataProvider",
                    return_value=MagicMock(),
                ):
                    with patch(
                        "ante.backtest.service.BacktestExecutor"
                    ) as mock_executor_cls:
                        mock_executor = MagicMock()
                        mock_executor.run = AsyncMock(return_value=mock_result)
                        mock_executor_cls.return_value = mock_executor

                        result = await service.run(config)

        assert result == mock_result  # 정상 반환
