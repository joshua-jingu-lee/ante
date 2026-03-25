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
        assert body["items"] == []
        assert body["total"] == 0

    def test_datasets_no_catalog_fundamental(self, client):
        resp = client.get("/api/data/datasets", params={"data_type": "fundamental"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["items"] == []
        assert body["total"] == 0

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
        body = resp.json()
        assert isinstance(body["items"], list)
        assert "total" in body

    def test_datasets_with_store_data_type_ohlcv(self, tmp_path):
        """data_type=ohlcv 파라미터로 OHLCV 데이터셋만 반환."""
        from ante.data.store import ParquetStore

        store = ParquetStore(base_path=tmp_path / "data")
        app = create_app(data_store=store)
        client = TestClient(app)

        resp = client.get("/api/data/datasets", params={"data_type": "ohlcv"})
        assert resp.status_code == 200
        body = resp.json()
        for ds in body["items"]:
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
        for ds in body["items"]:
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
        resp = client.post(
            "/api/reports",
            json={
                "strategy_name": "test",
                "strategy_version": "1.0.0",
                "strategy_path": "strategies/test.py",
            },
        )
        assert resp.status_code == 503
        data = resp.json()
        assert data["type"] == "/errors/internal"

    def test_submit_missing_fields(self):
        from unittest.mock import AsyncMock

        store = AsyncMock()
        app = create_app(report_store=store)
        c = TestClient(app)
        resp = c.post("/api/reports", json={"strategy_name": "incomplete"})
        assert resp.status_code == 422


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


# ── response_model 커버리지 테스트 ────────────────────────


class TestResponseModelCoverage:
    """모든 엔드포인트에 response_model이 설정되어 있는지 검증."""

    # response_model 면제 대상 (동적 스키마를 반환하는 엔드포인트)
    _EXEMPT_PATHS = {
        "/api/reports/schema",
        "/api/data/schema",
    }

    def test_all_endpoints_have_response_model(self, app):
        """204를 제외한 모든 API 엔드포인트에 response_model이 설정되어야 한다."""
        missing = []
        for route in app.routes:
            if not hasattr(route, "methods"):
                continue
            path = getattr(route, "path", "")
            if not path.startswith("/api"):
                continue
            if path in self._EXEMPT_PATHS:
                continue
            # 204 응답(삭제)은 response_model 불필요
            status_code = getattr(route, "status_code", None) or 200
            if status_code == 204:
                continue
            response_model = getattr(route, "response_model", None)
            if response_model is None:
                methods = getattr(route, "methods", set())
                missing.append(f"{','.join(methods)} {path}")

        assert missing == [], "response_model 누락 엔드포인트:\n" + "\n".join(
            f"  - {m}" for m in missing
        )

    def test_openapi_schema_has_response_schemas(self, client):
        """OpenAPI 스키마에서 모든 엔드포인트에 응답 스키마가 존재."""
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        paths = openapi.get("paths", {})

        missing = []
        for path, methods in paths.items():
            if not path.startswith("/api"):
                continue
            if path in self._EXEMPT_PATHS:
                continue
            for method, spec in methods.items():
                if method in ("options", "head"):
                    continue
                responses = spec.get("responses", {})
                # 204 응답은 스키마 불필요
                if "204" in responses and len(responses) <= 2:
                    continue
                # 200 또는 201에 content schema가 있어야 함
                success_codes = [c for c in ("200", "201") if c in responses]
                if not success_codes:
                    continue
                for code in success_codes:
                    content = responses[code].get("content", {})
                    json_schema = content.get("application/json", {}).get("schema")
                    if json_schema is None:
                        missing.append(f"{method.upper()} {path} ({code})")

        assert missing == [], "OpenAPI 응답 스키마 누락:\n" + "\n".join(
            f"  - {m}" for m in missing
        )

    def test_response_model_validates_status_response(self, client):
        """StatusResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import StatusResponse

        resp = client.get("/api/system/status")
        assert resp.status_code == 200
        data = resp.json()
        # Pydantic 모델로 파싱 가능해야 함
        model = StatusResponse(**data)
        assert model.status == "running"

    def test_response_model_validates_health_response(self, client):
        """HealthResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import HealthResponse

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        model = HealthResponse(**data)
        assert model.ok is True

    def test_response_model_validates_strategy_validate(self, client, tmp_path):
        """StrategyValidateResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import StrategyValidateResponse

        path = tmp_path / "test.py"
        path.write_text("import os\nprint('not a strategy')")

        resp = client.post("/api/strategies/validate", json={"path": str(path)})
        assert resp.status_code == 200
        data = resp.json()
        model = StrategyValidateResponse(**data)
        assert model.valid is False

    def test_response_model_validates_dataset_list(self, client):
        """DatasetListResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import DatasetListResponse

        resp = client.get("/api/data/datasets")
        assert resp.status_code == 200
        data = resp.json()
        model = DatasetListResponse(**data)
        assert model.total == 0

    def test_response_model_validates_storage_summary(self, client):
        """StorageSummaryResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import StorageSummaryResponse

        resp = client.get("/api/data/storage")
        assert resp.status_code == 200
        data = resp.json()
        model = StorageSummaryResponse(**data)
        assert model.total_bytes == 0

    def test_response_model_validates_feed_status(self, client):
        """FeedStatusResponse 모델이 실제 응답과 일치하는지 검증."""
        from ante.web.schemas import FeedStatusResponse

        resp = client.get("/api/data/feed-status")
        assert resp.status_code == 200
        data = resp.json()
        model = FeedStatusResponse(**data)
        assert model.initialized is False
