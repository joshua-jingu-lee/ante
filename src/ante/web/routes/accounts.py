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


# Cold-path 전용 필드: 서버 실행 중에는 변경할 수 없다.
# 출처: docs/specs/account/04-account-service.md 51-58줄.
# - credentials, broker_config, buy_commission_rate, sell_commission_rate:
#   broker adapter 재초기화가 필요한 필드
# - exchange, currency, trading_mode, broker_type:
#   계좌 생성 후 불변 필드 (구조 변경 시 모든 소비자 재구성 필요)
STRUCTURAL_FIELDS: tuple[str, ...] = (
    "credentials",
    "broker_config",
    "buy_commission_rate",
    "sell_commission_rate",
    "broker_type",
    "exchange",
    "currency",
    "trading_mode",
)

# 응답 detail prefix로 노출되는 cold-path 식별자.
# 클라이언트는 이 prefix로 cold-path 응답과 다른 409 경로(예: 삭제된 계좌
# 수정 시도)를 구분한다.
STRUCTURAL_CHANGE_ERROR_CODE = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


def _cold_path_detail(message: str) -> str:
    """Cold-path 차단 응답의 표준 detail 문자열을 만든다."""
    return f"{STRUCTURAL_CHANGE_ERROR_CODE}: {message}"


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


@router.post(
    "",
    responses={
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 생성 차단"
            )
        },
    },
)
async def create_account(
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 생성.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 생성은 서버 정지 상태에서 ``ante account create`` CLI로
    수행한다.

    body 파라미터를 받지 않는 이유: cold-path 차단은 입력 valid 여부와
    무관하게 항상 409여야 하므로, FastAPI가 핸들러 진입 전에 body
    validation을 수행하지 않도록 시그니처에서 의도적으로 제외한다.
    또한 OpenAPI에서도 requestBody가 노출되지 않아 클라이언트에
    "런타임 POST는 어떤 body도 받지 않는다"는 계약이 정확히 전달된다.
    """
    # 다른 검증/서비스 호출 전, 진입 즉시 cold-path 409 응답.
    # AccountService 생성 호출, broker connect, 감사 로그 모두 발생하지 않는다.
    # 이 경로의 회귀 보호는 service-layer 테스트(`tests/unit/test_account.py`)가
    # 담당한다.
    raise HTTPException(
        status_code=409,
        detail=_cold_path_detail(
            "계좌 생성은 cold-path 전용입니다. "
            "서버를 정지한 뒤 ante account create로 수행하세요."
        ),
    )


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
        400: {"description": "수정할 필드가 없음"},
        404: {"description": "계좌를 찾을 수 없음"},
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "(런타임 구조 변경 차단) 또는 삭제된 계좌 수정 시도"
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
    """계좌 수정.

    런타임에서는 비구조 필드(``name``, ``timezone``, ``trading_hours_start``,
    ``trading_hours_end``)만 변경할 수 있다. ``STRUCTURAL_FIELDS`` 중 하나라도
    포함되면 cold-path 409로 즉시 차단된다 — 클라이언트는
    ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER:`` prefix로 cold-path
    응답과 ``AccountDeletedError`` 경로의 409를 구분한다.
    """
    from ante.account.errors import (
        AccountDeletedError,
        AccountNotFoundError,
    )

    # cold-path 가드: structural 필드가 하나라도 명시(`is not None`)되면
    # DB/서비스 호출 전 409로 즉시 차단한다.
    # 가드 이후의 service.update는 비구조 필드만 받으므로
    # AccountImmutableFieldError/BrokerReconnectFailedError 경로에 도달하지
    # 않는다. 해당 service-layer 동작 회귀는 `tests/unit/test_account.py`,
    # `tests/unit/test_account_immutable_fields.py`가 보호한다.
    triggered_structural = [
        name for name in STRUCTURAL_FIELDS if getattr(body, name, None) is not None
    ]
    if triggered_structural:
        raise HTTPException(
            status_code=409,
            detail=_cold_path_detail(
                f"다음 필드는 cold-path 전용입니다: {', '.join(triggered_structural)}"
            ),
        )

    # None이 아닌 비구조 필드만 업데이트 대상
    fields: dict[str, Any] = {}
    for field_name in (
        "name",
        "timezone",
        "trading_hours_start",
        "trading_hours_end",
    ):
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


@router.delete(
    "/{account_id}",
    responses={
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 삭제 차단"
            )
        },
    },
)
async def delete_account(
    account_id: str,
    request: Request,
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> None:
    """계좌 소프트 딜리트.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 삭제는 서버 정지 상태에서 ``ante account delete`` CLI로
    수행한다. service-layer 회귀 보호는 ``tests/unit/test_account.py``의
    ``test_delete_account``, ``test_delete_already_deleted_account_raises``가
    담당한다.
    """
    raise HTTPException(
        status_code=409,
        detail=_cold_path_detail(
            "계좌 삭제는 cold-path 전용입니다. "
            "서버를 정지한 뒤 ante account delete로 수행하세요."
        ),
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
