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


def _place_noncoercible_partition(data_path: Path) -> Path:
    """유효하나 결합-불가(non-coercible) fundamental 파티션을 사전 배치한다.

    공유키 컬럼 market_cap을 List로 두면 다음 scalar write와
    `pl.concat(how="diagonal_relaxed")` 시 supertype 결정 실패로 store_merge가
    발생한다(read는 성공, concat만 실패 = genuine merge-fail). corrupt(읽기 불가)
    파일과 달리 self-heal 격리 대상이 아니라 store_merge 게이트 경로다.
    """
    part_dir = data_path / "fundamental" / "KRX" / "005930"
    part_dir.mkdir(parents=True, exist_ok=True)
    filepath = part_dir / "2025-09.parquet"
    pl.DataFrame(
        {
            "date": [date(2025, 9, 10)],
            "symbol": ["005930"],
            "market_cap": [[1, 2, 3]],
            "source": ["data_go_kr"],
        }
    ).write_parquet(str(filepath))
    return filepath


class _AnomalyDataGoKrCollector:
    """store 이상(merge 실패 또는 self-heal)을 발생시키는 stub data.go.kr collector.

    `.collect()`가 호출되면, 사전에 배치해 둔 이상 파티션 위로 fundamental write를
    시도한다. 사전 파티션이 결합-불가(non-coercible·읽기 가능)면 ParquetStore는
    기존 파일을 보존하고 `store_merge` 경고를 적재한다(#1964). 사전 파티션이
    손상(읽기 불가)이면 격리 후 재생성하고 `store_recovered` 경고를 적재한다
    (#2413 self-heal). 둘 다 store 경고 버퍼를 통해 표면화된다.
    """

    async def collect(
        self,
        target_date: str,
        store: ParquetStore,
    ) -> tuple[int, bool, set[str], list[dict]]:
        df = pl.DataFrame(
            {
                "date": [date(2025, 9, 30)],
                "symbol": ["005930"],
                "market_cap": [510000000000],
                "source": ["data_go_kr"],
            }
        )
        # merge 실패 시 store.write는 net_delta=0, self-heal은 net_delta>0.
        net_delta = store.write("005930", "krx", df, data_type="fundamental")
        # (net_delta, stored_ok, syms, warns) 4-tuple (#1993). 유효 데이터 write
        # 호출 완료 → stored_ok=True. store 이상은 store 경고로 표면화된다.
        return net_delta, True, {"005930"}, []


@pytest.mark.asyncio
async def test_daily_run_surfaces_store_merge_warning(tmp_path: Path) -> None:
    """store merge anomaly가 daily 결과의 warnings에 등장하고 pending이 비워진다.

    수정 전에는 store 덮어쓰기가 stderr 로그/내부 버퍼로만 남고
    CollectionResult.warnings는 비어 있었다(#2002). #2413 이후 store_merge는
    **읽기 가능한** 결합-불가 파티션에서만 발생하므로 non-coercible fixture로
    재현한다(읽기 불가 파티션은 self-heal로 store_recovered 경로).
    """
    data_path = tmp_path / "data"
    feed_dir = data_path / ".feed"
    (feed_dir / "checkpoints").mkdir(parents=True)

    # 결합-불가(읽기 가능) 파티션을 사전 배치 → 다음 write에서 merge 실패 유발.
    filepath = _place_noncoercible_partition(data_path)
    before = filepath.read_bytes()

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

    # 유효한 결합-불가 파티션은 보존됨(데이터 손실 방지, self-heal 대상 아님).
    assert filepath.read_bytes() == before


@pytest.mark.asyncio
async def test_daily_run_surfaces_store_recovered_warning(tmp_path: Path) -> None:
    """손상(읽기 불가) 파티션 → self-heal → store_recovered가 daily warnings에 등장.

    daily_runner의 drain 경로는 store_recovered도 함께 표면화한다(#2413).
    checkpoint 게이트가 없는 daily 경로에서 self-heal 이벤트가 사용자에게
    노출되는지 잠근다.
    """
    data_path = tmp_path / "data"
    feed_dir = data_path / ".feed"
    (feed_dir / "checkpoints").mkdir(parents=True)

    # 손상(읽기 불가) 파티션을 사전 배치 → 다음 write에서 self-heal 유발.
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

    recovered = [w for w in result.warnings if w.get("type") == "store_recovered"]
    assert recovered, (
        f"store_recovered 경고가 result.warnings에 없음: {result.warnings}"
    )
    assert "2025-09.parquet" in recovered[0]["path"]
    # self-heal은 store_merge를 만들지 않는다(비게이트).
    assert all(w.get("type") != "store_merge" for w in result.warnings)

    # drain 후 store 내부 버퍼는 비워진다.
    assert store.drain_warnings() == []

    # 손상 파일은 `.corrupted`로 격리되고 파티션은 신규 데이터로 재생성된다.
    assert (part_dir / "2025-09.corrupted").read_bytes() == b"corrupt-not-parquet"
    assert (part_dir / "2025-09.parquet").exists()


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
        ) -> tuple[int, bool, set[str], list[dict]]:
            df = pl.DataFrame(
                {
                    "date": [date(2025, 9, 30)],
                    "symbol": ["005930"],
                    "market_cap": [510000000000],
                    "source": ["data_go_kr"],
                }
            )
            net_delta = store.write("005930", "krx", df, data_type="fundamental")
            # (net_delta, stored_ok, syms, warns) 4-tuple (#1993).
            return net_delta, True, {"005930"}, []

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
