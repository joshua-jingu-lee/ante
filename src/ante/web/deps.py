"""Web API 공통 의존성 함수.

모든 라우트 핸들러는 getattr(request.app.state, ...) 대신
이 모듈의 의존성 함수를 Annotated[Type, Depends(...)] 형태로 사용한다.

필수 의존성: 서비스가 없으면 HTTPException 503을 발생시킨다.
선택적 의존성: 서비스가 없으면 None을 반환한다.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException, Request

# ── 필수 의존성 ─────────────────────────────────────────


def get_approval_service(request: Request) -> Any:
    """결재 서비스 (필수)."""
    svc = getattr(request.app.state, "approval_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Approval service not available")
    return svc


def get_audit_logger(request: Request) -> Any:
    """감사 로거 (필수)."""
    svc = getattr(request.app.state, "audit_logger", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Audit logger not available")
    return svc


def get_bot_manager(request: Request) -> Any:
    """봇 매니저 (필수)."""
    svc = getattr(request.app.state, "bot_manager", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Bot manager not available")
    return svc


def get_strategy_registry(request: Request) -> Any:
    """전략 레지스트리 (필수)."""
    svc = getattr(request.app.state, "strategy_registry", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Strategy registry not available")
    return svc


def get_treasury(request: Request) -> Any:
    """자금 관리 (필수)."""
    svc = getattr(request.app.state, "treasury", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Treasury not available")
    return svc


def get_trade_service(request: Request) -> Any:
    """거래 서비스 (필수)."""
    svc = getattr(request.app.state, "trade_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Trade service not available")
    return svc


def get_report_store(request: Request) -> Any:
    """리포트 저장소 (필수)."""
    svc = getattr(request.app.state, "report_store", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Report store not available")
    return svc


def get_dynamic_config(request: Request) -> Any:
    """동적 설정 서비스 (필수)."""
    svc = getattr(request.app.state, "dynamic_config", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Config service not available")
    return svc


def get_system_state(request: Request) -> Any:
    """시스템 상태 (필수)."""
    svc = getattr(request.app.state, "system_state", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="System state not available")
    return svc


def get_notification_service(request: Request) -> Any:
    """알림 서비스 (필수)."""
    svc = getattr(request.app.state, "notification_service", None)
    if svc is None:
        raise HTTPException(
            status_code=503, detail="Notification service not available"
        )
    return svc


def get_member_service(request: Request) -> Any:
    """멤버 서비스 (필수)."""
    svc = getattr(request.app.state, "member_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Member service not available")
    return svc


def get_session_service(request: Request) -> Any:
    """세션 서비스 (필수)."""
    svc = getattr(request.app.state, "session_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Session service not available")
    return svc


def get_db(request: Request) -> Any:
    """데이터베이스 (필수)."""
    db = getattr(request.app.state, "db", None)
    if db is None:
        raise HTTPException(status_code=503, detail="Database not available")
    return db


# ── 선택적 의존성 ───────────────────────────────────────


def get_data_store(request: Request) -> Any | None:
    """데이터 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "data_store", None)


def get_bot_manager_optional(request: Request) -> Any | None:
    """봇 매니저 (선택적). 없으면 None."""
    return getattr(request.app.state, "bot_manager", None)


def get_strategy_registry_optional(request: Request) -> Any | None:
    """전략 레지스트리 (선택적). 없으면 None."""
    return getattr(request.app.state, "strategy_registry", None)


def get_treasury_optional(request: Request) -> Any | None:
    """자금 관리 (선택적). 없으면 None."""
    return getattr(request.app.state, "treasury", None)


def get_trade_service_optional(request: Request) -> Any | None:
    """거래 서비스 (선택적). 없으면 None."""
    return getattr(request.app.state, "trade_service", None)


def get_report_store_optional(request: Request) -> Any | None:
    """리포트 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "report_store", None)


def get_system_state_optional(request: Request) -> Any | None:
    """시스템 상태 (선택적). 없으면 None."""
    return getattr(request.app.state, "system_state", None)


def get_config(request: Request) -> Any | None:
    """앱 설정 (선택적). 없으면 None."""
    return getattr(request.app.state, "config", None)


def get_broker(request: Request) -> Any | None:
    """브로커 (선택적). 없으면 None."""
    return getattr(request.app.state, "broker", None)


def get_audit_logger_optional(request: Request) -> Any | None:
    """감사 로거 (선택적). 없으면 None."""
    return getattr(request.app.state, "audit_logger", None)
