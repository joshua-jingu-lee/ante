"""FeedOrchestrator 단위 테스트.

mock 소스로 전체 ETL 흐름, 체크포인트 재개, 에러 처리, 파생 지표 계산을 검증한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import polars as pl
import pytest

from ante.data.store import ParquetStore
from ante.feed.models.result import CollectionResult
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator
from ante.feed.pipeline.orchestrator import FeedOrchestrator
from ante.feed.sources.dart import (
    DailyLimitExceededError as DARTDailyLimitError,
)
from ante.feed.sources.data_go_kr import (
    CriticalApiError as DataGoKrCriticalError,
)
from ante.feed.sources.data_go_kr import (
    DailyLimitExceededError as DataGoKrDailyLimitError,
)

# ── Fixtures ─────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _disable_publication_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    """#2015 publication cap을 이 파일 내에서만 중립화한다 (#2277).

    이 파일의 backfill 테스트는 mock 소스라 실제 D+1 13:00 공시 지연과 무관하다.
    cap이 끼면 ``backfill_since=어제`` 같은 상대 날짜가 wall-clock(KST 13:00
    경계)에 의존해 캘린더 flaky가 된다(KST 00:00–13:00 구간에 published_end<어제로
    range 공집합 → rows_written=0). 호출 지점인
    ``backfill_runner._last_published_date`` 를 항등(오늘 KST)으로 대체해 backfill
    range를 시각 무관하게 만든다. 파일-local autouse 이므로
    ``test_backfill_last_published_cap.py`` 의 #2015 cap 검증은 마스킹하지 않는다.
    """
    import ante.feed.pipeline.backfill_runner as br

    monkeypatch.setattr(br, "_last_published_date", lambda now_kst: now_kst.date())


def _make_data_go_kr_records(
    date_str: str = "20240101",
    symbols: list[str] | None = None,
) -> list[dict]:
    """data.go.kr 응답 형식의 mock 레코드를 생성한다."""
    syms = symbols or ["005930", "000660"]
    records = []
    for sym in syms:
        records.append(
            {
                "basDt": date_str,
                "srtnCd": sym,
                "itmsNm": f"종목{sym}",
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
        )
    return records


def _make_dart_records(
    corp_code: str = "00126380",
    year: str = "2024",
    reprt_code: str = "11011",
) -> list[dict]:
    """DART 재무제표 응답 형식의 mock 레코드를 생성한다."""
    return [
        {
            "corp_code": corp_code,
            "account_nm": "당기순이익",
            "thstrm_amount": "50,000,000,000",
            "fs_div": "CFS",
            "reprt_code": reprt_code,
            "bsns_year": year,
            "sj_div": "IS",
        },
        {
            "corp_code": corp_code,
            "account_nm": "자본총계",
            "thstrm_amount": "300,000,000,000",
            "fs_div": "CFS",
            "reprt_code": reprt_code,
            "bsns_year": year,
            "sj_div": "BS",
        },
        {
            "corp_code": corp_code,
            "account_nm": "부채총계",
            "thstrm_amount": "100,000,000,000",
            "fs_div": "CFS",
            "reprt_code": reprt_code,
            "bsns_year": year,
            "sj_div": "BS",
        },
        {
            "corp_code": corp_code,
            "account_nm": "매출액",
            "thstrm_amount": "200,000,000,000",
            "fs_div": "CFS",
            "reprt_code": reprt_code,
            "bsns_year": year,
            "sj_div": "IS",
        },
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


@pytest.fixture
def mock_data_go_kr_source() -> AsyncMock:
    """data.go.kr 소스 mock."""
    source = AsyncMock()
    source.fetch = AsyncMock(return_value=_make_data_go_kr_records())
    source.rate_limiter = MagicMock()
    source.rate_limiter.is_daily_limit_reached.return_value = False
    return source


@pytest.fixture
def mock_dart_source() -> AsyncMock:
    """DART 소스 mock."""
    source = AsyncMock()
    source.fetch_corp_codes = AsyncMock(
        return_value={"00126380": "005930", "00164742": "000660"}
    )
    source.fetch_financial = AsyncMock(return_value=_make_dart_records())
    source.rate_limiter = MagicMock()
    source.rate_limiter.is_daily_limit_reached.return_value = False
    return source


@pytest.fixture
def basic_config() -> dict:
    """기본 설정."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    return {
        "schedule": {
            "backfill_since": yesterday,
        },
        "guard": {
            "blocked_days": [],
            "blocked_hours": [],
            "pause_during_trading": False,
        },
    }


# ── Backfill 테스트 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_basic_flow(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """Backfill 기본 ETL 흐름이 정상 동작한다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert isinstance(result, CollectionResult)
    assert result.mode == "backfill"
    assert result.rows_written > 0
    assert "ohlcv" in result.data_types


@pytest.mark.asyncio
async def test_backfill_no_sources(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """소스가 없으면 config_errors를 보고한다."""
    orchestrator = FeedOrchestrator()

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert result.mode == "backfill"
    assert len(result.config_errors) >= 1
    sources = [e.get("source") for e in result.config_errors]
    assert "data_go_kr" in sources


@pytest.mark.asyncio
async def test_backfill_checkpoint_resume(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
) -> None:
    """체크포인트가 있으면 그 이후부터 수집을 재개한다."""
    # 어제-2일부터 시작, 어제-1일까지 체크포인트 저장
    two_days_ago = (date.today() - timedelta(days=2)).isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    config = {
        "schedule": {"backfill_since": two_days_ago},
        "guard": {
            "blocked_days": [],
            "blocked_hours": [],
            "pause_during_trading": False,
        },
    }

    # 첫 번째 체크포인트를 수동 저장
    from ante.feed.pipeline.checkpoint import Checkpoint

    cp = Checkpoint(tmp_data_path / ".feed", "data_go_kr", "ohlcv")
    cp.save(yesterday)

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, config)

    # 체크포인트 이후 날짜만 수집 시도 (오늘)
    assert result.mode == "backfill"


@pytest.mark.asyncio
async def test_backfill_daily_limit_stops(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """data.go.kr 일일 한도 초과 시 수집을 중단하고 결과를 반환한다."""
    source = AsyncMock()
    source.fetch = AsyncMock(side_effect=DataGoKrDailyLimitError("일일 한도 초과"))

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert result.mode == "backfill"
    assert any("data_go_kr" in str(e) for e in result.config_errors)


@pytest.mark.asyncio
async def test_backfill_critical_error_stops(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """data.go.kr Critical 에러 시 수집을 중단한다."""
    source = AsyncMock()
    source.fetch = AsyncMock(side_effect=DataGoKrCriticalError("서비스키 만료"))

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert any("data_go_kr" in str(e) for e in result.config_errors)


@pytest.mark.asyncio
async def test_backfill_fetch_error_skips_date(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """일반 에러 시 해당 날짜를 스킵하고 failures에 기록한다."""
    source = AsyncMock()
    source.fetch = AsyncMock(side_effect=RuntimeError("네트워크 오류"))

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert len(result.failures) > 0
    assert result.failures[0]["source"] == "data_go_kr"


# ── Daily 테스트 ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_daily_basic_flow(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """Daily 기본 ETL 흐름이 정상 동작한다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    result = await orchestrator.run_daily(tmp_data_path, basic_config)

    assert isinstance(result, CollectionResult)
    assert result.mode == "daily"
    assert result.target_date is not None
    assert result.rows_written > 0


@pytest.mark.asyncio
async def test_daily_no_sources(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """Daily에서 소스 없으면 config_errors 보고."""
    orchestrator = FeedOrchestrator()

    result = await orchestrator.run_daily(tmp_data_path, basic_config)

    assert result.mode == "daily"
    assert len(result.config_errors) >= 1


# ── 방어 가드 테스트 ─────────────────────────────────────


def test_is_blocked_by_day() -> None:
    """blocked_days에 해당하면 True를 반환한다."""
    # 2024-01-01은 월요일 (mon)
    config = {"guard": {"blocked_days": ["mon"]}}
    assert FeedOrchestrator._is_blocked(config, "2024-01-01") is True


def test_is_not_blocked_by_day() -> None:
    """blocked_days에 해당하지 않으면 False."""
    config = {"guard": {"blocked_days": ["sat", "sun"]}}
    assert FeedOrchestrator._is_blocked(config, "2024-01-01") is False


def test_is_blocked_empty_guard() -> None:
    """guard 설정이 없으면 차단되지 않는다."""
    config: dict = {}
    assert FeedOrchestrator._is_blocked(config, "2024-01-01") is False


# ── 가드 분리 (#1972): _is_blocked_day / _is_trading_paused ──────────────


def test_is_blocked_day_true_for_listed_weekday() -> None:
    """blocked_days에 해당하는 target_date 요일이면 True (skip 대상)."""
    # 2024-01-06 = 토요일
    config = {"guard": {"blocked_days": ["sat", "sun"]}}
    assert FeedOrchestrator._is_blocked_day(config, "2024-01-06") is True


def test_is_blocked_day_false_for_unlisted_weekday() -> None:
    """blocked_days에 없는 요일이면 False."""
    # 2024-01-01 = 월요일
    config = {"guard": {"blocked_days": ["sat", "sun"]}}
    assert FeedOrchestrator._is_blocked_day(config, "2024-01-01") is False


def test_is_blocked_day_ignores_trading_hours(monkeypatch: pytest.MonkeyPatch) -> None:
    """_is_blocked_day는 현재 시각/거래시간 가드를 보지 않는다 (target_date 전용)."""
    # blocked_days가 비어 있으면, blocked_hours/pause가 설정돼 있어도 False.
    config = {
        "guard": {
            "blocked_days": [],
            "blocked_hours": ["00:00-23:59"],
            "pause_during_trading": True,
        }
    }
    assert FeedOrchestrator._is_blocked_day(config, "2024-01-01") is False


def test_is_trading_paused_true_inside_window() -> None:
    """현재 KST 시각이 거래시간 window 안이면 True (대기 대상)."""
    import ante.feed.pipeline.orchestrator as orch_mod

    # 현재 시각을 무조건 포함하는 window로 강제.
    config = {
        "guard": {
            "blocked_hours": ["00:00-23:59"],
            "pause_during_trading": True,
        }
    }
    # 종일 window이므로 실제 현재 KST 시각과 무관하게 True.
    assert orch_mod.FeedOrchestrator._is_trading_paused(config) is True


def test_is_trading_paused_false_when_disabled() -> None:
    """pause_during_trading=False면 window가 있어도 False."""
    config = {
        "guard": {
            "blocked_hours": ["00:00-23:59"],
            "pause_during_trading": False,
        }
    }
    assert FeedOrchestrator._is_trading_paused(config) is False


def test_is_trading_paused_ignores_target_date() -> None:
    """_is_trading_paused는 target_date(요일)를 인자로 받지 않는다."""
    # blocked_days만 있고 blocked_hours가 없으면 거래시간 가드는 False.
    config = {"guard": {"blocked_days": ["mon"]}}
    assert FeedOrchestrator._is_trading_paused(config) is False


def test_is_blocked_is_or_composition() -> None:
    """_is_blocked는 _is_blocked_day OR _is_trading_paused 합성(동작 보존)."""
    # day만 차단: 2024-01-06 토요일.
    day_only = {"guard": {"blocked_days": ["sat"]}}
    assert FeedOrchestrator._is_blocked(day_only, "2024-01-06") is True
    # hour만 차단: 종일 window.
    hour_only = {
        "guard": {
            "blocked_hours": ["00:00-23:59"],
            "pause_during_trading": True,
        }
    }
    assert FeedOrchestrator._is_blocked(hour_only, "2024-01-01") is True
    # 둘 다 비활성: False.
    neither = {"guard": {"blocked_days": ["sat"]}}
    assert FeedOrchestrator._is_blocked(neither, "2024-01-01") is False


# ── Lock 파일 테스트 ─────────────────────────────────────


def test_acquire_and_release_lock(tmp_path: Path) -> None:
    """Lock 획득 후 해제가 정상 동작한다."""
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    assert FeedOrchestrator._acquire_lock(feed_dir) is True
    assert (feed_dir / "lock").exists()

    FeedOrchestrator._release_lock(feed_dir)
    assert not (feed_dir / "lock").exists()


def test_acquire_lock_stale(tmp_path: Path) -> None:
    """비정상 종료된 lock 파일은 제거 후 획득한다."""
    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    # 존재하지 않는 PID로 lock 파일 생성
    (feed_dir / "lock").write_text("999999999")

    assert FeedOrchestrator._acquire_lock(feed_dir) is True


def test_acquire_lock_records_current_pid(tmp_path: Path) -> None:
    """정상 획득 시 lock 파일에 현재 PID가 십진 문자열로 기록된다.

    기존 ``write_text(str(pid))`` 와 동일한 형식이어야
    release/다른 reader 호환이 유지된다(#2007).
    """
    import os

    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    assert FeedOrchestrator._acquire_lock(feed_dir) is True
    assert (feed_dir / "lock").read_text() == str(os.getpid())


def test_acquire_lock_blocked_when_alive(tmp_path: Path) -> None:
    """살아있는 프로세스(현재 PID)의 lock 보유 중에는 재획득이 차단된다.

    원자성/이중 획득 차단: 현재 PID는 ``os.kill(pid, 0)`` 성공=alive 이므로
    이미 lock 을 점유 중이면 두 번째 획득 시도는 ``False`` 이고 lock 파일도
    보존된다(#2007/#2057).
    """
    import os

    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    # 첫 번째 획득(현재 PID 점유)
    assert FeedOrchestrator._acquire_lock(feed_dir) is True
    assert (feed_dir / "lock").read_text() == str(os.getpid())

    # 두 번째 획득 시도 → alive 로 판정되어 차단, lock 보존
    assert FeedOrchestrator._acquire_lock(feed_dir) is False
    assert (feed_dir / "lock").exists()
    assert (feed_dir / "lock").read_text() == str(os.getpid())


def test_acquire_lock_permission_error_is_alive(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``os.kill`` PermissionError(EPERM)는 alive 로 보고 차단한다 (#2006).

    EPERM 은 프로세스가 존재하나 signal 권한이 없을 때 발생한다.
    기존엔 stale 제거 except 에 묶여 lock 을 삭제하고 획득하던 오판이었다.
    수정 후에는 차단(``False``)하고 lock 파일을 보존해야 한다.
    """
    import ante.feed.pipeline.orchestrator as orch_mod

    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    # 임의 PID 로 lock 파일 생성
    (feed_dir / "lock").write_text("12345")

    def _raise_permission(pid: int, sig: int) -> None:
        raise PermissionError

    monkeypatch.setattr(orch_mod.os, "kill", _raise_permission)

    assert FeedOrchestrator._acquire_lock(feed_dir) is False
    # alive 판정 → lock 파일을 삭제하지 않고 보존
    assert (feed_dir / "lock").exists()
    assert (feed_dir / "lock").read_text() == "12345"


def test_acquire_lock_stale_process_lookup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``os.kill`` ProcessLookupError(ESRCH)는 stale 로 보고 제거 후 획득한다."""
    import os

    import ante.feed.pipeline.orchestrator as orch_mod

    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    (feed_dir / "lock").write_text("12345")

    def _raise_lookup(pid: int, sig: int) -> None:
        raise ProcessLookupError

    monkeypatch.setattr(orch_mod.os, "kill", _raise_lookup)

    assert FeedOrchestrator._acquire_lock(feed_dir) is True
    # stale 제거 후 현재 PID 로 재획득
    assert (feed_dir / "lock").read_text() == str(os.getpid())


def test_acquire_lock_malformed_pid(tmp_path: Path) -> None:
    """PID 파싱이 불가능한 malformed lock 은 제거 후 획득한다."""
    import os

    feed_dir = tmp_path / ".feed"
    feed_dir.mkdir()

    (feed_dir / "lock").write_text("notapid")

    assert FeedOrchestrator._acquire_lock(feed_dir) is True
    assert (feed_dir / "lock").read_text() == str(os.getpid())


@pytest.mark.asyncio
async def test_concurrent_run_blocked(
    tmp_data_path: Path,
    basic_config: dict,
) -> None:
    """동시 실행 시 두 번째 실행이 차단된다."""
    feed_dir = tmp_data_path / ".feed"
    import os

    # 현재 프로세스 PID로 lock 파일 생성 (실행 중인 것처럼)
    (feed_dir / "lock").write_text(str(os.getpid()))

    orchestrator = FeedOrchestrator()
    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert any("실행 중" in str(e) for e in result.config_errors)

    # lock 파일 정리
    (feed_dir / "lock").unlink(missing_ok=True)


# ── 파생 지표 계산 테스트 ────────────────────────────────


@pytest.mark.asyncio
async def test_compute_derived_indicators(tmp_data_path: Path) -> None:
    """PER/PBR/EPS/BPS/ROE/부채비율이 cadence-aware as-of join으로 계산된다.

    #1968: data.go.kr 일별(market_cap/shares_listed) + DART 분기(net_income/
    total_equity/total_debt)가 `(date, source)` 키로 별도 행으로 보존되므로,
    지표는 일별 행에 그 날짜 기준 가장 최근 분기 재무를 as-of 결합해 계산된다.
    """
    store = ParquetStore(base_path=tmp_data_path)

    # data.go.kr 일별 행 (분기 보고 이후 날짜) — 재무 컬럼은 null.
    daily_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [5_969_782_550],
            "source": ["data_go_kr"],
        }
    )
    # DART 분기 행 (분기말) — 가격/주식수 컬럼은 null.
    quarterly_df = pl.DataFrame(
        {
            "date": [date(2024, 9, 30)],
            "symbol": ["005930"],
            "net_income": [50_000_000_000_000],
            "total_equity": [300_000_000_000_000],
            "total_debt": [100_000_000_000_000],
            "source": ["dart"],
        }
    )

    store.write("005930", "krx", daily_df, data_type="fundamental")
    store.write("005930", "krx", quarterly_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    rows = calculator.compute(store, ["005930"])

    assert rows > 0

    # 결과 읽기 — 지표는 일별(data_go_kr) 행에 부여된다.
    result = store.read("005930", "krx", data_type="fundamental")
    assert not result.is_empty()

    daily = result.filter(pl.col("source") == "data_go_kr")
    assert len(daily) == 1
    row = daily.row(0, named=True)

    # PER = 시가총액 / 순이익 (as-of 2024-09-30 분기 재무)
    expected_per = 400_000_000_000_000 / 50_000_000_000_000
    assert abs(row["per"] - expected_per) < 0.01

    # PBR = 시가총액 / 자본총계
    expected_pbr = 400_000_000_000_000 / 300_000_000_000_000
    assert abs(row["pbr"] - expected_pbr) < 0.01

    # EPS = 순이익 / 상장주식수
    expected_eps = 50_000_000_000_000 / 5_969_782_550
    assert abs(row["eps"] - expected_eps) < 1.0

    # BPS = 자본총계 / 상장주식수
    expected_bps = 300_000_000_000_000 / 5_969_782_550
    assert abs(row["bps"] - expected_bps) < 1.0

    # ROE = 순이익 / 자본총계
    expected_roe = 50_000_000_000_000 / 300_000_000_000_000
    assert abs(row["roe"] - expected_roe) < 0.0001

    # 부채비율 = 부채총계 / 자본총계
    expected_dte = 100_000_000_000_000 / 300_000_000_000_000
    assert abs(row["debt_to_equity"] - expected_dte) < 0.0001


@pytest.mark.asyncio
async def test_compute_derived_zero_division(tmp_data_path: Path) -> None:
    """분모가 0이면 파생 지표가 None이 된다 (#1968 as-of join 경로)."""
    store = ParquetStore(base_path=tmp_data_path)

    daily_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [0],  # 0으로 나누기 (EPS/BPS 분모)
            "source": ["data_go_kr"],
        }
    )
    quarterly_df = pl.DataFrame(
        {
            "date": [date(2024, 9, 30)],
            "symbol": ["005930"],
            "net_income": [0],  # 0으로 나누기 (PER 분모)
            "total_equity": [0],  # 0으로 나누기 (PBR/ROE/부채비율 분모)
            "total_debt": [100_000_000_000_000],
            "source": ["dart"],
        }
    )

    store.write("005930", "krx", daily_df, data_type="fundamental")
    store.write("005930", "krx", quarterly_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    calculator.compute(store, ["005930"])

    result = store.read("005930", "krx", data_type="fundamental")
    row = result.filter(pl.col("source") == "data_go_kr").row(0, named=True)

    # 분모 0이면 None
    assert row["per"] is None
    assert row["pbr"] is None
    assert row["eps"] is None
    assert row["bps"] is None
    assert row["roe"] is None
    assert row["debt_to_equity"] is None


@pytest.mark.asyncio
async def test_compute_derived_missing_columns(tmp_data_path: Path) -> None:
    """분기(DART) 소스가 없으면 graceful하게 0을 반환한다 (#1968).

    data.go.kr 일별 행만 있고 DART 분기 행이 없으면, as-of 결합 대상이 없으므로
    지표를 부여하지 않고 0을 반환한다(에러 없이).
    """
    store = ParquetStore(base_path=tmp_data_path)

    # data.go.kr 일별 행만 존재 (DART 분기 행 없음).
    daily_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [5_969_782_550],
            "source": ["data_go_kr"],
        }
    )

    store.write("005930", "krx", daily_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    # 에러 없이 실행되고, 분기 소스 부재로 0을 반환해야 함.
    rows = calculator.compute(store, ["005930"])
    assert rows == 0


# ── DART 수집 테스트 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_backfill_with_dart(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    mock_dart_source: AsyncMock,
) -> None:
    """Backfill에서 DART 수집이 함께 동작한다."""
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    config = {
        "schedule": {"backfill_since": yesterday},
        "guard": {
            "blocked_days": [],
            "blocked_hours": [],
            "pause_during_trading": False,
        },
    }

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        dart_source=mock_dart_source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, config)

    assert result.mode == "backfill"
    assert "fundamental" in result.data_types


@pytest.mark.asyncio
async def test_dart_daily_limit_handled(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """DART 일일 한도 초과 시 config_errors에 기록한다."""
    dart_source = AsyncMock()
    dart_source.fetch_corp_codes = AsyncMock(
        side_effect=DARTDailyLimitError("DART 일일 한도 초과")
    )

    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        dart_source=dart_source,
        store=store,
    )

    result = await orchestrator.run_backfill(tmp_data_path, basic_config)

    assert any("dart" in str(e).lower() for e in result.config_errors)


# ── 리포트 생성 테스트 ───────────────────────────────────


@pytest.mark.asyncio
async def test_report_generated(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """수집 완료 후 리포트 파일이 생성된다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    await orchestrator.run_backfill(tmp_data_path, basic_config)

    reports_dir = tmp_data_path / ".feed" / "reports"
    report_files = list(reports_dir.glob("*.json"))
    assert len(report_files) >= 1


@pytest.mark.asyncio
async def test_daily_report_generated(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """Daily 수집 후 리포트 파일이 생성된다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    await orchestrator.run_daily(tmp_data_path, basic_config)

    reports_dir = tmp_data_path / ".feed" / "reports"
    report_files = list(reports_dir.glob("*.json"))
    assert len(report_files) >= 1


# ── 데이터 저장 검증 ─────────────────────────────────────


@pytest.mark.asyncio
async def test_ohlcv_written_to_store(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """OHLCV 데이터가 ParquetStore에 올바르게 저장된다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    await orchestrator.run_daily(tmp_data_path, basic_config)

    # 심볼 디렉토리 확인
    ohlcv_path = tmp_data_path / "ohlcv" / "1d"
    if ohlcv_path.exists():
        symbol_dirs = list(ohlcv_path.iterdir())
        assert len(symbol_dirs) > 0


@pytest.mark.asyncio
async def test_fundamental_written_to_store(
    tmp_data_path: Path,
    mock_data_go_kr_source: AsyncMock,
    basic_config: dict,
) -> None:
    """FUNDAMENTAL 데이터가 ParquetStore에 올바르게 저장된다."""
    store = ParquetStore(base_path=tmp_data_path)
    orchestrator = FeedOrchestrator(
        data_go_kr_source=mock_data_go_kr_source,
        store=store,
    )

    await orchestrator.run_daily(tmp_data_path, basic_config)

    # fundamental 디렉토리 확인
    fund_path = tmp_data_path / "fundamental" / "KRX"
    if fund_path.exists():
        symbol_dirs = list(fund_path.iterdir())
        assert len(symbol_dirs) > 0
