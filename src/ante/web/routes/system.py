"""시스템 상태 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ante.web.deps import (
    get_account_service,
    get_account_service_optional,
    get_audit_logger_optional,
)
from ante.web.schemas import HealthResponse, KillSwitchResponse, StatusResponse

router = APIRouter()


class HaltRequest(BaseModel):
    """거래 중지 요청."""

    reason: str = ""


class ActivateRequest(BaseModel):
    """거래 재개 요청."""

    reason: str = ""


@router.get("/status", response_model=StatusResponse)
async def get_system_status(
    account_service: Annotated[Any | None, Depends(get_account_service_optional)],
) -> dict:
    """시스템 상태 조회."""
    result: dict = {
        "status": "running",
        "version": "0.1.0",
    }

    if account_service is not None:
        from ante.account.models import AccountStatus

        accounts = await account_service.list()
        suspended = [a for a in accounts if a.status == AccountStatus.SUSPENDED]
        if suspended:
            result["trading_status"] = "SUSPENDED"
        else:
            result["trading_status"] = "ACTIVE"

    return result


@router.get("/health", response_model=HealthResponse)
async def health_check(
    request: Request,
    account_service: Annotated[Any | None, Depends(get_account_service_optional)],
) -> dict:
    """헬스체크 — 핵심 의존성(DB, Broker)의 실제 상태를 반영한다."""
    checks: dict[str, bool] = {"db": False, "broker": False}

    # DB 접근 확인
    db = getattr(request.app.state, "db", None)
    if db is not None:
        try:
            await db.fetch_one("SELECT 1")
            checks["db"] = True
        except Exception:
            pass

    # Broker 연결 확인: 연결된 Broker 1개라도 있으면 True
    if account_service is not None:
        try:
            accounts = await account_service.list()
            for a in accounts:
                try:
                    broker = await account_service.get_broker(a.account_id)
                    if getattr(broker, "connected", False):
                        checks["broker"] = True
                        break
                except Exception:
                    continue
        except Exception:
            pass

    ok = all(checks.values())
    return {"ok": ok, "checks": checks}


@router.post(
    "/halt",
    response_model=KillSwitchResponse,
    responses={
        503: {"description": "Account service not available"},
    },
)
async def halt(
    body: HaltRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전체 거래 중지 (모든 계좌 SUSPENDED)."""
    from datetime import UTC, datetime

    reason = body.reason or "dashboard"
    count = await account_service.suspend_all(reason=reason, suspended_by="dashboard")

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="system.halt",
            resource="system:kill_switch",
            detail=body.reason,
            ip=request.client.host if request.client else "",
        )

    return {
        "status": f"suspended ({count} accounts)",
        "changed_at": datetime.now(UTC).isoformat(),
    }


@router.post(
    "/activate",
    response_model=KillSwitchResponse,
    responses={
        503: {"description": "Account service not available"},
    },
)
async def activate(
    body: ActivateRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전체 거래 재개 (모든 계좌 ACTIVE)."""
    from datetime import UTC, datetime

    count = await account_service.activate_all(activated_by="dashboard")

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="system.activate",
            resource="system:kill_switch",
            detail=body.reason,
            ip=request.client.host if request.client else "",
        )

    return {
        "status": f"activated ({count} accounts)",
        "changed_at": datetime.now(UTC).isoformat(),
    }
