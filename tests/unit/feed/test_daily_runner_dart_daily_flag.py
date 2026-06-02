"""DailyRunner가 DART collect를 daily=True로 호출하는지 검증한다(#2101).

`feed run daily`는 DART를 daily-incremental("최신 분기 1개")로 수집해야 하며,
backfill_since 전 분기를 순회해서는 안 된다. DailyRunner._collect_dart가
DARTCollector.collect(..., daily=True)를 전달하는지 잠근다. 반대로 BackfillRunner는
daily 인자를 넘기지 않아(기본 False) 전 분기 순회를 유지한다.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from ante.data.store import ParquetStore
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.daily_runner import DailyRunner


class _RecordingDARTCollector:
    """collect 호출 시 ``daily`` 인자 값을 기록하는 stub DARTCollector."""

    def __init__(self) -> None:
        self.daily_calls: list[bool] = []

    async def collect(
        self,
        data_path: Path,
        feed_dir: Path,
        checkpoint: Checkpoint,
        config: dict[str, Any],
        store: ParquetStore,
        daily: bool = False,
    ) -> tuple[int, set[str], list[dict]]:
        self.daily_calls.append(daily)
        return 0, set(), []


@pytest.mark.asyncio
async def test_daily_runner_calls_dart_collect_with_daily_true(
    tmp_path: Path,
) -> None:
    """DailyRunner._collect_dart가 collect(..., daily=True)를 전달한다."""
    data_path = tmp_path / "data"
    feed_dir = data_path / ".feed"
    (feed_dir / "checkpoints").mkdir(parents=True)

    dart = _RecordingDARTCollector()
    store = ParquetStore(base_path=data_path)
    runner = DailyRunner(
        data_go_kr_collector=None,
        dart_collector=dart,
        store=store,
    )

    await runner.run(
        data_path=data_path,
        config={"schedule": {"backfill_since": "2015-01-01"}},
        feed_dir=feed_dir,
        started_at=datetime.now(tz=UTC),
        is_blocked=lambda config, target_date: False,
        target_date="2026-05-29",
    )

    assert dart.daily_calls == [True]
