"""FastAPI 앱 생성."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.staticfiles import StaticFiles

from ante import __version__
from ante.web.schemas import ErrorResponse

logger = logging.getLogger(__name__)

# 프론트엔드 정적 파일 탐색 순서:
# 1) 패키지 내장 (pip install ante 시 포함)
# 2) 개발 환경 (frontend/dist/ 직접 빌드)
_BUNDLED_DIR = Path(__file__).resolve().parent / "static"
_DEV_DIR = Path(__file__).resolve().parents[3] / "frontend" / "dist"


def _get_frontend_dir() -> Path | None:
    """프론트엔드 빌드 디렉토리를 탐색한다."""
    for candidate in (_BUNDLED_DIR, _DEV_DIR):
        if (candidate / "index.html").is_file():
            return candidate
    return None


def create_app(**services: Any) -> FastAPI:
    """FastAPI 앱 생성. 서비스 의존성 주입.

    Args:
        **services: app.state에 저장될 서비스 인스턴스.
            예: bot_manager, trade_service, treasury, report_store,
                eventbus, data_catalog, data_store, config
    """
    app = FastAPI(
        title="Ante",
        version=__version__,
        description="AI-Native Trading Engine API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from ante.web.middleware.audit import AuditMiddleware
    from ante.web.middleware.token_auth import TokenAuthMiddleware

    app.add_middleware(AuditMiddleware)
    app.add_middleware(TokenAuthMiddleware)

    for name, service in services.items():
        setattr(app.state, name, service)

    from ante.web.routes.accounts import router as accounts_router
    from ante.web.routes.approvals import router as approvals_router
    from ante.web.routes.audit import router as audit_router
    from ante.web.routes.auth import router as auth_router
    from ante.web.routes.bots import router as bots_router
    from ante.web.routes.config import router as config_router
    from ante.web.routes.data import router as data_router
    from ante.web.routes.members import router as members_router
    from ante.web.routes.notifications import router as notifications_router
    from ante.web.routes.portfolio import router as portfolio_router
    from ante.web.routes.reports import router as report_router
    from ante.web.routes.strategies import router as strategy_router
    from ante.web.routes.system import router as system_router
    from ante.web.routes.trades import router as trades_router
    from ante.web.routes.treasury import router as treasury_router

    app.include_router(accounts_router, prefix="/api/accounts", tags=["accounts"])
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    app.include_router(approvals_router, prefix="/api/approvals", tags=["approvals"])
    app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
    app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
    app.include_router(members_router, prefix="/api/members", tags=["members"])
    app.include_router(config_router, prefix="/api/config", tags=["config"])
    app.include_router(system_router, prefix="/api/system", tags=["system"])
    app.include_router(strategy_router, prefix="/api/strategies", tags=["strategies"])
    app.include_router(report_router, prefix="/api/reports", tags=["reports"])
    app.include_router(data_router, prefix="/api/data", tags=["data"])
    app.include_router(trades_router, prefix="/api/trades", tags=["trades"])
    app.include_router(bots_router, prefix="/api/bots", tags=["bots"])
    app.include_router(treasury_router, prefix="/api/treasury", tags=["treasury"])
    app.include_router(
        notifications_router,
        prefix="/api/notifications",
        tags=["notifications"],
    )

    from ante.web.errors import register_exception_handlers

    register_exception_handlers(app)

    # OpenAPI customizer 설치 — components.schemas.ErrorResponse 보장 (#1164).
    _install_openapi_customizer(app)

    # 프론트엔드 정적 파일 서빙 (빌드 결과물이 존재할 때만)
    _mount_frontend(app)

    return app


def _install_openapi_customizer(app: FastAPI) -> None:
    """OpenAPI customizer 단일 설치 지점 (#1164).

    - ``ErrorResponse``가 ``components.schemas``에 항상 등록되도록 보장.
      라우트 모듈에서 ``model: ErrorResponse`` shorthand를 제거하고 명시
      ``$ref`` 매핑만 남기면 FastAPI 기본 동작에서 ``ErrorResponse``
      component가 누락될 수 있다. ``setdefault``로 fallback 등록한다.
    - ``MemberCreateRequest``가 ``components.schemas``에 항상 등록되도록 보장
      (#1339 P1 — Codex finding). POST /api/members 라우트는 인증 가드가
      body validation보다 먼저 실행되어야 해서 raw body 패턴을 쓴다. 이 때
      ``body: MemberCreateRequest`` 파라미터가 라우트 시그니처에 없어
      FastAPI 자동 components 등록 경로를 타지 않는다. inline schema로 두면
      frontend codegen이 ``export type MemberCreateRequest``를 만들지 못해
      ``frontend/src/api/members.ts`` 빌드가 깨진다. 그래서 라우트
      ``openapi_extra``는 ``$ref`` 매핑만 노출하고 본체 schema는 여기서
      등록한다.
    - ``ScopesUpdateRequest`` 도 동일한 이유로 등록 보장(#1351 1차 Codex
      review FAIL — Finding 1). PUT /api/members/{id}/scopes 가 raw body
      패턴으로 전환되면서 ``body: ScopesUpdateRequest`` 인자가 시그니처에서
      사라졌고, frontend codegen에서 ``ScopesUpdateRequest`` export가 누락되어
      ``frontend/src/api/members.ts`` 의 ``tsc -b`` 빌드가 깨진다.
      ``MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA`` 본체를 ``components.schemas``에
      ``setdefault`` 등록한다.
    - ``BotUpdateRequest``, ``BalanceSetRequest`` 도 동일 이유로 등록 보장
      (#1352). PUT /api/bots/{id} 와 POST /api/treasury/balance 가 raw body
      패턴으로 전환되면서 ``body: BotUpdateRequest`` / ``body: BalanceSetRequest``
      인자가 시그니처에서 사라졌고, frontend codegen에서 두 타입 export가
      누락되어 ``frontend/src/api/bots.ts`` / ``treasury.ts``의 ``tsc -b``
      빌드가 깨진다. ``BOT_UPDATE_REQUEST_SCHEMA`` /
      ``BALANCE_SET_REQUEST_SCHEMA`` 본체를 ``components.schemas``에
      ``setdefault`` 등록한다.
    - ``AccountSuspendRequest`` 도 동일 이유로 등록 보장(#1352 2차 Codex
      review FAIL). POST /api/accounts/{id}/suspend 가 raw body 패턴으로
      전환되면서 ``body: AccountSuspendRequest`` 인자가 시그니처에서 사라졌고,
      inline schema로 두면 frontend codegen이
      ``export type AccountSuspendRequest``를 만들지 못한다.
      ``ACCOUNT_SUSPEND_REQUEST_SCHEMA`` 본체를 ``components.schemas``에
      ``setdefault`` 등록한다.
    - 명시 4xx/5xx 응답에서 FastAPI가 자동 추가한 빈 ``application/json``
      content entry를 제거한다. ``status_code=409`` 같은 데코레이터를 사용한
      cold-path 라우트(``accounts.py`` POST/DELETE)에서 success contract용
      빈 schema가 응답 entry에 자동 병합되어 ``application/json`` +
      ``application/problem+json`` split이 발생한다. ``$ref``가 비어 있는
      ``application/json`` entry만 정리해 명시 ``application/problem+json``
      매핑이 단일 노출되도록 한다. ``HTTPValidationError`` ref를 갖는 422
      자동 응답은 보존한다 (FastAPI 기본 동작 유지, 본 이슈 Non-Goal).
    - 향후 다른 customizer가 필요하면 같은 함수에 모은다.
    """
    # 지연 import: ``app.py``는 라우트 모듈을 ``create_app`` 내부에서만
    # import하므로 모듈 top-level circular import를 피하려면 같은 패턴을
    # 따른다.
    from ante.web.routes.accounts import ACCOUNT_SUSPEND_REQUEST_SCHEMA
    from ante.web.routes.bots import BOT_UPDATE_REQUEST_SCHEMA
    from ante.web.routes.members import (
        MEMBER_CREATE_REQUEST_SCHEMA,
        MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA,
    )
    from ante.web.routes.treasury import BALANCE_SET_REQUEST_SCHEMA

    def custom_openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=getattr(app, "openapi_tags", None),
            servers=getattr(app, "servers", None),
        )
        schemas = schema.setdefault("components", {}).setdefault("schemas", {})
        schemas.setdefault("ErrorResponse", ErrorResponse.model_json_schema())
        schemas.setdefault("MemberCreateRequest", MEMBER_CREATE_REQUEST_SCHEMA)
        schemas.setdefault("ScopesUpdateRequest", MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA)
        schemas.setdefault("BotUpdateRequest", BOT_UPDATE_REQUEST_SCHEMA)
        schemas.setdefault("BalanceSetRequest", BALANCE_SET_REQUEST_SCHEMA)
        schemas.setdefault("AccountSuspendRequest", ACCOUNT_SUSPEND_REQUEST_SCHEMA)
        _strip_autogenerated_application_json(schema)
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


def _strip_autogenerated_application_json(schema: dict[str, Any]) -> None:
    """4xx/5xx 응답에서 FastAPI가 자동 생성한 빈 ``application/json`` entry 제거.

    조건:
    - status code가 4xx/5xx (``int(code) >= 400``).
    - ``content`` map에 ``application/problem+json`` (``$ref`` 명시 매핑)이
      함께 등록되어 있다.
    - ``content["application/json"]["schema"]`` 가 비어 있다 (``{}``) — 즉
      autogeneration 결과로 본다. ``$ref``가 있는 명시 entry는 보존한다.
      특히 ``HTTPValidationError`` ref를 갖는 422 자동 응답은 보존된다 —
      해당 entry는 ``application/problem+json``과 동시에 등장하지 않으므로
      위 두 번째 조건에서 자연 제외된다.

    이 customizer 분기는 ``status_code=`` 데코레이터를 사용한 cold-path
    핸들러(``accounts.py`` POST/DELETE)에서 발생하는 split을 흡수한다.
    """
    paths = schema.get("paths", {})
    if not isinstance(paths, dict):
        return
    for methods in paths.values():
        if not isinstance(methods, dict):
            continue
        for spec in methods.values():
            if not isinstance(spec, dict):
                continue
            responses = spec.get("responses")
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
                if "application/problem+json" not in content:
                    continue
                json_obj = content.get("application/json")
                if not isinstance(json_obj, dict):
                    continue
                schema_obj = json_obj.get("schema")
                if isinstance(schema_obj, dict) and not schema_obj:
                    del content["application/json"]


def _mount_frontend(app: FastAPI) -> None:
    """프론트엔드 정적 파일 서빙 + SPA fallback 설정."""
    frontend_dir = _get_frontend_dir()

    if frontend_dir is None:
        logger.info("프론트엔드 빌드 없음 — 정적 파일 서빙 비활성화")
        return

    static_dir: Path = frontend_dir
    index_html = static_dir / "index.html"
    logger.info("프론트엔드 정적 파일 서빙: %s", static_dir)

    # /assets/* 빌드 산출물 서빙 (Vite 번들)
    assets_dir = static_dir / "assets"
    if assets_dir.is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets_dir)),
            name="frontend-assets",
        )

    # SPA fallback middleware: /api 외 404 → index.html
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response

    class SPAFallbackMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next: Any) -> Response:
            response = await call_next(request)
            path = request.url.path

            # API 경로는 그대로 반환
            if path.startswith("/api"):
                return response

            # 404인 비-API 요청: 정적 파일이 있으면 반환, 없으면 index.html
            if response.status_code == 404:
                from fastapi.responses import FileResponse

                file_path = static_dir / path.lstrip("/")
                if file_path.is_file():
                    return FileResponse(str(file_path))
                return FileResponse(str(index_html))

            return response

    app.add_middleware(SPAFallbackMiddleware)
