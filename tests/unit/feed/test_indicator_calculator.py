"""IndicatorCalculator (feed pipeline) — cadence-aware as-of join 단위 테스트.

#1968: data.go.kr 일별(market_cap/shares_listed) + DART 분기(net_income/
total_equity/total_debt)가 `(date, source)` natural key로 별도 행으로 보존된다
(#1964). 파생지표는 일별 거래일에 그 시점 이전 **공시된** 가장 최근 분기 재무를
`join_asof(strategy="backward")`로 결합하여 계산한다.

#2067 (lookahead 제거): as-of join 키를 분기 period_end가 아니라 effective
availability(`coalesce(available_date, period_end + statutory_lag)`)로 바꾼다.
- `available_date`(#2010, 공시 접수일)가 있으면 그대로 쓴다.
- 없는 legacy 행은 법정 제출기한으로 fallback: period_end 월 ∈ {3,6,9} → +45일,
  월 == 12 → +90일. 비표준 월/effective null 행은 join 전 제거한다.

따라서 period_end 3/31 분기 재무는 (available_date 미지정 legacy 기준) 5/15부터
일별 행에 적용된다 — 공시 전인 4월 거래일에는 미래 정보를 쓰지 않는다.

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

    #2067: as-of 키는 공시 시점(effective availability)이다. 일별 날짜는 각
    분기의 **공시 이후** 시점으로 둔다.
    - Q1(period_end 3/31, available_date 5/15) → 6/15 일별이 Q1 적용.
    - Q2(period_end 6/30, available_date 8/14) → 9/15 일별이 Q2 적용.
    """
    # data.go.kr 일별 행: 각 분기의 공시 시점 이후 두 날짜.
    _write_daily(
        store,
        [
            {
                "date": date(2024, 6, 15),
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2024, 9, 15),
                "symbol": SYMBOL,
                "market_cap": 440_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    # DART 분기 행: Q1(period_end 3/31, 공시 5/15), Q2(period_end 6/30, 공시 8/14).
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "available_date": date(2024, 5, 15),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
            {
                "date": date(2024, 6, 30),
                "available_date": date(2024, 8, 14),
                "symbol": SYMBOL,
                "net_income": 55_000_000_000_000,
                "total_equity": 310_000_000_000_000,
                "total_debt": 105_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    # 지표 계산은 기존 일별 행을 비율 컬럼만 채워 같은 natural key로 in-place
    # overwrite한다(행 수 불변) → net-new 저장 행 수 = 0(#1993). 데이터 정확성은
    # 아래 비율 assert로 검증한다(rows_written 과대계상 제거).
    rows = IndicatorCalculator().compute(store, [SYMBOL])
    assert rows == 0

    daily = _daily_rows(store)
    assert len(daily) == 2

    # 6/15 → Q1 공시(5/15) 이후, Q2 공시(8/14) 이전 → Q1(3/31) 재무.
    jun = daily.filter(pl.col("date") == date(2024, 6, 15)).row(0, named=True)
    assert jun["per"] is not None
    assert abs(jun["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6
    assert abs(jun["pbr"] - 420_000_000_000_000 / 300_000_000_000_000) < 1e-9
    assert abs(jun["eps"] - 50_000_000_000_000 / 5_969_782_550) < 1e-3
    assert abs(jun["bps"] - 300_000_000_000_000 / 5_969_782_550) < 1e-3
    assert abs(jun["roe"] - 50_000_000_000_000 / 300_000_000_000_000) < 1e-12
    assert (
        abs(jun["debt_to_equity"] - 100_000_000_000_000 / 300_000_000_000_000) < 1e-12
    )

    # 9/15 → Q2 공시(8/14) 이후 → Q2(6/30) 재무 (가장 최근 공시).
    sep = daily.filter(pl.col("date") == date(2024, 9, 15)).row(0, named=True)
    assert abs(sep["per"] - 440_000_000_000_000 / 55_000_000_000_000) < 1e-6
    assert abs(sep["pbr"] - 440_000_000_000_000 / 310_000_000_000_000) < 1e-9
    assert abs(sep["roe"] - 55_000_000_000_000 / 310_000_000_000_000) < 1e-12
    assert (
        abs(sep["debt_to_equity"] - 105_000_000_000_000 / 310_000_000_000_000) < 1e-12
    )


def test_indicator_lookahead_blocked_until_available_date(store: ParquetStore) -> None:
    """[#2067 lookahead 차단] period_end 이후라도 공시 전이면 재무가 null이다.

    Q1 period_end 3/31, available_date(공시) 5/15. 일별 4/15는 period_end
    이후지만 **공시 전**이라 재무 미적용(null) — period_end 기준이면 lookahead로
    적용됐을 시점. 5/20은 공시 이후라 Q1 적용.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 4, 15),  # period_end(3/31) 이후, 공시(5/15) 이전
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2024, 5, 20),  # 공시(5/15) 이후
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
                "available_date": date(2024, 5, 15),
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

    # 4/15: period_end 이후지만 공시(5/15) 전 → 미공시 → null (lookahead 차단).
    apr = daily.filter(pl.col("date") == date(2024, 4, 15)).row(0, named=True)
    assert apr["per"] is None
    assert apr["pbr"] is None
    assert apr["eps"] is None
    assert apr["bps"] is None
    assert apr["roe"] is None
    assert apr["debt_to_equity"] is None

    # 5/20: 공시 이후 → Q1 적용.
    may = daily.filter(pl.col("date") == date(2024, 5, 20)).row(0, named=True)
    assert may["per"] is not None
    assert abs(may["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_available_date_boundary_inclusive(store: ParquetStore) -> None:
    """[#2067 경계] 일별 date == available_date면 backward inclusive로 적용된다."""
    _write_daily(
        store,
        [
            {
                "date": date(2024, 5, 15),  # 공시일 당일
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
                "available_date": date(2024, 5, 15),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    row = _daily_rows(store).row(0, named=True)
    # 공시일 당일은 적용(inclusive).
    assert row["per"] is not None
    assert abs(row["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_legacy_fallback_statutory_lag_quarterly(store: ParquetStore) -> None:
    """[#2067 legacy fallback] available_date null이면 period_end+45일을 쓴다.

    Q1 period_end 3/31, available_date 미지정(legacy) → effective 5/15(+45일).
    일별 5/01은 effective 전 → null, 5/20은 이후 → 적용.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 5, 1),  # effective(5/15) 이전
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2024, 5, 20),  # effective(5/15) 이후
                "symbol": SYMBOL,
                "market_cap": 420_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
        ],
    )
    # available_date 컬럼 자체를 쓰지 않는 legacy 분기 행.
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

    # 5/01: effective(3/31+45=5/15) 이전 → null.
    may1 = daily.filter(pl.col("date") == date(2024, 5, 1)).row(0, named=True)
    assert may1["per"] is None
    assert may1["pbr"] is None
    assert may1["roe"] is None

    # 5/20: effective 이후 → Q1 적용.
    may20 = daily.filter(pl.col("date") == date(2024, 5, 20)).row(0, named=True)
    assert may20["per"] is not None
    assert abs(may20["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_legacy_fallback_statutory_lag_annual(store: ParquetStore) -> None:
    """[#2067 연간 fallback] period_end 12/31, available null → 익년 3/31(+90일)."""
    _write_daily(
        store,
        [
            {
                "date": date(2025, 3, 15),  # effective(익년 3/31) 이전
                "symbol": SYMBOL,
                "market_cap": 400_000_000_000_000,
                "shares_listed": 5_969_782_550,
                "source": "data_go_kr",
            },
            {
                "date": date(2025, 4, 15),  # effective(2025-03-31) 이후
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
                "date": date(2024, 12, 31),
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

    # 2025-03-15: effective(2024-12-31 + 90일 = 2025-03-31) 이전 → null.
    mar = daily.filter(pl.col("date") == date(2025, 3, 15)).row(0, named=True)
    assert mar["per"] is None

    # 2025-04-15: effective 이후 → 연간 재무 적용.
    apr = daily.filter(pl.col("date") == date(2025, 4, 15)).row(0, named=True)
    assert apr["per"] is not None
    assert abs(apr["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_available_date_used_over_fallback(store: ParquetStore) -> None:
    """[#2067] available_date가 있으면 법정기한 fallback이 아니라 실제 공시일 사용.

    period_end 3/31 fallback은 5/15(+45일)이지만 실제 공시(available_date)는
    4/20으로 더 빠르다. 일별 4/25는 fallback(5/15) 기준이면 null이지만 실제
    공시(4/20) 기준이면 적용 — available_date가 우선임을 검증한다.
    """
    _write_daily(
        store,
        [
            {
                # available_date(4/20) 이후, fallback(5/15) 이전.
                "date": date(2024, 4, 25),
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
                # fallback(5/15)보다 빠른 실제 공시일.
                "available_date": date(2024, 4, 20),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    IndicatorCalculator().compute(store, [SYMBOL])

    row = _daily_rows(store).row(0, named=True)
    # 실제 공시일(4/20) 기준 적용 — fallback(5/15)이면 null이었을 시점.
    assert row["per"] is not None
    assert abs(row["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_nonstandard_period_end_month_removed(store: ParquetStore) -> None:
    """[#2067] 비표준 period_end 월 + available_date null 분기 행은 join 전 제거.

    표준 분기 행(3/31, 공시 5/15)과 비표준 월 행(2/28, available_date null)을
    함께 둔다. 비표준 행은 effective null로 제거되고, 표준 행만 as-of 적용된다.
    graceful — 예외 없이 동작한다.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 5, 20),
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
            # 비표준 period_end 월(2/28) + available_date 없음 → 제거 대상.
            {
                "date": date(2024, 2, 28),
                "symbol": SYMBOL,
                "net_income": 999_000_000_000_000,
                "total_equity": 999_000_000_000_000,
                "total_debt": 999_000_000_000_000,
                "source": "dart",
            },
            # 표준 분기 행(3/31, 공시 5/15).
            {
                "date": date(2024, 3, 31),
                "available_date": date(2024, 5, 15),
                "symbol": SYMBOL,
                "net_income": 50_000_000_000_000,
                "total_equity": 300_000_000_000_000,
                "total_debt": 100_000_000_000_000,
                "source": "dart",
            },
        ],
    )

    # in-place overwrite(같은 natural key) → net-new 저장 0(#1993). 정확성은
    # 아래 비율 assert로 검증.
    rows = IndicatorCalculator().compute(store, [SYMBOL])
    assert rows == 0

    row = _daily_rows(store).row(0, named=True)
    # 비표준 행이 제거되고 표준 Q1만 적용 → Q1 값으로 산출(999 값이 아님).
    assert row["per"] is not None
    assert abs(row["per"] - 420_000_000_000_000 / 50_000_000_000_000) < 1e-6


def test_indicator_zero_denominator_null(store: ParquetStore) -> None:
    """분모가 0이면 해당 지표가 null이다 (as-of 결합 경로).

    재무가 실제 적용되도록 일별 날짜를 공시(available_date) 이후로 둔다.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 5, 20),  # 공시(5/15) 이후 → 재무 적용
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
                "available_date": date(2024, 5, 15),
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
    """분기 재무 일부가 null이면 그 분모를 쓰는 지표만 null이 된다.

    재무가 실제 적용되도록 일별 날짜를 공시(available_date) 이후로 둔다.
    """
    _write_daily(
        store,
        [
            {
                "date": date(2024, 5, 20),  # 공시(5/15) 이후 → 재무 적용
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
                "available_date": date(2024, 5, 15),
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
    # 분기 행에 스키마 밖 컬럼(total_assets) 포함. 4/15 일별이 재무를 받도록
    # available_date(공시일)를 4/1로 둔다(period_end 3/31 fallback 5/15보다 빠름).
    _write_quarterly(
        store,
        [
            {
                "date": date(2024, 3, 31),
                "available_date": date(2024, 4, 1),
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

    # 일별 행이 들어간 파티션 파일을 직접 검사 → 스키마 밖 컬럼(total_assets,
    # available_date 외 effective/temp 키 등) 없어야 함.
    daily_path = store.resolve_path(SYMBOL, "krx", data_type="fundamental")
    schema_set = set(FUNDAMENTAL_COLUMNS)
    daily_partition = daily_path / "2024-04.parquet"
    assert daily_partition.exists()
    written = pl.read_parquet(daily_partition)
    assert set(written.columns).issubset(schema_set), (
        f"일별 write-back에 스키마 밖 컬럼 누출: {set(written.columns) - schema_set}"
    )
    assert written["source"].to_list() == ["data_go_kr"]
    # 재무가 실제 적용됐는지(효력 있는 검증)도 함께 확인.
    assert written["per"].to_list()[0] is not None


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
                "available_date": date(2024, 4, 1),  # 4/15 일별이 재무를 받도록
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
    # 지표 값도 안정적(non-null이며 동일).
    apr_first = first.filter(pl.col("source") == "data_go_kr").row(0, named=True)
    apr_second = second.filter(pl.col("source") == "data_go_kr").row(0, named=True)
    assert apr_first["per"] is not None
    assert apr_first["per"] == apr_second["per"]
