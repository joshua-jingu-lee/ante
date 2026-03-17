"""FeedInjector 단위 테스트.

ante.data.injector.DataInjector에서 ante.feed.injector.FeedInjector로 이관된
주입 기능을 검증한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import pytest

from ante.data.normalizer import DataNormalizer
from ante.data.store import ParquetStore
from ante.feed.injector import FeedInjector

# ── Fixtures ─────────────────────────────────────────


@pytest.fixture
def data_dir(tmp_path):
    """테스트용 데이터 디렉토리."""
    return tmp_path / "data"


@pytest.fixture
def store(data_dir):
    """ParquetStore 인스턴스."""
    return ParquetStore(base_path=data_dir)


@pytest.fixture
def normalizer():
    """DataNormalizer 인스턴스."""
    return DataNormalizer()


@pytest.fixture
def injector(store, normalizer):
    """FeedInjector 인스턴스."""
    return FeedInjector(store=store, normalizer=normalizer)


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


# ── CSV 주입 테스트 ─────────────────────────────────


class TestFeedInjectorCSV:
    """CSV 파일 주입 테스트."""

    async def test_inject_csv(self, injector, store, tmp_path):
        """CSV 파일에서 데이터를 주입한다."""
        csv_path = tmp_path / "test.csv"
        csv_path.write_text(
            "date,open,high,low,close,volume\n"
            "2026-03-01T09:00:00,50000,50100,49900,50050,1000\n"
            "2026-03-01T09:01:00,50100,50200,50000,50150,1100\n"
        )

        count = await injector.inject_csv(csv_path, "005930", "1m")
        assert count == 2

        result = await store.read("005930", "1m")
        assert len(result) == 2

    async def test_inject_csv_not_found(self, injector):
        """존재하지 않는 CSV 파일은 FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            await injector.inject_csv("/nonexistent.csv", "005930", "1m")

    async def test_inject_csv_empty(self, injector, tmp_path):
        """빈 CSV 파일은 0행 반환."""
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("date,open,high,low,close,volume\n")

        count = await injector.inject_csv(csv_path, "005930", "1d")
        assert count == 0

    async def test_inject_csv_default_timeframe(self, injector, store, tmp_path):
        """timeframe 미지정 시 기본값 '1d' 사용."""
        csv_path = tmp_path / "daily.csv"
        csv_path.write_text(
            "date,open,high,low,close,volume\n"
            "2026-03-01T00:00:00,50000,50100,49900,50050,1000\n"
        )

        count = await injector.inject_csv(csv_path, "005930")
        assert count == 1

        result = await store.read("005930", "1d")
        assert len(result) == 1


# ── DataFrame 주입 테스트 ─────────────────────────────


class TestFeedInjectorDataFrame:
    """DataFrame 직접 주입 테스트."""

    async def test_inject_dataframe(self, injector, store):
        """DataFrame을 직접 주입한다."""
        df = _make_ohlcv_df(n=3)
        count = await injector.inject_dataframe(df, "005930", "1m")
        assert count == 3

        result = await store.read("005930", "1m")
        assert len(result) == 3

    async def test_inject_empty_dataframe(self, injector):
        """빈 DataFrame은 0행 반환."""
        count = await injector.inject_dataframe(pl.DataFrame(), "005930", "1m")
        assert count == 0

    async def test_inject_dataframe_adds_symbol(self, injector, store):
        """symbol 컬럼이 없는 DataFrame에 symbol을 추가한다."""
        df = pl.DataFrame(
            {
                "timestamp": pl.datetime_range(
                    datetime(2026, 3, 1, 9, 0),
                    datetime(2026, 3, 1, 9, 2),
                    interval="1m",
                    eager=True,
                    time_zone="UTC",
                ),
                "open": [50000.0, 50100.0, 50200.0],
                "high": [50100.0, 50200.0, 50300.0],
                "low": [49900.0, 50000.0, 50100.0],
                "close": [50050.0, 50150.0, 50250.0],
                "volume": [1000, 1100, 1200],
                "source": ["test"] * 3,
            }
        )
        count = await injector.inject_dataframe(df, "005930", "1m")
        assert count == 3

        result = await store.read("005930", "1m")
        assert result["symbol"][0] == "005930"

    async def test_inject_dataframe_adds_source(self, injector, store):
        """source 컬럼이 없는 DataFrame에 source를 추가한다."""
        df = _make_ohlcv_df(n=2).drop("source")
        count = await injector.inject_dataframe(df, "005930", "1m", source="custom")
        assert count == 2


# ── 4계층 검증 통합 테스트 ───────────────────────────


class TestFeedInjectorValidation:
    """FeedInjector의 4계층 검증 통합 테스트."""

    async def test_schema_validation_passes(self, injector, store):
        """올바른 스키마의 DataFrame은 검증을 통과한다."""
        df = _make_ohlcv_df(n=2)
        count = await injector.inject_dataframe(df, "005930", "1m")
        assert count == 2

    async def test_business_validation_warnings_allow_storage(self, injector, store):
        """비즈니스 검증 경고가 있어도 저장은 허용된다."""
        # low > close (비즈니스 규칙 위반이지만 경고)
        df = pl.DataFrame(
            {
                "timestamp": [datetime(2026, 3, 1, 9, 0, tzinfo=UTC)],
                "symbol": ["005930"],
                "open": [50000.0],
                "high": [51000.0],
                "low": [50500.0],  # low > close
                "close": [50000.0],
                "volume": [1000],
                "source": ["test"],
            }
        )
        count = await injector.inject_dataframe(df, "005930", "1m")
        assert count == 1

        result = await store.read("005930", "1m")
        assert len(result) == 1
