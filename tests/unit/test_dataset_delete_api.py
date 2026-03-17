"""데이터셋 삭제 API 테스트."""

from __future__ import annotations

from datetime import datetime

import polars as pl
import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.data.store import ParquetStore  # noqa: E402
from ante.web.app import create_app  # noqa: E402


def _make_ohlcv_df() -> pl.DataFrame:
    timestamps = pl.datetime_range(
        datetime(2026, 3, 1, 9, 0),
        datetime(2026, 3, 1, 9, 2),
        interval="1m",
        eager=True,
        time_zone="UTC",
    )
    n = len(timestamps)
    return pl.DataFrame(
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


@pytest.fixture
def store(tmp_path):
    return ParquetStore(base_path=tmp_path / "data")


@pytest.fixture
def client(store):
    app = create_app(data_store=store)
    return TestClient(app)


class TestDeleteDataset:
    async def test_delete_success(self, client, store):
        """데이터셋 삭제 성공."""
        await store.write("005930", "1d", _make_ohlcv_df())
        resp = client.delete("/api/data/datasets/005930__1d")
        assert resp.status_code == 204

    def test_delete_nonexistent(self, client):
        """존재하지 않는 데이터셋 → 404."""
        resp = client.delete("/api/data/datasets/999999__1d")
        assert resp.status_code == 404

    def test_delete_invalid_id_format(self, client):
        """잘못된 dataset_id 형식 → 400."""
        resp = client.delete("/api/data/datasets/invalid_format")
        assert resp.status_code == 400

    async def test_datasets_empty_after_delete(self, client, store):
        """삭제 후 목록에서 제거 확인."""
        await store.write("005930", "1d", _make_ohlcv_df())
        client.delete("/api/data/datasets/005930__1d")
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        assert resp.json()["datasets"] == []
