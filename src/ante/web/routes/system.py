"""시스템 상태 API."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from ante import __version__
from ante.web.deps import (
    get_account_service,
    get_account_service_optional,
    get_audit_logger_optional,
    get_db_optional,
)
from ante.web.schemas import (
    HealthResponse,
    KillSwitchResponse,
    StatusResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class HaltRequest(BaseModel):
    """거래 중지 요청."""

    reason: str = ""


class ClearHaltRequest(BaseModel):
    """전역 정지 해제 요청."""

    reason: str = ""


@router.get("/status", response_model=StatusResponse)
async def get_system_status(
    account_service: Annotated[Any | None, Depends(get_account_service_optional)],
) -> dict:
    """시스템 상태 조회."""
    result: dict = {
        "status": "running",
        "version": __version__,
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


def _kill_switch_payload(status: str, accounts: list[dict[str, Any]]) -> dict:
    """Kill Switch 응답 envelope.

    SSOT: ``docs/specs/web-api/04-system-endpoints.md`` Kill Switch 응답 SSOT.
    ``changed_at``은 ISO 8601 UTC ``Z`` suffix를 사용한다 (Refs #1360).
    """
    from datetime import UTC, datetime

    from ante.core.time import format_utc

    return {
        "status": status,
        "accounts_changed": sum(1 for a in accounts if a.get("changed")),
        "changed_at": format_utc(datetime.now(UTC)),
        "accounts": accounts,
    }


@router.post(
    "/halt",
    response_model=KillSwitchResponse,
    responses={
        503: {
            "description": "Account service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def halt(
    body: HaltRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전체 거래 중지 (모든 ACTIVE 계좌 SUSPENDED)."""
    reason = body.reason or "dashboard"
    accounts = await account_service.suspend_all(
        reason=reason, suspended_by="dashboard"
    )

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="system.halt",
            resource="system:kill_switch",
            detail=body.reason,
            ip=request.client.host if request.client else "",
        )

    return _kill_switch_payload("halted", accounts)


@router.post(
    "/clear-halt",
    response_model=KillSwitchResponse,
    responses={
        503: {
            "description": "Account service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def clear_halt(
    body: ClearHaltRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전역 정지 해제 (모든 SUSPENDED 계좌 ACTIVE).

    계좌 상태만 ACTIVE로 복구하며 봇을 자동 재시작하지 않는다.
    """
    accounts = await account_service.activate_all(activated_by="dashboard")

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="system.clear_halt",
            resource="system:kill_switch",
            detail=body.reason,
            ip=request.client.host if request.client else "",
        )

    return _kill_switch_payload("halt_cleared", accounts)
