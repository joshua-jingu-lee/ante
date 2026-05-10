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

    def test_submit_unauth_returns_401(self, client):
        """#1374: 인증 없는 호출은 401. 인증 가드가 service availability /
        body validation 보다 먼저 실행된다.

        과거(``test_submit_no_store``)에는 ``report_store`` 미주입 시 503 을
        반환했으나, ``require_report_write`` dependency 가 라우트 시그니처
        앞쪽에 위치해 인증 누락이 우선 401 로 차단된다.
        """
        resp = client.post(
            "/api/reports",
            json={
                "strategy_name": "test",
                "strategy_version": "1.0.0",
                "strategy_path": "strategies/test.py",
            },
        )
        assert resp.status_code == 401
        data = resp.json()
        assert data["status"] == 401

    def test_submit_missing_fields_unauth_returns_401(self):
        """#1374: unauth + missing fields → 401 (NOT 422). auth-first 계약.

        과거(``test_submit_missing_fields``)에는 422 가 우선 반환되었으나,
        raw body 패턴 + ``require_report_write`` 가드로 인해 인증 실패 시
        body validation 은 실행되지 않고 401 이 우선 반환된다.
        """
        from unittest.mock import AsyncMock

        store = AsyncMock()
        app = create_app(report_store=store)
        c = TestClient(app)
        resp = c.post("/api/reports", json={"strategy_name": "incomplete"})
        assert resp.status_code == 401


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
            "/errors/unsupported-media-type",
            "/errors/internal",
        }
        actual_types = {t for t, _ in ERROR_CATALOG.values()}
        assert required_types == actual_types

    def test_error_catalog_has_415_entry(self):
        """ERROR_CATALOG 415 entry는 RFC 7807 패턴(이슈 #1153).

        PUT /api/accounts/{account_id}의 Content-Type 게이트가 415를 raise할
        때 fallback ``("/errors/internal", "Error")``로 떨어지지 않도록 415
        entry를 명시 등록한다.
        """
        from ante.web.errors import ERROR_CATALOG

        assert 415 in ERROR_CATALOG, (
            "ERROR_CATALOG에 415 entry가 없으면 415 HTTPException이 fallback "
            "type/title로 직렬화된다."
        )
        type_uri, title = ERROR_CATALOG[415]
        assert type_uri == "/errors/unsupported-media-type"
        assert title == "Unsupported Media Type"

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

    def test_all_router_explicit_4xx_5xx_responses_reference_error_response(
        self,
    ):
        """라우트의 명시 등록된 4xx/5xx ``responses=``가 ``model: ErrorResponse``를
        참조 (이슈 #1145, invariant C1).

        ``src/ante/web/routes/`` 하위 router 모듈을 모두 import하여
        ``APIRoute.responses`` **정적 dict**를 순회한다. ``int(code) >= 400``인
        명시 항목은 모두 ``model is ErrorResponse`` 여야 한다.

        - C1 — ``src/ante/web/routes/`` 하위 모든 router 모듈을 포함
        - C2 — FastAPI 자동 생성 422(``HTTPValidationError``)는 검사 대상
          아님. 명시 등록된 422(예: accounts.put mutable type 검증)는 본
          검사 대상에 포함된다.
        - C3 — 신규 status code 추가는 본 PR scope 밖. 기존 ``responses=``
          항목 갱신만 수행한다.
        """
        import importlib
        import pkgutil

        from fastapi.routing import APIRoute

        import ante.web.routes as routes_pkg
        from ante.web.schemas import ErrorResponse

        violations: list[str] = []
        for mod_info in pkgutil.iter_modules(routes_pkg.__path__):
            if mod_info.name == "__init__":
                continue
            mod = importlib.import_module(f"ante.web.routes.{mod_info.name}")
            router = getattr(mod, "router", None)
            if router is None:
                continue
            for route in router.routes:
                if not isinstance(route, APIRoute):
                    continue
                responses = route.responses or {}
                for code, entry in responses.items():
                    try:
                        code_int = int(code)
                    except (TypeError, ValueError):
                        continue
                    if code_int < 400:
                        continue
                    if not isinstance(entry, dict):
                        violations.append(
                            f"{mod_info.name} {route.path} {code_int}: "
                            f"entry는 dict 여야 함 (got {type(entry).__name__})"
                        )
                        continue

                    # 조건 1: FastAPI shorthand — ``model: ErrorResponse``
                    if entry.get("model") is ErrorResponse:
                        continue

                    # 조건 2: 명시 content map — 후속 이슈에서
                    # ``application/problem+json``으로 정렬할 때도 통과하도록
                    # forward-compatible 검사를 함께 둔다. 어느 media type 이든
                    # schema가 ``ErrorResponse`` 클래스 자체이거나
                    # ``$ref`` 문자열이 ``/ErrorResponse``로 끝나면 인정.
                    matched_via_content = False
                    content = entry.get("content")
                    if isinstance(content, dict):
                        for media_obj in content.values():
                            if not isinstance(media_obj, dict):
                                continue
                            schema = media_obj.get("schema")
                            if schema is ErrorResponse:
                                matched_via_content = True
                                break
                            if isinstance(schema, dict):
                                ref = schema.get("$ref", "")
                                if isinstance(ref, str) and ref.endswith(
                                    "/ErrorResponse"
                                ):
                                    matched_via_content = True
                                    break
                    if matched_via_content:
                        continue

                    violations.append(
                        f"{mod_info.name} {route.path} {code_int}: "
                        f"ErrorResponse 참조 누락 — model shorthand도 명시 "
                        f"content map의 $ref도 일치하지 않음 "
                        f"(model={entry.get('model')!r}, "
                        f"keys={sorted(entry.keys())})"
                    )

        assert violations == [], (
            "router 명시 4xx/5xx responses=가 ErrorResponse를 참조하지 않음:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_all_router_explicit_4xx_5xx_use_problem_json_only(self):
        """명시 등록된 4xx/5xx OpenAPI ``responses`` entry는
        ``application/problem+json`` content-type **만** 노출한다 (이슈 #1164).

        런타임 ``register_exception_handlers``는 ``media_type=PROBLEM_JSON``
        (``application/problem+json``)으로 응답하므로, OpenAPI doc과 런타임
        content-type drift를 invariant로 잠근다.

        - FastAPI 자동 생성 422(``HTTPValidationError``) 응답은 검사 대상에서
          **제외**한다 (``application/json`` 유지가 FastAPI 기본 동작이며
          본 이슈 Non-Goal). ``$ref``가 ``/HTTPValidationError``로 끝나는
          422 응답을 정밀 필터링한다.
        - 명시 등록된 422(``ErrorResponse`` 참조)는 검사 **포함**한다.
        - ``application/json`` 키가 등장하면 FAIL — shorthand
          ``model: ErrorResponse``와 명시 ``content`` 매핑이 병합되어 두
          media type이 동시에 노출되는 split을 차단한다.
        """
        app = create_app()
        schema = app.openapi()
        violations: list[str] = []

        for path, methods in schema.get("paths", {}).items():
            if not isinstance(methods, dict):
                continue
            for method, spec in methods.items():
                if not isinstance(spec, dict):
                    continue
                responses = spec.get("responses", {})
                if not isinstance(responses, dict):
                    continue
                for code, entry in responses.items():
                    try:
                        code_int = int(code)
                    except (TypeError, ValueError):
                        continue
                    if code_int < 400:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    content = entry.get("content")
                    if not isinstance(content, dict):
                        continue

                    # FastAPI 자동 생성 422(HTTPValidationError ref) 제외.
                    if str(code) == "422":
                        json_obj = content.get("application/json")
                        if isinstance(json_obj, dict):
                            schema_obj = json_obj.get("schema", {})
                            ref = (
                                schema_obj.get("$ref", "")
                                if isinstance(schema_obj, dict)
                                else ""
                            )
                            if isinstance(ref, str) and ref.endswith(
                                "/HTTPValidationError"
                            ):
                                continue

                    media_keys = set(content.keys())
                    if media_keys != {"application/problem+json"}:
                        violations.append(
                            f"{path} {method.upper()} {code}: "
                            f"{sorted(media_keys)} expected only "
                            f"application/problem+json"
                        )

        assert violations == [], (
            "OpenAPI 명시 4xx/5xx responses content-type drift:\n"
            + "\n".join(f"  - {v}" for v in violations)
        )

    def test_openapi_components_includes_error_response(self):
        """``components.schemas.ErrorResponse``가 항상 등록되어 있다 (이슈 #1164).

        ``model: ErrorResponse`` shorthand를 제거하고 명시 ``$ref`` 매핑만
        남기면, FastAPI 기본 동작에서 ``ErrorResponse`` component가
        components 트리에 포함되지 않을 수 있다.
        ``_install_openapi_customizer(app)``가 ``setdefault``로 fallback
        등록을 보장한다. 본 테스트는 customizer fallback 경로를 invariant로
        잠근다.
        """
        app = create_app()
        schema = app.openapi()
        components = schema.get("components", {})
        schemas = components.get("schemas", {})
        assert "ErrorResponse" in schemas, (
            "ErrorResponse가 components.schemas에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요"
        )
        error_schema = schemas["ErrorResponse"]
        assert isinstance(error_schema, dict)
        assert error_schema.get("type") == "object", (
            f"ErrorResponse schema type=object가 아님: {error_schema!r}"
        )
        properties = error_schema.get("properties", {})
        for required_field in ("type", "title", "detail", "status", "instance"):
            assert required_field in properties, (
                f"ErrorResponse properties에 {required_field} 누락: "
                f"{sorted(properties.keys())}"
            )

    def test_openapi_components_includes_member_create_request(self):
        """``components.schemas.MemberCreateRequest``가 항상 등록되어 있다 (#1339 P1).

        POST /api/members 라우트는 raw body 패턴(``request: Request``)으로
        동작하므로 FastAPI 자동 components 등록 경로를 타지 않는다.
        ``openapi_extra``를 inline schema로 두면 ``components.schemas``에
        ``MemberCreateRequest``가 노출되지 않아, frontend
        ``openapi-typescript`` 산출물에서 ``export type MemberCreateRequest``
        가 사라지고 ``frontend/src/api/members.ts`` 빌드가 깨진다.
        ``_install_openapi_customizer``가 ``setdefault``로 fallback 등록해
        이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "MemberCreateRequest" in schemas, (
            "MemberCreateRequest가 components.schemas에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1339 P1)"
        )
        member_schema = schemas["MemberCreateRequest"]
        assert isinstance(member_schema, dict)
        assert member_schema.get("type") == "object"
        # 필수 필드 contract 보존 검증.
        required = member_schema.get("required", [])
        assert "member_id" in required, (
            f"MemberCreateRequest.required에 member_id 누락: {required}"
        )
        assert "member_type" in required, (
            f"MemberCreateRequest.required에 member_type 누락: {required}"
        )

    def test_post_members_request_body_uses_component_ref(self):
        """POST /api/members requestBody가 ``$ref`` 매핑을 노출한다 (#1339 P1).

        inline schema로 두면 frontend codegen이
        ``export type MemberCreateRequest``를 생성하지 않는다.
        ``$ref: #/components/schemas/MemberCreateRequest``로 노출되어야
        ``frontend/src/api/members.ts``의 import가 깨지지 않는다.
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/members"]["post"]
        request_body = post_op.get("requestBody", {})
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/MemberCreateRequest"}, (
            "POST /api/members requestBody schema가 component $ref가 아님: "
            f"{body_schema!r}"
        )

    def test_openapi_components_includes_scopes_update_request(self):
        """``components.schemas.ScopesUpdateRequest``가 항상 등록되어 있다 (#1351).

        PUT /api/members/{member_id}/scopes 라우트도 ``create_member`` 와 동일한
        raw body 패턴(``request: Request``)으로 전환되었다(인증 가드 우선).
        그 결과 ``body: ScopesUpdateRequest`` 인자가 시그니처에서 사라져 FastAPI
        자동 components 등록 경로를 타지 않으며, inline schema로 두면 frontend
        ``openapi-typescript`` 산출물이 ``export type ScopesUpdateRequest``를
        잃고 ``frontend/src/api/members.ts``의 ``tsc -b``가 깨진다.
        ``_install_openapi_customizer``가 ``setdefault``로 fallback 등록해 이
        회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "ScopesUpdateRequest" in schemas, (
            "ScopesUpdateRequest가 components.schemas에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1351 1차 Codex review)"
        )
        scopes_schema = schemas["ScopesUpdateRequest"]
        assert isinstance(scopes_schema, dict)
        assert scopes_schema.get("type") == "object"
        required = scopes_schema.get("required", [])
        assert "scopes" in required, (
            f"ScopesUpdateRequest.required에 scopes 누락: {required}"
        )
        properties = scopes_schema.get("properties", {})
        scopes_field = properties.get("scopes", {})
        assert scopes_field.get("type") == "array", (
            f"ScopesUpdateRequest.scopes는 array여야 함: {scopes_field!r}"
        )

    def test_put_members_scopes_request_body_uses_component_ref(self):
        """PUT /api/members/{id}/scopes requestBody가 ``$ref`` 매핑을 노출한다 (#1351).

        inline schema로 두면 frontend codegen이 ``export type
        ScopesUpdateRequest``를 만들지 못해 ``frontend/src/api/members.ts``의
        import가 깨진다.
        """
        app = create_app()
        schema = app.openapi()
        put_op = schema["paths"]["/api/members/{member_id}/scopes"]["put"]
        request_body = put_op.get("requestBody", {})
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/ScopesUpdateRequest"}, (
            "PUT /api/members/{member_id}/scopes requestBody schema가 component "
            f"$ref가 아님: {body_schema!r}"
        )

    def test_openapi_components_includes_account_suspend_request(self):
        """``components.schemas.AccountSuspendRequest``가 항상 등록되어 있다.

        Codex review #1352 2차에서 식별된 회귀를 잠근다.

        POST /api/accounts/{account_id}/suspend 라우트도 ``create_member`` /
        ``update_scopes`` / ``update_bot`` / ``set_balance`` 와 동일한 raw body
        패턴(``request: Request``)으로 전환되었다(인증 가드 우선). 그 결과
        ``body: AccountSuspendRequest`` 인자가 시그니처에서 사라져 FastAPI 자동
        components 등록 경로를 타지 않으며, inline schema로 두면 frontend
        ``openapi-typescript`` 산출물이 ``export type AccountSuspendRequest``를
        잃어 빌드가 깨진다. ``_install_openapi_customizer``가 ``setdefault``로
        fallback 등록해 이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "AccountSuspendRequest" in schemas, (
            "AccountSuspendRequest가 components.schemas에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1352 2차 Codex review)"
        )
        suspend_schema = schemas["AccountSuspendRequest"]
        assert isinstance(suspend_schema, dict)
        assert suspend_schema.get("type") == "object"
        # 빈 body 허용이므로 ``required``는 비어 있어야 한다.
        assert not suspend_schema.get("required", []), (
            "AccountSuspendRequest는 빈 body를 허용해야 하므로 required가 비어야 함: "
            f"{suspend_schema.get('required')!r}"
        )
        # ``additionalProperties: false``로 unknown 키를 차단한다.
        assert suspend_schema.get("additionalProperties") is False, (
            "AccountSuspendRequest.additionalProperties는 False여야 함: "
            f"{suspend_schema.get('additionalProperties')!r}"
        )
        properties = suspend_schema.get("properties", {})
        reason_field = properties.get("reason", {})
        assert reason_field.get("type") == "string", (
            f"AccountSuspendRequest.reason은 string이어야 함: {reason_field!r}"
        )

    def test_post_accounts_suspend_request_body_uses_component_ref(self):
        """POST /api/accounts/{id}/suspend requestBody가 nullable ``$ref``를 노출.

        Codex review #1352 2차/3차/4차에서 식별된 회귀를 잠근다.

        inline schema로 두면 frontend codegen이 ``export type
        AccountSuspendRequest``를 만들지 못해 frontend 빌드가 깨진다.
        ``required: False``는 빈 body도 허용하기 위함이며(default reason),
        다른 mutation 라우트와 패턴 정합을 위해 ``$ref``는 그대로 유지한다.

        4차 review (P2): 런타임은 JSON ``null`` body를 빈 body와 동일하게
        default reason 으로 흘려보내지만, 이전에는 schema가 ``$ref`` 단일
        이라 codegen 타입이 null body를 거부해 OpenAPI 계약과 drift가
        있었다. OpenAPI 3.1.0 기준 nullable은 ``oneOf``/``anyOf`` +
        ``{"type": "null"}`` 로 표현해야 하므로 body schema는 ``$ref`` +
        ``{"type": "null"}`` 의 ``oneOf`` 를 노출한다.
        """
        app = create_app()
        schema = app.openapi()
        # OpenAPI 3.1.0 가정 — nullable 표현이 oneOf/anyOf + {"type":"null"}.
        assert schema.get("openapi", "").startswith("3.1"), (
            "ante OpenAPI 버전이 3.1 계열이 아님 — nullable 표현 재검토 필요: "
            f"{schema.get('openapi')!r}"
        )
        post_op = schema["paths"]["/api/accounts/{account_id}/suspend"]["post"]
        request_body = post_op.get("requestBody", {})
        # 빈 body도 허용되므로 required는 False다.
        assert request_body.get("required") is False, (
            "POST /api/accounts/{id}/suspend requestBody.required는 False여야 함 — "
            "빈 body는 default reason으로 흘려보낸다."
        )
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        # Nullable: oneOf [$ref, {"type":"null"}].
        one_of = body_schema.get("oneOf")
        assert isinstance(one_of, list) and len(one_of) == 2, (
            "POST /api/accounts/{account_id}/suspend body schema가 nullable "
            f"oneOf 형태가 아님: {body_schema!r}"
        )
        assert {"$ref": "#/components/schemas/AccountSuspendRequest"} in one_of, (
            "POST /api/accounts/{account_id}/suspend body oneOf에 "
            f"AccountSuspendRequest $ref 누락: {one_of!r}"
        )
        assert {"type": "null"} in one_of, (
            "POST /api/accounts/{account_id}/suspend body oneOf에 null 타입 "
            f"누락 — JSON null body 호환 계약: {one_of!r}"
        )

    def test_openapi_components_includes_budget_change_request(self):
        """``components.schemas.BudgetChangeRequest``가 항상 등록되어 있다 (#1372).

        POST /api/treasury/bots/{bot_id}/allocate, /deallocate 라우트도 raw
        body 패턴(``request: Request`` + ``Depends(require_master_caller)``)으로
        전환되었다(인증 가드 우선). 그 결과 ``body: BudgetChangeRequest`` 인자가
        시그니처에서 사라져 FastAPI 자동 components 등록 경로를 타지 않으며,
        inline schema로 두면 frontend ``openapi-typescript`` 산출물이
        ``export type BudgetChangeRequest`` 를 잃어
        ``frontend/src/api/treasury.ts``의 ``allocateBudget``/``deallocateBudget``
        type import 가 깨진다. ``_install_openapi_customizer`` 가
        ``setdefault`` 로 fallback 등록해 이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "BudgetChangeRequest" in schemas, (
            "BudgetChangeRequest가 components.schemas에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1372)"
        )
        budget_schema = schemas["BudgetChangeRequest"]
        assert isinstance(budget_schema, dict)
        assert budget_schema.get("type") == "object"
        required = budget_schema.get("required", [])
        assert "amount" in required, (
            f"BudgetChangeRequest.required에 amount 누락: {required}"
        )
        properties = budget_schema.get("properties", {})
        amount_field = properties.get("amount", {})
        assert amount_field.get("type") == "number", (
            f"BudgetChangeRequest.amount는 number여야 함: {amount_field!r}"
        )

    def test_post_treasury_allocate_request_body_uses_component_ref(self):
        """POST /api/treasury/bots/{id}/allocate requestBody가 ``$ref`` 매핑을 노출.

        inline schema로 두면 frontend codegen이 ``export type
        BudgetChangeRequest`` 를 만들지 못해 ``frontend/src/api/treasury.ts``의
        import 가 깨진다 (#1372).
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/treasury/bots/{bot_id}/allocate"]["post"]
        request_body = post_op.get("requestBody", {})
        assert request_body.get("required") is True, (
            "POST /api/treasury/bots/{id}/allocate requestBody.required는 True여야 함"
        )
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/BudgetChangeRequest"}, (
            "POST /api/treasury/bots/{id}/allocate requestBody schema가 component "
            f"$ref가 아님: {body_schema!r}"
        )

    def test_post_treasury_deallocate_request_body_uses_component_ref(self):
        """POST /api/treasury/bots/{id}/deallocate requestBody가 ``$ref`` 매핑을 노출.

        ``allocate`` 와 동일 contract (#1372).
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/treasury/bots/{bot_id}/deallocate"]["post"]
        request_body = post_op.get("requestBody", {})
        assert request_body.get("required") is True, (
            "POST /api/treasury/bots/{id}/deallocate requestBody.required는 True여야 함"
        )
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/BudgetChangeRequest"}, (
            "POST /api/treasury/bots/{id}/deallocate requestBody schema가 component "
            f"$ref가 아님: {body_schema!r}"
        )

    def test_openapi_components_includes_config_update_request(self):
        """``components.schemas.ConfigUpdateRequest`` 가 항상 등록되어 있다 (#1373).

        PUT /api/config/{key} 라우트도 raw body 패턴(``request: Request`` +
        ``Depends(require_config_write)``)으로 전환되었다(인증 가드 우선). 그
        결과 ``body: ConfigUpdateRequest`` 인자가 시그니처에서 사라져 FastAPI
        자동 components 등록 경로를 타지 않으며, inline schema 로 두면
        frontend ``openapi-typescript`` 산출물이 ``export type
        ConfigUpdateRequest`` 를 잃어 ``frontend/src/api/system.ts`` 의
        ``updateConfig`` type import 가 깨진다. ``_install_openapi_customizer``
        가 ``setdefault`` 로 fallback 등록해 이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "ConfigUpdateRequest" in schemas, (
            "ConfigUpdateRequest 가 components.schemas 에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1373)"
        )
        config_schema = schemas["ConfigUpdateRequest"]
        assert isinstance(config_schema, dict)
        assert config_schema.get("type") == "object"
        required = config_schema.get("required", [])
        assert "value" in required, (
            f"ConfigUpdateRequest.required 에 value 누락: {required}"
        )
        properties = config_schema.get("properties", {})
        assert "value" in properties, (
            f"ConfigUpdateRequest.properties 에 value 누락: {sorted(properties.keys())}"
        )
        category_field = properties.get("category", {})
        assert category_field.get("type") == "string", (
            f"ConfigUpdateRequest.category 는 string 이어야 함: {category_field!r}"
        )

    def test_put_config_request_body_uses_component_ref(self):
        """PUT /api/config/{key} requestBody 가 ``$ref`` 매핑을 노출 (#1373).

        inline schema 로 두면 frontend codegen 이 ``export type
        ConfigUpdateRequest`` 를 만들지 못해 ``frontend/src/api/system.ts``
        의 import 가 깨진다.
        """
        app = create_app()
        schema = app.openapi()
        put_op = schema["paths"]["/api/config/{key}"]["put"]
        request_body = put_op.get("requestBody", {})
        assert request_body.get("required") is True, (
            "PUT /api/config/{key} requestBody.required 는 True 여야 함"
        )
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/ConfigUpdateRequest"}, (
            "PUT /api/config/{key} requestBody schema 가 component $ref 가 아님: "
            f"{body_schema!r}"
        )

    def test_openapi_components_includes_report_submit_request(self):
        """``components.schemas.ReportSubmitRequest`` 가 항상 등록되어 있다 (#1374).

        POST /api/reports 라우트도 raw body 패턴(``request: Request`` +
        ``Depends(require_report_write)``)으로 전환되었다(인증 가드 우선).
        그 결과 ``body: ReportSubmitRequest`` 인자가 시그니처에서 사라져
        FastAPI 자동 components 등록 경로를 타지 않으며, inline schema 로
        두면 frontend ``openapi-typescript`` 산출물이 ``export type
        ReportSubmitRequest`` 를 잃는다. ``_install_openapi_customizer`` 가
        ``setdefault`` 로 fallback 등록해 이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        assert "ReportSubmitRequest" in schemas, (
            "ReportSubmitRequest 가 components.schemas 에 등록되지 않음 — "
            "_install_openapi_customizer 동작 확인 필요 (#1374)"
        )
        report_schema = schemas["ReportSubmitRequest"]
        assert isinstance(report_schema, dict)
        assert report_schema.get("type") == "object"
        required = report_schema.get("required", [])
        for field_name in ("strategy_name", "strategy_version", "strategy_path"):
            assert field_name in required, (
                f"ReportSubmitRequest.required 에 {field_name} 누락: {required}"
            )
        # extra='forbid' 를 OpenAPI 에 반영 (#1353 invariant 노출).
        assert report_schema.get("additionalProperties") is False, (
            "ReportSubmitRequest.additionalProperties 는 False 여야 함: "
            f"{report_schema.get('additionalProperties')!r}"
        )

    def test_post_reports_request_body_uses_component_ref(self):
        """POST /api/reports requestBody 가 ``$ref`` 매핑을 노출 (#1374).

        inline schema 로 두면 frontend codegen 이 ``export type
        ReportSubmitRequest`` 를 만들지 못한다.
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/reports"]["post"]
        request_body = post_op.get("requestBody", {})
        assert request_body.get("required") is True, (
            "POST /api/reports requestBody.required 는 True 여야 함"
        )
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/ReportSubmitRequest"}, (
            "POST /api/reports requestBody schema 가 component $ref 가 아님: "
            f"{body_schema!r}"
        )

    def test_openapi_components_includes_halt_and_clear_halt_request(self):
        """``components.schemas.HaltRequest`` / ``ClearHaltRequest`` 가 항상
        등록되어 있다 (#1375).

        POST /api/system/halt / clear-halt 라우트도 raw body 패턴
        (``request: Request`` + ``Depends(require_master_caller)``) 으로
        전환되었다 (인증 가드 우선). 그 결과 ``body: HaltRequest`` /
        ``body: ClearHaltRequest`` 인자가 시그니처에서 사라져 FastAPI 자동
        components 등록 경로를 타지 않으며, inline schema 로 두면 frontend
        ``openapi-typescript`` 산출물이 ``export type HaltRequest`` /
        ``export type ClearHaltRequest`` 를 잃어
        ``frontend/src/api/system.ts`` 의 ``haltSystem`` /
        ``clearHaltSystem`` type import 가 깨진다.
        ``_install_openapi_customizer`` 가 ``setdefault`` 로 fallback 등록해
        이 회귀를 잠근다.
        """
        app = create_app()
        schema = app.openapi()
        schemas = schema.get("components", {}).get("schemas", {})
        for schema_name in ("HaltRequest", "ClearHaltRequest"):
            assert schema_name in schemas, (
                f"{schema_name} 가 components.schemas 에 등록되지 않음 — "
                "_install_openapi_customizer 동작 확인 필요 (#1375)"
            )
            comp = schemas[schema_name]
            assert isinstance(comp, dict)
            assert comp.get("type") == "object"
            properties = comp.get("properties", {})
            assert "reason" in properties, (
                f"{schema_name}.properties 에 reason 누락: {sorted(properties.keys())}"
            )
            # ``reason`` 은 default ``""`` 를 가지므로 required 에 들어가지
            # 않아야 한다 (Pydantic SSOT 정합).
            required = comp.get("required", [])
            assert "reason" not in required, (
                f"{schema_name}.required 에 reason 이 들어가면 안 됨: {required}"
            )

    def test_post_system_halt_request_body_uses_component_ref(self):
        """POST /api/system/halt requestBody 가 ``$ref`` 매핑을 노출 (#1375).

        inline schema 로 두면 frontend codegen 이 ``export type HaltRequest``
        를 만들지 못해 ``frontend/src/api/system.ts`` 의 ``haltSystem`` import
        가 깨진다.
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/system/halt"]["post"]
        request_body = post_op.get("requestBody", {})
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/HaltRequest"}, (
            "POST /api/system/halt requestBody schema 가 component $ref 가 아님: "
            f"{body_schema!r}"
        )

    def test_post_system_clear_halt_request_body_uses_component_ref(self):
        """POST /api/system/clear-halt requestBody 가 ``$ref`` 매핑을 노출
        (#1375).

        inline schema 로 두면 frontend codegen 이 ``export type
        ClearHaltRequest`` 를 만들지 못해 ``frontend/src/api/system.ts`` 의
        ``clearHaltSystem`` import 가 깨진다.
        """
        app = create_app()
        schema = app.openapi()
        post_op = schema["paths"]["/api/system/clear-halt"]["post"]
        request_body = post_op.get("requestBody", {})
        json_content = request_body.get("content", {}).get("application/json", {})
        body_schema = json_content.get("schema", {})
        assert body_schema == {"$ref": "#/components/schemas/ClearHaltRequest"}, (
            "POST /api/system/clear-halt requestBody schema 가 component $ref "
            f"가 아님: {body_schema!r}"
        )

    def test_frontend_openapi_json_matches_live_app_openapi(self):
        """``frontend/openapi.json``이 live ``app.openapi()``와 동기화 (C4).

        기본 앱(``create_app()``)이 생성한 ``app.openapi()``의
        ``paths.*.*.responses`` 트리가 ``frontend/openapi.json``의 동일
        트리와 정확히 일치해야 한다. version 등 노이즈를 피하려고 비교
        범위는 ``responses`` 노드로 좁힌다.
        """
        import json

        live_app = create_app()
        live_openapi = live_app.openapi()
        frontend_openapi_path = (
            Path(__file__).resolve().parents[2] / "frontend" / "openapi.json"
        )
        assert frontend_openapi_path.is_file(), (
            f"frontend/openapi.json 미존재: {frontend_openapi_path}"
        )
        with frontend_openapi_path.open(encoding="utf-8") as fp:
            frontend_openapi = json.load(fp)

        live_paths = live_openapi.get("paths", {})
        frontend_paths = frontend_openapi.get("paths", {})

        # path × method 단위 responses 트리 비교
        # (C4 brittle 시 범위 좁힘 가이드 적용).
        diffs: list[str] = []

        live_path_set = set(live_paths.keys())
        frontend_path_set = set(frontend_paths.keys())
        if live_path_set != frontend_path_set:
            only_live = sorted(live_path_set - frontend_path_set)
            only_frontend = sorted(frontend_path_set - live_path_set)
            if only_live:
                diffs.append(f"live에만 존재하는 path: {only_live}")
            if only_frontend:
                diffs.append(f"frontend에만 존재하는 path: {only_frontend}")

        for path in sorted(live_path_set & frontend_path_set):
            live_methods = live_paths[path]
            frontend_methods = frontend_paths[path]
            method_set = set(live_methods.keys()) | set(frontend_methods.keys())
            for method in sorted(method_set):
                live_responses = live_methods.get(method, {}).get("responses")
                frontend_responses = frontend_methods.get(method, {}).get("responses")
                if live_responses != frontend_responses:
                    diffs.append(f"{method.upper()} {path} responses 불일치")

        assert diffs == [], (
            "frontend/openapi.json이 live app.openapi()와 동기화되지 않음:\n"
            + "\n".join(f"  - {d}" for d in diffs)
            + '\n해결: python -c "from ante.web.app import create_app; '
            "import json; print(json.dumps(create_app().openapi(), "
            'ensure_ascii=False, indent=2))" > frontend/openapi.json'
        )


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
        """204를 제외한 모든 API 엔드포인트에 response_model이 설정되어야 한다.

        예외:
        - ``status_code=204`` 라우트 (body 자체가 없음).
        - ``status_code=409`` cold-path 라우트 (#1164): handler가 항상
          ``HTTPException(409)``을 raise하므로 ``response_model`` 검증
          효과가 없으며, 명시 ``responses[409]`` content map이 단일 SSOT.
        """
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
            # cold-path 라우트(status_code=409로 항상 차단)는 response_model
            # 이 의미가 없다. 명시 responses[409] content map이 SSOT.
            if status_code == 409:
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
        4xx/5xx 응답은 ``application/problem+json`` content map에서
        ``ErrorResponse``를 ``$ref``로 가리켜야 OpenAPI/codegen에서
        bodyless 4xx/5xx로 표현되지 않는다 (#1164 정렬 후).

        FastAPI가 자동 생성하는 path/dependency 검증용 422 응답은
        ``HTTPValidationError`` 표준 schema를 사용하지만, 본 PUT 라우트는
        attempt 9에서 mutable 필드 type 검증 실패에 대한 422 응답을 명시
        등록했으므로 본 테스트의 검증 대상에 포함한다. body requestBody의
        schema accuracy(mutable 모델 직접 노출)는 후속 이슈 #1143에서
        다룬다.
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
                problem_json_content = content.get("application/problem+json")
                if problem_json_content is None:
                    missing.append(
                        f"{method.upper()} {path} ({code}): "
                        "application/problem+json content 없음"
                    )
                    continue
                schema = problem_json_content.get("schema", {})
                ref = schema.get("$ref", "")
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
        의 ``application/problem+json`` content map이 ``ErrorResponse``를
        ``$ref``로 가리켜 OpenAPI/codegen에서 422가 bodyless가 아닌
        ``ErrorResponse`` 본문을 갖도록 한다 — 클라이언트는 type-safe하게
        422 응답을 다룰 수 있다 (#1164 정렬 후).

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
        problem_json_content = response_422.get("content", {}).get(
            "application/problem+json"
        )
        assert problem_json_content is not None, (
            "PUT 422에 application/problem+json content 없음"
        )
        ref = problem_json_content.get("schema", {}).get("$ref", "")
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


# ── 이슈 #1153: PUT request body schema accuracy + Content-Type 415 게이트 ─


class TestPutAccountRequestBodySchema:
    """PUT /api/accounts/{account_id} requestBody OpenAPI schema 노출(이슈 #1153).

    런타임 핸들러는 raw body 파싱 + structural 가드(I1/I4) + Content-Type 415
    게이트 + mutable 검증 순서로 처리한다. OpenAPI/codegen 클라이언트는 정확한
    mutable 입력 contract(name/timezone/trading_hours_start/trading_hours_end,
    additionalProperties: False, nullable 없음)를 발견할 수 있어야 한다.

    ``AccountUpdateRequest.model_json_schema()`` 직접 노출은 금지(다른 소비자
    호환을 위해 모든 필드가 ``str | None`` 옵션이고 structural 키도 포함).
    spec-aligned dict 상수 ``ACCOUNT_MUTABLE_UPDATE_REQUEST_SCHEMA``로 별도
    정의해 노출한다.
    """

    @staticmethod
    def _put_request_body(client: TestClient) -> dict:
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        openapi = resp.json()
        spec = (
            openapi.get("paths", {})
            .get("/api/accounts/{account_id}", {})
            .get("put", {})
        )
        request_body = spec.get("requestBody")
        assert request_body is not None, (
            "PUT /api/accounts/{account_id} requestBody가 OpenAPI에 노출되지 않음"
        )
        return request_body

    @staticmethod
    def _put_request_schema(client: TestClient) -> dict:
        request_body = TestPutAccountRequestBodySchema._put_request_body(client)
        json_content = request_body.get("content", {}).get("application/json")
        assert json_content is not None, (
            "PUT /api/accounts/{account_id} requestBody에 application/json content 없음"
        )
        schema = json_content.get("schema")
        assert isinstance(schema, dict), (
            "PUT /api/accounts/{account_id} requestBody schema가 dict가 아님"
        )
        return schema

    def test_openapi_put_account_request_body_is_strict_mutable_schema(self, client):
        """PUT requestBody가 mutable 4 필드 strict schema."""
        schema = self._put_request_schema(client)

        assert schema.get("type") == "object", schema
        # additionalProperties: False — 알 수 없는 키 차단을 contract에 표현
        ap = schema.get("additionalProperties")
        assert ap is False, f"additionalProperties가 False가 아님: {ap!r}"

        properties = schema.get("properties", {})
        expected = {
            "name",
            "timezone",
            "trading_hours_start",
            "trading_hours_end",
        }
        actual = set(properties.keys())
        assert actual == expected, (
            f"mutable 필드가 정확히 4개여야 함. expected={expected}, actual={actual}"
        )

        # 각 property는 단일 type=string, nullable이 아님.
        for name, prop in properties.items():
            assert isinstance(prop, dict), f"properties.{name}가 dict가 아님: {prop!r}"
            assert prop.get("type") == "string", (
                f"properties.{name}.type이 'string'이 아님: {prop!r}"
            )
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

    def test_openapi_put_account_request_body_not_anyof_null(self, client):
        """PUT requestBody schema 자체가 nullable(anyOf null)이 아님."""
        schema = self._put_request_schema(client)

        # schema-level anyOf/oneOf에 null type 변형이 없어야 함
        for combinator in ("anyOf", "oneOf"):
            variants = schema.get(combinator)
            if variants:
                for variant in variants:
                    assert variant.get("type") != "null", (
                        f"requestBody schema {combinator}에 null type 포함: {schema!r}"
                    )

    def test_openapi_put_account_request_body_required_true(self, client):
        """codegen이 body를 optional로 만들지 않도록 requestBody.required: True."""
        request_body = self._put_request_body(client)
        assert request_body.get("required") is True, (
            f"requestBody.required가 True가 아님: {request_body.get('required')!r}"
        )

    def test_openapi_put_account_request_body_has_min_properties(self, client):
        """PUT requestBody schema에 ``minProperties: 1``이 노출된다(이슈 #1152).

        빈 dict(``{}``) / 빈 body / ``{"name": null}`` 처럼 effective payload가
        비는 요청은 422 Unprocessable Entity로 응답한다. 이는 OpenAPI 계약으로
        ``minProperties: 1``로 표현되며, requestBody schema에만 적용된다 —
        응답 content-type customizer(#1164)와 entangle 금지.
        """
        schema = self._put_request_schema(client)
        assert schema.get("minProperties") == 1, (
            f"requestBody schema.minProperties가 1이 아님: {schema!r}"
        )

    def test_openapi_put_account_415_references_error_response(self, client):
        """PUT 415 응답이 ErrorResponse를 가리킨다.

        명시 415 응답은 ``application/problem+json`` content map의
        ``$ref``로 ``ErrorResponse``를 노출한다 (#1164 정렬 후).
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
        response_415 = responses.get("415")
        assert response_415 is not None, "PUT 415 응답이 명시 등록되지 않음"
        problem_json_content = response_415.get("content", {}).get(
            "application/problem+json"
        )
        assert problem_json_content is not None, (
            "PUT 415에 application/problem+json content 없음"
        )
        ref = problem_json_content.get("schema", {}).get("$ref", "")
        assert "ErrorResponse" in ref, (
            f"PUT 415가 ErrorResponse를 가리키지 않음 (schema ref={ref!r})"
        )


class TestGeneratedTsPutAccountRequestBody:
    """generated TS api.generated.ts에서 PUT /api/accounts/{account_id} request
    body가 spec-aligned 형태로 노출되는지 보조 단언(이슈 #1153).

    같은 PR에 ``frontend/src/types/api.generated.ts``가 함께 갱신되어야 하므로
    generated artifact drift를 차단한다.
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
    def _put_account_operation_block(text: str) -> str:
        """update_account_api_accounts__account_id__put operation 블록을 잘라낸다."""
        marker = "update_account_api_accounts__account_id__put:"
        idx = text.find(marker)
        assert idx != -1, "generated TS에 update_account operation이 없음"
        rest = text[idx:]
        next_markers = [
            "delete_account_api_accounts__account_id__delete:",
            "suspend_account_api_accounts__account_id__suspend_post:",
            "activate_account_api_accounts__account_id__activate_post:",
            "get_account_rules_api_accounts__account_id__rules_get:",
        ]
        end_offsets = [rest.find(m, 1) for m in next_markers]
        end_offsets = [o for o in end_offsets if o != -1]
        end = min(end_offsets) if end_offsets else len(rest)
        return rest[:end]

    def test_generated_ts_put_account_request_body_not_unknown_or_null(self):
        """PUT body가 `{ [key: string]: unknown } | null` 패턴이 아니어야 한다."""
        block = self._put_account_operation_block(self._generated_ts_text())
        # 회귀 패턴: anyOf null 노출이 sanitize되지 않은 경우 ` | null` 또는
        # `[key: string]: unknown` 단독 패턴이 등장.
        assert " | null" not in block, (
            "PUT body가 nullable로 노출됨(`| null` 회귀):\n" + block
        )
        # body가 unknown record로 좁혀지면 안 된다(spec-aligned mutable 4 필드).
        assert "[key: string]: unknown" not in block, (
            "PUT body가 unknown record로 좁혀짐:\n" + block
        )

    def test_generated_ts_put_account_request_body_required_not_optional(self):
        """PUT body가 optional 표시(?:)가 아닌 required."""
        block = self._put_account_operation_block(self._generated_ts_text())
        assert "requestBody?:" not in block, "PUT body가 optional로 노출됨:\n" + block
        assert "requestBody:" in block, "PUT에 requestBody: 정의가 없음:\n" + block

    def test_generated_ts_put_account_mutable_fields_not_nullable(self):
        """mutable 필드 4개가 `string | null`이 아니라 `string`."""
        block = self._put_account_operation_block(self._generated_ts_text())
        for field in ("name", "timezone", "trading_hours_start", "trading_hours_end"):
            # `field?: string;` 또는 `field: string;` 패턴 검출. nullable 부재 단언.
            assert f"{field}?: string | null" not in block, (
                f"PUT body의 {field}이 nullable로 노출됨:\n" + block
            )
            assert f"{field}: string | null" not in block, (
                f"PUT body의 {field}이 nullable로 노출됨:\n" + block
            )
