"""Account REST API — 계좌 CRUD + 정지/활성화."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from ante.web.deps import (
    get_account_service,
    get_audit_logger_optional,
    get_config,
    get_dynamic_config,
)
from ante.web.schemas import (
    AccountActionResponse,
    AccountCreateRequest,
    AccountDetailResponse,
    AccountListResponse,
    AccountSuspendRequest,
    AccountUpdateRequest,
    RuleListResponse,
    RuleUpdateRequest,
    RuleUpdateResponse,
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
        "broker_config": account.broker_config,
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
        MissingCredentialsError,
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
        broker_config=body.broker_config,
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
    except MissingCredentialsError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # 브로커 어댑터 인스턴스 생성 가능 여부 검증
    # BROKER_REGISTRY에 미등록된 타입은 생성 직후 롤백
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


@router.put(
    "/{account_id}",
    response_model=AccountDetailResponse,
    responses={
        400: {"description": "수정할 필드가 없거나 불변 필드 수정 시도"},
        404: {"description": "계좌를 찾을 수 없음"},
        409: {"description": "삭제된 계좌 수정 시도"},
        503: {
            "description": (
                "DB에는 계좌 정보가 저장되었으나 새 설정으로 브로커 재연결에 "
                "실패한 부분 성공 상태. 자격증명/브로커 설정을 확인한 뒤 재시도."
            )
        },
    },
)
async def update_account(
    account_id: str,
    body: AccountUpdateRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 수정."""
    from ante.account.errors import (
        AccountDeletedError,
        AccountImmutableFieldError,
        AccountNotFoundError,
        BrokerReconnectFailedError,
    )

    # None이 아닌 필드만 업데이트 대상
    fields: dict[str, Any] = {}
    for field_name in (
        "name",
        "timezone",
        "trading_hours_start",
        "trading_hours_end",
        "credentials",
        "broker_config",
        "buy_commission_rate",
        "sell_commission_rate",
    ):
        value = getattr(body, field_name, None)
        if value is not None:
            if field_name in ("buy_commission_rate", "sell_commission_rate"):
                from decimal import Decimal

                value = Decimal(str(value))
            fields[field_name] = value

    # 불변 필드가 요청에 포함된 경우 서비스 레이어에서 차단하도록 전달
    for field_name in ("exchange", "currency", "trading_mode", "broker_type"):
        value = getattr(body, field_name, None)
        if value is not None:
            fields[field_name] = value

    if not fields:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    try:
        updated = await account_service.update(account_id, **fields)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountDeletedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountImmutableFieldError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BrokerReconnectFailedError as e:
        # 계좌 정보는 DB에 반영됐지만 새 설정으로 브로커를 재연결하지
        # 못한 부분 실패 상태. 503으로 명시해 운영자가 자격증명/설정을
        # 교정 후 재시도하도록 유도한다. 캐시에는 기존 브로커가 그대로
        # 남아 있어 기존 연결 기반 호출은 계속 동작한다.
        raise HTTPException(
            status_code=503,
            detail=(
                f"{e} 계좌 정보는 저장되었으나 브로커 재연결에 실패했습니다. "
                "자격증명/브로커 설정을 확인한 뒤 다시 시도하세요."
            ),
        )

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
    from ante.account.errors import AccountAlreadySuspendedError, AccountNotFoundError

    reason = (body.reason if body else None) or "dashboard"
    suspended_by = getattr(request.state, "member_id", "dashboard")

    try:
        await account_service.suspend(
            account_id, reason=reason, suspended_by=suspended_by
        )
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountAlreadySuspendedError as e:
        raise HTTPException(status_code=409, detail=str(e))

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
        raise HTTPException(status_code=409, detail=str(e))

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


# ── 리스크 룰 ─────────────────────────────────────────


def _config_key(account_id: str) -> str:
    """계좌별 룰 설정 Config 키."""
    return f"accounts.{account_id}.rules"


def _rule_config_to_item(cfg: dict[str, Any]) -> dict[str, Any]:
    """룰 설정 dict를 RuleItem 호환 dict로 변환.

    config dict에서 type, enabled를 분리하고 나머지를 params로 묶는다.
    """
    params = {k: v for k, v in cfg.items() if k not in ("type", "id", "enabled")}
    return {
        "type": cfg.get("type", ""),
        "enabled": cfg.get("enabled", True),
        "params": params,
    }


def _item_to_rule_config(
    rule_type: str, enabled: bool, params: dict[str, Any]
) -> dict[str, Any]:
    """RuleItem 데이터를 룰 설정 dict로 변환."""
    cfg: dict[str, Any] = {"type": rule_type, "enabled": enabled}
    cfg.update(params)
    return cfg


@router.get("/{account_id}/rules", response_model=RuleListResponse)
async def get_account_rules(
    account_id: str,
    account_service: Annotated[Any, Depends(get_account_service)],
    config: Annotated[Any | None, Depends(get_config)],
    dynamic_config: Annotated[Any | None, Depends(get_dynamic_config)],
) -> dict[str, Any]:
    """계좌 리스크 룰 목록 조회.

    DynamicConfig를 우선 조회하고, 없으면 정적 Config에서 읽는다.
    RULE_REGISTRY에 등록된 룰 타입만 구조화하여 반환한다.
    """
    from ante.account.errors import AccountNotFoundError
    from ante.rule.engine import RULE_REGISTRY

    # 계좌 존재 확인
    try:
        await account_service.get(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    key = _config_key(account_id)
    raw_rules: list[dict[str, Any]] = []

    # 1) DynamicConfig에서 조회
    if dynamic_config is not None:
        try:
            value = await dynamic_config.get(key)
            if isinstance(value, list):
                raw_rules = value
        except Exception:
            pass

    # 2) 정적 Config fallback
    if not raw_rules and config is not None and hasattr(config, "get"):
        value = config.get(key)
        if isinstance(value, list):
            raw_rules = value

    # RULE_REGISTRY에 등록된 타입만 필터링
    rules = []
    for cfg in raw_rules:
        rule_type = cfg.get("type", "")
        if rule_type in RULE_REGISTRY:
            rules.append(_rule_config_to_item(cfg))

    return {"account_id": account_id, "rules": rules}


@router.put("/{account_id}/rules/{rule_type}", response_model=RuleUpdateResponse)
async def update_account_rule(
    account_id: str,
    rule_type: str,
    body: RuleUpdateRequest,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    config: Annotated[Any | None, Depends(get_config)],
    dynamic_config: Annotated[Any, Depends(get_dynamic_config)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 리스크 룰 개별 수정.

    RULE_REGISTRY에 등록된 타입만 허용하며,
    DynamicConfigService에 위임하여 ConfigChangedEvent를 발행한다.
    """
    from ante.account.errors import AccountNotFoundError
    from ante.rule.engine import RULE_REGISTRY

    # 계좌 존재 확인
    try:
        await account_service.get(account_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # 룰 타입 유효성 검증
    if rule_type not in RULE_REGISTRY:
        raise HTTPException(
            status_code=400,
            detail=f"알 수 없는 룰 타입: '{rule_type}'. "
            f"가능한 값: {list(RULE_REGISTRY.keys())}",
        )

    # config 파라미터 범위 검증
    rule_class = RULE_REGISTRY[rule_type]
    validation_errors = rule_class.validate_config(body.params)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail=f"룰 config 검증 실패: {'; '.join(validation_errors)}",
        )

    key = _config_key(account_id)

    # 기존 룰 설정 조회
    raw_rules: list[dict[str, Any]] = []

    # DynamicConfig에서 조회
    try:
        value = await dynamic_config.get(key)
        if isinstance(value, list):
            raw_rules = value
    except Exception:
        pass

    # 정적 Config fallback
    if not raw_rules and config is not None and hasattr(config, "get"):
        value = config.get(key)
        if isinstance(value, list):
            raw_rules = list(value)  # 복사

    # 해당 rule_type 찾아서 업데이트 또는 새로 추가
    new_config = _item_to_rule_config(rule_type, body.enabled, body.params)
    updated = False
    for i, cfg in enumerate(raw_rules):
        if cfg.get("type") == rule_type:
            raw_rules[i] = new_config
            updated = True
            break

    if not updated:
        raw_rules.append(new_config)

    # DynamicConfig에 저장 (ConfigChangedEvent 발행됨)
    changed_by = getattr(request.state, "member_id", "dashboard")
    await dynamic_config.set(key, raw_rules, category="rule", changed_by=changed_by)

    if audit_logger:
        await audit_logger.log(
            member_id=changed_by,
            action="account.rule.update",
            resource=f"account:{account_id}:rule:{rule_type}",
            detail=f"룰 수정: {rule_type} enabled={body.enabled}",
            ip=request.client.host if request.client else "",
        )

    rule_item = _rule_config_to_item(new_config)
    return {
        "account_id": account_id,
        "rule_type": rule_type,
        "rule": rule_item,
    }
