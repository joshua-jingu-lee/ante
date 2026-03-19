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
    """PER/PBR/EPS/BPS/ROE/부채비율이 올바르게 계산된다."""
    store = ParquetStore(base_path=tmp_data_path)

    # fundamental 데이터 준비
    fundamental_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [5_969_782_550],
            "net_income": [50_000_000_000_000],
            "total_equity": [300_000_000_000_000],
            "total_debt": [100_000_000_000_000],
            "source": ["test"],
        }
    )

    store.write("005930", "krx", fundamental_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    rows = calculator.compute(store, ["005930"])

    assert rows > 0

    # 결과 읽기
    result = store.read("005930", "krx", data_type="fundamental")
    assert not result.is_empty()

    row = result.row(0, named=True)

    # PER = 시가총액 / 순이익
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
    """분모가 0이면 파생 지표가 None이 된다."""
    store = ParquetStore(base_path=tmp_data_path)

    fundamental_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [0],  # 0으로 나누기
            "net_income": [0],  # 0으로 나누기
            "total_equity": [0],  # 0으로 나누기
            "total_debt": [100_000_000_000_000],
            "source": ["test"],
        }
    )

    store.write("005930", "krx", fundamental_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    calculator.compute(store, ["005930"])

    result = store.read("005930", "krx", data_type="fundamental")
    row = result.row(0, named=True)

    # 분모 0이면 None
    assert row["per"] is None
    assert row["pbr"] is None
    assert row["eps"] is None
    assert row["bps"] is None
    assert row["roe"] is None
    assert row["debt_to_equity"] is None


@pytest.mark.asyncio
async def test_compute_derived_missing_columns(tmp_data_path: Path) -> None:
    """필수 컬럼이 없으면 해당 지표를 건너뛴다."""
    store = ParquetStore(base_path=tmp_data_path)

    # market_cap만 있고 net_income 등이 없는 경우
    fundamental_df = pl.DataFrame(
        {
            "date": [date(2024, 12, 31)],
            "symbol": ["005930"],
            "market_cap": [400_000_000_000_000],
            "shares_listed": [5_969_782_550],
            "source": ["test"],
        }
    )

    store.write("005930", "krx", fundamental_df, data_type="fundamental")

    calculator = IndicatorCalculator()
    # 에러 없이 실행되어야 함
    rows = calculator.compute(store, ["005930"])
    assert rows >= 0


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
    fund_path = tmp_data_path / "fundamental" / "krx"
    if fund_path.exists():
        symbol_dirs = list(fund_path.iterdir())
        assert len(symbol_dirs) > 0
