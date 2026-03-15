"""데이터셋 삭제 API 테스트."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


class FakeCatalog:
    """테스트용 DataCatalog stub."""

    def __init__(self) -> None:
        self._datasets: dict[str, dict] = {}

    def list_datasets(self) -> list[dict]:
        return list(self._datasets.values())

    def delete_dataset(self, symbol: str, timeframe: str) -> bool:
        key = f"{symbol}__{timeframe}"
        if key in self._datasets:
            del self._datasets[key]
            return True
        return False

    def get_schema(self) -> dict:
        return {}

    def get_storage_summary(self) -> dict:
        return {"total_bytes": 0, "total_mb": 0.0, "by_timeframe": {}}


@pytest.fixture
def catalog():
    return FakeCatalog()


@pytest.fixture
def client(catalog):
    app = create_app(data_catalog=catalog)
    return TestClient(app)


class TestDeleteDataset:
    def test_delete_success(self, client, catalog):
        """데이터셋 삭제 성공."""
        catalog._datasets["005930__1d"] = {
            "symbol": "005930",
            "timeframe": "1d",
            "start": "2025-01",
            "end": "2025-03",
        }
        resp = client.delete("/api/data/datasets/005930__1d")
        assert resp.status_code == 204
        assert "005930__1d" not in catalog._datasets

    def test_delete_nonexistent(self, client):
        """존재하지 않는 데이터셋 → 404."""
        resp = client.delete("/api/data/datasets/999999__1d")
        assert resp.status_code == 404

    def test_delete_invalid_id_format(self, client):
        """잘못된 dataset_id 형식 → 400."""
        resp = client.delete("/api/data/datasets/invalid_format")
        assert resp.status_code == 400

    def test_datasets_empty_after_delete(self, client, catalog):
        """삭제 후 목록에서 제거 확인."""
        catalog._datasets["005930__1d"] = {
            "symbol": "005930",
            "timeframe": "1d",
        }
        client.delete("/api/data/datasets/005930__1d")
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        assert resp.json()["datasets"] == []
