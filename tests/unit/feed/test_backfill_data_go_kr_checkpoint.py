"""data.go.kr backfill 실패 시 checkpoint 미전진 검증 (#2078).

``BackfillRunner._collect_data_go_kr`` 는 날짜를 오름차순으로 순회하며 성공
시 ``checkpoint.save(target_date)`` 를 호출한다. ``Checkpoint.save`` 는
last-write-wins이므로, 중간 날짜가 transient 예외로 실패한 뒤 이후 날짜가
성공하면 checkpoint가 실패 날짜 너머로 전진해 그 실패 날짜가 다음 run에서
영구 skip되던 버그(#2078)를 검증한다.

#2054(DART 분기 checkpoint halt)의 동형 sibling이다. 수정은 첫 transient
실패에서 ``halt = True`` 를 세우고, 이후 ``checkpoint.save`` 를 가드한다.
``break`` 는 도입하지 않으므로 실패 이후 날짜 수집은 best-effort로 계속된다.

수정 전 동작에서는:
- (a) 단일 transient 실패가 checkpoint를 저장하지 않으나(continue), 단일
      날짜라 미전진은 자명하다 — 대신 실패 직후 success가 전진시키는지를 본다.
- (b) D2 실패 후 D3 성공 → checkpoint가 D3로 전진 → 테스트 FAIL.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ante.feed.pipeline.backfill_runner import BackfillRunner, _RunContext
from ante.feed.pipeline.checkpoint import Checkpoint


class _ScriptedDataGoKrCollector:
    """target_date별 raise/성공 응답을 스크립트로 지정하는 collector 스텁.

    ``BackfillRunner._collect_data_go_kr`` 가 호출하는
    ``collect(target_date, store) -> (written, syms, warns)`` 시그니처를
    그대로 구현한다.

    Args:
        fail_dates: 이 집합에 든 날짜는 ``collect`` 가 transient 예외를 raise.
        written_per_date: 성공 시 보고할 기록 행 수(>0이면 success로 집계).

    Attributes:
        calls: ``collect`` 가 실제로 호출된 ``target_date`` 의 순서 리스트.
            best-effort continue가 실제로 이후 날짜를 호출했는지(break 허점
            차단) 검증에 쓴다.
    """

    def __init__(
        self,
        fail_dates: set[str],
        written_per_date: int = 1,
    ) -> None:
        self._fail_dates = fail_dates
        self._written = written_per_date
        self.calls: list[str] = []

    async def collect(
        self,
        target_date: str,
        store: object,
    ) -> tuple[int, set[str], list[dict]]:
        self.calls.append(target_date)
        if target_date in self._fail_dates:
            raise RuntimeError(f"transient failure on {target_date}")
        return self._written, {f"SYM-{target_date[-2:]}"}, []


async def _run_collect(
    feed_dir: Path,
    dates: list[str],
    fail_dates: set[str],
) -> tuple[Checkpoint, _RunContext, _ScriptedDataGoKrCollector]:
    """``_collect_data_go_kr`` 를 직접 호출해 checkpoint/ctx/collector를 반환한다.

    이슈 #2078 재현 스크립트와 동일한 진입점(메서드 직접 호출 + 가드 no-op)을
    사용한다. store는 collect 스텁이 사용하지 않으므로 sentinel object로 둔다.
    """
    collector = _ScriptedDataGoKrCollector(fail_dates=fail_dates)
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


# ── (a) 단일 날짜 transient 실패 → 해당 날짜 checkpoint 미저장 ───────────────


@pytest.mark.asyncio
async def test_single_transient_failure_does_not_save_checkpoint(
    tmp_path: Path,
) -> None:
    """단 하나의 날짜가 실패하면 그 날짜는 checkpoint에 저장되지 않는다.

    실패 한 건뿐이므로 checkpoint는 그대로 None(이전 상태)에 머문다.
    """
    feed_dir = tmp_path / ".feed"
    checkpoint, ctx, collector = await _run_collect(
        feed_dir,
        dates=["2026-01-02"],
        fail_dates={"2026-01-02"},
    )

    # 실패 날짜는 checkpoint로 저장되지 않는다.
    assert checkpoint.get_last_date() is None
    # 실패가 ctx.failures에 기록된다.
    assert ctx.failures == [
        {
            "date": "2026-01-02",
            "source": "data_go_kr",
            "reason": "transient failure on 2026-01-02",
        }
    ]
    # collect는 그 날짜에 한 번 호출됐다.
    assert collector.calls == ["2026-01-02"]


# ── (b) D2 실패 후 D3 성공 → checkpoint가 D1에 고정 + D3 collect 호출됨 ──────


@pytest.mark.asyncio
async def test_mid_failure_pins_checkpoint_and_continues_collecting(
    tmp_path: Path,
) -> None:
    """D1 성공 → D2 실패 → D3 성공: checkpoint는 D1에 머무르고, D3 collect도 호출.

    핵심 회귀 가드(#2078, #2054 동형):
      - checkpoint가 실패 날짜(D2) 너머 D3로 전진하면 D2가 영구 skip된다.
        수정 후에는 첫 실패(D2)에서 halt → 이후 success(D3)는 checkpoint를
        전진시키지 않아 checkpoint == D1.
      - break가 아니라 continue(best-effort)여야 한다 — D3 collect가 실제로
        호출되었는지(collector.calls에 D3 포함) assert한다. break 구현이면
        D3가 호출되지 않아 이 assert가 실패한다.
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-01", "2026-01-02", "2026-01-03"]
    checkpoint, ctx, collector = await _run_collect(
        feed_dir,
        dates=dates,
        fail_dates={"2026-01-02"},
    )

    # checkpoint는 마지막 연속 성공(D1)에 고정 — 실패 날짜(D2) 너머 미전진.
    assert checkpoint.get_last_date() == "2026-01-01", (
        "실패 날짜(D2) 이후 success(D3)가 checkpoint를 전진시키면 안 된다"
    )

    # best-effort continue: D3 collect가 실제로 호출됐다(break 허점 차단).
    assert collector.calls == ["2026-01-01", "2026-01-02", "2026-01-03"], (
        "break면 D3가 호출되지 않는다 — continue best-effort가 보장돼야 한다"
    )

    # D3 성공이 ctx에 반영됐다(written/symbol 집계).
    assert "SYM-03" in ctx.success_symbols
    assert ctx.rows_written == 2  # D1 + D3 각 1행

    # 실패 날짜는 failures에 보존된다(재시도 근거).
    assert ctx.failures == [
        {
            "date": "2026-01-02",
            "source": "data_go_kr",
            "reason": "transient failure on 2026-01-02",
        }
    ]


# ── (c) 전부 성공 → checkpoint가 마지막 날짜까지 정상 전진 ───────────────────


@pytest.mark.asyncio
async def test_all_success_advances_checkpoint_to_last_date(
    tmp_path: Path,
) -> None:
    """실패가 없으면 checkpoint는 마지막 날짜까지 정상 전진한다(회귀 방지)."""
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-01", "2026-01-02", "2026-01-03"]
    checkpoint, ctx, collector = await _run_collect(
        feed_dir,
        dates=dates,
        fail_dates=set(),
    )

    assert checkpoint.get_last_date() == "2026-01-03"
    assert ctx.failures == []
    assert collector.calls == dates
    assert ctx.rows_written == 3


# ── (d) 이슈 재현(중간 날짜 실패) → checkpoint 미전진 ───────────────────────


@pytest.mark.asyncio
async def test_issue_reproduction_mid_date_failure_blocks_advance(
    tmp_path: Path,
) -> None:
    """이슈 #2078 재현 스크립트와 동일 시나리오로 checkpoint 미전진을 확인한다.

    재현: dates=[D1, D2, D3], D2만 실패. 수정 전 checkpoint=D3(전진), 수정 후
    checkpoint=D1(미전진). success_symbols/failures shape도 재현 스크립트의
    기대(실제 결과) 형태를 그대로 확인한다.
    """
    feed_dir = tmp_path / ".feed"
    dates = ["2026-01-01", "2026-01-02", "2026-01-03"]
    checkpoint, ctx, _collector = await _run_collect(
        feed_dir,
        dates=dates,
        fail_dates={"2026-01-02"},
    )

    # 재현 스크립트가 보고하던 버그(checkpoint == '2026-01-03')가 더 이상
    # 발생하지 않는다.
    assert checkpoint.get_last_date() != "2026-01-03"
    # 실패 날짜 직전(D1)에 checkpoint가 고정된다 → 다음 run에서 D2부터 재시도.
    assert checkpoint.get_last_date() == "2026-01-01"

    # 부분 성공 symbol(D1, D3)과 실패(D2)는 result에 그대로 보존된다.
    assert sorted(ctx.success_symbols) == ["SYM-01", "SYM-03"]
    assert [f["date"] for f in ctx.failures] == ["2026-01-02"]
