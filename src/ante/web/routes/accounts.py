"""Account REST API — 계좌 CRUD + 정지/활성화."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError

from ante.web.deps import (
    get_account_service,
    get_audit_logger_optional,
    get_config,
    get_dynamic_config,
    require_master_caller,
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
# 출처: docs/specs/account/04-account-service.md.
# - credentials, broker_config, buy_commission_rate, sell_commission_rate,
#   market_order_reserve_buffer_rate:
#   broker adapter / Treasury reserve 정책에 영향을 주는 필드.
# - exchange, currency, trading_mode, broker_type:
#   계좌 생성 후 불변 필드 (구조 변경 시 모든 소비자 재구성 필요).
STRUCTURAL_FIELDS: tuple[str, ...] = (
    "credentials",
    "broker_config",
    "buy_commission_rate",
    "sell_commission_rate",
    "market_order_reserve_buffer_rate",
    "broker_type",
    "exchange",
    "currency",
    "trading_mode",
)

# PUT /api/accounts/{account_id} 비구조(런타임 mutable) 필드 화이트리스트.
# 출처: docs/specs/account/10-web-api.md 16-22줄,
#       docs/specs/account/04-account-service.md.
# 런타임 PUT은 이 4개 필드만 변경할 수 있으며, 나머지는 STRUCTURAL_FIELDS로 분류되어
# cold-path 409로 차단된다.
MUTABLE_FIELDS: tuple[str, ...] = (
    "name",
    "timezone",
    "trading_hours_start",
    "trading_hours_end",
)

# 응답 detail prefix로 노출되는 cold-path 식별자.
# 클라이언트는 이 prefix로 cold-path 응답과 다른 409 경로(예: 삭제된 계좌
# 수정 시도)를 구분한다.
STRUCTURAL_CHANGE_ERROR_CODE = "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER"


# PUT /api/accounts/{account_id} 런타임 mutable 입력 contract.
# 출처: docs/specs/account/10-web-api.md 16-22줄(런타임 차단 규칙 + mutable 필드).
#
# 런타임 PUT 핸들러는 raw body 파싱 → structural 가드(I1/I4) → Content-Type 415
# 게이트 → mutable 검증 순서로 처리하지만(이슈 #1153), Swagger UI / agent client /
# SDK는 정확한 mutable 입력 contract를 발견할 수 있어야 한다.
#
# ``AccountUpdateRequest.model_json_schema()`` 직접 노출 금지: 다른 소비자(테스트,
# CLI) 호환을 위해 모든 필드가 ``str | None = None`` 옵션이고 structural 키도
# 포함되어 있다. 본 dict 상수는 mutable 4 필드만 노출하며, ``required``는 schema
# 안에 두지 않는다(빈 dict + ``{"name": null}``는 422 Unprocessable Entity로
# 차단된다 — #1152 정렬 완료). ``required: True``는 ``requestBody`` level에
# 둔다. ``minProperties: 1``은 effective payload가 비는 케이스(``{}`` /
# ``{"name": null}``)를 OpenAPI/runtime 계약 양쪽에서 거부 의미로 표현한다.
ACCOUNT_MUTABLE_UPDATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "AccountMutableUpdateRequest",
    "description": (
        "PUT /api/accounts/{account_id} 런타임 mutable 입력 contract. "
        "런타임에는 비구조 필드만 변경할 수 있다. "
        "structural 필드(credentials, broker_config, "
        "buy_commission_rate, sell_commission_rate, broker_type, exchange, "
        "currency, trading_mode)는 cold-path 409로 차단된다. "
        "스키마 SSOT: docs/specs/account/10-web-api.md 16-22줄."
    ),
    "additionalProperties": False,
    "minProperties": 1,
    "properties": {
        "name": {
            "type": "string",
            "description": "사용자에게 표시되는 이름.",
        },
        "timezone": {
            "type": "string",
            "description": "거래소 현지 시간대 (IANA).",
        },
        "trading_hours_start": {
            "type": "string",
            "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
            "description": (
                "거래 시작 시각 (현지 시간, strict HH:MM 24시간 형식). "
                "초/마이크로초 포함, 빈 문자열, invalid 시간은 422로 거부된다 (#1334)."
            ),
        },
        "trading_hours_end": {
            "type": "string",
            "pattern": "^([01]\\d|2[0-3]):[0-5]\\d$",
            "description": (
                "거래 종료 시각 (현지 시간, strict HH:MM 24시간 형식). "
                "초/마이크로초 포함, 빈 문자열, invalid 시간은 422로 거부된다 (#1334)."
            ),
        },
    },
}


# POST /api/accounts cold-path 전용 OpenAPI request body 문서.
# 출처: docs/specs/account/03-data-model.md 60-87줄 필드 표(SSOT) +
# docs/specs/account/04-account-service.md 51-58줄 cold-path 전용 필드.
#
# 런타임 라우트는 cold-path 가드로 어떤 입력이든 즉시 409로 차단되지만
# (invariant I1), Swagger UI / agent client / SDK는 cold-path 계좌 생성
# payload 필드를 정확히 발견할 수 있어야 한다(이슈 #1143).
#
# ``AccountCreateRequest.model_json_schema()`` 직접 노출 금지: BrokerPreset
# 자동 채움 때문에 Pydantic 모델은 모든 필드가 default를 갖고 있어 spec 표
# (``exchange``/``currency``/``broker_type`` required)와 어긋난다(#1143
# attempt 6 finding). 본 dict 상수는 spec과 1:1 정합한 cold-path 문서 전용
# schema이며, ``AccountCreateRequest`` Pydantic 모델은 다른 소비자(테스트,
# CLI 등) 호환을 위해 변경하지 않는다.
ACCOUNT_CREATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "AccountCreateRequest",
    "description": (
        "POST /api/accounts cold-path 입력 contract. "
        "런타임에서는 cold-path 가드가 어떤 입력이든 즉시 409로 차단한다 "
        "(ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER). "
        "실제 계좌 생성은 서버 정지 상태에서 ante account create CLI로 수행한다. "
        "스키마 SSOT: docs/specs/account/03-data-model.md 60-87줄."
    ),
    "additionalProperties": False,
    "required": [
        "account_id",
        "name",
        "exchange",
        "currency",
        "broker_type",
    ],
    "properties": {
        "account_id": {
            "type": "string",
            "description": "고유 식별자 (영문+숫자+하이픈, 3–30자).",
        },
        "name": {
            "type": "string",
            "description": "사용자에게 표시되는 이름.",
        },
        "exchange": {
            "type": "string",
            "enum": ["KRX", "NYSE", "NASDAQ", "TEST"],
            "description": "대상 거래소 코드.",
        },
        "currency": {
            "type": "string",
            "description": "거래 통화 (ISO 4217).",
        },
        "timezone": {
            "type": "string",
            "default": "Asia/Seoul",
            "description": "거래소 현지 시간대 (IANA).",
        },
        "trading_hours_start": {
            "type": "string",
            "default": "09:00",
            "pattern": "^(([01]\\d|2[0-3]):[0-5]\\d)?$",
            "description": (
                "거래 시작 시각 (현지 시간, strict HH:MM 24시간 형식). "
                "AccountCreateRequest는 cold-path payload이며 "
                "빈 문자열은 BrokerPreset fallback sentinel로 허용된다. "
                "초/마이크로초 포함, invalid 시간은 422로 거부된다 (#1334)."
            ),
        },
        "trading_hours_end": {
            "type": "string",
            "default": "15:30",
            "pattern": "^(([01]\\d|2[0-3]):[0-5]\\d)?$",
            "description": (
                "거래 종료 시각 (현지 시간, strict HH:MM 24시간 형식). "
                "AccountCreateRequest는 cold-path payload이며 "
                "빈 문자열은 BrokerPreset fallback sentinel로 허용된다. "
                "초/마이크로초 포함, invalid 시간은 422로 거부된다 (#1334)."
            ),
        },
        "trading_mode": {
            "type": "string",
            "enum": ["VIRTUAL", "LIVE"],
            "default": "VIRTUAL",
            "description": "거래 모드 (VIRTUAL / LIVE).",
        },
        "broker_type": {
            "type": "string",
            "description": "브로커 어댑터 유형.",
        },
        "credentials": {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "default": {},
            "description": (
                "브로커 인증 정보 (dict[str, str], 암호화 저장). cold-path 전용."
            ),
        },
        "broker_config": {
            "type": "object",
            "additionalProperties": True,
            "default": {},
            "description": (
                "브로커 동작 설정 (예: KIS is_paper). 임의 키-값 dict. cold-path 전용."
            ),
        },
        "buy_commission_rate": {
            "type": "number",
            "default": 0,
            "description": "매수 수수료율 (cold-path 전용).",
        },
        "sell_commission_rate": {
            "type": "number",
            "default": 0,
            "description": "매도 수수료율, 세금 포함 (cold-path 전용).",
        },
        "market_order_reserve_buffer_rate": {
            "type": "number",
            "description": (
                "시장가 매수 reserve buffer 비율 (cold-path 전용, #1333). "
                "omit 시 BrokerPreset 기본값을 사용한다 "
                "(예: kis-domestic=0.005, test=0)."
            ),
        },
    },
}


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
        "market_order_reserve_buffer_rate": float(
            account.market_order_reserve_buffer_rate
        ),
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
    responses={
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 생성 차단"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": ACCOUNT_CREATE_REQUEST_SCHEMA,
                },
            },
        },
    },
)
async def create_account(request: Request) -> None:
    """계좌 생성.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 생성은 서버 정지 상태에서 ``ante account create`` CLI로
    수행한다.

    의존성/Pydantic body schema/audit logger를 모두 시그니처에서 제외해
    핸들러 진입 즉시 409가 반환되도록 한다(invariant I1). OpenAPI에는
    success contract(200/201/204)가 노출되지 않으며, 409 응답은 명시
    ``responses[409]`` content map의 ``application/problem+json``으로
    ``ErrorResponse``를 노출한다(invariant I2/I3, #1164).

    이 경로의 service-layer 회귀 보호는 ``tests/unit/test_account.py``가
    담당한다.

    본 PR(#1143)에서 OpenAPI requestBody schema가 spec-aligned
    ``ACCOUNT_CREATE_REQUEST_SCHEMA``로 노출되어 codegen 클라이언트가
    cold-path payload 필드를 발견할 수 있게 됐다. 런타임은 어떤 body든
    무시하고 409를 반환한다.
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
            "description": ("수정할 필드가 없거나 service-layer가 거부한 비구조 필드"),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization header "
                "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
                "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
                "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": "Permission denied (master 권한 필요)",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "계좌를 찾을 수 없음",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "(런타임 구조 변경 차단) 또는 삭제된 계좌 수정 시도"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        415: {
            "description": "Content-Type이 application/json이 아님",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "비구조(mutable) 필드 type 검증 실패 또는 unknown 키. "
                "structural 필드 키는 422가 아닌 409로 차단된다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Account service not available 또는 broker 재연결 실패",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        "requestBody": {
            # 빈 body 400 no-op 호환을 위해 schema-level required 강제 X.
            # 단, requestBody-level은 True로 두어 codegen이 body를 optional로
            # 만들지 않도록 한다(#1153 패턴 SSOT — POST 패턴 일치).
            "required": True,
            "content": {
                "application/json": {
                    "schema": ACCOUNT_MUTABLE_UPDATE_REQUEST_SCHEMA,
                },
            },
        },
    },
)
async def update_account(
    account_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)] = None,
) -> dict[str, Any]:
    """계좌 수정.

    인증된 master 호출자만 사용할 수 있다(이슈 #1352 — oracle A7). dependency
    ``require_master_caller``가 인증/권한 검증을 담당하며, 401/403은 raw body
    파싱과 cold-path 가드(invariant I1/I4)보다 먼저 평가된다 — Bearer 또는
    ``ante_session`` 쿠키 어느 쪽으로도 caller가 결정되지 않으면 401, master가
    아니면 403.

    런타임에서는 비구조 필드(``name``, ``timezone``, ``trading_hours_start``,
    ``trading_hours_end``)만 변경할 수 있다. ``STRUCTURAL_FIELDS`` 중 하나라도
    포함되면 cold-path 409로 즉시 차단된다 — 클라이언트는
    ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER:`` prefix로 cold-path
    응답과 ``AccountDeletedError`` 경로의 409를 구분한다.

    body는 raw bytes로 받는다(``request.body()``). FastAPI 선행 Pydantic
    검증을 거치면 cold-path 가드(invariant I1/I4) 도달 전 422가 먼저 나가
    structural 키 존재가 schema validation 신호로 흘러갈 수 있기 때문이다.

    핸들러 단계 순서(이슈 #1153 + #1152 Implementation Plan):

    1. raw bytes 읽기.
    2. **빈 body**(``b""``) → ``payload = {}``로 두고 Content-Type 검사·JSON
       파싱 모두 건너뛰고 mutable 단계까지 흘려보낸다(단계 6에서 422로 처리).
    3. **JSON 파싱 실패**: Content-Type ≠ application/json → 415,
       Content-Type 정상 → 422.
    4. **non-dict JSON**: Content-Type ≠ application/json → 415,
       Content-Type 정상 → 422.
    5. **structural 가드(I4 우선)**: dict payload에 structural 키 존재 → 409
       (Content-Type 무관, structural+text/plain도 409).
    6. ``len(payload) == 0`` (``{}`` 명시 송신 또는 빈 body) → 422 no-op
       (Content-Type 검사 건너뜀; #1152 정렬 완료 — schema의
       ``minProperties: 1``과 정합).
    7. **Content-Type 415 게이트**: ``application/json``(charset suffix 허용)
       이외 → 415.
    8. **unknown 키 / mutable type**: structural 제외한 raw dict의 unknown
       키 → 422. ``AccountUpdateRequest.model_validate`` ValidationError → 422.
    9. ``model_dump(exclude_none=True)`` 결과 비면 422 (예: ``{"name": null}``
       단독 — effective payload empty no-op; #1152 정렬 완료).
    10. service 호출.
    """
    from ante.account.errors import (
        AccountDeletedError,
        AccountImmutableFieldError,
        AccountNotFoundError,
        AccountStructuralChangeRequiresStoppedServerError,
        BrokerReconnectFailedError,
    )

    # 1. raw body 읽기.
    raw = await request.body()

    # Content-Type media type 추출(charset suffix 허용 — `;` 앞부분 lowercase
    # 매칭으로 `application/json; charset=utf-8` 같은 정상 변형을 통과시킨다).
    content_type_header = request.headers.get("content-type", "") or ""
    media_type = content_type_header.split(";", 1)[0].strip().lower()
    is_json_media = media_type == "application/json"

    # 2. 빈 body — Content-Type 검사·JSON 파싱 건너뛰고 payload = {} 로 두어
    # 단계 6의 400 no-op 분기로 떨어지게 한다(기존 의미 보존).
    if raw == b"":
        payload: Any = {}
    else:
        # 3. JSON 파싱.
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            # Content-Type 자체가 잘못된 경우 415가 더 정보량이 크므로 우선.
            if not is_json_media:
                raise HTTPException(
                    status_code=415,
                    detail=(
                        "Content-Type은 application/json이어야 합니다. "
                        f"받은 값: {content_type_header!r}"
                    ),
                ) from None
            raise HTTPException(
                status_code=422,
                detail="요청 body의 JSON 파싱에 실패했습니다.",
            ) from None

        # 4. non-dict JSON(예: [], "x", 123): Content-Type 분기.
        if not isinstance(payload, dict):
            if not is_json_media:
                raise HTTPException(
                    status_code=415,
                    detail=(
                        "Content-Type은 application/json이어야 합니다. "
                        f"받은 값: {content_type_header!r}"
                    ),
                )
            raise HTTPException(
                status_code=422,
                detail="요청 body는 JSON object여야 합니다.",
            )

    # 5. structural 가드(I4 우선): structural 키가 등장하면 Content-Type과
    # 무관하게 409로 차단(structural+text/plain도 409).
    structural_hits = sorted(set(payload) & set(STRUCTURAL_FIELDS))
    if structural_hits:
        raise HTTPException(
            status_code=409,
            detail=_cold_path_detail(
                f"다음 필드는 cold-path 전용입니다: {', '.join(structural_hits)}"
            ),
        )

    # 6. ``len(payload) == 0`` (``{}`` 명시 송신 또는 빈 body): Content-Type
    # 검사 건너뛰고 422 no-op로 즉시 떨어뜨린다(#1152 정렬 완료 — schema의
    # ``minProperties: 1``과 정합).
    if len(payload) == 0:
        raise HTTPException(status_code=422, detail="수정할 필드가 없습니다.")

    # 7. Content-Type 415 게이트: 비-application/json은 415.
    if not is_json_media:
        raise HTTPException(
            status_code=415,
            detail=(
                "Content-Type은 application/json이어야 합니다. "
                f"받은 값: {content_type_header!r}"
            ),
        )

    # 8. unknown 키 / mutable type 검증.
    mutable_payload_in = {
        k: v for k, v in payload.items() if k not in STRUCTURAL_FIELDS
    }
    unknown_keys = sorted(set(mutable_payload_in) - set(MUTABLE_FIELDS))
    if unknown_keys:
        raise HTTPException(
            status_code=422,
            detail=(f"알 수 없는 필드가 포함되었습니다: {', '.join(unknown_keys)}"),
        )

    try:
        validated = AccountUpdateRequest.model_validate(mutable_payload_in)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    # 9. ``exclude_none=True``로 set된 mutable 필드만 추출. ``{"name": null}``
    # 같이 명시적으로 null이 들어온 경우 model_dump에서 빠지므로 service까지
    # null이 흘러가지 않는다(P1: DB 오염 차단). effective payload가 비면
    # 422 — schema의 ``minProperties: 1``과 정합(#1152 정렬 완료).
    fields = validated.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=422, detail="수정할 필드가 없습니다.")

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
    except AccountStructuralChangeRequiresStoppedServerError as e:
        # Defense-in-depth (#1144): 라우트 1차 가드(I1/I4)가 structural 키를
        # 이미 409로 차단하므로 이 분기는 정상 흐름에서 도달하지 않는다.
        # 라우트 가드를 우회하는 비정상 경로(예: 테스트 monkeypatch)에서
        # service가 직접 raise한 경우에만 도달한다 — cold-path 409 detail로
        # 매핑한다(``_cold_path_detail``로 STRUCTURAL_CHANGE_ERROR_CODE prefix 부착).
        raise HTTPException(status_code=409, detail=_cold_path_detail(str(e)))
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
            member_id=caller_id,
            action="account.update",
            resource=f"account:{account_id}",
            detail=f"계좌 수정: {list(fields.keys())}",
            ip=request.client.host if request.client else "",
        )

    return {"account": _account_to_response(updated)}


_AUTH_REQUIRED_RESPONSE: dict[str, Any] = {
    "description": (
        "Authentication required (missing or invalid Authorization header "
        "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
        "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
        "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
    ),
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
        },
    },
}

_PERMISSION_DENIED_RESPONSE: dict[str, Any] = {
    "description": "Permission denied (master 권한 필요)",
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
        },
    },
}


# POST /api/accounts/{account_id}/suspend OpenAPI request body 문서.
#
# ``suspend_account``는 ``create_member`` / ``update_scopes`` / ``update_bot`` /
# ``set_balance``와 동일하게 raw body 파싱 패턴을 쓰며(인증 가드 우선, body
# validation 후행 — 이슈 #1352 Codex review 2차) ``body: AccountSuspendRequest``
# 인자가 라우트 시그니처에서 제거됐다. 그 결과 FastAPI 자동 components 등록
# 경로를 거치지 않으므로 inline schema로 두면 frontend ``openapi-typescript``
# 산출물에서 ``export type AccountSuspendRequest``가 사라진다.
#
# 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고 본체 schema는
# ``_install_openapi_customizer``가 ``components.schemas``에 등록한다(#1351
# ``ScopesUpdateRequest`` SSOT 패턴).
ACCOUNT_SUSPEND_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "AccountSuspendRequest",
    "description": (
        "POST /api/accounts/{account_id}/suspend 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1352). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다. "
        "빈 body도 허용되며 reason은 default 'dashboard'로 채워진다."
    ),
    "additionalProperties": False,
    "properties": {
        "reason": {
            "type": "string",
            "default": "",
            "description": (
                "정지 사유. 빈 문자열 또는 omit 시 server-side default "
                "'dashboard'로 기록된다."
            ),
        },
    },
}


@router.post(
    "/{account_id}/suspend",
    response_model=AccountActionResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: _PERMISSION_DENIED_RESPONSE,
        404: {
            "description": "Account not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Account already suspended",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        # 빈 body도 허용되므로(default reason 흘려보내기) requestBody-level
        # ``required: False``. ``$ref`` 매핑은 frontend codegen이
        # ``export type AccountSuspendRequest``를 export할 수 있도록 노출하며,
        # 본체 schema는 ``_install_openapi_customizer``가
        # ``components.schemas``에 등록한다(#1352 2차 Codex review FAIL).
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/AccountSuspendRequest"},
                },
            },
        },
    },
)
async def suspend_account(
    account_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 정지. 인증된 master만 호출 가능 (#1352).

    ``update_bot`` / ``set_balance`` / ``update_scopes``와 동일한 raw body 파싱
    패턴을 적용해 인증 가드가 body validation보다 먼저 실행되도록 한다(#1352
    Codex review 2차). FastAPI가 ``body: AccountSuspendRequest``를 typed로
    먼저 검증하면 unauth + malformed body 시 401이 아닌 422가 먼저 반환되어
    ``update_bot`` / ``set_balance``의 auth-first 계약과 어긋난다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_master_caller)``) — caller 빈 → 401,
       non-master → 403.
    2. raw bytes 읽기. 빈 body → default reason (``dashboard``)로 흘려보낸다
       (기존 의미 보존).
    3. JSON 파싱 실패 → 422.
    4. ``AccountSuspendRequest.model_validate`` ValidationError(extra forbid
       포함) → 422.
    5. service 호출.
    """
    from ante.account.errors import AccountAlreadySuspendedError, AccountNotFoundError

    # 1. raw body 읽기 + JSON 파싱 (인증은 dependency에서 이미 통과한 상태).
    raw = await request.body()
    if raw == b"":
        # 빈 body는 기존 의미를 보존한다 — default reason.
        body = None
    else:
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(
                status_code=422, detail="요청 body의 JSON 파싱에 실패했습니다."
            ) from None
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=422, detail="요청 body는 JSON object여야 합니다."
            )
        # 2. Pydantic 검증 — 인증 통과 후에만 실행된다.
        try:
            body = AccountSuspendRequest.model_validate(payload)
        except ValidationError as e:
            raise HTTPException(status_code=422, detail=e.errors()) from None

    reason = (body.reason if body else None) or "dashboard"

    try:
        await account_service.suspend(account_id, reason=reason, suspended_by=caller_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountAlreadySuspendedError as e:
        raise HTTPException(status_code=409, detail=str(e))

    account = await account_service.get(account_id)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="account.suspend",
            resource=f"account:{account_id}",
            detail=f"계좌 정지: {reason}",
            ip=request.client.host if request.client else "",
        )

    return {
        "account": _account_to_response(account),
        "message": f"계좌 '{account_id}'가 정지되었습니다.",
    }


@router.post(
    "/{account_id}/activate",
    response_model=AccountActionResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: _PERMISSION_DENIED_RESPONSE,
        404: {
            "description": "Account not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Account deleted",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def activate_account(
    account_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict[str, Any]:
    """계좌 재활성화. 인증된 master만 호출 가능 (#1352)."""
    from ante.account.errors import AccountDeletedError, AccountNotFoundError

    try:
        await account_service.activate(account_id, activated_by=caller_id)
    except AccountNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AccountDeletedError as e:
        raise HTTPException(status_code=409, detail=str(e))

    account = await account_service.get(account_id)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
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
    responses={
        409: {
            "description": (
                "ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER "
                "— 런타임 계좌 삭제 차단"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def delete_account(account_id: str, request: Request) -> None:
    """계좌 소프트 딜리트.

    런타임 Web API에서는 cold-path 가드가 모든 요청을 즉시 409로 차단한다.
    실제 계좌 삭제는 서버 정지 상태에서 ``ante account delete`` CLI로
    수행한다.

    의존성/audit logger를 시그니처에서 제외해 핸들러 진입 즉시 409가
    반환되도록 한다(invariant I1). OpenAPI에는 success contract(200/201/
    204)가 노출되지 않으며, 409 응답은 명시 ``responses[409]`` content
    map의 ``application/problem+json``으로 ``ErrorResponse``를 노출한다
    (invariant I2/I3, #1164). service-layer 회귀 보호는
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

    저장되는 ``accounts.{account_id}.rules`` 값은 explicit overrides(stored
    rules)다. RuleEngine이 실제로 적용하는 effective rules는
    ``ante.rule.defaults.resolve_effective_rules``가 broker_type별 defaults와
    이 stored rules를 merge한 결과이며, ``ConfigChangedEvent`` reload 시
    동일 helper가 다시 호출된다. 본 GET/PUT API는 stored rules만 다룬다 —
    effective view는 후속 이슈에서 별도 엔드포인트로 노출한다 (#1296).
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
