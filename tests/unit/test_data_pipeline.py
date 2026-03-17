"""Data Pipeline 모듈 단위 테스트."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import polars as pl
import pytest

from ante.data.collector import DataCollector
from ante.data.injector import DataInjector
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
        await store.write("005930", "1m", df)

        result = await store.read("005930", "1m")
        assert len(result) == 5
        assert result["symbol"][0] == "005930"

    async def test_read_empty(self, store):
        result = await store.read("999999", "1d")
        assert result.is_empty()

    async def test_write_creates_partitioned_files(self, store, data_dir):
        df = _make_ohlcv_df()
        await store.write("005930", "1m", df)

        parquet_path = data_dir / "ohlcv" / "1m" / "005930" / "2026-03.parquet"
        assert parquet_path.exists()

    async def test_write_merge_dedup(self, store):
        """같은 timestamp 데이터를 두 번 쓰면 중복 제거."""
        df = _make_ohlcv_df(n=3)
        await store.write("005930", "1m", df)
        await store.write("005930", "1m", df)

        result = await store.read("005930", "1m")
        assert len(result) == 3  # 중복 제거됨

    async def test_read_with_time_filter(self, store):
        df = _make_ohlcv_df(n=10, start="2026-03-01T09:00:00")
        await store.write("005930", "1m", df)

        result = await store.read(
            "005930",
            "1m",
            start="2026-03-01T09:03:00",
            end="2026-03-01T09:07:00",
        )
        assert len(result) == 5

    async def test_read_with_limit(self, store):
        df = _make_ohlcv_df(n=10)
        await store.write("005930", "1m", df)

        result = await store.read("005930", "1m", limit=3)
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
        await store.append("005930", "1m", rows)
        result = await store.read("005930", "1m")
        assert len(result) == 1

    async def test_list_symbols(self, store):
        await store.write("005930", "1d", _make_ohlcv_df("005930"))
        await store.write("000660", "1d", _make_ohlcv_df("000660"))

        symbols = store.list_symbols("1d")
        assert symbols == ["000660", "005930"]

    async def test_list_symbols_empty(self, store):
        assert store.list_symbols("1d") == []

    async def test_get_date_range(self, store):
        await store.write("005930", "1m", _make_ohlcv_df())
        result = store.get_date_range("005930", "1m")
        assert result is not None
        assert result == ("2026-03", "2026-03")

    async def test_get_date_range_none(self, store):
        assert store.get_date_range("999999", "1m") is None

    async def test_get_storage_usage(self, store):
        await store.write("005930", "1d", _make_ohlcv_df())
        usage = store.get_storage_usage()
        assert "1d" in usage
        assert usage["1d"] > 0

    async def test_delete_file(self, store):
        await store.write("005930", "1m", _make_ohlcv_df())
        assert store.delete_file("005930", "1m", "2026-03") is True
        result = await store.read("005930", "1m")
        assert result.is_empty()

    async def test_delete_file_nonexistent(self, store):
        assert store.delete_file("005930", "1m", "2099-01") is False

    async def test_write_empty_df(self, store):
        empty = pl.DataFrame()
        await store.write("005930", "1m", empty)
        result = await store.read("005930", "1m")
        assert result.is_empty()

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
        await store.write("005930", "1m", df)

        march_file = data_dir / "ohlcv" / "1m" / "005930" / "2026-03.parquet"
        april_file = data_dir / "ohlcv" / "1m" / "005930" / "2026-04.parquet"
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
        await store.write("005930", "", df, data_type="fundamental")
        result = await store.read("005930", "", data_type="fundamental")
        assert len(result) == 2
        assert result["market_cap"][0] == 500000000000

    async def test_fundamental_path_structure(self, store, data_dir):
        """fundamental은 {base}/fundamental/krx/{symbol}/ 경로."""
        from datetime import date

        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1)],
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        await store.write("005930", "", df, data_type="fundamental")
        path = data_dir / "fundamental" / "krx" / "005930"
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
        await store.write("005930", "", df, data_type="fundamental")
        symbols = store.list_symbols(data_type="fundamental")
        assert symbols == ["005930"]

    async def test_storage_usage_includes_fundamental(self, store):
        """get_storage_usage가 fundamental 용량도 포함."""
        from datetime import date

        await store.write("005930", "1d", _make_ohlcv_df())
        df = pl.DataFrame(
            {
                "date": [date(2026, 3, 1)],
                "symbol": ["005930"],
                "source": ["dart"],
            }
        )
        await store.write("005930", "", df, data_type="fundamental")
        usage = store.get_storage_usage()
        assert "1d" in usage
        assert "fundamental" in usage

    async def test_ohlcv_default_backward_compat(self, store):
        """data_type 미지정 시 기존 OHLCV 동작 유지."""
        df = _make_ohlcv_df()
        await store.write("005930", "1m", df)
        result = await store.read("005930", "1m")
        assert len(result) == 5


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
        await collector.add_data("005930", "1m", row)
        assert len(collector.buffer["005930:1m"]) == 1

        flushed = await collector.flush_all()
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
            await collector.add_data("005930", "1m", row)

        # buffer_size=2이므로 자동 flush됨
        assert "005930:1m" not in collector.buffer

        result = await store.read("005930", "1m")
        assert len(result) == 2

    async def test_start_and_stop(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus, collect_interval=0.05)

        await collector.start(["005930"], ["1m"])
        assert collector.running is True

        await asyncio.sleep(0.02)
        await collector.stop()
        assert collector.running is False

    async def test_start_twice_ignored(self, store):
        from unittest.mock import AsyncMock

        eventbus = AsyncMock()
        collector = DataCollector(store=store, eventbus=eventbus)

        await collector.start(["005930"], ["1m"])
        await collector.start(["005930"], ["1m"])  # 두 번째 호출은 무시
        assert collector.running is True

        await collector.stop()

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
        await collector.start(["005930"], ["1m"])
        await asyncio.sleep(0.1)
        await collector.stop()

        result = await store.read("005930", "1m")
        assert len(result) >= 1


# ── injector.py 테스트 ─────────────────────────────


class TestDataInjector:
    async def test_inject_csv(self, store, normalizer, tmp_path):
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(
            "date,open,high,low,close,volume\n"
            "2026-03-01T09:00:00,50000,50100,49900,50050,1000\n"
            "2026-03-01T09:01:00,50100,50200,50000,50150,1100\n"
        )

        injector = DataInjector(store=store, normalizer=normalizer)
        count = await injector.inject_csv(csv_path, "005930", "1m")
        assert count == 2

        result = await store.read("005930", "1m")
        assert len(result) == 2

    async def test_inject_csv_not_found(self, store, normalizer):
        injector = DataInjector(store=store, normalizer=normalizer)
        with pytest.raises(FileNotFoundError):
            await injector.inject_csv("/nonexistent.csv", "005930", "1m")

    async def test_inject_dataframe(self, store, normalizer):
        df = _make_ohlcv_df(n=3)
        injector = DataInjector(store=store, normalizer=normalizer)
        count = await injector.inject_dataframe(df, "005930", "1m")
        assert count == 3

    async def test_inject_empty_dataframe(self, store, normalizer):
        injector = DataInjector(store=store, normalizer=normalizer)
        count = await injector.inject_dataframe(pl.DataFrame(), "005930", "1m")
        assert count == 0


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
        await store.write("005930", "1m", _make_ohlcv_df())

        # 1분봉 보존 기간을 0일로 설정 → 모든 데이터 삭제 대상
        policy = RetentionPolicy(store, retention_days={"1m": 0})
        now = datetime(2026, 6, 1, tzinfo=UTC)
        deleted = await policy.enforce(now=now)

        assert "1m" in deleted
        assert deleted["1m"] >= 1

        result = await store.read("005930", "1m")
        assert result.is_empty()

    async def test_enforce_keeps_recent_data(self, store):
        """보존 기간 내 데이터는 유지."""
        await store.write("005930", "1m", _make_ohlcv_df())

        policy = RetentionPolicy(store, retention_days={"1m": 365})
        now = datetime(2026, 3, 15, tzinfo=UTC)
        deleted = await policy.enforce(now=now)

        # 2026-03 데이터는 15일 전이므로 삭제 안 됨
        assert deleted == {}
        result = await store.read("005930", "1m")
        assert len(result) == 5

    async def test_enforce_skips_negative_retention(self, store):
        """보존 기간이 -1(무기한)이면 삭제하지 않는다."""
        await store.write("005930", "1m", _make_ohlcv_df())
        policy = RetentionPolicy(store, retention_days={"1m": -1})
        now = datetime(2099, 1, 1, tzinfo=UTC)
        deleted = await policy.enforce(now=now)
        assert deleted == {}
        result = await store.read("005930", "1m")
        assert len(result) == 5

    async def test_enforce_empty_store(self, store):
        policy = RetentionPolicy(store)
        deleted = await policy.enforce()
        assert deleted == {}
