"""Account REST API — 계좌 CRUD + 정지/활성화."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ante.web.deps import get_account_service, get_audit_logger_optional
from ante.web.schemas import (
    AccountActionResponse,
    AccountCreateRequest,
    AccountDetailResponse,
    AccountListResponse,
    AccountSuspendRequest,
    AccountUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _account_to_response(account: Any) -> dict[str, Any]:
    """Account 객체를 AccountResponse 호환 dict로 변환.

    credentials는 보안상 응답에 포함하지 않는다.
    """
    return {
        "account_id": account.account_id,
        "name": account.name,
        "exchange": account.exchange,
        "currency": account.currency,
        "timezone": account.timezone,
        "trading_hours_start": account.trading_hours_start,
        "trading_hours_end": account.trading_hours_end,
        "trading_mode": (
            account.trading_mode.value
            if hasattr(account.trading_mode, "value")
            else str(account.trading_mode)
        ),
        "broker_type": account.broker_type,
        "buy_commission_rate": float(account.buy_commission_rate),
        "sell_commission_rate": float(account.sell_commission_rate),
        "status": (
            account.status.value
            if hasattr(account.status, "value")
            else str(account.status)
        ),
        "created_at": (account.created_at.isoformat() if account.created_at else ""),
        "updated_at": (account.updated_at.isoformat() if account.updated_at else ""),
    }


@router.get("", response_model=AccountListResponse)
async def list_accounts(
    account_service: Annotated[Any, Depends(get_account_service)],
    status: str | None = None,
) -> dict[str, Any]:
    """계좌 목록 조회."""
    from ante.account.models import AccountStatus

    filter_status: AccountStatus | None = None
    if status is not None:
        try:
            filter_status = AccountStatus(status)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"유효하지 않은 status 값: '{status}'. "
                f"가능한 값: {[s.value for s in AccountStatus]}",
            )

    accounts = await account_service.list(status=filter_status)
    return {"accounts": [_account_to_response(a) for a in accounts]}


@router.post("", response_model=AccountDetailResponse, status_code=201)
async def create_account(
    body: AccountCreateRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 생성."""
    from ante.account.errors import (
        AccountAlreadyExistsError,
        InvalidBrokerTypeError,
    )
    from ante.account.models import Account, TradingMode
    from ante.account.presets import BROKER_PRESETS

    # broker_type에서 프리셋 기본값 적용
    preset = BROKER_PRESETS.get(body.broker_type)

    try:
        trading_mode = TradingMode(body.trading_mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"유효하지 않은 trading_mode: '{body.trading_mode}'",
        )

    from decimal import Decimal

    account = Account(
        account_id=body.account_id,
        name=body.name,
        exchange=body.exchange or (preset.exchange if preset else ""),
        currency=body.currency or (preset.currency if preset else ""),
        timezone=body.timezone or (preset.timezone if preset else "Asia/Seoul"),
        trading_hours_start=body.trading_hours_start
        or (preset.trading_hours_start if preset else "09:00"),
        trading_hours_end=body.trading_hours_end
        or (preset.trading_hours_end if preset else "15:30"),
        trading_mode=trading_mode,
        broker_type=body.broker_type,
        credentials=body.credentials,
        buy_commission_rate=Decimal(str(body.buy_commission_rate))
        if body.buy_commission_rate
        else (preset.buy_commission_rate if preset else Decimal("0")),
        sell_commission_rate=Decimal(str(body.sell_commission_rate))
        if body.sell_commission_rate
        else (preset.sell_commission_rate if preset else Decimal("0")),
    )

    try:
        created = await account_service.create(account)
    except InvalidBrokerTypeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except AccountAlreadyExistsError as e:
        raise HTTPException(status_code=409, detail=str(e))

    # 브로커 어댑터 인스턴스 생성 가능 여부 검증
    # kis-overseas 등 BROKER_REGISTRY에 미등록된 타입은 생성 직후 롤백
    try:
        await account_service.get_broker(created.account_id)
    except InvalidBrokerTypeError as e:
        await account_service.delete(created.account_id, deleted_by="system")
        raise HTTPException(status_code=400, detail=str(e))

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="account.create",
            resource=f"account:{created.account_id}",
            detail=f"계좌 생성: {created.account_id} ({created.broker_type})",
            ip=request.client.host if request.client else "",
        )

    return {"account": _account_to_response(created)}


@router.get("/{account_id}", response_model=AccountDetailResponse)
async def get_account(
    account_id: str,
    account_service: Annotated[Any, Depends(get_account_service)],
) -> dict[str, Any]:
    """계좌 상세 조회."""
    from ante.account.errors import AccountNotFoundError

    try:
        account = await account_service.get(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return {"account": _account_to_response(account)}


@router.put("/{account_id}", response_model=AccountDetailResponse)
async def update_account(
    account_id: str,
    body: AccountUpdateRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 수정."""
    from ante.account.errors import AccountDeletedError, AccountNotFoundError

    # None이 아닌 필드만 업데이트 대상
    fields: dict[str, Any] = {}
    for field_name in (
        "name",
        "exchange",
        "currency",
        "timezone",
        "trading_hours_start",
        "trading_hours_end",
        "trading_mode",
        "broker_type",
        "credentials",
        "buy_commission_rate",
        "sell_commission_rate",
    ):
        value = getattr(body, field_name, None)
        if value is not None:
            if field_name in ("buy_commission_rate", "sell_commission_rate"):
                from decimal import Decimal

                value = Decimal(str(value))
            elif field_name == "trading_mode":
                from ante.account.models import TradingMode

                try:
                    value = TradingMode(value)
                except ValueError:
                    raise HTTPException(
                        status_code=400,
                        detail=f"유효하지 않은 trading_mode: '{value}'",
                    )
            fields[field_name] = value

    if not fields:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    try:
        updated = await account_service.update(account_id, **fields)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountDeletedError as e:
        raise HTTPException(status_code=400, detail=str(e))

    if audit_logger:
        await audit_logger.log(
            member_id=getattr(request.state, "member_id", "dashboard"),
            action="account.update",
            resource=f"account:{account_id}",
            detail=f"계좌 수정: {list(fields.keys())}",
            ip=request.client.host if request.client else "",
        )

    return {"account": _account_to_response(updated)}


@router.post("/{account_id}/suspend", response_model=AccountActionResponse)
async def suspend_account(
    account_id: str,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
    body: AccountSuspendRequest | None = None,
) -> dict[str, Any]:
    """계좌 정지."""
    from ante.account.errors import AccountNotFoundError

    reason = (body.reason if body else None) or "dashboard"
    suspended_by = getattr(request.state, "member_id", "dashboard")

    try:
        await account_service.suspend(
            account_id, reason=reason, suspended_by=suspended_by
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    account = await account_service.get(account_id)

    if audit_logger:
        await audit_logger.log(
            member_id=suspended_by,
            action="account.suspend",
            resource=f"account:{account_id}",
            detail=f"계좌 정지: {reason}",
            ip=request.client.host if request.client else "",
        )

    return {
        "account": _account_to_response(account),
        "message": f"계좌 '{account_id}'가 정지되었습니다.",
    }


@router.post("/{account_id}/activate", response_model=AccountActionResponse)
async def activate_account(
    account_id: str,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 재활성화."""
    from ante.account.errors import AccountDeletedError, AccountNotFoundError

    activated_by = getattr(request.state, "member_id", "dashboard")

    try:
        await account_service.activate(account_id, activated_by=activated_by)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountDeletedError as e:
        raise HTTPException(status_code=400, detail=str(e))

    account = await account_service.get(account_id)

    if audit_logger:
        await audit_logger.log(
            member_id=activated_by,
            action="account.activate",
            resource=f"account:{account_id}",
            detail="계좌 활성화",
            ip=request.client.host if request.client else "",
        )

    return {
        "account": _account_to_response(account),
        "message": f"계좌 '{account_id}'가 활성화되었습니다.",
    }


@router.delete("/{account_id}", status_code=204)
async def delete_account(
    account_id: str,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> None:
    """계좌 소프트 딜리트."""
    from ante.account.errors import AccountNotFoundError

    deleted_by = getattr(request.state, "member_id", "dashboard")

    try:
        await account_service.delete(account_id, deleted_by=deleted_by)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if audit_logger:
        await audit_logger.log(
            member_id=deleted_by,
            action="account.delete",
            resource=f"account:{account_id}",
            detail="계좌 삭제",
            ip=request.client.host if request.client else "",
        )
