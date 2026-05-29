"""DailyRunner.run의 target_date 파라미터 회귀 테스트.

#1943: `feed run daily --date` 가 monkey-patch 무효로 무시되던 버그를
명시 파라미터 chain으로 고친 변경의 회귀 잠금.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.feed.pipeline.daily_runner import DailyRunner


@pytest.fixture
def runner_with_mock_collectors() -> tuple[DailyRunner, AsyncMock, AsyncMock]:
    """DataGoKr / DART collector를 mock으로 채운 DailyRunner."""
    data_go_kr = AsyncMock()
    data_go_kr.collect = AsyncMock(return_value=(0, set(), []))

    dart = AsyncMock()
    dart.collect = AsyncMock(return_value=(0, set(), []))

    indicator = MagicMock()
    indicator.compute = MagicMock(return_value=0)

    store = MagicMock()

    runner = DailyRunner(
        data_go_kr_collector=data_go_kr,
        dart_collector=dart,
        indicator_calculator=indicator,
        store=store,
    )
    return runner, data_go_kr, dart


@pytest.mark.asyncio
async def test_run_uses_explicit_target_date(
    runner_with_mock_collectors: tuple[DailyRunner, AsyncMock, AsyncMock],
    tmp_path: Path,
) -> None:
    """``target_date`` 명시 시 그 값이 collector에 전달된다."""
    runner, data_go_kr, _dart = runner_with_mock_collectors

    explicit_date = "2024-12-30"
    started_at = datetime(2026, 5, 28, tzinfo=UTC)
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    def _never_blocked(_config: dict, _target_date: str) -> bool:
        return False

    # generate_daily_date가 호출되지 않아야 함 — 명시 값이 우선.
    with patch("ante.feed.pipeline.daily_runner.generate_daily_date") as mock_fallback:
        result = await runner.run(
            data_path=tmp_path,
            config={},
            feed_dir=feed_dir,
            started_at=started_at,
            is_blocked=_never_blocked,
            target_date=explicit_date,
        )

    assert mock_fallback.call_count == 0
    # data.go.kr collector가 명시 날짜로 호출됨
    data_go_kr.collect.assert_awaited_once()
    call_args = data_go_kr.collect.await_args
    assert call_args.args[0] == explicit_date
    # 결과 target_date도 명시 값
    assert result.target_date == explicit_date


@pytest.mark.asyncio
async def test_run_falls_back_when_target_date_none(
    runner_with_mock_collectors: tuple[DailyRunner, AsyncMock, AsyncMock],
    tmp_path: Path,
) -> None:
    """``target_date=None`` 시 ``generate_daily_date()`` fallback."""
    runner, data_go_kr, _dart = runner_with_mock_collectors

    fallback_date = "2026-05-27"  # 어제 가정
    started_at = datetime(2026, 5, 28, tzinfo=UTC)
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    def _never_blocked(_config: dict, _target_date: str) -> bool:
        return False

    with patch(
        "ante.feed.pipeline.daily_runner.generate_daily_date",
        return_value=fallback_date,
    ) as mock_fallback:
        result = await runner.run(
            data_path=tmp_path,
            config={},
            feed_dir=feed_dir,
            started_at=started_at,
            is_blocked=_never_blocked,
            target_date=None,
        )

    mock_fallback.assert_called_once()
    data_go_kr.collect.assert_awaited_once()
    assert data_go_kr.collect.await_args.args[0] == fallback_date
    assert result.target_date == fallback_date


@pytest.mark.asyncio
async def test_run_default_target_date_is_none(
    runner_with_mock_collectors: tuple[DailyRunner, AsyncMock, AsyncMock],
    tmp_path: Path,
) -> None:
    """``target_date`` 인자 미제공(기본값) 시에도 fallback 경로."""
    runner, data_go_kr, _dart = runner_with_mock_collectors

    fallback_date = "2026-05-27"
    started_at = datetime(2026, 5, 28, tzinfo=UTC)
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    def _never_blocked(_config: dict, _target_date: str) -> bool:
        return False

    with patch(
        "ante.feed.pipeline.daily_runner.generate_daily_date",
        return_value=fallback_date,
    ) as mock_fallback:
        # target_date 인자 자체를 생략 — 기존 호출자(테스트/내부) 보호.
        result = await runner.run(
            data_path=tmp_path,
            config={},
            feed_dir=feed_dir,
            started_at=started_at,
            is_blocked=_never_blocked,
        )

    mock_fallback.assert_called_once()
    assert data_go_kr.collect.await_args.args[0] == fallback_date
    assert result.target_date == fallback_date


@pytest.mark.asyncio
async def test_run_explicit_target_date_propagates_to_blocked_check(
    runner_with_mock_collectors: tuple[DailyRunner, AsyncMock, AsyncMock],
    tmp_path: Path,
) -> None:
    """방어 가드(is_blocked)에 명시 날짜가 전달된다."""
    runner, data_go_kr, _dart = runner_with_mock_collectors

    explicit_date = "2024-12-30"
    started_at = datetime(2026, 5, 28, tzinfo=UTC)
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    seen: list[str] = []

    def _capturing_blocked(_config: dict, target_date: str) -> bool:
        seen.append(target_date)
        return True  # 가드로 차단 → 빠른 종료

    result = await runner.run(
        data_path=tmp_path,
        config={},
        feed_dir=feed_dir,
        started_at=started_at,
        is_blocked=_capturing_blocked,
        target_date=explicit_date,
    )

    assert seen == [explicit_date]
    # 차단됐으므로 collector 호출 없음
    data_go_kr.collect.assert_not_awaited()
    assert result.target_date == explicit_date
