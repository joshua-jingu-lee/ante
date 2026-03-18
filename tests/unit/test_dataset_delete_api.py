"""데이터셋 API 테스트 — 목록 조회(페이지네이션·필터) 및 삭제."""

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


class TestListDatasets:
    """GET /api/data/datasets — 응답 형식·필드·페이지네이션·필터 검증."""

    async def test_response_wrapper_format(self, client, store):
        """응답이 {items, total} 래퍼를 사용한다."""
        await store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
        assert body["total"] == 1
        assert len(body["items"]) == 1

    async def test_field_names(self, client, store):
        """각 데이터셋에 id, start_date, end_date, row_count 필드가 있다."""
        await store.write("005930", "1d", _make_ohlcv_df())
        resp = client.get("/api/data/datasets")
        ds = resp.json()["items"][0]
        assert ds["id"] == "005930__1d"
        assert ds["symbol"] == "005930"
        assert ds["timeframe"] == "1d"
        assert "start_date" in ds
        assert "end_date" in ds
        assert isinstance(ds["row_count"], int)
        assert ds["row_count"] > 0

    async def test_pagination(self, client, store):
        """offset/limit 파라미터로 페이지네이션이 동작한다."""
        for sym in ["000010", "000020", "000030"]:
            await store.write(sym, "1d", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"offset": 0, "limit": 2})
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2

        resp2 = client.get("/api/data/datasets", params={"offset": 2, "limit": 2})
        body2 = resp2.json()
        assert body2["total"] == 3
        assert len(body2["items"]) == 1

    async def test_filter_by_symbol(self, client, store):
        """symbol 필터로 특정 종목만 반환한다."""
        await store.write("005930", "1d", _make_ohlcv_df())
        await store.write("035720", "1d", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"symbol": "005930"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["symbol"] == "005930"

    async def test_filter_by_timeframe(self, client, store):
        """timeframe 필터로 특정 타임프레임만 반환한다."""
        await store.write("005930", "1d", _make_ohlcv_df())
        await store.write("005930", "1h", _make_ohlcv_df())

        resp = client.get("/api/data/datasets", params={"timeframe": "1d"})
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["timeframe"] == "1d"

    def test_empty_store(self, client):
        """데이터가 없으면 빈 목록과 total=0을 반환한다."""
        resp = client.get("/api/data/datasets")
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


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
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0


class TestFundamentalDatasets:
    """fundamental 데이터 유형 API 테스트."""

    async def test_list_fundamental_datasets(self, client, store):
        """fundamental 데이터셋 목록 조회."""
        await store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["items"]) == 1
        ds = body["items"][0]
        assert ds["symbol"] == "005930"
        assert ds["data_type"] == "fundamental"

    async def test_list_ohlcv_excludes_fundamental(self, client, store):
        """OHLCV 조회 시 fundamental 데이터가 포함되지 않음."""
        await store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.get("/api/data/datasets", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    async def test_delete_fundamental_dataset(self, client, store):
        """fundamental 데이터셋 삭제."""
        await store.write("005930", "", _make_fundamental_df(), data_type="fundamental")
        resp = client.delete(
            "/api/data/datasets/005930__fundamental",
            params={"data_type": "fundamental"},
        )
        assert resp.status_code == 204

        # 삭제 후 목록에서 제거 확인
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.json()["items"] == []

    def test_schema_fundamental(self, client):
        """fundamental 스키마 조회."""
        resp = client.get("/api/data/schema", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert "per" in data
        assert "pbr" in data
        assert "market_cap" in data
