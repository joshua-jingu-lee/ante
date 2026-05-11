"""data_type Query 파라미터 검증 테스트 (#1354).

`/api/data/schema`와 `/api/data/datasets`는 enum SSOT (DATA_TYPES)에 정의된
`ohlcv` / `fundamental`만 허용해야 한다. 그 외 값은 422로 거부된다.

Default 동작:
- `get_data_schema`: data_type 미지정 시 OHLCV schema 반환.
- `list_datasets`: data_type 미지정 시 전체 (ohlcv + fundamental) 반환.
"""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402
from tests.unit.conftest import (  # noqa: E402
    make_authed_client,
    make_master_member_service,
)


@pytest.fixture
def client() -> TestClient:
    return make_authed_client(create_app(member_service=make_master_member_service()))


# ── /api/data/schema ─────────────────────────────────────


class TestDataSchemaValidation:
    def test_schema_ohlcv_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/data/schema", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        data = resp.json()
        # OHLCV schema 키 확인
        assert "timestamp" in data
        assert "open" in data
        assert "high" in data
        assert "low" in data
        assert "close" in data
        assert "volume" in data

    def test_schema_fundamental_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/data/schema", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        data = resp.json()
        # FUNDAMENTAL schema 키 확인
        assert "date" in data
        assert "per" in data
        assert "pbr" in data

    def test_schema_invalid_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/data/schema", params={"data_type": "oracle_invalid_type"}
        )
        assert resp.status_code == 422

    def test_schema_empty_string_returns_422(self, client: TestClient) -> None:
        resp = client.get("/api/data/schema", params={"data_type": ""})
        assert resp.status_code == 422

    def test_schema_default_returns_ohlcv(self, client: TestClient) -> None:
        resp = client.get("/api/data/schema")
        assert resp.status_code == 200
        data = resp.json()
        # OHLCV schema 키 (생략 시 default = ohlcv)
        assert "timestamp" in data
        assert "open" in data
        assert "close" in data
        # FUNDAMENTAL 전용 키는 없어야 한다
        assert "per" not in data
        assert "pbr" not in data


# ── /api/data/datasets ───────────────────────────────────


class TestDatasetsListValidation:
    def test_datasets_ohlcv_returns_200(self, client: TestClient) -> None:
        resp = client.get("/api/data/datasets", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body

    def test_datasets_invalid_returns_422(self, client: TestClient) -> None:
        resp = client.get(
            "/api/data/datasets",
            params={"data_type": "oracle_invalid_type"},
        )
        assert resp.status_code == 422

    def test_datasets_default_returns_all(self, client: TestClient) -> None:
        # data_type 생략 시 전체 (ohlcv + fundamental) 모드 - 200 응답.
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert "items" in body
        assert "total" in body
