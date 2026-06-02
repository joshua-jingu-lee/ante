"""BacktestCompleteEvent 발행 + 결과 artifact 저장(#1998) 통합 테스트."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.backtest.config import BacktestConfig
from ante.backtest.service import BacktestService
from ante.eventbus.events import BacktestCompleteEvent
from ante.report.draft import ReportDraftGenerator
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


# #1998: result.to_dict() 가 json.dumps 로 직렬화되므로(durable artifact 저장),
# mock result 는 MagicMock 이 아니라 실제 dict 를 반환해야 한다. 아래 shape 은
# BacktestResult.to_dict()/ReportDraftGenerator._load_result 가 소비하는 계약.
def _sample_result_dict(strategy: str) -> dict:
    return {
        "strategy": strategy,
        "period": "2025-01-01 ~ 2025-12-31",
        "initial_balance": 10_000_000,
        "final_balance": 11_000_000,
        "total_return_pct": 10.0,
        "total_trades": 3,
        "metrics": {"sharpe_ratio": 1.1, "max_drawdown": -5.0, "win_rate": 0.6},
        "equity_curve": [],
        "trades": [],
        "config": {},
        "datasets": [],
    }


def _mock_result(
    *,
    strategy_name: str,
    strategy_version: str,
) -> MagicMock:
    """실제 dict 를 반환하는 to_dict 를 단 BacktestResult mock.

    ``result_path`` 는 service.run() 이 저장 후 set 하므로 초기값 "" 로 둔다
    (BacktestResult dataclass 기본값과 동일).
    """
    result = MagicMock()
    result.strategy_name = strategy_name
    result.strategy_version = strategy_version
    result.result_path = ""
    result.to_dict = MagicMock(
        return_value=_sample_result_dict(f"{strategy_name}_v{strategy_version}")
    )
    return result


def _patched_run(service: BacktestService, mock_result: MagicMock, data_path: str):
    """run() 의 무거운 의존성(validator/loader/provider/executor)을 mock 한다.

    ``_validate_config`` 는 data_paths 가 *data_path* 를 가리키도록 한 effective
    BacktestConfig 를 반환해, #1998 artifact 가 격리된 디렉토리에 저장되게 한다.
    """
    cfg = BacktestConfig(strategy_path="strategies/test.py", data_paths=[data_path])

    def _run():
        return patch.object(service, "_validate_config", return_value=cfg)

    mock_executor = MagicMock()
    mock_executor.run = AsyncMock(return_value=mock_result)

    return (
        _run(),
        _bypass_validator(),
        patch(
            "ante.backtest.service.StrategyLoader.load",
            return_value=_strategy_cls_with_meta(),
        ),
        patch(
            "ante.backtest.service.BacktestDataProvider",
            return_value=MagicMock(),
        ),
        patch("ante.backtest.service.BacktestExecutor", return_value=mock_executor),
    )


class TestBacktestCompleteEventPublish:
    @pytest.mark.asyncio
    async def test_run_publishes_complete_event(self, tmp_path):
        """BacktestService.run() 완료 시 BacktestCompleteEvent 발행."""
        mock_eventbus = MagicMock()
        mock_eventbus.publish = AsyncMock()

        service = BacktestService(data_path=str(tmp_path), eventbus=mock_eventbus)
        mock_result = _mock_result(strategy_name="momentum", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with p1, p2, p3, p4, p5:
            await service.run(config)

        mock_eventbus.publish.assert_called_once()
        event = mock_eventbus.publish.call_args[0][0]
        assert isinstance(event, BacktestCompleteEvent)
        assert event.strategy_id == "momentum_v1.0.0"
        assert event.status == "completed"

    @pytest.mark.asyncio
    async def test_run_saves_result_artifact(self, tmp_path):
        """#1998: run() 이 결과를 .backtest/results/*.json 으로 저장한다."""
        service = BacktestService(data_path=str(tmp_path), eventbus=None)
        mock_result = _mock_result(strategy_name="momentum", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with p1, p2, p3, p4, p5:
            result = await service.run(config)

        results_dir = tmp_path / ".backtest" / "results"
        saved = list(results_dir.glob("momentum_v1.0.0_*.json"))
        assert len(saved) == 1
        # result.result_path 가 저장 경로로 set 되고 파일이 실제 존재
        assert result.result_path == str(saved[0])
        assert Path(result.result_path).exists()

    @pytest.mark.asyncio
    async def test_event_result_path_points_to_saved_artifact(self, tmp_path):
        """#1998: event.result_path 가 비어있지 않고 실제 artifact 를 가리킨다."""
        mock_eventbus = MagicMock()
        mock_eventbus.publish = AsyncMock()

        service = BacktestService(data_path=str(tmp_path), eventbus=mock_eventbus)
        mock_result = _mock_result(strategy_name="momentum", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with p1, p2, p3, p4, p5:
            await service.run(config)

        event = mock_eventbus.publish.call_args[0][0]
        assert event.result_path != ""
        assert Path(event.result_path).exists()

    @pytest.mark.asyncio
    async def test_saved_artifact_roundtrips_to_draft_loader(self, tmp_path):
        """#1998: 저장된 artifact 를 ReportDraftGenerator._load_result 가 소비한다."""
        mock_eventbus = MagicMock()
        mock_eventbus.publish = AsyncMock()

        service = BacktestService(data_path=str(tmp_path), eventbus=mock_eventbus)
        mock_result = _mock_result(strategy_name="momentum", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with p1, p2, p3, p4, p5:
            await service.run(config)

        event = mock_eventbus.publish.call_args[0][0]
        loaded = ReportDraftGenerator._load_result(event.result_path)
        assert loaded is not None
        assert loaded["strategy"] == "momentum_v1.0.0"
        assert loaded["total_return_pct"] == 10.0
        # 실제 draft 생성까지 라운드트립 가능
        report = ReportDraftGenerator.generate_draft(loaded, event.strategy_id)
        assert report.strategy_name == "momentum"
        assert report.total_return_pct == 10.0

    @pytest.mark.asyncio
    async def test_run_graceful_when_artifact_save_fails(self, tmp_path, caplog):
        """#1998: 저장 실패(write_text raise) → result_path="" graceful + 이벤트 발행.

        read-only/ephemeral data dir 보호: backtest 자체는 실패하지 않고, 빈
        result_path 로 이벤트가 발행되어 자동 draft 만 skip 된다(무회귀).
        """
        mock_eventbus = MagicMock()
        mock_eventbus.publish = AsyncMock()

        service = BacktestService(data_path=str(tmp_path), eventbus=mock_eventbus)
        mock_result = _mock_result(strategy_name="momentum", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with (
            p1,
            p2,
            p3,
            p4,
            p5,
            patch(
                "pathlib.Path.write_text",
                side_effect=OSError("Read-only file system"),
            ),
            caplog.at_level("WARNING"),
        ):
            result = await service.run(config)

        # backtest 비실패 + 빈 result_path fallback
        assert result is mock_result
        assert result.result_path == ""
        # 이벤트는 빈 경로로 정상 발행(무회귀)
        mock_eventbus.publish.assert_called_once()
        event = mock_eventbus.publish.call_args[0][0]
        assert event.status == "completed"
        assert event.result_path == ""
        # 운영 가시성을 위한 warning 기록
        assert any("artifact 저장 실패" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_run_without_eventbus(self, tmp_path):
        """EventBus 미설정 시 이벤트 발행 건너뜀."""
        service = BacktestService(data_path=str(tmp_path), eventbus=None)
        mock_result = _mock_result(strategy_name="test", strategy_version="1.0.0")

        config = {
            "strategy_path": "strategies/test.py",
            "start_date": "2025-01-01",
            "end_date": "2025-12-31",
        }

        p1, p2, p3, p4, p5 = _patched_run(service, mock_result, str(tmp_path))
        with p1, p2, p3, p4, p5:
            result = await service.run(config)

        assert result is mock_result  # 정상 반환
