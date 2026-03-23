"""GET /api/data/datasets/{dataset_id} 데이터셋 상세 API 테스트."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.data.store import ParquetStore  # noqa: E402
from ante.web.app import create_app  # noqa: E402


def _make_ohlcv_df(n: int = 10) -> pl.DataFrame:
    timestamps = pl.datetime_range(
        datetime(2026, 3, 1, 9, 0),
        datetime(2026, 3, 1, 9, n - 1),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    count = len(timestamps)
    return pl.DataFrame(
        {
            "timestamp": timestamps,
            "symbol": ["005930"] * count,
            "open": [50000.0 + i for i in range(count)],
            "high": [50100.0] * count,
            "low": [49900.0] * count,
            "close": [50050.0] * count,
            "volume": [1000] * count,
            "source": ["test"] * count,
        }
    )


def _make_fundamental_df() -> pl.DataFrame:
    from datetime import date

    return pl.DataFrame(
        {
            "date": [date(2026, 3, 1), date(2026, 3, 2)],
            "symbol": ["005930", "005930"],
            "market_cap": [400_000_000_000, 401_000_000_000],
            "per": [12.5, 12.6],
            "pbr": [1.2, 1.3],
            "source": ["test", "test"],
        }
    )


@pytest.fixture
def store(tmp_path):
    return ParquetStore(base_path=tmp_path / "data")


@pytest.fixture
def client(store):
    app = create_app(data_store=store)
    return TestClient(app)


class TestDatasetDetail:
    """GET /api/data/datasets/{dataset_id} 상세 조회 테스트."""

    async def test_basic_response_structure(self, client, store):
        """응답이 dataset + preview 구조를 갖는다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        assert resp.status_code == 200
        body = resp.json()
        assert "dataset" in body
        assert "preview" in body

    async def test_metadata_fields(self, client, store):
        """메타데이터에 필수 필드가 모두 포함된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        ds = resp.json()["dataset"]
        assert ds["id"] == "005930__1d"
        assert ds["symbol"] == "005930"
        assert ds["timeframe"] == "1d"
        assert ds["data_type"] == "ohlcv"
        assert ds["start_date"] is not None
        assert ds["end_date"] is not None
        assert isinstance(ds["row_count"], int)
        assert ds["row_count"] > 0

    async def test_preview_limit_5(self, client, store):
        """미리보기는 최대 5행을 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df(n=10))
        resp = client.get("/api/data/datasets/005930__1d")
        preview = resp.json()["preview"]
        assert len(preview) == 5

    async def test_preview_less_than_5(self, client, store):
        """데이터가 5행 미만이면 전체를 반환한다."""
        store.write("005930", "1d", _make_ohlcv_df(n=3))
        resp = client.get("/api/data/datasets/005930__1d")
        preview = resp.json()["preview"]
        assert len(preview) == 3

    async def test_preview_contains_ohlcv_fields(self, client, store):
        """미리보기 행에 OHLCV 필드가 포함된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        row = resp.json()["preview"][0]
        for field in ("timestamp", "open", "high", "low", "close", "volume"):
            assert field in row, f"missing field: {field}"

    async def test_preview_serializes_datetime(self, client, store):
        """datetime이 ISO 문자열로 직렬화된다."""
        store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets/005930__1d")
        row = resp.json()["preview"][0]
        assert isinstance(row["timestamp"], str)

    def test_not_found(self, client):
        """존재하지 않는 dataset_id는 404를 반환한다."""
        resp = client.get("/api/data/datasets/999999__1d")
        assert resp.status_code == 404

    def test_invalid_id_format(self, client):
        """잘못된 dataset_id 형식은 400을 반환한다."""
        resp = client.get("/api/data/datasets/invalid_format")
        assert resp.status_code == 400

    def test_store_unavailable(self):
        """store가 None이면 503을 반환한다."""
        app = create_app(data_store=None)
        c = TestClient(app)
        resp = c.get("/api/data/datasets/005930__1d")
        assert resp.status_code == 503

    async def test_fundamental_dataset_detail(self, client, store):
        """fundamental 데이터셋 상세 조회."""
        store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets/005930__fundamental")
        assert resp.status_code == 200
        body = resp.json()
        assert body["dataset"]["data_type"] == "fundamental"
        assert body["dataset"]["symbol"] == "005930"
        assert len(body["preview"]) > 0
