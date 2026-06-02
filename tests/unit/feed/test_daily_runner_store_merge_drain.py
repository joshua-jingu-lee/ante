"""DailyRunner의 store_merge 경고 drain 회귀 테스트(#2002).

backfill_runner는 각 store 쓰기 단계(data.go.kr/DART/지표) 직후
``ctx.warnings.extend(store.drain_warnings())`` 를 호출해 store의 merge 이상
경고를 ``CollectionResult.warnings`` (→ daily report ``warnings``)로 표면화한다.
daily_runner에는 이 drain 경로가 없어 store merge 경고가 store 내부
``_pending_warnings`` 버퍼에만 남고 ``.feed/reports/*-daily.json`` 에 안 나타났다.

이 테스트는 backfill 회귀 테스트
(``test_report.py::TestBackfillReportSurfacesStoreMergeWarning``)와 동형으로,
daily 경로에서도 store_merge 경고가 결과 warnings에 표면화되고 store pending이
비워지는지를 잠근다.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import pytest

from ante.data.store import ParquetStore
from ante.feed.pipeline.daily_runner import DailyRunner


class _AnomalyDataGoKrCollector:
    """store merge 이상을 발생시키는 stub data.go.kr collector.

    `.collect()`가 호출되면, 사전에 손상시켜 둔(읽기 불가) 파티션 위로
    fundamental write를 시도한다. ParquetStore는 기존 파일을 덮어쓰지 않고
    `store_merge` 이상 경고만 버퍼에 적재한다(#1964 silent-overwrite 제거).
    """

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, set[str], list[dict]]:
        df = pl.DataFrame(
            {
                "date": [date(2025, 9, 30)],
                "symbol": ["005930"],
                "market_cap": [510000000000],
                "source": ["data_go_kr"],
            }
        )
        store.write("005930", "krx", df, data_type="fundamental")
        return 1, {"005930"}, []


@pytest.mark.asyncio
async def test_daily_run_surfaces_store_merge_warning(tmp_path: Path) -> None:
    """store merge anomaly가 daily 결과의 warnings에 등장하고 pending이 비워진다.

    수정 전에는 store 덮어쓰기가 stderr 로그/내부 버퍼로만 남고
    CollectionResult.warnings는 비어 있었다(#2002).
    """
    data_path = tmp_path / "data"
    feed_dir = data_path / ".feed"
    (feed_dir / "checkpoints").mkdir(parents=True)

    # 손상된(읽기 불가) 파티션을 사전 배치 → 다음 write에서 merge 실패 유발.
    part_dir = data_path / "fundamental" / "KRX" / "005930"
    part_dir.mkdir(parents=True)
    (part_dir / "2025-09.parquet").write_bytes(b"corrupt-not-parquet")

    store = ParquetStore(base_path=data_path)
    runner = DailyRunner(
        data_go_kr_collector=_AnomalyDataGoKrCollector(),
        dart_collector=None,
        store=store,
    )

    result = await runner.run(
        data_path=data_path,
        config={},
        feed_dir=feed_dir,
        started_at=datetime.now(tz=UTC),
        is_blocked=lambda config, target_date: False,
        target_date="2025-09-30",
    )

    store_merge_warnings = [
        w for w in result.warnings if w.get("type") == "store_merge"
    ]
    assert store_merge_warnings, (
        f"store_merge 경고가 result.warnings에 없음: {result.warnings}"
    )
    assert "2025-09.parquet" in store_merge_warnings[0]["path"]

    # drain 후 store 내부 버퍼는 비워져 중복 전파되지 않는다.
    assert store.drain_warnings() == []

    # 손상 파일은 보존됨(데이터 손실 방지).
    assert (part_dir / "2025-09.parquet").read_bytes() == b"corrupt-not-parquet"


@pytest.mark.asyncio
async def test_daily_run_no_store_warnings_when_clean(tmp_path: Path) -> None:
    """store 이상이 없으면 daily 결과 warnings에 store_merge가 없다.

    drain 추가가 정상 경로에 store_merge 잡음을 만들지 않음을 확인한다.
    """
    data_path = tmp_path / "data"
    feed_dir = data_path / ".feed"
    (feed_dir / "checkpoints").mkdir(parents=True)

    class _CleanCollector:
        async def collect(
            self,
            target_date: str,
            store: ParquetStore,
        ) -> tuple[int, set[str], list[dict]]:
            df = pl.DataFrame(
                {
                    "date": [date(2025, 9, 30)],
                    "symbol": ["005930"],
                    "market_cap": [510000000000],
                    "source": ["data_go_kr"],
                }
            )
            store.write("005930", "krx", df, data_type="fundamental")
            return 1, {"005930"}, []

    store = ParquetStore(base_path=data_path)
    runner = DailyRunner(
        data_go_kr_collector=_CleanCollector(),
        dart_collector=None,
        store=store,
    )

    result = await runner.run(
        data_path=data_path,
        config={},
        feed_dir=feed_dir,
        started_at=datetime.now(tz=UTC),
        is_blocked=lambda config, target_date: False,
        target_date="2025-09-30",
    )

    store_merge_warnings = [
        w for w in result.warnings if w.get("type") == "store_merge"
    ]
    assert store_merge_warnings == []
