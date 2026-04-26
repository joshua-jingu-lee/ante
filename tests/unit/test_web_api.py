"""Web API 모듈 단위 테스트."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

httpx = pytest.importorskip("httpx", reason="httpx required for web API tests")

from fastapi.testclient import TestClient  # noqa: E402

from ante.web.app import create_app  # noqa: E402


def _expected_release_version() -> str:
    """pyproject.toml의 release 버전(SSOT)을 직접 읽어 반환.

    `ante.__version__`을 통하지 않고 pyproject.toml을 직접 파싱하여,
    공개 버전 표면이 SSOT 버전과 일치하는지 고정값으로 검증한다.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    with pyproject.open("rb") as fp:
        return tomllib.load(fp)["project"]["version"]


EXPECTED_VERSION = _expected_release_version()


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
        assert data["version"] == EXPECTED_VERSION

    def test_health(self, client):
        # 기본 앱에는 db/account_service가 주입되어 있지 않다.
        # - db 미주입 → checks.db = False
        # - account_service 미주입 → checks.broker = False (unhealthy)
        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "ok" in data
        assert "checks" in data
        assert data["checks"]["db"] is False
        assert data["checks"]["broker"] is False
        assert data["ok"] is False

    def test_health_db_ok_no_accounts(self, app, client):
        # DB 성공 + 계좌 0개
        class _DB:
            async def fetch_one(self, sql, params=()):
                return {"1": 1}

        class _AccountService:
            async def list(self):
                return []

        app.state.db = _DB()
        app.state.account_service = _AccountService()
        try:
            resp = client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"ok": True, "checks": {"db": True, "broker": True}}
        finally:
            app.state.db = None
            app.state.account_service = None

    def test_health_db_failure(self, app, client):
        # DB 실패 → checks.db = False, ok = False
        class _DB:
            async def fetch_one(self, sql, params=()):
                raise RuntimeError("db down")

        class _AccountService:
            async def list(self):
                return []

        app.state.db = _DB()
        app.state.account_service = _AccountService()
        try:
            resp = client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is False
            assert data["checks"]["db"] is False
            assert data["checks"]["broker"] is True
        finally:
            app.state.db = None
            app.state.account_service = None

    def test_health_broker_disconnected(self, app, client):
        # 일부 계좌 broker 끊김 → checks.broker = False
        class _DB:
            async def fetch_one(self, sql, params=()):
                return {"1": 1}

        class _Account:
            def __init__(self, account_id):
                self.account_id = account_id

        class _Broker:
            def __init__(self, connected):
                self.is_connected = connected

        class _AccountService:
            def __init__(self):
                self._brokers = {
                    "a1": _Broker(True),
                    "a2": _Broker(False),
                }

            async def list(self):
                return [_Account("a1"), _Account("a2")]

            async def get_broker(self, account_id):
                return self._brokers[account_id]

        app.state.db = _DB()
        app.state.account_service = _AccountService()
        try:
            resp = client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is False
            assert data["checks"]["db"] is True
            assert data["checks"]["broker"] is False
        finally:
            app.state.db = None
            app.state.account_service = None

    def test_health_account_service_missing(self, app, client):
        # account_service 미주입 → checks.broker = False (unhealthy)
        # 스펙: broker=True는 "계좌 0개"에만 허용되며, account_service 자체가
        # 없어 계좌를 확인할 수 없는 상태는 healthy로 판정하지 않는다.
        class _DB:
            async def fetch_one(self, sql, params=()):
                return {"1": 1}

        app.state.db = _DB()
        app.state.account_service = None
        try:
            resp = client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is False
            assert data["checks"] == {"db": True, "broker": False}
        finally:
            app.state.db = None

    def test_health_all_brokers_connected(self, app, client):
        # 모든 계좌 broker 연결됨 → checks.broker = True
        class _DB:
            async def fetch_one(self, sql, params=()):
                return {"1": 1}

        class _Account:
            def __init__(self, account_id):
                self.account_id = account_id

        class _Broker:
            is_connected = True

        class _AccountService:
            async def list(self):
                return [_Account("a1"), _Account("a2")]

            async def get_broker(self, account_id):
                return _Broker()

        app.state.db = _DB()
        app.state.account_service = _AccountService()
        try:
            resp = client.get("/api/system/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"ok": True, "checks": {"db": True, "broker": True}}
        finally:
            app.state.db = None
            app.state.account_service = None


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
        # PYTHONPATH=$PWD/src 실행 경로에서도 SSOT 버전이 노출되어야 한다.
        assert data["info"]["version"] == EXPECTED_VERSION


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
        """HealthResponse 모델이 실제 응답과 일치하는지 검증.

        기본 앱에는 db가 주입되어 있지 않아 ok=False가 정상이다. 여기서는
        응답 구조(필수 필드 존재, checks 타입)만 검증한다.
        `ok`와 `checks`는 모두 필수 필드여야 한다 (스펙 SSOT).
        """
        import pytest
        from pydantic import ValidationError

        from ante.web.schemas import HealthResponse

        resp = client.get("/api/system/health")
        assert resp.status_code == 200
        data = resp.json()

        # 응답에 필수 키가 모두 존재해야 한다.
        assert "ok" in data
        assert "checks" in data
        assert isinstance(data["checks"], dict)

        model = HealthResponse(**data)
        assert isinstance(model.ok, bool)
        assert isinstance(model.checks, dict)
        assert "db" in model.checks
        assert "broker" in model.checks

        # checks가 누락되면 ValidationError가 발생해야 한다 (required 필드).
        with pytest.raises(ValidationError):
            HealthResponse(ok=True)  # type: ignore[call-arg]
        assert "broker" in model.checks

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

    def test_openapi_account_routes_have_error_response_models(self, client):
        """cold-path 라우트의 명시 4xx/5xx 응답이 ErrorResponse를 노출.

        PUT/DELETE/POST 라우트가 ``responses=`` 데코레이터에 명시 등록한
        4xx/5xx 응답은 ``model: ErrorResponse``를 일관 등록해야 OpenAPI/
        codegen에서 bodyless 4xx/5xx로 표현되지 않는다. ``application/json``
        content가 있고 schema가 ``ErrorResponse``를 가리키는지 확인한다.

        FastAPI가 자동 생성하는 path/dependency 검증용 422 응답은
        ``HTTPValidationError`` 표준 schema를 사용하지만, 본 PUT 라우트는
        attempt 9에서 mutable 필드 type 검증 실패에 대한 422 응답을 명시
        등록(``model: ErrorResponse``)했으므로 본 테스트의 검증 대상에 포함
        한다. body requestBody의 schema accuracy(mutable 모델 직접 노출)는
        후속 이슈 #1143에서 다룬다.
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        paths = openapi.get("paths", {})

        # cold-path PUT/POST/DELETE 라우트만 본 attempt에서 강제한다.
        # 다른 account 라우트(suspend/activate/rules)의 4xx 커버리지 확장은
        # 후속 이슈(#1143 schema accuracy)에서 다룬다.
        # 각 튜플의 세 번째 요소는 ``responses=`` 데코레이터에 명시 등록된
        # 에러 status code 집합 — FastAPI 자동 422는 제외하지만, attempt 9
        # 에서 PUT은 mutable type 검증용 422를 명시 등록했으므로 PUT 422도
        # 강제 단언 대상에 포함한다.
        target_routes: list[tuple[str, str, set[str]]] = [
            ("/api/accounts", "post", {"409"}),
            (
                "/api/accounts/{account_id}",
                "put",
                {"400", "404", "409", "422", "503"},
            ),
            ("/api/accounts/{account_id}", "delete", {"409"}),
        ]

        missing: list[str] = []
        for path, method, explicit_codes in target_routes:
            spec = paths.get(path, {}).get(method)
            assert spec is not None, f"라우트 정의 누락: {method.upper()} {path}"

            responses = spec.get("responses", {})
            for code in explicit_codes:
                response_spec = responses.get(code)
                if response_spec is None:
                    missing.append(f"{method.upper()} {path} ({code}): 응답 정의 누락")
                    continue
                content = response_spec.get("content", {})
                json_content = content.get("application/json")
                if json_content is None:
                    missing.append(
                        f"{method.upper()} {path} ({code}): "
                        "application/json content 없음"
                    )
                    continue
                schema = json_content.get("schema", {})
                ref = schema.get("$ref", "")
                # FastAPI는 model: ErrorResponse를 받으면
                # `#/components/schemas/ErrorResponse`로 참조한다.
                if "ErrorResponse" not in ref:
                    missing.append(
                        f"{method.upper()} {path} ({code}): "
                        f"ErrorResponse 참조 없음 (schema={schema!r})"
                    )

        assert missing == [], (
            "cold-path account 라우트 에러 응답에 ErrorResponse 모델 누락:\n"
            + "\n".join(f"  - {m}" for m in missing)
        )

    def test_openapi_put_account_422_references_error_response(self, client):
        """PUT /api/accounts/{account_id}의 422 응답이 ErrorResponse를 가리킨다.

        attempt 9 P1 회귀 보호: 라우트는 비구조 필드 type 검증 실패를
        ``HTTPException(status_code=422)``로 명시 변환한다. ``responses[422]``
        에 ``model: ErrorResponse``가 등록되어 OpenAPI/codegen에서 422가
        bodyless가 아닌 ``ErrorResponse`` 본문을 갖도록 한다 — 클라이언트는
        type-safe하게 422 응답을 다룰 수 있다.

        body requestBody schema accuracy(mutable 모델 직접 노출)는
        후속 이슈 #1143에서 다룬다.
        """
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        spec = (
            openapi.get("paths", {})
            .get("/api/accounts/{account_id}", {})
            .get("put", {})
        )
        responses = spec.get("responses", {})
        response_422 = responses.get("422")
        assert response_422 is not None, "PUT 422 응답이 명시 등록되지 않음"
        json_content = response_422.get("content", {}).get("application/json")
        assert json_content is not None, "PUT 422에 application/json content 없음"
        ref = json_content.get("schema", {}).get("$ref", "")
        assert "ErrorResponse" in ref, (
            f"PUT 422가 ErrorResponse를 가리키지 않음 (schema ref={ref!r})"
        )


# ── #1143 POST /api/accounts request body schema 노출 ──────────────


class TestPostAccountRequestBodySchema:
    """POST /api/accounts requestBody OpenAPI schema 노출 (이슈 #1143).

    cold-path 가드는 어떤 입력이든 즉시 409로 차단하지만(invariant I1),
    OpenAPI/codegen 클라이언트는 정확한 입력 contract를 발견할 수 있어야
    한다. 본 테스트군은 ``openapi_extra``로 노출한 spec-aligned schema가
    docs/specs/account/03-data-model.md 60-87줄 필드 표와 1:1 정합한지
    단언한다.

    Pydantic ``AccountCreateRequest.model_json_schema()`` 직접 노출은 금지다
    (BrokerPreset 자동 채움 때문에 모든 필드가 default를 갖고 있어
    ``exchange``/``currency``/``broker_type`` required와 어긋남 — attempt 6
    finding). spec-aligned dict 상수 ``ACCOUNT_CREATE_REQUEST_SCHEMA``로
    별도 정의해 노출한다.
    """

    @staticmethod
    def _post_request_body(client: TestClient) -> dict:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        spec = openapi.get("paths", {}).get("/api/accounts", {}).get("post", {})
        request_body = spec.get("requestBody")
        assert request_body is not None, (
            "POST /api/accounts requestBody가 OpenAPI에 노출되지 않음"
        )
        return request_body

    @staticmethod
    def _post_request_schema(client: TestClient) -> dict:
        request_body = TestPostAccountRequestBodySchema._post_request_body(client)
        json_content = request_body.get("content", {}).get("application/json")
        assert json_content is not None, (
            "POST /api/accounts requestBody에 application/json content 없음"
        )
        schema = json_content.get("schema")
        assert isinstance(schema, dict), (
            "POST /api/accounts requestBody schema가 dict가 아님"
        )
        return schema

    def test_openapi_post_account_request_body_is_spec_aligned(self, client):
        """spec 표(docs/specs/account/03-data-model.md 60-87줄)와 정합."""
        schema = self._post_request_schema(client)

        # additionalProperties: False — 알 수 없는 키 차단을 contract에 표현
        ap = schema.get("additionalProperties")
        assert ap is False, f"additionalProperties가 False가 아님: {ap!r}"

        # required 표현
        required = schema.get("required", [])
        for field in ("account_id", "name", "exchange", "currency", "broker_type"):
            assert field in required, (
                f"required에 필수 필드 '{field}' 누락: {required!r}"
            )

        properties = schema.get("properties", {})
        assert isinstance(properties, dict), f"properties가 dict가 아님: {properties!r}"

        # default 표현
        assert properties.get("timezone", {}).get("default") == "Asia/Seoul"
        assert properties.get("trading_hours_start", {}).get("default") == "09:00", (
            properties.get("trading_hours_start")
        )
        assert properties.get("trading_hours_end", {}).get("default") == "15:30", (
            properties.get("trading_hours_end")
        )
        assert properties.get("trading_mode", {}).get("default") == "VIRTUAL", (
            properties.get("trading_mode")
        )

        # exchange enum
        assert properties.get("exchange", {}).get("enum") == [
            "KRX",
            "NYSE",
            "NASDAQ",
            "TEST",
        ], properties.get("exchange")

        # trading_mode enum (보조)
        assert properties.get("trading_mode", {}).get("enum") == [
            "VIRTUAL",
            "LIVE",
        ], properties.get("trading_mode")

        # 어떤 properties도 nullable이 아님 — anyOf/oneOf에 null type 없음,
        # nullable: True 없음. 각 property는 단일 type을 가져야 한다.
        for name, prop in properties.items():
            assert isinstance(prop, dict), f"properties.{name}가 dict가 아님: {prop!r}"
            assert "nullable" not in prop or prop.get("nullable") is not True, (
                f"properties.{name}에 nullable: True가 노출됨"
            )
            for combinator in ("anyOf", "oneOf"):
                variants = prop.get(combinator)
                if variants:
                    for variant in variants:
                        assert variant.get("type") != "null", (
                            f"properties.{name}.{combinator}에 null type 포함"
                        )

    def test_openapi_post_account_request_body_required_true(self, client):
        """codegen이 body를 optional로 만들지 않도록 required: True."""
        request_body = self._post_request_body(client)
        assert request_body.get("required") is True, (
            f"requestBody.required가 True가 아님: {request_body.get('required')!r}"
        )

    def test_openapi_post_account_credentials_is_string_map(self, client):
        """credentials는 dict[str, str] — codegen Record<string, never> 회피."""
        schema = self._post_request_schema(client)
        credentials = schema.get("properties", {}).get("credentials", {})
        assert credentials.get("type") == "object", credentials
        assert credentials.get("additionalProperties") == {"type": "string"}, (
            f"credentials.additionalProperties가 string map이 아님: {credentials!r}"
        )
        assert credentials.get("default") == {}, credentials

    def test_openapi_post_account_broker_config_is_open_map(self, client):
        """broker_config는 임의 dict — additionalProperties: True."""
        schema = self._post_request_schema(client)
        broker_config = schema.get("properties", {}).get("broker_config", {})
        assert broker_config.get("type") == "object", broker_config
        assert broker_config.get("additionalProperties") is True, (
            f"broker_config.additionalProperties가 True가 아님: {broker_config!r}"
        )
        assert broker_config.get("default") == {}, broker_config


class TestGeneratedTsPostAccountRequestBody:
    """generated TS api.generated.ts에서 POST /api/accounts request body가
    spec-aligned 형태로 노출되는지 보조 단언한다(이슈 #1143).

    같은 PR에 ``frontend/src/types/api.generated.ts``가 함께 갱신되어야
    하므로 generated artifact drift를 차단한다.
    """

    @staticmethod
    def _generated_ts_text() -> str:
        path = (
            Path(__file__).resolve().parents[2]
            / "frontend"
            / "src"
            / "types"
            / "api.generated.ts"
        )
        assert path.exists(), f"generated TS 파일이 존재하지 않음: {path}"
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _post_account_operation_block(text: str) -> str:
        """create_account_api_accounts_post operation 블록을 잘라낸다."""
        marker = "create_account_api_accounts_post:"
        idx = text.find(marker)
        assert idx != -1, "generated TS에 create_account operation이 없음"
        # 다음 operation 시작 전까지 잘라낸다(들여쓰기 4 + 식별자).
        rest = text[idx:]
        # 다음 operation 식별자를 정규식 없이 단순 키워드로 찾는다.
        next_markers = [
            "get_account_api_accounts__account_id__get:",
            "update_account_api_accounts__account_id__put:",
            "delete_account_api_accounts__account_id__delete:",
        ]
        end_offsets = [rest.find(m, 1) for m in next_markers]
        end_offsets = [o for o in end_offsets if o != -1]
        end = min(end_offsets) if end_offsets else len(rest)
        return rest[:end]

    def test_generated_ts_post_account_request_body_not_never(self):
        """POST /api/accounts에 requestBody?: never가 없어야 한다."""
        block = self._post_account_operation_block(self._generated_ts_text())
        assert "requestBody?: never" not in block, (
            "POST /api/accounts에 requestBody?: never 회귀:\n" + block
        )

    def test_generated_ts_post_account_request_body_required_not_optional(self):
        """POST /api/accounts requestBody가 optional 표시(?:)가 아닌 required."""
        block = self._post_account_operation_block(self._generated_ts_text())
        # requestBody?: 가 등장하면 codegen이 body를 optional로 만든 것이다.
        assert "requestBody?:" not in block, (
            "POST /api/accounts requestBody가 optional로 노출됨:\n" + block
        )
        # 명시 requestBody: 정의가 있어야 한다.
        assert "requestBody:" in block, (
            "POST /api/accounts에 requestBody: 정의가 없음:\n" + block
        )

    @staticmethod
    def _field_type_block(operation_block: str, field_name: str) -> str:
        """operation 블록에서 ``field_name`` 정의 라인부터 닫는 ``};``까지를 잘라낸다.

        openapi-typescript 멀티라인 출력(예: credentials의 본문은 다음 라인의
        ``[key: string]: string;``)에서 type 본문을 한 덩어리로 보기 위해 사용한다.
        """
        lines = operation_block.splitlines()
        start_idx: int | None = None
        for idx, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith(f"{field_name}:") or stripped.startswith(
                f"{field_name}?:"
            ):
                start_idx = idx
                break
        assert start_idx is not None, (
            f"field '{field_name}'가 operation block에 없음:\n{operation_block}"
        )
        # 시작 라인이 inline type(같은 줄에 ;로 끝남)이면 그 줄만 반환.
        first_line = lines[start_idx].rstrip()
        if first_line.endswith(";") and "{" not in first_line:
            return first_line
        # 멀티라인 type — base 들여쓰기 추적해서 매칭되는 ``};``를 찾는다.
        base_indent = len(first_line) - len(first_line.lstrip())
        collected = [first_line]
        for line in lines[start_idx + 1 :]:
            collected.append(line)
            stripped = line.lstrip()
            indent = len(line) - len(stripped)
            if indent <= base_indent and stripped.startswith("};"):
                break
        return "\n".join(collected)

    def test_generated_ts_post_account_credentials_not_record_never(self):
        """credentials 타입이 Record<string, never> / {}가 아니어야 한다.

        spec dict[str, str] → openapi-typescript는 보통
        ``Record<string, string>`` 또는 ``{[key: string]: string}``로 생성한다.
        """
        operation_block = self._post_account_operation_block(self._generated_ts_text())
        field_block = self._field_type_block(operation_block, "credentials")
        assert "Record<string, never>" not in field_block, (
            "credentials가 Record<string, never>로 좁혀짐:\n" + field_block
        )
        # 빈 객체 타입({})만 단독으로 사용되면 안 된다.
        assert (
            "Record<string, string>" in field_block
            or "[key: string]: string" in field_block
        ), f"credentials가 string-map 형태로 노출되지 않음:\n{field_block}"

    def test_generated_ts_post_account_broker_config_not_record_never(self):
        """broker_config 타입이 Record<string, never> / {}가 아니어야 한다."""
        operation_block = self._post_account_operation_block(self._generated_ts_text())
        field_block = self._field_type_block(operation_block, "broker_config")
        assert "Record<string, never>" not in field_block, (
            "broker_config가 Record<string, never>로 좁혀짐:\n" + field_block
        )
        assert (
            "Record<string, unknown>" in field_block
            or "[key: string]: unknown" in field_block
        ), f"broker_config가 open-map 형태로 노출되지 않음:\n{field_block}"
