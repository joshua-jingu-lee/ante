"""FeedOrchestrator.run_daily의 target_date forward 회귀 테스트.

#1943: CLI ``--date`` → orchestrator → DailyRunner 의 명시 파라미터
chain 회귀 잠금. ``_daily_runner`` 를 mock으로 교체해 호출 인자만 검증.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.orchestrator import FeedOrchestrator


def _make_runner_result(target_date: str | None) -> CollectionResult:
    return CollectionResult(
        mode="daily",
        started_at="2026-05-28T00:00:00Z",
        finished_at="2026-05-28T00:00:01Z",
        duration_seconds=1.0,
        target_date=target_date,
    )


def _make_orchestrator_with_mock_runner(
    expected_result: CollectionResult,
) -> tuple[FeedOrchestrator, AsyncMock]:
    """`_daily_runner.run` 만 mock 으로 바꾼 orchestrator."""
    orch = FeedOrchestrator()
    mock_run = AsyncMock(return_value=expected_result)
    orch._daily_runner = MagicMock()  # type: ignore[assignment]
    orch._daily_runner.run = mock_run  # type: ignore[assignment]
    # 리포트 생성 부수효과 차단
    orch._save_report = MagicMock()  # type: ignore[assignment]
    return orch, mock_run


@pytest.mark.asyncio
async def test_run_daily_forwards_explicit_target_date(
    tmp_path: Path,
) -> None:
    """명시 ``target_date`` 가 DailyRunner.run 에 keyword 로 전달된다."""
    explicit = "2024-12-30"
    orch, mock_run = _make_orchestrator_with_mock_runner(_make_runner_result(explicit))

    result = await orch.run_daily(
        data_path=tmp_path,
        config={},
        target_date=explicit,
    )

    mock_run.assert_awaited_once()
    kwargs = mock_run.await_args.kwargs
    assert kwargs.get("target_date") == explicit
    assert result.target_date == explicit


@pytest.mark.asyncio
async def test_run_daily_forwards_none_target_date_default(
    tmp_path: Path,
) -> None:
    """``target_date`` 미제공 시 None 이 forward 된다 (fallback은 DailyRunner 책임)."""
    orch, mock_run = _make_orchestrator_with_mock_runner(
        _make_runner_result("2026-05-27")
    )

    await orch.run_daily(
        data_path=tmp_path,
        config={},
    )

    mock_run.assert_awaited_once()
    kwargs = mock_run.await_args.kwargs
    assert kwargs.get("target_date") is None


@pytest.mark.asyncio
async def test_run_daily_forwards_explicit_none(
    tmp_path: Path,
) -> None:
    """스케줄러처럼 ``target_date=None`` 명시 전달 케이스."""
    orch, mock_run = _make_orchestrator_with_mock_runner(
        _make_runner_result("2026-05-27")
    )

    await orch.run_daily(
        data_path=tmp_path,
        config={},
        target_date=None,
    )

    kwargs = mock_run.await_args.kwargs
    assert kwargs.get("target_date") is None
