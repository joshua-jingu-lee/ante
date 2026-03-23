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
    """자금 관리 (필수).

    app.state.treasury가 없으면 treasury_manager에서
    첫 번째 Treasury 인스턴스를 fallback으로 반환한다.
    """
    svc = getattr(request.app.state, "treasury", None)
    if svc is not None:
        return svc

    # fallback: treasury_manager에서 첫 번째 Treasury 반환
    manager = getattr(request.app.state, "treasury_manager", None)
    if manager is not None:
        treasuries = manager.list_all()
        if treasuries:
            return treasuries[0]

    raise HTTPException(status_code=503, detail="Treasury not available")


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


def get_account_service(request: Request) -> Any:
    """계좌 서비스 (필수)."""
    svc = getattr(request.app.state, "account_service", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Account service not available")
    return svc


def get_treasury_manager(request: Request) -> Any:
    """Treasury 매니저 (필수)."""
    svc = getattr(request.app.state, "treasury_manager", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Treasury manager not available")
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


def get_db_optional(request: Request) -> Any | None:
    """데이터베이스 (선택적). 없으면 None."""
    return getattr(request.app.state, "db", None)


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


def get_account_service_optional(request: Request) -> Any | None:
    """계좌 서비스 (선택적). 없으면 None."""
    return getattr(request.app.state, "account_service", None)


def get_treasury_manager_optional(request: Request) -> Any | None:
    """Treasury 매니저 (선택적). 없으면 None."""
    return getattr(request.app.state, "treasury_manager", None)


def get_config(request: Request) -> Any | None:
    """앱 설정 (선택적). 없으면 None."""
    return getattr(request.app.state, "config", None)


def get_broker(request: Request) -> Any | None:
    """브로커 (선택적). 없으면 None."""
    return getattr(request.app.state, "broker", None)


def get_audit_logger_optional(request: Request) -> Any | None:
    """감사 로거 (선택적). 없으면 None."""
    return getattr(request.app.state, "audit_logger", None)


def get_event_history_store(request: Request) -> Any:
    """이벤트 히스토리 저장소 (필수)."""
    svc = getattr(request.app.state, "event_history_store", None)
    if svc is None:
        raise HTTPException(status_code=503, detail="Event history store not available")
    return svc


def get_event_history_store_optional(request: Request) -> Any | None:
    """이벤트 히스토리 저장소 (선택적). 없으면 None."""
    return getattr(request.app.state, "event_history_store", None)


def get_eventbus_optional(request: Request) -> Any | None:
    """EventBus (선택적). 없으면 None."""
    return getattr(request.app.state, "eventbus", None)
