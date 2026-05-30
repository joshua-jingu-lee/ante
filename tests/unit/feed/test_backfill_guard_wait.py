"""Backfill 방어 가드 분리 동작 검증 (#1972).

가드 두 축을 분리한 뒤의 backfill 날짜별 루프 동작을 검증한다:

- ``blocked_days`` (target_date 요일): 해당 날짜는 **skip** (데이터 없음).
- ``blocked_hours``+``pause_during_trading`` (현재 시각): 해당 시 window가
  풀릴 때까지 **대기 후** 그 날짜를 수집한다.
- 거래시간 가드가 영구히 풀리지 않으면(대기 상한 초과) ``GUARD_PERMANENTLY_BLOCKED``
  config_error로 비-clean 종료.
- 상주 스케줄러 stop_event로 대기가 중단되면 ``BACKFILL_STOP_REQUESTED``
  config_error로 partial 종료(daemon은 "중단" echo).

수정 전(스킵 동작)에는:
- 거래시간 가드 활성 날짜가 누락되고 체크포인트가 정지 → wait/collect 테스트 FAIL.
- 거래시간 가드가 영구 활성이면 전 날짜 skip + clean success → permanent 테스트 FAIL.
- stop 마커가 없어 clean success → cancel 테스트 FAIL.

모든 대기는 patch/주입으로 시간 비의존(결정적)이다.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import ante.feed.pipeline.backfill_runner as bf_mod
from ante.data.store import ParquetStore
from ante.feed.pipeline.backfill_runner import (
    BACKFILL_DATE_ERROR_CODES,
    CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
    CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED,
)
from ante.feed.pipeline.checkpoint import Checkpoint
from ante.feed.pipeline.orchestrator import FeedOrchestrator

# ── Fixtures ─────────────────────────────────────────────


def _ohlcv_records_for(target_date: str, symbol: str = "005930") -> list[dict]:
    """``target_date`` (YYYY-MM-DD) 의 OHLCV mock 레코드를 생성한다.

    ``basDt`` 를 ``target_date`` 에서 유도해, 저장된 데이터로 어떤 날짜가
    실제로 수집되었는지 역추적할 수 있게 한다.
    """
    bas_dt = target_date.replace("-", "")
    return [
        {
            "basDt": bas_dt,
            "srtnCd": symbol,
            "itmsNm": f"종목{symbol}",
            "mrktCtg": "KOSPI",
            "mkp": "70000",
            "hipr": "72000",
            "lopr": "69000",
            "clpr": "71000",
            "trqu": "10000000",
            "trPrc": "710000000000",
            "lstgStCnt": "5969782550",
            "mrktTotAmt": "423814400050000",
        }
    ]


@pytest.fixture
def tmp_data_path(tmp_path: Path) -> Path:
    """테스트용 데이터 디렉토리."""
    data_path = tmp_path / "data"
    data_path.mkdir()
    feed_dir = data_path / ".feed"
    feed_dir.mkdir()
    (feed_dir / "checkpoints").mkdir()
    (feed_dir / "reports").mkdir()
    return data_path


def _date_driven_source() -> AsyncMock:
    """fetch(target_date) → 그 날짜의 OHLCV 레코드를 반환하는 소스 mock."""
    source = AsyncMock()

    async def _fetch(target_date: str) -> list[dict]:
        return _ohlcv_records_for(target_date)

    source.fetch = AsyncMock(side_effect=_fetch)
    source.rate_limiter = MagicMock()
    source.rate_limiter.is_daily_limit_reached.return_value = False
    return source


def _config_with_window(
    start: str,
    end: str,
    *,
    backfill_since: str,
    blocked_days: list[str] | None = None,
) -> dict[str, Any]:
    """거래시간 window + (옵션) blocked_days 설정을 만든다."""
    return {
        "schedule": {"backfill_since": backfill_since},
        "guard": {
            "blocked_days": blocked_days or [],
            "blocked_hours": [f"{start}-{end}"],
            "pause_during_trading": True,
        },
    }


def _stored_dates(store: ParquetStore, symbol: str = "005930") -> set[str]:
    """store에 저장된 OHLCV 날짜(YYYY-MM-DD) 집합을 읽어온다."""
    df = store.read(symbol, "1d", data_type="ohlcv", exchange="KRX")
    if df.is_empty() or "timestamp" not in df.columns:
        return set()
    return {ts.date().isoformat() for ts in df["timestamp"].to_list()}


# ── (1) blocked_hours → 대기 후 해당 날짜 수집 ───────────────────────────


@pytest.mark.asyncio
async def test_backfill_blocked_hours_waits_and_collects_guarded_date(
    tmp_data_path: Path,
) -> None:
    """거래시간 가드 활성 → window가 풀릴 때까지 대기 후 **그 날짜 자체**를 수집.

    다중 날짜 범위에서 ``is_trading_paused`` 가 처음 N회 True → 이후 False가
    되도록 패치한다(asyncio.sleep no-op로 결정적). 가드가 걸렸던 첫 날짜의
    행이 store에 존재하고, 체크포인트가 범위 끝까지 진행됨을 단언한다.

    수정 전(skip): 가드 활성 날짜가 누락되고 체크포인트가 정지 → FAIL.
    """
    # 2024-01-01(월) ~ 2024-01-03(수): 모두 평일(blocked_days 미적용).
    # 날짜 범위는 _resolve_dates 패치로 고정(기본 end=today 비결정성 제거).
    config = _config_with_window("09:00", "15:30", backfill_since="2024-01-01")
    target_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    cp = Checkpoint(tmp_data_path / ".feed", "data_go_kr", "ohlcv")

    store = ParquetStore(base_path=tmp_data_path)
    source = _date_driven_source()
    orchestrator = FeedOrchestrator(data_go_kr_source=source, store=store)

    # is_trading_paused: 첫 3회 True(첫 날짜 대기), 이후 False(해제).
    pause_flags = iter([True, True, True])

    def _fake_paused(_config: dict[str, Any]) -> bool:
        try:
            return next(pause_flags)
        except StopIteration:
            return False

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with (
        patch.object(
            FeedOrchestrator, "_is_trading_paused", staticmethod(_fake_paused)
        ),
        patch.object(bf_mod.asyncio, "sleep", _fake_sleep),
        patch.object(
            bf_mod.BackfillRunner,
            "_resolve_dates",
            staticmethod(lambda _config, _feed_dir: list(target_dates)),
        ),
    ):
        result = await orchestrator.run_backfill(tmp_data_path, config)

    # 가드 marker는 없어야 한다(대기 후 정상 수집 → clean).
    codes = {e.get("code") for e in result.config_errors if isinstance(e, dict)}
    assert not (codes & BACKFILL_DATE_ERROR_CODES)

    # 대기가 실제로 발생했다(one-shot sleep 경로, 3회 폴링 후 해제).
    assert len(sleep_calls) == 3, "거래시간 가드 대기(sleep)가 3회 발생해야 한다"

    # 가드가 걸렸던 첫 날짜(2024-01-01)를 포함해 범위 전체가 수집됐다.
    stored = _stored_dates(store)
    assert "2024-01-01" in stored, "가드 활성 날짜 자체가 수집되어야 한다"
    assert {"2024-01-01", "2024-01-02", "2024-01-03"} == stored

    # 체크포인트가 범위 끝까지 진행됐다.
    assert cp.get_last_date() == "2024-01-03"


# ── (2) blocked_days → 주말 skip, 평일 수집, hang 없음 ────────────────────


@pytest.mark.asyncio
async def test_backfill_blocked_days_skips_weekday(
    tmp_data_path: Path,
) -> None:
    """blocked_days=[sat,sun] → 주말 날짜는 skip, 평일은 수집. 무한 hang 없음.

    blocked_days는 target_date 요일 기반이므로 대기하지 않고 즉시 skip한다.
    """
    # 2024-01-05(금) ~ 2024-01-08(월): 06(토)/07(일)이 주말.
    config = {
        "schedule": {"backfill_since": "2024-01-05"},
        "guard": {
            "blocked_days": ["sat", "sun"],
            "blocked_hours": [],
            "pause_during_trading": False,
        },
    }
    target_dates = ["2024-01-05", "2024-01-06", "2024-01-07", "2024-01-08"]
    cp = Checkpoint(tmp_data_path / ".feed", "data_go_kr", "ohlcv")

    store = ParquetStore(base_path=tmp_data_path)
    source = _date_driven_source()
    orchestrator = FeedOrchestrator(data_go_kr_source=source, store=store)

    # 거래시간 대기가 절대 호출되지 않아야 한다(주말은 skip이지 wait가 아님).
    async def _must_not_sleep(_delay: float) -> None:
        raise AssertionError("blocked_days는 skip이어야 하며 대기하면 안 된다")

    with (
        patch.object(bf_mod.asyncio, "sleep", _must_not_sleep),
        patch.object(
            bf_mod.BackfillRunner,
            "_resolve_dates",
            staticmethod(lambda _config, _feed_dir: list(target_dates)),
        ),
    ):
        result = await orchestrator.run_backfill(tmp_data_path, config)

    stored = _stored_dates(store)
    # 주말(토/일)은 수집되지 않는다.
    assert "2024-01-06" not in stored
    assert "2024-01-07" not in stored
    # 평일(금/월)은 수집된다.
    assert "2024-01-05" in stored
    assert "2024-01-08" in stored

    # 가드 marker 없음(skip은 정상 동작).
    codes = {e.get("code") for e in result.config_errors if isinstance(e, dict)}
    assert not (codes & BACKFILL_DATE_ERROR_CODES)

    # 체크포인트는 마지막으로 수집된 평일(2024-01-08)까지 진행.
    assert cp.get_last_date() == "2024-01-08"


# ── (3) 거래시간 가드 영구 활성 → GUARD_PERMANENTLY_BLOCKED ──────────────


@pytest.mark.asyncio
async def test_backfill_trading_pause_permanent_surfaces_config_error(
    tmp_data_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """거래시간 가드가 항상 활성 + 짧은 max_wait → GUARD_PERMANENTLY_BLOCKED.

    누적 대기가 상한을 넘으면 config_error를 적재하고 종료한다. 이 code는
    BACKFILL_DATE_ERROR_CODES에 포함되어 비-clean(one-shot exit-1 / daemon
    차단 echo).

    수정 전(skip): 전 날짜 skip + clean success → FAIL.
    """
    config = _config_with_window("00:00", "23:59", backfill_since="2024-01-01")
    target_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    # 체크포인트 미존재(None) → 범위는 _resolve_dates 패치로 고정.

    store = ParquetStore(base_path=tmp_data_path)
    source = _date_driven_source()
    orchestrator = FeedOrchestrator(data_go_kr_source=source, store=store)

    # 짧은 max_wait + poll 주입(2회 polling 후 상한 초과).
    monkeypatch.setattr(bf_mod, "GUARD_WAIT_POLL_SECONDS", 10.0)
    monkeypatch.setattr(bf_mod, "MAX_GUARD_WAIT_SECONDS", 20.0)

    # 항상 거래시간(True).
    def _always_paused(_config: dict[str, Any]) -> bool:
        return True

    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with (
        patch.object(
            FeedOrchestrator, "_is_trading_paused", staticmethod(_always_paused)
        ),
        patch.object(bf_mod.asyncio, "sleep", _fake_sleep),
        patch.object(
            bf_mod.BackfillRunner,
            "_resolve_dates",
            staticmethod(lambda _config, _feed_dir: list(target_dates)),
        ),
    ):
        result = await orchestrator.run_backfill(tmp_data_path, config)

    codes = {e.get("code") for e in result.config_errors if isinstance(e, dict)}
    assert CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED in codes
    # 비-clean 매핑 집합에 포함.
    assert CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED in BACKFILL_DATE_ERROR_CODES
    # 어떤 날짜도 수집되지 않았다(첫 날짜에서 영구 차단).
    assert _stored_dates(store) == set()
    # 무한 루프가 아니라 상한에서 종료(폴링 유한 횟수).
    assert 0 < len(sleep_calls) <= 3


# ── (4) stop_event로 대기 중단 → BACKFILL_STOP_REQUESTED ─────────────────


@pytest.mark.asyncio
async def test_backfill_wait_cancelled_by_stop_event(
    tmp_data_path: Path,
) -> None:
    """대기 중 stop_event set → 대기 종료, 체크포인트 저장된 partial 반환.

    ``result.config_errors`` 에 ``BACKFILL_STOP_REQUESTED`` 가 적재되어
    clean-success가 아니다. ``asyncio.wait_for`` (daemon 경로)가 대기 중
    stop이 도착한 것을 시뮬레이션한다.
    """
    config = _config_with_window("00:00", "23:59", backfill_since="2024-01-01")
    target_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    # 체크포인트 미존재(None) → 범위는 _resolve_dates 패치로 고정.

    store = ParquetStore(base_path=tmp_data_path)
    source = _date_driven_source()
    orchestrator = FeedOrchestrator(data_go_kr_source=source, store=store)

    stop_event = asyncio.Event()

    # 항상 거래시간(True) → 대기 진입.
    def _always_paused(_config: dict[str, Any]) -> bool:
        return True

    # daemon 경로: wait_for(stop_event.wait(), timeout)가 대기하던 중
    # stop이 도착한 것을 시뮬레이션 — 이벤트를 set하고 정상 반환한다.
    async def _fake_wait_for(_awaitable: Any, timeout: float) -> None:
        # 미사용 coroutine 경고 방지를 위해 닫는다.
        if asyncio.iscoroutine(_awaitable):
            _awaitable.close()
        stop_event.set()

    with (
        patch.object(
            FeedOrchestrator, "_is_trading_paused", staticmethod(_always_paused)
        ),
        patch.object(bf_mod.asyncio, "wait_for", _fake_wait_for),
        patch.object(
            bf_mod.BackfillRunner,
            "_resolve_dates",
            staticmethod(lambda _config, _feed_dir: list(target_dates)),
        ),
    ):
        result = await orchestrator.run_backfill(
            tmp_data_path, config, stop_event=stop_event
        )

    codes = {e.get("code") for e in result.config_errors if isinstance(e, dict)}
    assert CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED in codes
    assert CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED in BACKFILL_DATE_ERROR_CODES
    # 중단 시점까지 어떤 날짜도 수집되지 않았다(첫 날짜 대기 중 중단).
    assert _stored_dates(store) == set()


@pytest.mark.asyncio
async def test_backfill_stop_requested_before_wait(
    tmp_data_path: Path,
) -> None:
    """대기 진입 직전 stop_event가 이미 set → 즉시 BACKFILL_STOP_REQUESTED.

    wait_for를 거치지 않고 루프 top 체크에서 즉시 중단되는 경로.
    """
    config = _config_with_window("00:00", "23:59", backfill_since="2024-01-01")
    target_dates = ["2024-01-01", "2024-01-02", "2024-01-03"]
    # 체크포인트 미존재(None) → 범위는 _resolve_dates 패치로 고정.

    store = ParquetStore(base_path=tmp_data_path)
    source = _date_driven_source()
    orchestrator = FeedOrchestrator(data_go_kr_source=source, store=store)

    stop_event = asyncio.Event()
    stop_event.set()  # 진입 전부터 set.

    def _always_paused(_config: dict[str, Any]) -> bool:
        return True

    async def _must_not_wait(_awaitable: Any, timeout: float) -> None:
        raise AssertionError("이미 stop된 상태에서는 wait_for를 호출하면 안 된다")

    with (
        patch.object(
            FeedOrchestrator, "_is_trading_paused", staticmethod(_always_paused)
        ),
        patch.object(bf_mod.asyncio, "wait_for", _must_not_wait),
        patch.object(
            bf_mod.BackfillRunner,
            "_resolve_dates",
            staticmethod(lambda _config, _feed_dir: list(target_dates)),
        ),
    ):
        result = await orchestrator.run_backfill(
            tmp_data_path, config, stop_event=stop_event
        )

    codes = {e.get("code") for e in result.config_errors if isinstance(e, dict)}
    assert CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED in codes


# ── (5) daemon _run_backfill_job: stop 중단 시 "중단" echo ────────────────


def test_daemon_run_backfill_job_echoes_stop_not_complete() -> None:
    """stop 중단 partial을 받은 daemon은 "완료" 대신 "중단"을 echo한다."""
    from ante.feed import cli_scheduler
    from ante.feed.models.result import CollectionResult

    started = datetime.now(tz=UTC)
    finished = started + timedelta(seconds=1)
    stop_result = CollectionResult(
        mode="backfill",
        started_at=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_seconds=1.0,
        config_errors=[
            {
                "code": CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED,
                "error": "중단 요청으로 backfill 거래시간 대기를 종료했습니다",
                "source": "data_go_kr",
            }
        ],
    )

    mock_orch = MagicMock()
    mock_orch.run_backfill = AsyncMock(return_value=stop_result)

    echoed: list[str] = []
    with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
        asyncio.run(
            cli_scheduler._run_backfill_job(
                mock_orch, "data/", {}, "2026-05-30", asyncio.Event()
            )
        )

    # 완료 메시지 미출력, "중단" 라인 출력.
    assert not any("Backfill 완료" in line for line in echoed)
    assert any("Backfill 중단" in line for line in echoed)
    assert any(CONFIG_ERROR_CODE_BACKFILL_STOP_REQUESTED in line for line in echoed)


def test_daemon_run_backfill_job_echoes_permanent_block() -> None:
    """GUARD_PERMANENTLY_BLOCKED partial을 받은 daemon은 "차단"을 echo한다."""
    from ante.feed import cli_scheduler
    from ante.feed.models.result import CollectionResult

    started = datetime.now(tz=UTC)
    finished = started + timedelta(seconds=1)
    blocked_result = CollectionResult(
        mode="backfill",
        started_at=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        finished_at=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_seconds=1.0,
        config_errors=[
            {
                "code": CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED,
                "error": "거래시간 가드가 대기 상한을 초과했습니다",
                "source": "data_go_kr",
            }
        ],
    )

    mock_orch = MagicMock()
    mock_orch.run_backfill = AsyncMock(return_value=blocked_result)

    echoed: list[str] = []
    with patch.object(cli_scheduler.click, "echo", side_effect=echoed.append):
        asyncio.run(
            cli_scheduler._run_backfill_job(
                mock_orch, "data/", {}, "2026-05-30", asyncio.Event()
            )
        )

    assert not any("Backfill 완료" in line for line in echoed)
    assert any("Backfill 차단" in line for line in echoed)
    assert any(CONFIG_ERROR_CODE_GUARD_PERMANENTLY_BLOCKED in line for line in echoed)


# ── (6) stop_event 전파: run_scheduler_loop → _run_backfill_job ──────────


def test_run_scheduler_loop_forwards_stop_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """run_scheduler_loop가 보유한 stop_event를 _run_backfill_job로 전달한다."""
    from ante.feed import cli_scheduler

    captured: dict[str, Any] = {}

    async def _fake_backfill_job(
        orchestrator: Any,
        data_path: str,
        config: dict[str, Any],
        current_date: str,
        stop_event: asyncio.Event | None = None,
    ) -> None:
        captured["stop_event"] = stop_event
        # 한 번 실행되면 루프를 종료시킨다.
        if stop_event is not None:
            stop_event.set()

    async def _noop_daily(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def _instant_wait(stop_event: asyncio.Event, *, timeout: float) -> None:
        return None

    monkeypatch.setattr(cli_scheduler, "_run_backfill_job", _fake_backfill_job)
    monkeypatch.setattr(cli_scheduler, "_run_daily_job", _noop_daily)
    monkeypatch.setattr(cli_scheduler, "_wait_or_stop", _instant_wait)

    # backfill_at을 항상 도달하도록 과거 시각으로, daily는 미래로 둔다.
    asyncio.run(
        cli_scheduler.run_scheduler_loop(
            orchestrator=MagicMock(),
            data_path="data/",
            config={},
            daily_at="23:59",
            backfill_at="00:00",
        )
    )

    assert "stop_event" in captured
    assert isinstance(captured["stop_event"], asyncio.Event)
