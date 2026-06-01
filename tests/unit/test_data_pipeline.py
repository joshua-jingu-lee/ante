"""Data Pipeline 모듈 단위 테스트."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import polars as pl
import pytest

from ante.data.collector import DataCollector
from ante.data.normalizer import (
    DataNormalizer,
)
from ante.data.retention import RetentionPolicy
from ante.data.schemas import (
    FUNDAMENTAL_COLUMNS,
    FUNDAMENTAL_SCHEMA,
    OHLCV_COLUMNS,
    TIMEFRAMES,
    validate_fundamental,
    validate_ohlcv,
)
from ante.data.store import ParquetStore

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path):
    """테스트용 데이터 디렉토리."""
    return tmp_path / "data"


@pytest.fixture
def store(data_dir):
    return ParquetStore(base_path=data_dir)


@pytest.fixture
def normalizer():
    return DataNormalizer()


def _make_ohlcv_df(
    symbol: str = "005930",
    n: int = 5,
    start: str = "2026-03-01T09:00:00",
) -> pl.DataFrame:
    """테스트용 OHLCV DataFrame 생성."""
    timestamps = pl.datetime_range(
        datetime.fromisoformat(start),
        datetime.fromisoformat(start).replace(minute=n - 1),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [50000.0 + i * 100 for i in range(n)],
            "high": [50100.0 + i * 100 for i in range(n)],
            "low": [49900.0 + i * 100 for i in range(n)],
            "close": [50050.0 + i * 100 for i in range(n)],
            "volume": [1000 + i * 10 for i in range(n)],
            "source": ["test"] * n,
        }
    )


# ── schemas.py 테스트 ─────────────────────────────────


class TestSchemas:
    def test_ohlcv_columns_list(self):
        assert "timestamp" in OHLCV_COLUMNS
        assert "symbol" in OHLCV_COLUMNS
        assert "close" in OHLCV_COLUMNS
        assert "amount" in OHLCV_COLUMNS
        assert len(OHLCV_COLUMNS) == 9

    def test_timeframes(self):
        assert "1m" in TIMEFRAMES
        assert "1d" in TIMEFRAMES

    def test_validate_ohlcv_valid(self):
        df = _make_ohlcv_df()
        assert validate_ohlcv(df) is True

    def test_validate_ohlcv_missing_column(self):
        df = _make_ohlcv_df().drop("volume")
        assert validate_ohlcv(df) is False

    def test_fundamental_schema_field_count(self):
        assert len(FUNDAMENTAL_SCHEMA) == 18

    def test_fundamental_columns_list(self):
        assert "date" in FUNDAMENTAL_COLUMNS
        assert "symbol" in FUNDAMENTAL_COLUMNS
        assert "market_cap" in FUNDAMENTAL_COLUMNS
        assert "per" in FUNDAMENTAL_COLUMNS
        assert "source" in FUNDAMENTAL_COLUMNS
        assert len(FUNDAMENTAL_COLUMNS) == 18

    def test_fundamental_schema_types(self):
        assert FUNDAMENTAL_SCHEMA["date"] == pl.Date
        assert FUNDAMENTAL_SCHEMA["symbol"] == pl.Utf8
        assert FUNDAMENTAL_SCHEMA["market_cap"] == pl.Int64
        assert FUNDAMENTAL_SCHEMA["per"] == pl.Float64
        assert FUNDAMENTAL_SCHEMA["source"] == pl.Utf8

    def test_validate_fundamental_valid(self):
        df = pl.DataFrame(
            {
                "date": [datetime(2026, 3, 1).date()],
                "symbol": ["005930"],
                "source": ["dart"],
                "market_cap": [None],
            }
        )
        assert validate_fundamental(df) is True

    def test_validate_fundamental_missing_required(self):
        df = pl.DataFrame({"date": [datetime(2026, 3, 1).date()], "symbol": ["005930"]})
        assert validate_fundamental(df) is False


# ── store.py 테스트 ─────────────────────────────────


class TestParquetStore:
    async def test_write_and_read(self, store):
        df = _make_ohlcv_df()
        store.write("005930", "1m", df)

        result = store.read("005930", "1m")
        assert len(result) == 5
        assert result["symbol"][0] == "005930"

    async def test_read_empty(self, store):
        result = store.read("999999", "1d")
        assert result.is_empty()

    async def test_write_creates_partitioned_files(self, store, data_dir):
        df = _make_ohlcv_df()
        store.write("005930", "1m", df)

        parquet_path = data_dir / "ohlcv" / "1m" / "KRX" / "005930" / "2026-03.parquet"
        assert parquet_path.exists()

    async def test_write_merge_dedup(self, store):
        """같은 timestamp 데이터를 두 번 쓰면 중복 제거."""
        df = _make_ohlcv_df(n=3)
        store.write("005930", "1m", df)
        store.write("005930", "1m", df)

        result = store.read("005930", "1m")
        assert len(result) == 3  # 중복 제거됨

    async def test_read_with_time_filter(self, store):
        df = _make_ohlcv_df(n=10, start="2026-03-01T09:00:00")
        store.write("005930", "1m", df)

        result = store.read(
            "005930",
            "1m",
            start="2026-03-01T09:03:00",
            end="2026-03-01T09:07:00",
        )
        assert len(result) == 5

    async def test_read_with_limit(self, store):
        df = _make_ohlcv_df(n=10)
        store.write("005930", "1m", df)

        result = store.read("005930", "1m", limit=3)
        assert len(result) == 3

    async def test_append(self, store):
        rows = [
            {
                "timestamp": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
                "symbol": "005930",
                "open": 50000.0,
                "high": 50100.0,
                "low": 49900.0,
                "close": 50050.0,
                "volume": 1000,
                "source": "test",
            }
        ]
        store.append("005930", "1m", rows)
        result = store.read("005930", "1m")
        assert len(result) == 1

    async def test_list_symbols(self, store):
        store.write("005930", "1d", _make_ohlcv_df("005930"))
        store.write("000660", "1d", _make_ohlcv_df("000660"))

        symbols = store.list_symbols("1d")
        assert symbols == ["000660", "005930"]

    async def test_list_symbols_empty(self, store):
        assert store.list_symbols("1d") == []

    async def test_get_date_range(self, store):
        store.write("005930", "1m", _make_ohlcv_df())
        result = store.get_date_range("005930", "1m")
        assert result is not None
        assert result == ("2026-03", "2026-03")

    async def test_get_date_range_none(self, store):
        assert store.get_date_range("999999", "1m") is None

    async def test_get_storage_usage(self, store):
        store.write("005930", "1d", _make_ohlcv_df())
        usage = store.get_storage_usage()
        assert "1d" in usage
        assert usage["1d"] > 0

    async def test_delete_file(self, store):
        store.write("005930", "1m", _make_ohlcv_df())
        assert store.delete_file("005930", "1m", "2026-03") is True
        result = store.read("005930", "1m")
        assert result.is_empty()

    async def test_delete_file_nonexistent(self, store):
        assert store.delete_file("005930", "1m", "2099-01") is False

    async def test_write_empty_df(self, store):
        empty = pl.DataFrame()
        store.write("005930", "1m", empty)
        result = store.read("005930", "1m")
        assert result.is_empty()

    async def test_write_null_timestamp_rejected(self, store, data_dir):
        """null timestamp(partition key) ohlcv df는 ValueError 거부·미저장(#2107)."""
        df = pl.DataFrame(
            {
                "timestamp": pl.Series([None], dtype=pl.Datetime(time_zone="UTC")),
                "symbol": ["005930"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
                "source": ["test"],
            }
        )
        with pytest.raises(ValueError):
            store.write("005930", "1m", df)

        # None.parquet 등 어떤 파티션도 생성되지 않아야 한다.
        # (path.mkdir 전에 raise되므로 디렉토리 자체가 없을 수 있다.)
        assert not data_dir.exists() or list(data_dir.rglob("*.parquet")) == []

    async def test_write_valid_timestamp_regression(self, store, data_dir):
        """유효 timestamp df는 정상 write/read, YYYY-MM.parquet 생성(#2107 회귀)."""
        df = _make_ohlcv_df()
        store.write("005930", "1m", df)

        parquet_path = data_dir / "ohlcv" / "1m" / "KRX" / "005930" / "2026-03.parquet"
        assert parquet_path.exists()

        result = store.read("005930", "1m")
        assert len(result) == 5
        assert result["timestamp"].is_null().any() is False

    async def test_write_mixed_null_timestamp_rejected(self, store, data_dir):
        """valid + null timestamp 혼합 df는 전체 거부·partial 미생성(#2107)."""
        valid = _make_ohlcv_df(n=2)
        null_row = pl.DataFrame(
            {
                "timestamp": pl.Series([None], dtype=pl.Datetime(time_zone="UTC")),
                "symbol": ["005930"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
                "source": ["test"],
            }
        )
        df = pl.concat([valid, null_row], how="vertical")
        with pytest.raises(ValueError):
            store.write("005930", "1m", df)

        assert not data_dir.exists() or list(data_dir.rglob("*.parquet")) == []

    async def test_write_fundamental_null_date_rejected(self, store, data_dir):
        """fundamental(time_col='date') null date df는 ValueError로 거부(#2107)."""
        df = pl.DataFrame(
            {
                "date": pl.Series([None], dtype=pl.Date),
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        with pytest.raises(ValueError):
            store.write("005930", "", df, data_type="fundamental")

        assert not data_dir.exists() or list(data_dir.rglob("*.parquet")) == []

    async def test_multi_month_partitioning(self, store, data_dir):
        """2개월에 걸친 데이터가 각각 별도 파일로 파티셔닝."""
        ts_march = pl.datetime_range(
            datetime(2026, 3, 1, 9, 0),
            datetime(2026, 3, 1, 9, 2),
            interval="1m",
            eager=True,
            time_zone="UTC",
        )
        ts_april = pl.datetime_range(
            datetime(2026, 4, 1, 9, 0),
            datetime(2026, 4, 1, 9, 2),
            interval="1m",
            eager=True,
            time_zone="UTC",
        )
        timestamps = ts_march.extend(ts_april)
        n = len(timestamps)
        df = pl.DataFrame(
            {
                "timestamp": timestamps,
                "symbol": ["005930"] * n,
                "open": [50000.0] * n,
                "high": [50100.0] * n,
                "low": [49900.0] * n,
                "close": [50050.0] * n,
                "volume": [1000] * n,
                "source": ["test"] * n,
            }
        )
        store.write("005930", "1m", df)

        march_file = data_dir / "ohlcv" / "1m" / "KRX" / "005930" / "2026-03.parquet"
        april_file = data_dir / "ohlcv" / "1m" / "KRX" / "005930" / "2026-04.parquet"
        assert march_file.exists()
        assert april_file.exists()

    async def test_fundamental_write_and_read(self, store):
        """fundamental 데이터 타입으로 write/read."""
        from datetime import date

        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1), date(2026, 3, 2)],
                "symbol": ["005930", "005930"],
                "market_cap": [500000000000, 510000000000],
                "per": [12.5, 12.8],
                "source": ["dart", "dart"],
            }
        )
        store.write("005930", "", df, data_type="fundamental")
        result = store.read("005930", "", data_type="fundamental")
        assert len(result) == 2
        assert result["market_cap"][0] == 500000000000

    async def test_fundamental_path_structure(self, store, data_dir):
        """fundamental은 {base}/fundamental/KRX/{symbol}/ 경로."""
        from datetime import date

        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1)],
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        store.write("005930", "", df, data_type="fundamental")
        path = data_dir / "fundamental" / "KRX" / "005930"
        assert path.exists()
        assert list(path.glob("*.parquet"))

    async def test_list_symbols_fundamental(self, store):
        """fundamental data_type의 종목 목록."""
        from datetime import date

        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1)],
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        store.write("005930", "", df, data_type="fundamental")
        symbols = store.list_symbols(data_type="fundamental")
        assert symbols == ["005930"]

    async def test_storage_usage_includes_fundamental(self, store):
        """get_storage_usage가 fundamental 용량도 포함."""
        from datetime import date

        store.write("005930", "1d", _make_ohlcv_df())
        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1)],
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        store.write("005930", "", df, data_type="fundamental")
        usage = store.get_storage_usage()
        assert "1d" in usage
        assert "fundamental" in usage

    async def test_ohlcv_default_backward_compat(self, store):
        """data_type 미지정 시 기존 OHLCV 동작 유지."""
        df = _make_ohlcv_df()
        store.write("005930", "1m", df)
        result = store.read("005930", "1m")
        assert len(result) == 5

    async def test_store_fundamental_multisource_no_data_loss(self, store):
        """다중 소스 fundamental이 같은 월 파티션에서 서로 덮어쓰지 않는다(#1964).

        data.go.kr(market_cap/shares_listed)를 먼저 쓰고, 같은 symbol/월에
        DART(재무제표)를 quarter-end date로 쓴 뒤 read하면 양쪽 소스의 행과
        컬럼이 **모두** 보존되어야 한다. 수정 전에는 schema mismatch로
        DART write가 기존 파일을 덮어써 data.go.kr 행이 소실됐다.
        """
        from datetime import date

        # data.go.kr: 9월 일별 fundamental (quarter-end 9/30 포함)
        dg = pl.DataFrame(
            {
                "date": [date(2025, 9, 29), date(2025, 9, 30)],
                "symbol": ["005930", "005930"],
                "market_cap": [500000000000, 510000000000],
                "shares_listed": [5970000000, 5970000000],
                "source": ["data_go_kr", "data_go_kr"],
            }
        )
        # DART: 3Q 재무제표 (date = quarter-end 9/30) — 다른 스키마
        dart = pl.DataFrame(
            {
                "date": [date(2025, 9, 30)],
                "symbol": ["005930"],
                "total_assets": [9000000000000.0],
                "total_debt": [3000000000000.0],
                "total_equity": [6000000000000.0],
                "revenue": [2000000000000.0],
                "net_income": [300000000000.0],
                "source": ["dart"],
            }
        )
        store.write("005930", "krx", dg, data_type="fundamental")
        store.write("005930", "krx", dart, data_type="fundamental")

        result = store.read("005930", "krx", data_type="fundamental")

        # 양쪽 소스 행이 모두 보존: data.go.kr 2행 + DART 1행 = 3행
        assert len(result) == 3
        assert sorted(result["source"].unique().to_list()) == ["dart", "data_go_kr"]

        # 양쪽 컬럼 집합이 모두 보존(합집합 스키마)
        cols = set(result.columns)
        assert {"market_cap", "shares_listed"} <= cols  # data.go.kr
        assert {"total_assets", "total_equity", "net_income"} <= cols  # DART

        # quarter-end(9/30)에서 data.go.kr 행과 DART 행이 공존
        q_end = result.filter(pl.col("date") == date(2025, 9, 30))
        assert len(q_end) == 2
        dg_row = q_end.filter(pl.col("source") == "data_go_kr")
        dart_row = q_end.filter(pl.col("source") == "dart")
        assert dg_row["market_cap"][0] == 510000000000
        assert dart_row["total_assets"][0] == 9000000000000.0

        # merge 이상이 없었음(silent overwrite 경로 제거 확인)
        assert store.drain_warnings() == []

    async def test_store_read_heterogeneous_monthly_schemas(self, store):
        """월마다 스키마가 다른 파티션을 raise 없이 합집합으로 읽는다(#1964).

        data.go.kr-only 월과 DART-only 월이 섞여 있어도 read가 예외 없이
        컬럼 합집합 DataFrame을 반환해야 한다. 수정 전에는 vertical concat이
        스키마 불일치로 raise했다.
        """
        from datetime import date

        # 8월: data.go.kr-only 스키마
        aug = pl.DataFrame(
            {
                "date": [date(2025, 8, 14)],
                "symbol": ["005930"],
                "market_cap": [480000000000],
                "shares_listed": [5970000000],
                "source": ["data_go_kr"],
            }
        )
        # 9월: DART-only 스키마 (완전히 다른 컬럼 집합)
        sep = pl.DataFrame(
            {
                "date": [date(2025, 9, 30)],
                "symbol": ["005930"],
                "total_assets": [9000000000000.0],
                "net_income": [300000000000.0],
                "source": ["dart"],
            }
        )
        store.write("005930", "krx", aug, data_type="fundamental")
        store.write("005930", "krx", sep, data_type="fundamental")

        # raise 없이 합집합 반환
        result = store.read("005930", "krx", data_type="fundamental")
        assert len(result) == 2
        cols = set(result.columns)
        assert {"market_cap", "shares_listed", "total_assets", "net_income"} <= cols


# ── normalizer.py 테스트 ─────────────────────────────


class TestDataNormalizer:
    def test_normalize_default_format(self, normalizer):
        df = pl.DataFrame(
            {
                "date": ["2026-03-01T09:00:00", "2026-03-01T09:01:00"],
                "open": [50000, 50100],
                "high": [50100, 50200],
                "low": [49900, 50000],
                "close": [50050, 50150],
                "volume": [1000, 1100],
            }
        )
        result = normalizer.normalize(df, source="external")
        assert "timestamp" in result.columns
        assert "source" in result.columns
        assert result["source"][0] == "external"

    def test_normalize_yahoo_format(self, normalizer):
        df = pl.DataFrame(
            {
                "Date": ["2026-03-01T09:00:00", "2026-03-01T09:01:00"],
                "Open": [50000, 50100],
                "High": [50100, 50200],
                "Low": [49900, 50000],
                "Close": [50050, 50150],
                "Volume": [1000, 1100],
            }
        )
        result = normalizer.normalize(df, source="yahoo")
        assert "timestamp" in result.columns
        assert len(result) == 2

    def test_normalize_adds_symbol_if_missing(self, normalizer):
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert "symbol" in result.columns
        assert result["symbol"][0] == ""

    def test_normalize_preserves_existing_source(self, normalizer):
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
                "source": ["custom"],
            }
        )
        result = normalizer.normalize(df)
        assert result["source"][0] == "custom"

    def test_normalize_no_timestamp_raises(self, normalizer):
        df = pl.DataFrame({"open": [50000.0], "close": [50050.0]})
        with pytest.raises(ValueError, match="timestamp"):
            normalizer.normalize(df)

    def test_normalize_date_type(self, normalizer):
        """Date 타입 timestamp도 정규화."""
        from datetime import date

        df = pl.DataFrame(
            {
                "timestamp": [date(2026, 3, 1)],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert isinstance(result["timestamp"].dtype, pl.Datetime)

    def test_normalize_fills_amount_null_when_missing(self, normalizer):
        """amount 컬럼이 없는 소스 데이터는 null로 채워진다."""
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert "amount" in result.columns
        assert result["amount"].dtype == pl.Int64
        assert result["amount"][0] is None

    def test_normalize_preserves_amount_when_present(self, normalizer):
        """amount 컬럼이 있는 소스 데이터는 값이 유지된다."""
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
                "amount": [5000000],
            }
        )
        result = normalizer.normalize(df)
        assert "amount" in result.columns
        assert result["amount"][0] == 5000000
        assert result["amount"].dtype == pl.Int64

    def test_normalize_casts_numeric_types(self, normalizer):
        df = pl.DataFrame(
            {
                "timestamp": ["2026-03-01T09:00:00"],
                "open": [50000],  # int
                "high": [50100],
                "low": [49900],
                "close": [50050],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert result["open"].dtype == pl.Float64
        assert result["volume"].dtype == pl.Int64

    def test_normalize_tz_aware_kst_converts_to_utc(self, normalizer):
        """tz-aware(KST) timestamp는 시점 보존하며 UTC로 변환된다 (#2105)."""
        from zoneinfo import ZoneInfo

        kst = ZoneInfo("Asia/Seoul")
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2026, 1, 1, 9, 0, tzinfo=kst)],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert isinstance(result["timestamp"].dtype, pl.Datetime)
        assert result["timestamp"].dtype.time_zone == "UTC"
        # KST 09:00 → UTC 00:00 (시점 보존 변환)
        assert result["timestamp"][0] == datetime(2026, 1, 1, 0, 0, tzinfo=UTC)

    def test_normalize_naive_datetime_labels_utc(self, normalizer):
        """naive datetime은 UTC 라벨만 붙이고 값은 불변 (#2105 회귀)."""
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2026, 1, 1, 9, 0)],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert result["timestamp"].dtype.time_zone == "UTC"
        # 라벨만 UTC, 값(시/분)은 그대로
        assert result["timestamp"][0] == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    def test_normalize_already_utc_unchanged(self, normalizer):
        """이미 UTC tz-aware timestamp는 값/타입 불변 (#2105 회귀)."""
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2026, 1, 1, 9, 0, tzinfo=UTC)],
                "open": [50000.0],
                "high": [50100.0],
                "low": [49900.0],
                "close": [50050.0],
                "volume": [1000],
            }
        )
        result = normalizer.normalize(df)
        assert result["timestamp"].dtype.time_zone == "UTC"
        assert result["timestamp"][0] == datetime(2026, 1, 1, 9, 0, tzinfo=UTC)

    async def test_normalize_kst_and_utc_merge_same_partition(self, normalizer, store):
        """KST·UTC 혼재 데이터가 같은 파티션에서 supertype 충돌 없이 merge (#2105)."""
        from zoneinfo import ZoneInfo

        kst_df = normalizer.normalize(
            pl.DataFrame(
                {
                    "timestamp": [
                        datetime(2026, 1, 1, 9, 0, tzinfo=ZoneInfo("Asia/Seoul"))
                    ],
                    "symbol": ["005930"],
                    "open": [50000.0],
                    "high": [50100.0],
                    "low": [49900.0],
                    "close": [50050.0],
                    "volume": [1000],
                }
            )
        )
        utc_df = normalizer.normalize(
            pl.DataFrame(
                {
                    "timestamp": [datetime(2026, 1, 1, 1, 0, tzinfo=UTC)],
                    "symbol": ["005930"],
                    "open": [51000.0],
                    "high": [51100.0],
                    "low": [50900.0],
                    "close": [51050.0],
                    "volume": [2000],
                }
            )
        )

        store.write("005930", "1m", kst_df)
        # 동일 symbol/timeframe/월 파티션으로 merge — supertype 실패 없이 성공해야 함
        store.write("005930", "1m", utc_df)

        result = store.read("005930", "1m")
        assert len(result) == 2
        assert result["timestamp"].dtype.time_zone == "UTC"


# ── DataGoKrNormalizer 테스트 ─────────────────────────


class TestDataGoKrNormalizer:
    """data.go.kr API 응답 정규화 테스트."""

    @pytest.fixture
    def dgk_normalizer(self):
        from ante.data.normalizer import DataGoKrNormalizer

        return DataGoKrNormalizer()

    @pytest.fixture
    def sample_df(self):
        """data.go.kr API 응답 샘플 (모든 값이 문자열)."""
        return pl.DataFrame(
            {
                "basDt": ["20260301", "20260302"],
                "srtnCd": ["005930", "005930"],
                "mkp": ["50000", "50500"],
                "hipr": ["51000", "51500"],
                "lopr": ["49500", "50000"],
                "clpr": ["50500", "51000"],
                "trqu": ["1000000", "1200000"],
                "trPrc": ["50500000000", "61200000000"],
                "mrktTotAmt": ["300000000000000", "305000000000000"],
                "lstgStCnt": ["5969782550", "5969782550"],
            }
        )

    def test_source_name(self, dgk_normalizer):
        assert dgk_normalizer.source_name == "data_go_kr"

    def test_registry_lookup(self):
        from ante.data.normalizer import get_normalizer

        n = get_normalizer("data_go_kr")
        assert n.source_name == "data_go_kr"

    def test_normalize_ohlcv(self, dgk_normalizer, sample_df):
        result = dgk_normalizer.normalize_ohlcv(sample_df)

        assert "timestamp" in result.columns
        assert "symbol" in result.columns
        assert "open" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert "amount" in result.columns
        assert "source" in result.columns

        assert result["open"].dtype == pl.Float64
        assert result["close"].dtype == pl.Float64
        assert result["volume"].dtype == pl.Int64
        assert result["amount"].dtype == pl.Int64
        assert isinstance(result["timestamp"].dtype, pl.Datetime)
        assert result["source"][0] == "data_go_kr"

        assert result["open"][0] == 50000.0
        assert result["close"][0] == 50500.0
        assert result["volume"][0] == 1000000
        assert result["amount"][0] == 50500000000
        assert result["symbol"][0] == "005930"

    def test_normalize_ohlcv_sorts_by_timestamp(self, dgk_normalizer):
        df = pl.DataFrame(
            {
                "basDt": ["20260302", "20260301"],
                "srtnCd": ["005930", "005930"],
                "mkp": ["50500", "50000"],
                "hipr": ["51500", "51000"],
                "lopr": ["50000", "49500"],
                "clpr": ["51000", "50500"],
                "trqu": ["1200000", "1000000"],
                "trPrc": ["61200000000", "50500000000"],
            }
        )
        result = dgk_normalizer.normalize_ohlcv(df)
        assert result["open"][0] == 50000.0

    def test_normalize_fundamental(self, dgk_normalizer, sample_df):
        result = dgk_normalizer.normalize_fundamental(sample_df)

        assert "date" in result.columns
        assert "symbol" in result.columns
        assert "market_cap" in result.columns
        assert "shares_listed" in result.columns
        assert "source" in result.columns

        assert result["date"].dtype == pl.Date
        assert result["market_cap"].dtype == pl.Int64
        assert result["shares_listed"].dtype == pl.Int64

        assert result["symbol"][0] == "005930"
        assert result["market_cap"][0] == 300000000000000
        assert result["shares_listed"][0] == 5969782550
        assert result["source"][0] == "data_go_kr"

    def test_normalize_fundamental_date_parsing(self, dgk_normalizer, sample_df):
        result = dgk_normalizer.normalize_fundamental(sample_df)
        from datetime import date

        assert result["date"][0] == date(2026, 3, 1)
        assert result["date"][1] == date(2026, 3, 2)

    def test_normalize_ohlcv_timestamp_parsing(self, dgk_normalizer):
        """YYYYMMDD 문자열이 Datetime으로 변환되는지 확인."""
        df = pl.DataFrame(
            {
                "basDt": ["20260315"],
                "srtnCd": ["005930"],
                "mkp": ["50000"],
                "hipr": ["51000"],
                "lopr": ["49500"],
                "clpr": ["50500"],
                "trqu": ["1000000"],
                "trPrc": ["50500000000"],
            }
        )
        result = dgk_normalizer.normalize_ohlcv(df)
        ts = result["timestamp"][0]
        assert ts.year == 2026
        assert ts.month == 3
        assert ts.day == 15

    def test_normalize_fundamental_excludes_ohlcv_columns(
        self, dgk_normalizer, sample_df
    ):
        """fundamental 결과에 OHLCV 전용 컬럼이 포함되지 않아야 한다."""
        result = dgk_normalizer.normalize_fundamental(sample_df)
        for col in ("open", "high", "low", "close", "volume", "amount", "timestamp"):
            assert col not in result.columns

    def test_normalize_ohlcv_via_base_normalize(self, dgk_normalizer, sample_df):
        """BaseNormalizer.normalize()를 직접 호출해도 OHLCV 결과가 동일."""
        result = dgk_normalizer.normalize(sample_df)
        assert "timestamp" in result.columns
        assert "close" in result.columns
        assert result["source"][0] == "data_go_kr"

    def test_export_from_package(self):
        """ante.data 패키지에서 DataGoKrNormalizer를 임포트할 수 있어야 한다."""
        from ante.data import DataGoKrNormalizer

        n = DataGoKrNormalizer()
        assert n.source_name == "data_go_kr"


# ── collector.py 테스트 ─────────────────────────────


class TestDataCollector:
    async def test_add_data_and_flush(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus, buffer_size=3)

        row = {
            "timestamp": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
            "symbol": "005930",
            "open": 50000.0,
            "high": 50100.0,
            "low": 49900.0,
            "close": 50050.0,
            "volume": 1000,
            "source": "test",
        }
        collector.add_data("005930", "1m", row)
        assert len(collector.buffer["005930:1m"]) == 1

        flushed = collector.flush_all()
        assert flushed == 1
        assert "005930:1m" not in collector.buffer

    async def test_auto_flush_on_buffer_full(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus, buffer_size=2)

        for i in range(2):
            row = {
                "timestamp": datetime(2026, 3, 1, 9, i, tzinfo=UTC),
                "symbol": "005930",
                "open": 50000.0,
                "high": 50100.0,
                "low": 49900.0,
                "close": 50050.0,
                "volume": 1000,
                "source": "test",
            }
            collector.add_data("005930", "1m", row)

        # buffer_size=2이므로 자동 flush됨
        assert "005930:1m" not in collector.buffer

        result = store.read("005930", "1m")
        assert len(result) == 2

    async def test_start_and_stop(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus, collect_interval=0.05)

        collector.start(["005930"], ["1m"])
        assert collector.running is True

        await asyncio.sleep(0.02)
        collector.stop()
        assert collector.running is False

    async def test_start_twice_ignored(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus)

        collector.start(["005930"], ["1m"])
        collector.start(["005930"], ["1m"])  # 두 번째 호출은 무시
        assert collector.running is True

        collector.stop()

    async def test_data_callback(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(
            store=store,
            eventbus=eventbus,
            collect_interval=0.05,
            buffer_size=100,
        )

        async def mock_callback(symbol, tf):
            return [
                {
                    "timestamp": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
                    "symbol": symbol,
                    "open": 50000.0,
                    "high": 50100.0,
                    "low": 49900.0,
                    "close": 50050.0,
                    "volume": 1000,
                    "source": "test",
                }
            ]

        collector.set_data_callback(mock_callback)
        collector.start(["005930"], ["1m"])
        await asyncio.sleep(0.1)
        collector.stop()

        result = store.read("005930", "1m")
        assert len(result) >= 1


# ── retention.py 테스트 ─────────────────────────────


class TestRetentionPolicy:
    def test_default_retention_days(self, store):
        policy = RetentionPolicy(store)
        assert policy.retention_days["1m"] == 365
        assert policy.retention_days["5m"] == 365
        assert policy.retention_days["1d"] == 3650
        assert policy.retention_days["fundamental"] == -1

    def test_custom_retention_days(self, store):
        custom = {"1m": 30, "1d": 100}
        policy = RetentionPolicy(store, retention_days=custom)
        assert policy.retention_days["1m"] == 30

    async def test_enforce_deletes_old_data(self, store):
        """보존 기간 초과 데이터 삭제."""
        store.write("005930", "1m", _make_ohlcv_df())

        # 1분봉 보존 기간을 0일로 설정 → 모든 데이터 삭제 대상
        policy = RetentionPolicy(store, retention_days={"1m": 0})
        now = datetime(2026, 6, 1, tzinfo=UTC)
        deleted = policy.enforce(now=now)

        assert "1m" in deleted
        assert deleted["1m"] >= 1

        result = store.read("005930", "1m")
        assert result.is_empty()

    async def test_enforce_keeps_recent_data(self, store):
        """보존 기간 내 데이터는 유지."""
        store.write("005930", "1m", _make_ohlcv_df())

        policy = RetentionPolicy(store, retention_days={"1m": 365})
        now = datetime(2026, 3, 15, tzinfo=UTC)
        deleted = policy.enforce(now=now)

        # 2026-03 데이터는 15일 전이므로 삭제 안 됨
        assert deleted == {}
        result = store.read("005930", "1m")
        assert len(result) == 5

    async def test_enforce_skips_negative_retention(self, store):
        """보존 기간이 -1(무기한)이면 삭제하지 않는다."""
        store.write("005930", "1m", _make_ohlcv_df())
        policy = RetentionPolicy(store, retention_days={"1m": -1})
        now = datetime(2099, 1, 1, tzinfo=UTC)
        deleted = policy.enforce(now=now)
        assert deleted == {}
        result = store.read("005930", "1m")
        assert len(result) == 5

    async def test_enforce_empty_store(self, store):
        policy = RetentionPolicy(store)
        deleted = policy.enforce()
        assert deleted == {}

    async def test_enforce_fundamental_path_resolution(self, store, data_dir):
        """fundamental data_type이 _resolve_path 경로를 사용하여 삭제."""
        from datetime import date

        df = pl.DataFrame(
            {
                "date": [date(2024, 1, 15), date(2024, 2, 15)],
                "symbol": ["005930", "005930"],
                "market_cap": [300000000000000, 305000000000000],
                "source": ["dart", "dart"],
            }
        )
        store.write("005930", "", df, data_type="fundamental")

        # fundamental/KRX/005930/ 경로에 파일이 생성되었는지 확인
        fundamental_path = data_dir / "fundamental" / "KRX" / "005930"
        assert fundamental_path.exists()
        assert len(list(fundamental_path.glob("*.parquet"))) == 2

        # fundamental 보존 기간을 0일로 설정 → 오래된 데이터 삭제 대상
        policy = RetentionPolicy(store, retention_days={"fundamental": 0})
        now = datetime(2026, 6, 1, tzinfo=UTC)
        deleted = policy.enforce(now=now)

        assert "fundamental" in deleted
        assert deleted["fundamental"] == 2

        result = store.read("005930", "", data_type="fundamental")
        assert result.is_empty()

    def test_is_expired_month_end_31day_regression(self):
        """#2100: 31일 월은 실제 월말(05-31) 기준 age를 계산해 보존.

        수정 전엔 월말을 28로 하드코딩해 05-31 데이터를 3일 일찍
        만료 처리(True)했다. 05-31 기준 30일 경과는 보존 기간(31일)
        이내이므로 보존(False)이어야 한다.
        """
        assert (
            RetentionPolicy._is_expired(
                "2026-05", 31, datetime(2026, 6, 30, tzinfo=UTC)
            )
            is False
        )

    def test_is_expired_leap_february_boundary(self):
        """#2100: 윤년 2월은 실제 월말(02-29) 기준으로 age 계산."""
        assert (
            RetentionPolicy._is_expired("2024-02", 1, datetime(2024, 3, 1, tzinfo=UTC))
            is False
        )

    def test_is_expired_common_february_boundary(self):
        """#2100: 평년 2월은 실제 월말(02-28) 기준으로 age 계산."""
        assert (
            RetentionPolicy._is_expired("2026-02", 1, datetime(2026, 3, 1, tzinfo=UTC))
            is False
        )

    def test_is_expired_31day_month_expires(self):
        """#2100: 보존 기간을 실제로 넘긴 31일 월은 정상 만료."""
        assert (
            RetentionPolicy._is_expired(
                "2026-05", 29, datetime(2026, 6, 30, tzinfo=UTC)
            )
            is True
        )

    def test_is_expired_invalid_filename(self):
        """#2100: 잘못된 파일명은 except 경로로 보존(False) 유지."""
        assert (
            RetentionPolicy._is_expired(
                "invalid", 30, datetime(2026, 6, 30, tzinfo=UTC)
            )
            is False
        )

    def test_is_expired_invalid_month(self):
        """#2100: 잘못된 월은 IllegalMonthError(⊂ ValueError)로 보존(False)."""
        assert (
            RetentionPolicy._is_expired("2024-13", 30, datetime(2026, 1, 1, tzinfo=UTC))
            is False
        )


# ── DARTNormalizer 테스트 ─────────────────────────────


def _make_dart_df(
    corp_codes: list[str] | None = None,
    accounts: list[str] | None = None,
    amounts: list[str] | None = None,
    fs_divs: list[str] | None = None,
    reprt_codes: list[str] | None = None,
    bsns_years: list[str] | None = None,
) -> pl.DataFrame:
    """테스트용 DART API 응답 DataFrame 생성."""
    if corp_codes is None:
        corp_codes = ["00126380"] * 5
    if accounts is None:
        accounts = [
            "매출액",
            "당기순이익",
            "자본총계",
            "부채총계",
            "자산총계",
        ]
    if amounts is None:
        amounts = [
            "1,000,000",
            "200,000",
            "500,000",
            "300,000",
            "800,000",
        ]
    if fs_divs is None:
        fs_divs = ["CFS"] * 5
    if reprt_codes is None:
        reprt_codes = ["11011"] * 5
    if bsns_years is None:
        bsns_years = ["2025"] * 5

    return pl.DataFrame(
        {
            "corp_code": corp_codes,
            "account_nm": accounts,
            "thstrm_amount": amounts,
            "fs_div": fs_divs,
            "reprt_code": reprt_codes,
            "bsns_year": bsns_years,
        }
    )


class TestDARTNormalizer:
    """DARTNormalizer 단위 테스트."""

    @pytest.fixture
    def dart_normalizer(self):
        from ante.data.normalizer import DARTNormalizer

        return DARTNormalizer()

    @pytest.fixture
    def corp_code_map(self) -> dict[str, str]:
        return {
            "00126380": "005930",
            "00164742": "000660",
        }

    def test_source_name(self, dart_normalizer):
        assert dart_normalizer.source_name == "dart"

    def test_normalize_basic(self, dart_normalizer, corp_code_map):
        """기본 정규화: 5개 계정과목 -> 피벗된 1행."""
        df = _make_dart_df()
        result = dart_normalizer.normalize(df, corp_code_map)

        assert len(result) == 1
        assert "symbol" in result.columns
        assert "date" in result.columns
        assert "source" in result.columns
        assert result["symbol"][0] == "005930"
        assert result["source"][0] == "dart"
        assert result["revenue"][0] == 1_000_000
        assert result["net_income"][0] == 200_000
        assert result["total_equity"][0] == 500_000
        assert result["total_debt"][0] == 300_000
        assert result["total_assets"][0] == 800_000

    def test_normalize_comma_removal(self, dart_normalizer, corp_code_map):
        """thstrm_amount 콤마 제거 후 숫자 변환."""
        df = _make_dart_df(amounts=["1,234,567,890"] * 5)
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["revenue"][0] == 1_234_567_890

    def test_normalize_reprt_code_1q(self, dart_normalizer, corp_code_map):
        """reprt_code 11013 -> 1Q (3월 말)."""
        from datetime import date

        df = _make_dart_df(
            reprt_codes=["11013"] * 5,
            bsns_years=["2025"] * 5,
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["date"][0] == date(2025, 3, 31)

    def test_normalize_reprt_code_semi(self, dart_normalizer, corp_code_map):
        """reprt_code 11012 -> semi (6월 말)."""
        from datetime import date

        df = _make_dart_df(
            reprt_codes=["11012"] * 5,
            bsns_years=["2025"] * 5,
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["date"][0] == date(2025, 6, 30)

    def test_normalize_reprt_code_3q(self, dart_normalizer, corp_code_map):
        """reprt_code 11014 -> 3Q (9월 말)."""
        from datetime import date

        df = _make_dart_df(
            reprt_codes=["11014"] * 5,
            bsns_years=["2025"] * 5,
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["date"][0] == date(2025, 9, 30)

    def test_normalize_reprt_code_annual(self, dart_normalizer, corp_code_map):
        """reprt_code 11011 -> annual (12월 말)."""
        from datetime import date

        df = _make_dart_df(
            reprt_codes=["11011"] * 5,
            bsns_years=["2025"] * 5,
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["date"][0] == date(2025, 12, 31)

    def test_normalize_cfs_priority(self, dart_normalizer, corp_code_map):
        """CFS 우선: CFS/OFS 둘 다 있으면 CFS만 사용."""
        df = pl.DataFrame(
            {
                "corp_code": ["00126380"] * 2,
                "account_nm": ["매출액", "매출액"],
                "thstrm_amount": ["1,000,000", "500,000"],
                "fs_div": ["CFS", "OFS"],
                "reprt_code": ["11011", "11011"],
                "bsns_year": ["2025", "2025"],
            }
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["revenue"][0] == 1_000_000

    def test_normalize_ofs_fallback(self, dart_normalizer, corp_code_map):
        """OFS 폴백: CFS가 없으면 OFS 사용."""
        df = _make_dart_df(fs_divs=["OFS"] * 5)
        result = dart_normalizer.normalize(df, corp_code_map)
        assert len(result) == 1
        assert result["revenue"][0] == 1_000_000

    def test_normalize_empty_df(self, dart_normalizer, corp_code_map):
        """빈 DataFrame 입력 시 빈 결과."""
        df = pl.DataFrame(
            schema={
                "corp_code": pl.Utf8,
                "account_nm": pl.Utf8,
                "thstrm_amount": pl.Utf8,
                "fs_div": pl.Utf8,
                "reprt_code": pl.Utf8,
                "bsns_year": pl.Utf8,
            }
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result.is_empty()

    def test_normalize_missing_columns_raises(self, dart_normalizer, corp_code_map):
        """필수 컬럼 누락 시 ValueError."""
        df = pl.DataFrame(
            {
                "corp_code": ["00126380"],
                "account_nm": ["매출액"],
            }
        )
        with pytest.raises(ValueError, match="필수 컬럼"):
            dart_normalizer.normalize(df, corp_code_map)

    def test_normalize_unknown_corp_code_filtered(self, dart_normalizer):
        """매핑되지 않는 corp_code는 필터링."""
        df = _make_dart_df(corp_codes=["99999999"] * 5)
        result = dart_normalizer.normalize(df, {"00126380": "005930"})
        assert result.is_empty()

    def test_normalize_alternative_account_names(self, dart_normalizer, corp_code_map):
        """대체 계정과목명 매핑."""
        df = _make_dart_df(
            accounts=[
                "수익(매출액)",
                "당기순이익(손실)",
                "자본총계",
                "부채총계",
                "자산총계",
            ]
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert result["revenue"][0] == 1_000_000
        assert result["net_income"][0] == 200_000

    def test_normalize_multi_symbol(self, dart_normalizer, corp_code_map):
        """여러 종목 동시 정규화."""
        df = pl.DataFrame(
            {
                "corp_code": [
                    "00126380",
                    "00126380",
                    "00164742",
                    "00164742",
                ],
                "account_nm": [
                    "매출액",
                    "당기순이익",
                    "매출액",
                    "당기순이익",
                ],
                "thstrm_amount": [
                    "1,000,000",
                    "200,000",
                    "500,000",
                    "100,000",
                ],
                "fs_div": ["CFS"] * 4,
                "reprt_code": ["11011"] * 4,
                "bsns_year": ["2025"] * 4,
            }
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert len(result) == 2
        symbols = result["symbol"].to_list()
        assert symbols == ["000660", "005930"]

    def test_normalize_unrecognized_account_filtered(
        self, dart_normalizer, corp_code_map
    ):
        """인식되지 않는 계정과목은 무시."""
        df = _make_dart_df(
            accounts=[
                "매출액",
                "당기순이익",
                "영업이익",
                "미지의계정",
                "자산총계",
            ],
        )
        result = dart_normalizer.normalize(df, corp_code_map)
        assert "revenue" in result.columns
        assert "net_income" in result.columns
        assert "total_assets" in result.columns

    def test_dart_in_registry(self):
        """DARTNormalizer가 DART_NORMALIZER_REGISTRY에 등록."""
        from ante.data.normalizer import (
            DART_NORMALIZER_REGISTRY,
            DARTNormalizer,
        )

        assert "dart" in DART_NORMALIZER_REGISTRY
        assert DART_NORMALIZER_REGISTRY["dart"] is DARTNormalizer
