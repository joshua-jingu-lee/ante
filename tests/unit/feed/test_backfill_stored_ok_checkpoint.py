"""rows_written net-delta 전환 시 checkpoint 가드 무회귀 검증(#1993, #2015 무회귀).

rows_written을 net-new 저장 delta로 바꾸면 재수집 날짜는 net_delta=0이 된다.
checkpoint 전진을 ``written > 0`` (net-delta)로 가드하면 재수집 날짜가 미전진해
stall이 생긴다. 그래서 가드를 collector의 ``stored_ok`` (유효 데이터 store 성공
반영) 신호로 전환했다. 3-state:
  - 빈 응답(stored_ok=False) → 미전진(#2015 보존)
  - 유효 재수집(stored_ok=True, net_delta=0) → 전진(stall 해소)
  - store-merge 실패(R1: raise 안 함, store 경고만) → 미전진

이 파일은:
  (f) 재수집(stored_ok, net_delta=0) → checkpoint 전진(#2015 무회귀)
  (g) store-merge 실패 → checkpoint 미전진(R1 가드)
  (k) partial multi-write(일부 성공/일부 merge 실패) → rows_written 반영 +
      checkpoint 미전진
을 잠근다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ante.feed.pipeline.backfill_runner import (
    MAX_WARNINGS_PER_TYPE,
    BackfillRunner,
    _RunContext,
)
from ante.feed.pipeline.checkpoint import Checkpoint


class _ScriptedStore:
    """날짜별로 net_delta / store_merge 경고를 스크립트로 지정하는 store 스텁.

    runner는 collect 직후 ``store.drain_warnings()`` 를 호출해 store-merge 실패를
    가드한다. 이 스텁은 ``merge_fail_dates`` 에 든 날짜에서 다음 drain이
    ``store_merge`` 경고를 반환하도록 한다(ParquetStore._pending_warnings 동형).
    """

    def __init__(self, merge_fail_dates: set[str]) -> None:
        self._merge_fail_dates = merge_fail_dates
        self._pending: list[dict] = []
        self.current_date: str | None = None

    def arm(self, target_date: str) -> None:
        """이 날짜의 collect가 store-merge 실패를 유발하면 경고를 적재한다."""
        if target_date in self._merge_fail_dates:
            self._pending.append(
                {
                    "type": "store_merge",
                    "path": f"/fake/{target_date}.parquet",
                    "message": "파티션 merge 실패로 기존 데이터 보존",
                }
            )

    def drain_warnings(self) -> list[dict]:
        drained = list(self._pending)
        self._pending.clear()
        return drained


class _ScriptedCollector:
    """날짜별 (net_delta, stored_ok)를 스크립트로 지정하는 collector 스텁.

    collect 시 store.arm(target_date)를 호출해 해당 날짜의 store-merge 경고를
    무장시킨다(실제 ParquetStore가 _pending_warnings를 적재하는 시점을 모사).
    """

    def __init__(
        self,
        net_delta_by_date: dict[str, int],
        stored_ok_by_date: dict[str, bool],
        default_stored_ok: bool = True,
        warns_per_date: int = 0,
    ) -> None:
        self._net = net_delta_by_date
        self._stored_ok = stored_ok_by_date
        self._default_stored_ok = default_stored_ok
        # 날짜당 반환할 행 단위 business_rule 경고 건수(#2414 유계성 검증용).
        self._warns_per_date = warns_per_date
        self.calls: list[str] = []

    async def collect(
        self,
        target_date: str,
        store: _ScriptedStore,
    ) -> tuple[int, bool, set[str], list[dict]]:
        self.calls.append(target_date)
        store.arm(target_date)
        net = self._net.get(target_date, 0)
        stored_ok = self._stored_ok.get(target_date, self._default_stored_ok)
        syms = {f"SYM-{target_date[-2:]}"} if stored_ok else set()
        warns = [
            {
                "type": "business_rule",
                "date": target_date,
                "message": f"low > close #{i}",
            }
            for i in range(self._warns_per_date)
        ]
        return net, stored_ok, syms, warns


async def _run(
    feed_dir: Path,
    collector: _ScriptedCollector,
    store: _ScriptedStore,
    dates: list[str],
) -> tuple[Checkpoint, _RunContext]:
    checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
    runner = BackfillRunner(data_go_kr_collector=collector)
    ctx = _RunContext()
    await runner._collect_data_go_kr(
        dates,
        {},
        store,
        checkpoint,
        ctx,
        lambda _config, _date: False,
        lambda _config: False,
        None,
    )
    return checkpoint, ctx


# ── (f) 재수집(stored_ok, net_delta=0) → checkpoint 전진(#2015 무회귀) ─────────


@pytest.mark.asyncio
async def test_recollect_delta_zero_advances_checkpoint(tmp_path: Path) -> None:
    """유효 재수집(net_delta=0, stored_ok=True)이어도 checkpoint가 전진한다.

    rows_written을 net-delta로 바꾸면 재수집 날짜는 net_delta=0이 된다. 만약
    checkpoint 가드가 ``written > 0`` 였다면 이 날짜가 미전진해 stall이 생긴다.
    stored_ok 가드로 전환했으므로, 유효 데이터가 store에 반영된 재수집 날짜는
    net_delta=0이어도 정상 전진한다(#1993, #2015 무회귀).
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02", "2026-01-03"]
    collector = _ScriptedCollector(
        net_delta_by_date={"2026-01-02": 0, "2026-01-03": 0},  # 전부 재수집(delta 0)
        stored_ok_by_date={"2026-01-02": True, "2026-01-03": True},
    )
    store = _ScriptedStore(merge_fail_dates=set())

    checkpoint, ctx = await _run(feed_dir, collector, store, dates)

    # 재수집(delta=0)이어도 stored_ok로 마지막 날짜까지 전진(stall 없음).
    assert checkpoint.get_last_date() == "2026-01-03"
    # rows_written은 net-delta 합 = 0(재수집 과대계상 제거).
    assert ctx.rows_written == 0


@pytest.mark.asyncio
async def test_empty_response_still_blocks_advance(tmp_path: Path) -> None:
    """빈 응답(stored_ok=False)은 여전히 checkpoint 미전진(#2015 보존).

    net_delta=0이 모두 전진을 유발하지 않도록, stored_ok=False(빈 응답)는
    재수집(stored_ok=True, delta=0)과 구분되어 미전진해야 한다.
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-05-28", "2026-05-29"]
    collector = _ScriptedCollector(
        net_delta_by_date={"2026-05-28": 3, "2026-05-29": 0},
        stored_ok_by_date={"2026-05-28": True, "2026-05-29": False},  # 29 빈 응답
    )
    store = _ScriptedStore(merge_fail_dates=set())

    checkpoint, _ctx = await _run(feed_dir, collector, store, dates)

    # 28(stored_ok)까지 전진, 29(빈 응답)는 미전진.
    assert checkpoint.get_last_date() == "2026-05-28"


# ── (g) store-merge 실패 → checkpoint 미전진(R1 가드) ─────────────────────────


@pytest.mark.asyncio
async def test_store_merge_failure_blocks_advance(tmp_path: Path) -> None:
    """store-merge 실패 날짜는 stored_ok=True여도 checkpoint를 전진시키지 않는다.

    R1: ``_persist_partition`` 은 merge 실패 시 raise하지 않고 store_merge 경고만
    적재한다(기존 파일 보존). 따라서 collector는 stored_ok=True를 보고할 수 있다.
    runner는 checkpoint save 직전 store 경고를 drain해 이번 날짜에 store_merge가
    있으면 미전진시킨다(데이터 미반영 날짜 영구 skip 방지).
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02", "2026-01-03"]
    collector = _ScriptedCollector(
        net_delta_by_date={"2026-01-02": 0, "2026-01-03": 5},
        stored_ok_by_date={"2026-01-02": True, "2026-01-03": True},
    )
    # 2026-01-03에서 store-merge 실패.
    store = _ScriptedStore(merge_fail_dates={"2026-01-03"})

    checkpoint, ctx = await _run(feed_dir, collector, store, dates)

    # 02는 전진, 03은 store_merge 실패라 미전진 → checkpoint=02.
    assert checkpoint.get_last_date() == "2026-01-02"
    # store_merge 경고가 ctx.warnings로 표면화된다.
    assert any(w.get("type") == "store_merge" for w in ctx.warnings)


# ── (k) partial multi-write → rows_written 반영 + checkpoint 미전진 ───────────


@pytest.mark.asyncio
async def test_partial_multi_write_reflects_rows_but_blocks_checkpoint(
    tmp_path: Path,
) -> None:
    """일부 파티션 성공/일부 merge 실패 → rows_written엔 성공분 반영, checkpoint 미전진.

    한 날짜의 collect가 여러 파티션에 걸쳐 일부는 net-new 저장(net_delta>0), 일부는
    merge 실패(store_merge 경고)를 동시에 낼 수 있다. 이때:
      - rows_written: 성공 파티션의 net-new는 반영된다(데이터 반영 사실 보존).
      - checkpoint: 같은 날짜에 store_merge 실패가 있으면 미전진(부분 손실 날짜를
        완료 처리하지 않음).
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02"]
    # 성공 파티션 net-new 4행 보고 + 같은 날짜 store_merge 실패 동시 발생.
    collector = _ScriptedCollector(
        net_delta_by_date={"2026-01-02": 4},
        stored_ok_by_date={"2026-01-02": True},
    )
    store = _ScriptedStore(merge_fail_dates={"2026-01-02"})

    checkpoint, ctx = await _run(feed_dir, collector, store, dates)

    # 성공 파티션의 net-new는 rows_written에 반영.
    assert ctx.rows_written == 4
    # store_merge 실패가 같은 날짜에 있으므로 checkpoint 미전진(None).
    assert checkpoint.get_last_date() is None
    assert any(w.get("type") == "store_merge" for w in ctx.warnings)


# ── (#2414) 경고 메모리가 날짜 범위와 무관하게 유계 ────────────────────────────

# 관측 밀도(거래일당 약 600건, 이슈 #2414 실측 99,691/165)를 그대로 쓴다.
_OBSERVED_WARNINGS_PER_DAY = 600


def _dates(count: int) -> list[str]:
    """연속 거래일 문자열 ``count`` 개(2026-01-02부터, 주말 무관 스텁용)."""
    return [f"2026-01-{day:02d}" for day in range(2, 2 + count)]


async def _run_with_warnings(tmp_path: Path, day_count: int) -> _RunContext:
    """``day_count`` 일 × 관측 밀도 경고를 낸 뒤 ctx를 반환한다."""
    dates = _dates(day_count)
    collector = _ScriptedCollector(
        net_delta_by_date=dict.fromkeys(dates, 1),
        stored_ok_by_date=dict.fromkeys(dates, True),
        warns_per_date=_OBSERVED_WARNINGS_PER_DAY,
    )
    store = _ScriptedStore(merge_fail_dates=set())
    _checkpoint, ctx = await _run(tmp_path / ".feed", collector, store, dates)
    return ctx


@pytest.mark.asyncio
async def test_warning_memory_is_independent_of_date_range(tmp_path: Path) -> None:
    """거래일 수를 2배·4배로 늘려도 보존 경고 수가 증가하지 않는다(#2414 수용 기준).

    이것이 "경고 메모리가 날짜 범위와 무관하게 유계"의 기계적 증명이다.
    관측 밀도(600/거래일)면 2일=1200, 4일=2400으로 둘 다 상한(1000)을 넘으므로
    1000+ 일자를 돌리지 않고도 범위 무관성이 드러난다.
    """
    ctx_2d = await _run_with_warnings(tmp_path / "d2", 2)
    ctx_4d = await _run_with_warnings(tmp_path / "d4", 4)

    # 날짜 수가 2배가 되어도 인메모리 보존량은 그대로다.
    assert len(ctx_2d.warnings) == MAX_WARNINGS_PER_TYPE
    assert len(ctx_4d.warnings) == len(ctx_2d.warnings)

    # 반면 집계는 실제 발생량을 정확히 따라간다(정보 손실 없음).
    assert ctx_2d.warnings_total == 2 * _OBSERVED_WARNINGS_PER_DAY
    assert ctx_4d.warnings_total == 4 * _OBSERVED_WARNINGS_PER_DAY
    assert ctx_2d.warnings_truncated is True
    assert ctx_4d.warnings_truncated is True


@pytest.mark.asyncio
async def test_drain_store_warnings_return_value_survives_truncation(
    tmp_path: Path,
) -> None:
    """store_merge가 절단 대상이어도 반환값(=checkpoint 미전진 신호)은 True다.

    ``_drain_store_warnings`` 는 ``drained`` 전수를 먼저 검사한 뒤 ctx에
    적재하므로, 상한을 넘겨 샘플에서 잘린 store_merge도 동일하게 미전진을
    유발한다. 입력 리스트도 변형되지 않는다(결정 6).
    """
    ctx = _RunContext()
    # store_merge 버킷을 상한까지 채워 다음 건이 반드시 절단되게 한다.
    ctx.add_warnings(
        [
            {"type": "store_merge", "message": f"pre{i}"}
            for i in range(MAX_WARNINGS_PER_TYPE)
        ]
    )
    store = _ScriptedStore(merge_fail_dates={"2026-01-02"})
    store.arm("2026-01-02")

    assert BackfillRunner._drain_store_warnings(store, ctx) is True
    assert ctx.warnings_truncated is True
    assert ctx.warnings_total == MAX_WARNINGS_PER_TYPE + 1
    # 절단분은 샘플에 들어가지 않는다(메모리 유계).
    assert len(ctx.warnings) == MAX_WARNINGS_PER_TYPE


@pytest.mark.asyncio
async def test_truncated_store_merge_still_blocks_checkpoint(tmp_path: Path) -> None:
    """상한 포화 상태에서도 store_merge 날짜는 checkpoint를 전진시키지 않는다."""
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02"]
    collector = _ScriptedCollector(
        net_delta_by_date={"2026-01-02": 1},
        stored_ok_by_date={"2026-01-02": True},
    )
    store = _ScriptedStore(merge_fail_dates={"2026-01-02"})

    checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
    runner = BackfillRunner(data_go_kr_collector=collector)
    ctx = _RunContext()
    ctx.add_warnings(
        [
            {"type": "store_merge", "message": f"pre{i}"}
            for i in range(MAX_WARNINGS_PER_TYPE)
        ]
    )
    await runner._collect_data_go_kr(
        dates,
        {},
        store,
        checkpoint,
        ctx,
        lambda _config, _date: False,
        lambda _config: False,
        None,
    )

    assert checkpoint.get_last_date() is None
    assert ctx.warnings_truncated is True
