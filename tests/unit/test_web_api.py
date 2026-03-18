"""Web API 모듈 단위 테스트."""

from __future__ import annotations

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
def client(app):
    return TestClient(app)


# ── System 라우트 테스트 ──────────────────────────


class TestSystemRoutes:
    def test_status(self, client):
        resp = client.get("/api/system/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "running"
        assert data["version"] == "0.1.0"

    def test_health(self, client):
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ── Strategy 라우트 테스트 ────────────────────────


class TestStrategyRoutes:
    def test_validate_valid(self, client, tmp_path):
        code = """
from ante.strategy.base import Strategy, StrategyMeta, Signal

class TestStrategy(Strategy):
    meta = StrategyMeta(name="test", version="1.0", description="t")
    async def on_step(self, context):
        return []
"""
        path = tmp_path / "good.py"
        path.write_text(code)

        resp = client.post(
            "/api/strategies/validate",
            json={"path": str(path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True

    def test_validate_invalid(self, client, tmp_path):
        path = tmp_path / "bad.py"
        path.write_text("import os\nprint('not a strategy')")

        resp = client.post(
            "/api/strategies/validate",
            json={"path": str(path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is False

    def test_validate_missing_path(self, client):
        resp = client.post(
            "/api/strategies/validate",
            json={},
        )
        assert resp.status_code == 400
        data = resp.json()
        assert data["type"] == "/errors/validation"
        assert data["status"] == 400

    def test_validate_nonexistent_file(self, client):
        resp = client.post(
            "/api/strategies/validate",
            json={"path": "/nonexistent.py"},
        )
        assert resp.status_code == 404
        data = resp.json()
        assert data["type"] == "/errors/not-found"
        assert data["status"] == 404


# ── Data 라우트 테스트 ────────────────────────────


class TestDataRoutes:
    def test_datasets_no_catalog(self, client):
        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        body = resp.json()
        assert body["datasets"] == []
        assert body["data_type"] == "ohlcv"

    def test_datasets_no_catalog_fundamental(self, client):
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["datasets"] == []
        assert body["data_type"] == "fundamental"

    def test_schema_no_catalog(self, client):
        resp = client.get("/api/data/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert "timestamp" in data

    def test_schema_fundamental(self, client):
        resp = client.get("/api/data/schema", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        data = resp.json()
        assert "date" in data
        assert "per" in data
        assert "pbr" in data

    def test_storage_no_catalog(self, client):
        resp = client.get("/api/data/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_bytes"] == 0

    def test_datasets_with_store(self, tmp_path):
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        assert isinstance(resp.json()["datasets"], list)

    def test_datasets_with_store_data_type_ohlcv(self, tmp_path):
        """data_type=ohlcv 파라미터로 OHLCV 데이터셋만 반환."""
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/datasets", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_type"] == "ohlcv"
        for ds in body["datasets"]:
            assert ds["data_type"] == "ohlcv"

    def test_datasets_with_store_data_type_fundamental(self, tmp_path):
        """data_type=fundamental 파라미터로 fundamental 데이터셋만 반환."""
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["data_type"] == "fundamental"
        for ds in body["datasets"]:
            assert ds["data_type"] == "fundamental"

    def test_storage_with_store(self, tmp_path):
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/storage")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_mb" in data

    def test_feed_status_no_store(self, client):
        resp = client.get("/api/data/feed-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initialized"] is False
        assert data["checkpoints"] == []
        assert data["recent_reports"] == []
        assert data["api_keys"] == []

    def test_feed_status_not_initialized(self, tmp_path):
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/feed-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initialized"] is False
        assert isinstance(data["api_keys"], list)

    def test_feed_status_initialized(self, tmp_path):
        import json

        from ante.data.store import ParquetStore
        from ante.feed.config import FeedConfig

        data_path = tmp_path / "data"
        store = ParquetStore(base_path=data_path)
        config = FeedConfig(data_path)
        config.init()

        # 체크포인트 생성
        cp_dir = config.feed_dir / "checkpoints"
        cp_dir.mkdir(parents=True, exist_ok=True)
        (cp_dir / "data_go_kr_ohlcv.json").write_text(
            json.dumps(
                {
                    "source": "data_go_kr",
                    "data_type": "ohlcv",
                    "last_date": "2026-03-17",
                    "updated_at": "2026-03-17T16:00:00Z",
                }
            )
        )

        # 리포트 생성
        rpt_dir = config.feed_dir / "reports"
        rpt_dir.mkdir(parents=True, exist_ok=True)
        (rpt_dir / "2026-03-17-daily.json").write_text(
            json.dumps(
                {
                    "mode": "daily",
                    "started_at": "2026-03-17T16:00:12Z",
                    "finished_at": "2026-03-17T16:05:34Z",
                    "duration_seconds": 322,
                    "target_date": "2026-03-16",
                    "summary": {
                        "symbols_total": 2487,
                        "symbols_success": 2485,
                        "symbols_failed": 2,
                        "rows_written": 2485,
                        "data_types": ["ohlcv", "fundamental"],
                    },
                    "failures": [],
                    "warnings": [],
                    "config_errors": [],
                }
            )
        )

        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/feed-status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["initialized"] is True
        assert len(data["checkpoints"]) == 1
        assert data["checkpoints"][0]["source"] == "data_go_kr"
        assert data["checkpoints"][0]["last_date"] == "2026-03-17"
        assert len(data["recent_reports"]) == 1
        assert data["recent_reports"][0]["mode"] == "daily"
        assert isinstance(data["api_keys"], list)


# ── Report 라우트 테스트 ────────────────────────


class TestReportRoutes:
    def test_schema(self, client):
        resp = client.get("/api/reports/schema")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, dict)

    def test_list_no_store(self, client):
        resp = client.get("/api/reports")
        assert resp.status_code == 503
        data = resp.json()
        assert data["type"] == "/errors/internal"
        assert data["status"] == 503

    def test_submit_no_store(self, client):
        resp = client.post("/api/reports", json={"test": True})
        assert resp.status_code == 503
        data = resp.json()
        assert data["type"] == "/errors/internal"


# ── RFC 7807 에러 응답 테스트 ────────────────────────


class TestRFC7807ErrorResponse:
    def test_404_returns_problem_json(self, client):
        resp = client.get("/api/nonexistent")
        assert resp.status_code == 404
        assert resp.headers["content-type"] == "application/problem+json"
        data = resp.json()
        assert data["type"] == "/errors/not-found"
        assert data["title"] == "Not Found"
        assert data["status"] == 404
        assert data["instance"] == "/api/nonexistent"

    def test_http_exception_returns_rfc7807(self, client):
        resp = client.post("/api/strategies/validate", json={})
        assert resp.status_code == 400
        assert resp.headers["content-type"] == "application/problem+json"
        data = resp.json()
        assert data["type"] == "/errors/validation"
        assert data["title"] == "Bad Request"
        assert data["status"] == 400
        assert "detail" in data
        assert "instance" in data

    def test_503_returns_rfc7807(self, client):
        resp = client.get("/api/reports")
        assert resp.status_code == 503
        assert resp.headers["content-type"] == "application/problem+json"
        data = resp.json()
        assert data["status"] == 503

    def test_error_response_schema(self):
        from ante.web.schemas import ErrorResponse

        error = ErrorResponse(
            type="/errors/not-found",
            title="Not Found",
            detail="Bot xyz not found",
            status=404,
            instance="/api/bots/xyz",
        )
        d = error.model_dump()
        assert d["type"] == "/errors/not-found"
        assert d["title"] == "Not Found"
        assert d["detail"] == "Bot xyz not found"
        assert d["status"] == 404
        assert d["instance"] == "/api/bots/xyz"

    def test_error_catalog_coverage(self):
        from ante.web.errors import ERROR_CATALOG

        required_types = {
            "/errors/not-found",
            "/errors/validation",
            "/errors/unauthorized",
            "/errors/forbidden",
            "/errors/conflict",
            "/errors/internal",
        }
        actual_types = {t for t, _ in ERROR_CATALOG.values()}
        assert required_types == actual_types

    def test_value_error_returns_400(self, app, client):
        from fastapi import APIRouter

        test_router = APIRouter()

        @test_router.get("/test-value-error")
        async def raise_value_error():
            raise ValueError("invalid input")

        app.include_router(test_router, prefix="/api")
        resp = client.get("/api/test-value-error")
        assert resp.status_code == 400
        assert resp.headers["content-type"] == "application/problem+json"
        data = resp.json()
        assert data["type"] == "/errors/validation"
        assert data["detail"] == "invalid input"


# ── App Factory 테스트 ────────────────────────────


class TestAppFactory:
    def test_create_app_default(self):
        app = create_app()
        assert app.title == "Ante"

    def test_create_app_with_services(self):
        app = create_app(config="test_config")
        assert app.state.config == "test_config"

    def test_cors_headers(self, client):
        resp = client.options(
            "/api/system/status",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert "access-control-allow-origin" in resp.headers

    def test_openapi_docs(self, client):
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        data = resp.json()
        assert data["info"]["title"] == "Ante"
