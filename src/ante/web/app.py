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
    - 향후 다른 customizer가 필요하면 같은 함수에 모은다.
    """

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
        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi  # type: ignore[method-assign]


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
