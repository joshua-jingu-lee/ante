"""시스템 상태 API."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ante.web.deps import (
    get_account_service,
    get_account_service_optional,
    get_audit_logger_optional,
    get_db_optional,
)
from ante.web.schemas import HealthResponse, KillSwitchResponse, StatusResponse

logger = logging.getLogger(__name__)

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
    db: Annotated[Any | None, Depends(get_db_optional)],
    account_service: Annotated[Any | None, Depends(get_account_service_optional)],
) -> dict:
    """헬스체크.

    - `db`: `SELECT 1` 성공 여부.
    - `broker`: 모든 계좌의 `broker.is_connected == True` AND 축약.
      계좌 0개이면 True. account_service 미주입 시 False (unhealthy).
    각 체크는 독립적이며, 예외는 내부에서 포착하고 해당 항목만 False로 기록한다.
    HTTP 상태 코드는 체크 결과와 무관하게 항상 200이다.
    """
    checks: dict[str, bool] = {}

    # db 체크
    checks["db"] = await _check_db(db)

    # broker 체크
    checks["broker"] = await _check_broker(account_service)

    return {"ok": all(checks.values()), "checks": checks}


async def _check_db(db: Any | None) -> bool:
    """DB 연결 체크. SELECT 1 성공 시 True."""
    if db is None:
        return False
    try:
        await db.fetch_one("SELECT 1")
        return True
    except Exception:  # noqa: BLE001
        logger.exception("health check: db failed")
        return False


async def _check_broker(account_service: Any | None) -> bool:
    """브로커 연결 체크. 모든 계좌의 is_connected AND.

    - 계좌 0개이면 True (스펙: 초기 설정 단계 허용).
    - account_service 미주입은 False (unhealthy): 계좌 정보를 확인할 수 없는
      상태는 "브로커 정상"으로 판정할 수 없다.
    """
    if account_service is None:
        return False
    try:
        accounts = await account_service.list()
    except Exception:  # noqa: BLE001
        logger.exception("health check: account_service.list failed")
        return False

    if not accounts:
        return True

    for account in accounts:
        try:
            broker = await account_service.get_broker(account.account_id)
        except Exception:  # noqa: BLE001
            logger.exception(
                "health check: get_broker failed for %s", account.account_id
            )
            return False
        if not getattr(broker, "is_connected", False):
            return False
    return True


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
