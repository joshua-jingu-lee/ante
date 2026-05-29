"""IndicatorCalculator (feed pipeline) — cadence-aware as-of join 단위 테스트.

#1968: data.go.kr 일별(market_cap/shares_listed) + DART 분기(net_income/
total_equity/total_debt)가 `(date, source)` natural key로 별도 행으로 보존된다
(#1964). 파생지표는 일별 행에 그 날짜 기준 **가장 최근 보고된 분기 재무**를
`join_asof(strategy="backward")`로 결합하여 계산한다.

이 모듈은 `ante.feed.pipeline.indicator_calculator.IndicatorCalculator`
(fundamental 비율 계산기)를 검증한다 — `ante.strategy.indicators`의
pandas-ta 기술지표 계산기와는 별개다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from ante.data.schemas import FUNDAMENTAL_COLUMNS
from ante.data.store import ParquetStore
from ante.feed.pipeline.indicator_calculator import IndicatorCalculator

SYMBOL = "005930"


@pytest.fixture
def store(tmp_path: Path) -> ParquetStore:
    """임시 디렉토리 기반 ParquetStore."""
    return ParquetStore(base_path=tmp_path / "data")


def _write_daily(store: ParquetStore, rows: list[dict]) -> None:
    """data.go.kr 일별 fundamental 행을 기록한다 (재무 컬럼 없음)."""
    store.write(SYMBOL, "krx", pl.DataFrame(rows), data_type="fundamental")


def _write_quarterly(store: ParquetStore, rows: list[dict]) -> None:
    """DART 분기 fundamental 행을 기록한다 (가격/주식수 컬럼 없음)."""
    store.write(SYMBOL, "krx", pl.DataFrame(rows), data_type="fundamental")


def _daily_rows(store: ParquetStore) -> pl.DataFrame:
    """저장된 data.go.kr 일별 행을 date순으로 반환한다."""
    result = store.read(SYMBOL, "krx", data_type="fundamental")
    return result.filter(pl.col("source") == "data_go_kr").sort("date")


def test_indicator_asof_join_non_null(store: ParquetStore) -> None:
    """일별+분기 혼합 fixture에서 as-of 결합 후 6종 지표가 non-null & 정확하다.

    수정 전(row-wise): 일별 행에 net_income 등이 null이라 모든 지표 null → FAIL.
    """
    # data.go.kr 일별 행: Q1 보고(3/31) 이후 두 날짜 (4월/7월).
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2024, 7, 15),
                "symbol": SYMBOL,
                "market_cap": 440_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    # DART 분기 행: Q1(3/31), Q2(6/30).
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
            {
                "date": date(2024, 6, 30),
                "symbol": SYMBOL,
                "net_income": 55_000_000_000_000,
                "total_equity": 310_000_000_000_000,
                "total_debt": 105_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    rows = IndicatorCalculator().compute(store, [SYMBOL])
    assert rows == 2

    daily = _daily_rows(store)
    assert len(daily) == 2

    # 4/15 → as-of Q1(3/31) 재무.
    apr = daily.filter(pl.col("date") == date(2024, 4, 15)).row(0, named=True)
    assert apr["per"] is not None
    assert abs(apr["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6
    assert abs(apr["pbr"] - 420_000_000_000_000 / 300_000_000_000_000) < 1e-9
    assert abs(apr["eps"] - 50_000_000_000_000 / 5_969_782_550) < 1e-3
    assert abs(apr["bps"] - 300_000_000_000_000 / 5_969_782_550) < 1e-3
    assert abs(apr["roe"] - 50_000_000_000_000 / 300_000_000_000_000) < 1e-12
    assert (
        abs(apr["debt_to_equity"] - 100_000_000_000_000 / 300_000_000_000_000) < 1e-12
    )

    # 7/15 → as-of Q2(6/30) 재무 (가장 최근 보고서).
    jul = daily.filter(pl.col("date") == date(2024, 7, 15)).row(0, named=True)
    assert abs(jul["per"] - 440_000_000_000_000 / 55_000_000_000_000) < 1e-6
    assert abs(jul["pbr"] - 440_000_000_000_000 / 310_000_000_000_000) < 1e-9
    assert abs(jul["roe"] - 55_000_000_000_000 / 310_000_000_000_000) < 1e-12
    assert (
        abs(jul["debt_to_equity"] - 105_000_000_000_000 / 310_000_000_000_000) < 1e-12
    )


def test_indicator_asof_boundary_before_first_report_null(store: ParquetStore) -> None:
    """첫 분기 보고 이전 일별 날짜는 결합할 재무가 없어 지표가 null이다."""
    # 일별 행: 1/15(Q1 3/31 이전), 4/15(Q1 이후).
    _write_daily(
        store,
        [
            {
                "date": date(2024, 1, 15),
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    daily = _daily_rows(store)

    # 1/15: 첫 분기 보고(3/31) 이전 → null.
    jan = daily.filter(pl.col("date") == date(2024, 1, 15)).row(0, named=True)
    assert jan["per"] is None
    assert jan["pbr"] is None
    assert jan["eps"] is None
    assert jan["bps"] is None
    assert jan["roe"] is None
    assert jan["debt_to_equity"] is None

    # 4/15: 분기 보고 이후 → non-null.
    apr = daily.filter(pl.col("date") == date(2024, 4, 15)).row(0, named=True)
    assert apr["per"] is not None
    assert abs(apr["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_zero_denominator_null(store: ParquetStore) -> None:
    """분모가 0이면 해당 지표가 null이다 (as-of 결합 경로)."""
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 0,  # EPS/BPS 분모 0
                "source": "data_go_kr",
            },
        ],
    )
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 0,  # PER 분모 0
                "total_equity": 0,  # PBR/ROE/부채비율 분모 0
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    row = _daily_rows(store).row(0, named=True)
    assert row["per"] is None
    assert row["pbr"] is None
    assert row["eps"] is None
    assert row["bps"] is None
    assert row["roe"] is None
    assert row["debt_to_equity"] is None


def test_indicator_null_denominator_null(store: ParquetStore) -> None:
    """분기 재무 일부가 null이면 그 분모를 쓰는 지표만 null이 된다."""
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    # net_income은 보고됐으나 total_equity는 null인 분기.
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": None,  # PBR/ROE/부채비율 분모 null
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    row = _daily_rows(store).row(0, named=True)
    # net_income 기반: PER/EPS 산출.
    assert abs(row["per"] - 400_000_000_000_000 / 50_000_000_000_000) < 1e-6
    assert abs(row["eps"] - 50_000_000_000_000 / 5_969_782_550) < 1e-3
    # total_equity null → PBR/ROE/BPS/부채비율 null.
    assert row["pbr"] is None
    assert row["roe"] is None
    assert row["bps"] is None
    assert row["debt_to_equity"] is None


def test_indicator_only_daily_source_returns_zero(store: ParquetStore) -> None:
    """DART 분기 소스가 없으면 graceful하게 0 반환 (지표 미부여)."""
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )

    rows = IndicatorCalculator().compute(store, [SYMBOL])
    assert rows == 0


def test_indicator_only_quarterly_source_returns_zero(store: ParquetStore) -> None:
    """data.go.kr 일별 소스가 없으면 graceful하게 0 반환."""
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    rows = IndicatorCalculator().compute(store, [SYMBOL])
    assert rows == 0


def test_indicator_no_data_returns_zero(store: ParquetStore) -> None:
    """fundamental 데이터가 전혀 없으면 0을 반환한다."""
    rows = IndicatorCalculator().compute(store, ["999999"])
    assert rows == 0


def test_indicator_writeback_within_fundamental_schema(store: ParquetStore) -> None:
    """write-back된 일별 행은 FUNDAMENTAL 스키마 부분집합이다.

    DART normalizer가 내보내는 스키마 밖 컬럼(total_assets 등)이 read union으로
    섞여도, 일별 write-back 프레임에는 누출되지 않아야 한다.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    # 분기 행에 스키마 밖 컬럼(total_assets) 포함.
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "total_assets": 400_000_000_000_000,  # 스키마 밖
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    # 일별 행이 들어간 파티션 파일을 직접 검사 → 스키마 밖 컬럼 없어야 함.
    daily_path = store.resolve_path(SYMBOL, "krx", data_type="fundamental")
    schema_set = set(FUNDAMENTAL_COLUMNS)
    daily_partition = daily_path / "2024-04.parquet"
    assert daily_partition.exists()
    written = pl.read_parquet(daily_partition)
    assert set(written.columns).issubset(schema_set), (
        f"일별 write-back에 스키마 밖 컬럼 누출: {set(written.columns) - schema_set}"
    )
    assert written["source"].to_list() == ["data_go_kr"]


def test_indicator_idempotent_recompute(store: ParquetStore) -> None:
    """반복 compute해도 행 수가 폭증하지 않는다 ((date,source) keep=last 멱등)."""
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    calc = IndicatorCalculator()
    calc.compute(store, [SYMBOL])
    first = store.read(SYMBOL, "krx", data_type="fundamental")
    calc.compute(store, [SYMBOL])
    second = store.read(SYMBOL, "krx", data_type="fundamental")

    assert len(second) == len(first)
    # 지표 값도 안정적.
    apr_first = first.filter(pl.col("source") == "data_go_kr").row(0, named=True)
    apr_second = second.filter(pl.col("source") == "data_go_kr").row(0, named=True)
    assert apr_first["per"] == apr_second["per"]
