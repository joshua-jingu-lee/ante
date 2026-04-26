"""Account REST API — 계좌 CRUD + 정지/활성화."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

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
    ErrorResponse,
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
    status_code=409,
    response_model=ErrorResponse,
    responses={
        409: {
            "model": ErrorResponse,
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 생성 차단"
            ),
        },
    },
)
async def create_account(request: Request) -> ErrorResponse:
    """계좌 생성.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 생성은 서버 정지 상태에서 ``ante account create`` CLI로
    수행한다.

    의존성/Pydantic body schema/audit logger를 모두 시그니처에서 제외해
    핸들러 진입 즉시 409가 반환되도록 한다(invariant I1). 또한 OpenAPI에는
    success contract(200/201/204)가 노출되지 않으며, 응답 모델은
    ``ErrorResponse``로 고정된다(invariant I2/I3).

    이 경로의 service-layer 회귀 보호는 ``tests/unit/test_account.py``가
    담당한다.
    """
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
        400: {
            "model": ErrorResponse,
            "description": ("수정할 필드가 없거나 service-layer가 거부한 비구조 필드"),
        },
        404: {"model": ErrorResponse, "description": "계좌를 찾을 수 없음"},
        409: {
            "model": ErrorResponse,
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "(런타임 구조 변경 차단) 또는 삭제된 계좌 수정 시도"
            ),
        },
        503: {
            "model": ErrorResponse,
            "description": "Account service not available 또는 broker 재연결 실패",
        },
    },
)
async def update_account(
    account_id: str,
    request: Request,
    body: dict[str, Any] | None = Body(default=None),
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)] = None,
) -> dict[str, Any]:
    """계좌 수정.

    런타임에서는 비구조 필드(``name``, ``timezone``, ``trading_hours_start``,
    ``trading_hours_end``)만 변경할 수 있다. ``STRUCTURAL_FIELDS`` 중 하나라도
    포함되면 cold-path 409로 즉시 차단된다 — 클라이언트는
    ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER:`` prefix로 cold-path
    응답과 ``AccountDeletedError`` 경로의 409를 구분한다.

    body는 자유 ``dict[str, Any] | None``로 받는다. FastAPI 선행 Pydantic
    검증이 켜지면 cold-path 가드(invariant I1/I4) 도달 전 422가 먼저 나가
    structural 키 존재가 schema validation 신호로 흘러갈 수 있기 때문이다.
    핸들러 본문에서는 raw payload key 검사로 cold-path 가드를 먼저 수행한 뒤,
    비구조 필드를 그대로 ``account_service.update``에 forward한다.
    service-layer가 알 수 없는/불변 필드는 자체 검증으로 거부한다
    (`AccountImmutableFieldError → 400`, `ValueError(unknown field)` 등).
    PUT requestBody의 OpenAPI schema accuracy 회복(mutable 모델 노출)은 후속
    이슈 #1143에서 다룬다.
    """
    from ante.account.errors import (
        AccountDeletedError,
        AccountImmutableFieldError,
        AccountNotFoundError,
        BrokerReconnectFailedError,
    )

    # body는 dict로 직접 받으므로 별도 raw bytes 파싱이 필요 없다.
    # FastAPI는 JSON 파싱 실패 / non-dict body를 자동 422로 처리한다.
    payload = body or {}

    # cold-path 가드: structural 필드 키가 payload에 하나라도 등장하면
    # DB/서비스 호출 전 409로 즉시 차단한다(invariant I1/I4). 값이 null이거나
    # 타입이 잘못돼도 동일하게 차단된다 — Pydantic 검증을 통과한 값이 아니라
    # 키 존재 여부만 본다.
    structural_hits = sorted(set(payload) & set(STRUCTURAL_FIELDS))
    if structural_hits:
        raise HTTPException(
            status_code=409,
            detail=_cold_path_detail(
                f"다음 필드는 cold-path 전용입니다: {', '.join(structural_hits)}"
            ),
        )

    # structural 가드를 통과한 키만 service.update에 forward한다. service가
    # unknown/invalid 필드를 거부하므로 라우트는 추가 schema 검증을 하지 않는다.
    fields = {k: v for k, v in payload.items() if k not in STRUCTURAL_FIELDS}
    if not fields:
        raise HTTPException(status_code=400, detail="수정할 필드가 없습니다.")

    # service는 비구조 분기에 도달한 뒤에만 lazy 해소한다. structural body가
    # 들어온 경로에서는 위 가드에서 이미 409가 raise되었기 때문에 service
    # 미주입 환경에서도 503이 선행되지 않는다(invariant I1/I4 보호 — P3 회귀).
    account_service = getattr(request.app.state, "account_service", None)
    if account_service is None:
        raise HTTPException(
            status_code=503,
            detail="Account service not available",
        )

    try:
        updated = await account_service.update(account_id, **fields)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountDeletedError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except AccountImmutableFieldError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except BrokerReconnectFailedError as e:
        raise HTTPException(
            status_code=503,
            detail=str(e),
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


@router.delete(
    "/{account_id}",
    status_code=409,
    response_model=ErrorResponse,
    responses={
        409: {
            "model": ErrorResponse,
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 삭제 차단"
            ),
        },
    },
)
async def delete_account(account_id: str, request: Request) -> ErrorResponse:
    """계좌 소프트 딜리트.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 삭제는 서버 정지 상태에서 ``ante account delete`` CLI로
    수행한다.

    의존성/audit logger를 시그니처에서 제외해 핸들러 진입 즉시 409가
    반환되도록 한다(invariant I1). OpenAPI에는 success contract(200/201/
    204)가 노출되지 않으며, 응답 모델은 ``ErrorResponse``로 고정된다
    (invariant I2/I3). service-layer 회귀 보호는
    ``tests/unit/test_account.py``의 ``test_delete_account``,
    ``test_delete_already_deleted_account_raises``가 담당한다.
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
