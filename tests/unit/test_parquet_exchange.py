"""Parquet 경로 exchange 차원 추가 테스트."""

from __future__ import annotations

from datetime import UTC
from pathlib import Path

import polars as pl
import pytest

from ante.data.store import ParquetStore, migrate_parquet_paths


def _is_case_sensitive_fs() -> bool:
    """현재 파일시스템이 대소문자를 구분하는지 검사."""
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        test_dir = Path(td) / "CaSe"
        test_dir.mkdir()
        return not (Path(td) / "case").exists()


@pytest.fixture
def tmp_store(tmp_path: Path) -> ParquetStore:
    """임시 디렉토리 기반 ParquetStore."""
    return ParquetStore(base_path=tmp_path)


def _make_ohlcv_df(
    symbol: str = "005930",
    n: int = 3,
    start: str = "2026-01-01T09:00:00",
) -> pl.DataFrame:
    """테스트용 OHLCV DataFrame 생성."""
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(start).replace(tzinfo=UTC)
    timestamps = [base + timedelta(days=i) for i in range(n)]
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": [symbol] * n,
            "open": [50000.0 + i * 100 for i in range(n)],
            "high": [51000.0 + i * 100 for i in range(n)],
            "low": [49000.0 + i * 100 for i in range(n)],
            "close": [50500.0 + i * 100 for i in range(n)],
            "volume": [1000000 + i * 10000 for i in range(n)],
            "amount": [50000000000 + i * 100000000 for i in range(n)],
            "source": ["test"] * n,
        }
    )


class TestResolvePathWithExchange:
    """_resolve_path에 exchange 차원이 포함되는지 검증."""

    def test_ohlcv_path_includes_exchange(self, tmp_store: ParquetStore) -> None:
        """OHLCV 경로: {base}/ohlcv/{timeframe}/{exchange}/{symbol}/"""
        path = tmp_store._resolve_path("005930", "1d", "ohlcv", "KRX")
        assert path == tmp_store.base_path / "ohlcv" / "1d" / "KRX" / "005930"

    def test_ohlcv_path_nyse(self, tmp_store: ParquetStore) -> None:
        """NYSE 거래소 경로 생성."""
        path = tmp_store._resolve_path("AAPL", "1d", "ohlcv", "NYSE")
        assert path == tmp_store.base_path / "ohlcv" / "1d" / "NYSE" / "AAPL"

    def test_fundamental_path_includes_exchange(self, tmp_store: ParquetStore) -> None:
        """Fundamental 경로: {base}/fundamental/{exchange}/{symbol}/"""
        path = tmp_store._resolve_path("005930", "", "fundamental", "KRX")
        assert path == tmp_store.base_path / "fundamental" / "KRX" / "005930"

    def test_tick_path_includes_exchange(self, tmp_store: ParquetStore) -> None:
        """Tick 경로: {base}/tick/{exchange}/{symbol}/"""
        path = tmp_store._resolve_path("005930", "", "tick", "KRX")
        assert path == tmp_store.base_path / "tick" / "KRX" / "005930"

    def test_default_exchange_is_krx(self, tmp_store: ParquetStore) -> None:
        """exchange 기본값은 KRX."""
        path = tmp_store._resolve_path("005930", "1d")
        assert "KRX" in path.parts


class TestReadWriteWithExchange:
    """exchange 파라미터를 사용한 읽기/쓰기 검증."""

    def test_write_creates_exchange_directory(
        self, tmp_store: ParquetStore, tmp_path: Path
    ) -> None:
        """write 시 exchange 디렉토리가 생성된다."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df)
        assert (tmp_path / "ohlcv" / "1d" / "KRX" / "005930").exists()

    def test_write_and_read_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange 파라미터로 쓰고 읽기."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df, exchange="KRX")
        result = tmp_store.read("005930", "1d", exchange="KRX")
        assert len(result) == 3

    def test_different_exchanges_are_isolated(self, tmp_store: ParquetStore) -> None:
        """서로 다른 거래소의 데이터는 격리된다."""
        df_krx = _make_ohlcv_df(symbol="005930")
        df_nyse = _make_ohlcv_df(symbol="AAPL")
        tmp_store.write("005930", "1d", df_krx, exchange="KRX")
        tmp_store.write("AAPL", "1d", df_nyse, exchange="NYSE")

        result_krx = tmp_store.read("005930", "1d", exchange="KRX")
        result_nyse = tmp_store.read("AAPL", "1d", exchange="NYSE")
        result_empty = tmp_store.read("005930", "1d", exchange="NYSE")

        assert len(result_krx) == 3
        assert len(result_nyse) == 3
        assert result_empty.is_empty()

    def test_list_symbols_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange별 종목 목록 조회."""
        df1 = _make_ohlcv_df(symbol="005930")
        df2 = _make_ohlcv_df(symbol="000660")
        df3 = _make_ohlcv_df(symbol="AAPL")
        tmp_store.write("005930", "1d", df1, exchange="KRX")
        tmp_store.write("000660", "1d", df2, exchange="KRX")
        tmp_store.write("AAPL", "1d", df3, exchange="NYSE")

        krx_symbols = tmp_store.list_symbols("1d", exchange="KRX")
        nyse_symbols = tmp_store.list_symbols("1d", exchange="NYSE")

        assert krx_symbols == ["000660", "005930"]
        assert nyse_symbols == ["AAPL"]

    def test_append_with_exchange(self, tmp_store: ParquetStore) -> None:
        """append도 exchange 경로를 사용한다."""
        from datetime import datetime

        rows = [
            {
                "timestamp": datetime(2026, 1, 1, 9, 0, tzinfo=UTC),
                "symbol": "005930",
                "open": 50000.0,
                "high": 51000.0,
                "low": 49000.0,
                "close": 50500.0,
                "volume": 1000000,
                "amount": 50000000000,
                "source": "test",
            }
        ]
        tmp_store.append("005930", "1m", rows, exchange="KRX")
        result = tmp_store.read("005930", "1m", exchange="KRX")
        assert len(result) == 1

    def test_get_date_range_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange별 데이터 기간 조회."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df, exchange="KRX")
        result = tmp_store.get_date_range("005930", "1d", exchange="KRX")
        assert result is not None
        assert result[0] == "2026-01"

    def test_get_row_count_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange별 행 수 조회."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df, exchange="KRX")
        count = tmp_store.get_row_count("005930", "1d", exchange="KRX")
        assert count == 3

    def test_delete_file_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange 경로에서 파일 삭제."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df, exchange="KRX")
        result = tmp_store.delete_file("005930", "1d", "2026-01", exchange="KRX")
        assert result is True
        remaining = tmp_store.read("005930", "1d", exchange="KRX")
        assert remaining.is_empty()

    def test_validate_with_exchange(self, tmp_store: ParquetStore) -> None:
        """exchange 경로에서 검증."""
        df = _make_ohlcv_df()
        tmp_store.write("005930", "1d", df, exchange="KRX")
        result = tmp_store.validate("005930", "1d", exchange="KRX")
        assert result["total"] == 1
        assert result["valid"] == 1


class TestMigrateParquetPaths:
    """기존 경로 → exchange 포함 경로 마이그레이션 검증."""

    def test_migrate_ohlcv_to_krx(self, tmp_path: Path) -> None:
        """기존 ohlcv/{tf}/{symbol}/ → ohlcv/{tf}/KRX/{symbol}/."""
        old_path = tmp_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 1
        assert not old_path.exists()
        new_path = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").exists()

    def test_migrate_multiple_timeframes(self, tmp_path: Path) -> None:
        """여러 타임프레임의 데이터를 모두 마이그레이션한다."""
        for tf in ("1d", "1m", "5m"):
            old_path = tmp_path / "ohlcv" / tf / "005930"
            old_path.mkdir(parents=True)
            (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 3
        for tf in ("1d", "1m", "5m"):
            new_path = tmp_path / "ohlcv" / tf / "KRX" / "005930"
            assert new_path.exists()

    def test_migrate_skips_existing_exchange_dir(self, tmp_path: Path) -> None:
        """이미 exchange 디렉토리가 있으면 스킵."""
        krx_path = tmp_path / "ohlcv" / "1d" / "KRX" / "005930"
        krx_path.mkdir(parents=True)
        (krx_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 0
        assert krx_path.exists()

    def test_migrate_skips_non_krx_symbol_format(self, tmp_path: Path) -> None:
        """6자리 숫자가 아닌 심볼은 마이그레이션하지 않는다."""
        old_path = tmp_path / "ohlcv" / "1d" / "AAPL"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        # AAPL은 6자리 숫자가 아니므로 스킵
        assert moved == 0
        assert old_path.exists()

    @pytest.mark.skipif(
        not _is_case_sensitive_fs(),
        reason="case-insensitive FS에서는 krx == KRX이므로 마이그레이션 불필요",
    )
    def test_migrate_fundamental_krx_lowercase(self, tmp_path: Path) -> None:
        """fundamental/krx/ → fundamental/KRX/ 마이그레이션 (case-sensitive FS)."""
        old_path = tmp_path / "fundamental" / "krx" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 1
        new_path = tmp_path / "fundamental" / "KRX" / "005930"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").exists()

    @pytest.mark.skipif(
        not _is_case_sensitive_fs(),
        reason="case-insensitive FS에서는 krx == KRX이므로 마이그레이션 불필요",
    )
    def test_migrate_tick_krx_lowercase(self, tmp_path: Path) -> None:
        """tick/krx/ → tick/KRX/ 마이그레이션 (case-sensitive FS)."""
        old_path = tmp_path / "tick" / "krx" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-03-12.parquet").write_bytes(b"dummy")

        moved = migrate_parquet_paths(tmp_path)

        assert moved == 1
        new_path = tmp_path / "tick" / "KRX" / "005930"
        assert new_path.exists()

    def test_migrate_returns_zero_on_empty(self, tmp_path: Path) -> None:
        """데이터 디렉토리가 비어있으면 0 반환."""
        moved = migrate_parquet_paths(tmp_path)
        assert moved == 0

    def test_migrate_idempotent(self, tmp_path: Path) -> None:
        """마이그레이션은 멱등이다. 두 번 실행해도 안전."""
        old_path = tmp_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy")

        moved1 = migrate_parquet_paths(tmp_path)
        moved2 = migrate_parquet_paths(tmp_path)

        assert moved1 == 1
        assert moved2 == 0

    def test_migrate_preserves_data(self, tmp_path: Path) -> None:
        """마이그레이션 후 데이터가 보존된다."""
        # 기존 경로에 직접 데이터 생성 (마이그레이션 전)
        old_path = tmp_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        df = _make_ohlcv_df()
        df.write_parquet(str(old_path / "2026-01.parquet"))

        migrate_parquet_paths(tmp_path)

        # 마이그레이션 후 새 경로로 읽기
        store_after = ParquetStore(base_path=tmp_path)
        result = store_after.read("005930", "1d", exchange="KRX")
        assert len(result) == 3
