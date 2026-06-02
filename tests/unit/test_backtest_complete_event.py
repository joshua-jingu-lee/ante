"""BacktestCompleteEvent 발행 통합 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.backtest.config import BacktestConfig
from ante.backtest.service import BacktestService
from ante.eventbus.events import BacktestCompleteEvent
from ante.strategy.base import StrategyMeta
from ante.strategy.validator import ValidationResult


def _bypass_validator():
    """service.run의 StrategyValidator 게이트(#2039)를 우회한다.

    이 파일의 테스트는 ``_validate_config`` 와 ``StrategyLoader.load`` 를 mock해
    실제 전략 파일 없이 run() 오케스트레이션만 검증한다. #2039에서 load 직전에
    추가된 정적 검증도 실제 파일을 읽지 않도록 valid 결과로 대체한다.
    """
    return patch(
        "ante.backtest.service.StrategyValidator.validate",
        return_value=ValidationResult(valid=True),
    )


def _strategy_cls_with_meta() -> MagicMock:
    """``StrategyLoader.load`` 가 반환할 strategy_cls 모사 (실제 ``.meta`` 보유).

    #2060 meta fallback 으로 run() 이 ``strategy_cls.meta`` 에 접근하므로 실제
    ``StrategyMeta`` 를 단 strategy_cls 를 반환한다(symbols=[] → no-symbols).
    """
    cls = MagicMock()
    cls.meta = StrategyMeta(name="s", version="1.0", description="evt")
    return cls


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

        with patch.object(
            service,
            "_validate_config",
            return_value=BacktestConfig(strategy_path="strategies/test.py"),
        ):
            with _bypass_validator():
                with patch(
                    "ante.backtest.service.StrategyLoader.load",
                    return_value=_strategy_cls_with_meta(),
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

        with patch.object(
            service,
            "_validate_config",
            return_value=BacktestConfig(strategy_path="strategies/test.py"),
        ):
            with _bypass_validator():
                with patch(
                    "ante.backtest.service.StrategyLoader.load",
                    return_value=_strategy_cls_with_meta(),
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
