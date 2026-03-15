"""FastAPI 앱 생성."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


def create_app(**services: Any) -> FastAPI:
    """FastAPI 앱 생성. 서비스 의존성 주입.

    Args:
        **services: app.state에 저장될 서비스 인스턴스.
            예: bot_manager, trade_service, treasury, report_store,
                eventbus, data_catalog, data_store, config
    """
    app = FastAPI(
        title="Ante",
        version="0.1.0",
        description="AI-Native Trading Engine API",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    for name, service in services.items():
        setattr(app.state, name, service)

    from ante.web.routes.audit import router as audit_router
    from ante.web.routes.bots import router as bots_router
    from ante.web.routes.data import router as data_router
    from ante.web.routes.notifications import router as notifications_router
    from ante.web.routes.portfolio import router as portfolio_router
    from ante.web.routes.reports import router as report_router
    from ante.web.routes.strategies import router as strategy_router
    from ante.web.routes.system import router as system_router
    from ante.web.routes.trades import router as trades_router
    from ante.web.routes.treasury import router as treasury_router

    app.include_router(audit_router, prefix="/api/audit", tags=["audit"])
    app.include_router(portfolio_router, prefix="/api/portfolio", tags=["portfolio"])
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

    return app
