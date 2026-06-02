"""data.go.kr backfill 빈 응답(written==0) 날짜의 checkpoint 미전진 검증 (#2015).

``BackfillRunner._collect_data_go_kr`` 는 날짜를 오름차순으로 순회하며 성공
시 ``checkpoint.save(target_date)`` 를 호출했다. ``written == 0`` 인 빈 응답
날짜(미공개/지연공개/캘린더 미인식 공휴일)에도 checkpoint를 전진시키면, 그
날짜가 다음 run에서 ``last_checkpoint`` 이전으로 간주되어 영구 skip된다
(데이터 손실). 관측: checkpoint=2026-05-31인데 실제 데이터 max=2026-05-28.

수정: ``if not halt and written > 0: checkpoint.save(target_date)``.
dates는 오름차순이므로 checkpoint = 마지막으로 written>0인 날짜가 되며,
내부 빈 날짜는 다음 데이터 날짜에서 jump해 커버(stall 없음), trailing 빈
날짜는 미전진 → 다음 실행에서 재시도(손실 없음).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ante.feed.pipeline.backfill_runner import BackfillRunner, _RunContext
from ante.feed.pipeline.checkpoint import Checkpoint


class _WrittenScriptedCollector:
    """target_date별 written 행 수를 스크립트로 지정하는 collector 스텁.

    ``BackfillRunner._collect_data_go_kr`` 가 호출하는
    ``collect(target_date, store) -> (written, syms, warns)`` 시그니처를
    그대로 구현한다.

    Args:
        written_by_date: 날짜→written 행 수 맵. 맵에 없는 날짜는 ``default``.
        default: 맵에 없는 날짜의 written(기본 0 = 빈 응답).

    Attributes:
        calls: ``collect`` 가 실제로 호출된 ``target_date`` 의 순서 리스트.
    """

    def __init__(
        self,
        written_by_date: dict[str, int],
        default: int = 0,
    ) -> None:
        self._written_by_date = written_by_date
        self._default = default
        self.calls: list[str] = []

    async def collect(
        self,
        target_date: str,
        store: object,
    ) -> tuple[int, set[str], list[dict]]:
        self.calls.append(target_date)
        written = self._written_by_date.get(target_date, self._default)
        # written > 0 인 날짜만 symbol을 보고한다(빈 응답은 symbol 없음).
        syms = {f"SYM-{target_date[-2:]}"} if written > 0 else set()
        return written, syms, []


async def _run_collect(
    feed_dir: Path,
    dates: list[str],
    written_by_date: dict[str, int],
) -> tuple[Checkpoint, _RunContext, _WrittenScriptedCollector]:
    """``_collect_data_go_kr`` 를 직접 호출해 checkpoint/ctx/collector를 반환한다.

    가드(is_blocked_day/is_trading_paused)는 no-op으로 두고, stop_event는
    None(one-shot)으로 둔다. store는 스텁이 사용하지 않으므로 sentinel.
    """
    collector = _WrittenScriptedCollector(written_by_date=written_by_date)
    checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
    runner = BackfillRunner(data_go_kr_collector=collector)
    ctx = _RunContext()

    await runner._collect_data_go_kr(
        dates,
        {},
        object(),  # store: 스텁 collect가 사용하지 않음
        checkpoint,
        ctx,
        lambda _config, _date: False,  # is_blocked_day: 항상 거래일
        lambda _config: False,  # is_trading_paused: 대기 없음
        None,  # stop_event: one-shot
    )
    return checkpoint, ctx, collector


# ── 내부 빈 날짜(D1 < H(빈) < D2) → checkpoint = D2 (H jump 커버, 영구 skip 아님)


@pytest.mark.asyncio
async def test_internal_empty_date_is_jumped_not_skipped(
    tmp_path: Path,
) -> None:
    """데이터 D1 < 빈 날짜 H < 데이터 D2: checkpoint=D2.

    H(예: 캘린더 미인식 공휴일)는 데이터가 영원히 없으므로 checkpoint가 H에
    멈추면 stall된다. 다음 데이터 날짜 D2에서 checkpoint가 jump해 H를 자연
    커버하므로 stall이 없다. (H는 데이터가 없으니 영구 skip돼도 무손실.)
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02", "2026-01-03", "2026-01-05"]
    checkpoint, ctx, collector = await _run_collect(
        feed_dir,
        dates=dates,
        # 2026-01-03 = 빈 응답(written 0), 양옆은 데이터 있음.
        written_by_date={"2026-01-02": 1, "2026-01-03": 0, "2026-01-05": 1},
    )

    # checkpoint는 마지막 written>0 날짜(D2=2026-01-05)로 jump한다.
    assert checkpoint.get_last_date() == "2026-01-05"
    # 빈 날짜를 포함해 모든 날짜에 collect 시도됐다(skip 아님 — best-effort).
    assert collector.calls == dates
    # 빈 날짜는 success_symbol을 보태지 않는다.
    assert sorted(ctx.success_symbols) == ["SYM-02", "SYM-05"]


# ── trailing 빈 날짜(미공개/지연공개) → checkpoint 미전진(마지막 데이터 날짜 유지)


@pytest.mark.asyncio
async def test_trailing_empty_dates_do_not_advance_checkpoint(
    tmp_path: Path,
) -> None:
    """마지막에 빈 응답 날짜가 이어지면 checkpoint는 마지막 데이터 날짜에 머문다.

    이것이 이슈 #2015의 핵심: 미공개/지연공개 날짜(빈 응답)가 checkpoint를
    전진시키면 공개 후에도 영구 skip된다. trailing 빈 날짜를 미전진시켜
    다음 실행에서 재시도(공개되면 수집)할 수 있게 한다.
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31"]
    checkpoint, _ctx, collector = await _run_collect(
        feed_dir,
        dates=dates,
        # 2026-05-28만 데이터, 이후는 미공개(빈 응답).
        written_by_date={"2026-05-28": 1},
    )

    # checkpoint는 마지막 데이터 날짜(2026-05-28)에 고정 — 빈 날짜 미전진.
    # 수정 전 버그에서는 checkpoint=2026-05-31(데이터 max 초과)였다.
    assert checkpoint.get_last_date() == "2026-05-28"
    # 빈 날짜에도 collect 시도는 됐다(다음 실행 재시도 경로 확보).
    assert collector.calls == dates


# ── 회귀: 이슈 관측(checkpoint > 데이터 max) 해소 ──────────────────────────────


@pytest.mark.asyncio
async def test_checkpoint_never_exceeds_data_max(
    tmp_path: Path,
) -> None:
    """checkpoint가 실제 데이터 max를 넘지 않는다(이슈 #2015 관측 재현→해소).

    관측: checkpoint=2026-05-31 vs 데이터 max=2026-05-28. written>0 guard로
    checkpoint가 데이터 max(2026-05-28)를 넘지 못함을 직접 assert한다.
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-05-28", "2026-05-29", "2026-05-30", "2026-05-31"]
    checkpoint, _ctx, _collector = await _run_collect(
        feed_dir,
        dates=dates,
        written_by_date={"2026-05-28": 3},  # 데이터 max = 2026-05-28
    )

    last = checkpoint.get_last_date()
    assert last is not None
    assert last <= "2026-05-28"
    assert last == "2026-05-28"


# ── 빈 응답만 있는 범위 → checkpoint 무전진(손실 없음) ───────────────────────


@pytest.mark.asyncio
async def test_all_empty_range_does_not_advance_checkpoint(
    tmp_path: Path,
) -> None:
    """범위 전체가 빈 응답이면 checkpoint는 전혀 전진하지 않는다."""
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-02", "2026-01-03", "2026-01-05"]
    checkpoint, _ctx, collector = await _run_collect(
        feed_dir,
        dates=dates,
        written_by_date={},  # 전부 default=0 (빈 응답)
    )

    # 어떤 날짜도 written>0이 아니므로 checkpoint는 생성조차 되지 않는다.
    assert checkpoint.get_last_date() is None
    assert collector.calls == dates


# ── halt 시 written>0이어도 전진 안 함(기존 #2078 가드 정합) ─────────────────


@pytest.mark.asyncio
async def test_halt_blocks_advance_even_when_written_positive(
    tmp_path: Path,
) -> None:
    """transient 실패로 halt된 뒤에는 written>0 날짜도 checkpoint를 전진시키지 않는다.

    #2078 halt 가드와 #2015 written>0 가드가 함께 동작해야 한다. 별도
    collector로 D2 실패를 주입한다(빈 응답이 아닌 예외).
    """

    class _FailThenWrittenCollector:
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def collect(
            self,
            target_date: str,
            store: object,
        ) -> tuple[int, set[str], list[dict]]:
            self.calls.append(target_date)
            if target_date == "2026-01-02":
                raise RuntimeError("transient")
            return 1, {f"SYM-{target_date[-2:]}"}, []  # written>0

    feed_dir = tmp_path / ".feed"
    collector = _FailThenWrittenCollector()
    checkpoint = Checkpoint(feed_dir, "data_go_kr", "ohlcv")
    runner = BackfillRunner(data_go_kr_collector=collector)
    ctx = _RunContext()

    await runner._collect_data_go_kr(
        ["2026-01-01", "2026-01-02", "2026-01-03"],
        {},
        object(),
        checkpoint,
        ctx,
        lambda _config, _date: False,
        lambda _config: False,
        None,
    )

    # D2 실패 → halt. D3(written>0)는 checkpoint를 전진시키지 못함 → D1 고정.
    assert checkpoint.get_last_date() == "2026-01-01"
    # best-effort continue: D3도 호출됨.
    assert collector.calls == ["2026-01-01", "2026-01-02", "2026-01-03"]
