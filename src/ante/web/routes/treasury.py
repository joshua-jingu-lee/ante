"""Treasury 자금 관리 API."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ante.treasury.treasury import TRANSACTION_TYPE_VOCABULARY
from ante.web.deps import (
    get_audit_logger_optional,
    get_bot_manager_optional,
    get_treasury,
    get_treasury_manager_optional,
    require_treasury_admin,
    require_treasury_read,
)
from ante.web.schemas import (
    BalanceSetResponse,
    BudgetListResponse,
    BudgetOperationResponse,
    SnapshotListResponse,
    SnapshotResponse,
    TransactionListResponse,
    TreasurySummaryResponse,
)
from ante.web.utils.date_params import (
    reject_inverted_date_range,
    validate_iso_date_only,
    validate_iso_date_param_for_sql_datetime,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# GET /api/treasury/transactions ``type`` query SSOT (#1477).
#
# 코드 SSOT는 ``ante.treasury.treasury.TRANSACTION_TYPE_VOCABULARY`` (5-value
# frozenset, #1476). FastAPI/Pydantic ``Literal``은 정적 리터럴 튜플을 요구하므로
# 별도 alias로 선언하되, 모듈 로드 시 vocabulary와 일치하지 않으면 즉시
# ``RuntimeError``를 raise해 contract drift를 차단한다. 새 vocabulary 값을
# 추가하면 양쪽을 함께 갱신해야 import 자체가 실패한다.
TransactionTypeQuery = Literal[
    "allocate",
    "deallocate",
    "release",
    "fill",
    "bot_stopped_release",
]

_TRANSACTION_TYPE_QUERY_VALUES: frozenset[str] = frozenset(
    {"allocate", "deallocate", "release", "fill", "bot_stopped_release"}
)

if _TRANSACTION_TYPE_QUERY_VALUES != TRANSACTION_TYPE_VOCABULARY:
    raise RuntimeError(
        "TransactionTypeQuery literal이 TRANSACTION_TYPE_VOCABULARY와 일치하지 "
        "않는다 — 둘을 함께 갱신하라. "
        f"literal={sorted(_TRANSACTION_TYPE_QUERY_VALUES)}, "
        f"vocabulary={sorted(TRANSACTION_TYPE_VOCABULARY)}"
    )


class BudgetChangeRequest(BaseModel):
    """예산 할당/회수 요청.

    OpenAPI ``BUDGET_CHANGE_REQUEST_SCHEMA``는 raw body 패턴(인증 가드 우선,
    body validation 후행)으로 동작하므로 FastAPI 자동 components 등록 경로를
    거치지 않는다. 본체 schema는 ``_install_openapi_customizer``가
    ``components.schemas``에 명시 등록한다(#1372).

    ``amount``는 finite-positive 숫자만 허용한다. ``NaN``/``±Infinity``/``0``/
    음수는 422로 거부된다(#1411). ``extra="forbid"``는 본 변경 scope 외 —
    frontend 호환 검증이 필요하므로 별도 이슈로 분리.
    """

    amount: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class BalanceSetRequest(BaseModel):
    """잔고 수동 설정 요청.

    OpenAPI ``BALANCE_SET_REQUEST_SCHEMA``는 ``additionalProperties: false``를
    선언한다. 런타임 모델도 ``extra="forbid"``로 동일하게 강제해 OpenAPI
    contract와 동작을 일치시킨다(#1352 — Codex Plan Review).
    """

    model_config = ConfigDict(extra="forbid")

    balance: Annotated[float, Field(ge=0, allow_inf_nan=False)]


# POST /api/treasury/bots/{bot_id}/allocate, /deallocate OpenAPI request body 문서.
#
# 두 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1372). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type BudgetChangeRequest``를
# 만들지 못한다. 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고
# 본체 schema는 ``_install_openapi_customizer``가 ``components.schemas``에
# 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴).
BUDGET_CHANGE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "BudgetChangeRequest",
    "description": (
        "POST /api/treasury/bots/{bot_id}/allocate, "
        "POST /api/treasury/bots/{bot_id}/deallocate 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1372). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    ),
    "required": ["amount"],
    "properties": {
        "amount": {
            "type": "number",
            "exclusiveMinimum": 0,
            "description": (
                "할당/회수 금액 (원). finite한 양수(> 0)만 허용된다. "
                "NaN, Infinity, -Infinity, 0, 음수는 422로 거부된다(#1411)."
            ),
        },
    },
}


# POST /api/treasury/balance OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1352). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type BalanceSetRequest``를
# 만들지 못한다. 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고
# 본체 schema는 ``_install_openapi_customizer``가 ``components.schemas``에
# 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴).
BALANCE_SET_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "BalanceSetRequest",
    "description": (
        "POST /api/treasury/balance 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1352). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    ),
    "additionalProperties": False,
    "required": ["balance"],
    "properties": {
        "balance": {
            "type": "number",
            "minimum": 0,
            "description": "수동 설정할 계좌 총 잔고 (음수 불가, NaN/Inf 불가).",
        },
    },
}


@router.get(
    "",
    response_model=TreasurySummaryResponse,
    response_model_exclude_none=True,
    responses={
        404: {
            "description": "Account not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_summary(
    request: Request,
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """자금 현황 요약. 인증된 master/human 또는 ``treasury:read`` scope 를
    보유한 agent 만 호출 가능 (#1407).

    account_id 지정 시 해당 계좌의 Treasury 요약을 반환한다.
    미지정 시 기본 Treasury 요약을 반환한다 (하위 호환).
    """
    target_treasury = treasury
    if account_id and treasury_manager is not None:
        try:
            target_treasury = treasury_manager.get(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"계좌를 찾을 수 없습니다: {account_id}",
            )

    summary = target_treasury.get_summary()
    # account_balance → total_balance 매핑 (TreasurySummaryResponse 스키마 정합)
    if "account_balance" in summary and "total_balance" not in summary:
        summary["total_balance"] = summary["account_balance"]
    summary["account_id"] = getattr(target_treasury, "account_id", None)
    summary["currency"] = getattr(target_treasury, "currency", "KRW")
    summary["commission_rate"] = getattr(
        target_treasury, "buy_commission_rate", 0.00015
    )
    summary["sell_tax_rate"] = getattr(target_treasury, "sell_commission_rate", 0.00195)

    # 브로커 메타정보 (하위 호환)
    broker = getattr(request.app.state, "broker", None)
    if broker is not None:
        summary["broker_id"] = broker.broker_id
        summary["broker_name"] = broker.broker_name
        summary["broker_short_name"] = broker.broker_short_name
        summary["exchange"] = broker.exchange

    # KIS 계좌 헤더 정보 (하위 호환)
    config = getattr(request.app.state, "config", None)
    if config is not None:
        try:
            account_no = config.secret("KIS_ACCOUNT_NO")
            if account_no and len(account_no) == 10:
                summary["account_no"] = f"{account_no[:8]}-{account_no[8:]}"
            elif account_no:
                summary["account_no"] = account_no
        except Exception as e:
            logger.warning("KIS 계좌번호 조회 실패: %s", e)
    # is_virtual: Account.trading_mode 기반 판정 (Refs #990)
    acct_svc = getattr(request.app.state, "account_service", None)
    target_account_id = getattr(target_treasury, "account_id", None) or account_id
    if acct_svc is not None and target_account_id:
        try:
            account = await acct_svc.get(target_account_id)
            if account is not None:
                trading_mode = getattr(account, "trading_mode", None)
                if trading_mode is not None:
                    summary["is_virtual"] = trading_mode.value == "virtual"
                else:
                    summary["is_virtual"] = True
            else:
                summary["is_virtual"] = True
        except Exception:
            summary["is_virtual"] = True
    else:
        summary["is_virtual"] = True

    last_synced = getattr(target_treasury, "last_synced_at", None)
    if last_synced is not None:
        summary["synced_at"] = last_synced.isoformat()

    return summary


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    responses={
        422: {
            "description": (
                "Invalid ``start_date``/``end_date`` (ISO ``YYYY-MM-DD`` required)."
                " ``treasury_transactions.created_at``은 SQLite ``datetime('now')``"
                " 포맷(``YYYY-MM-DD HH:MM:SS``)으로 저장되며, 검증된 boundary로만"
                " 비교한다 (#1440). ``start_date > end_date`` (inverted range)도"
                " 422로 거부한다 (#1595). ``type`` query는 정규 vocabulary"
                " ``{allocate, deallocate, release, fill, bot_stopped_release}``"
                " (#1476) 외 값을 ``Literal`` 좁힘으로 422 거부한다 (#1477)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_transactions(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    account_id: str | None = None,
    type: Annotated[
        TransactionTypeQuery | None,
        Query(
            alias="type",
            description=(
                "Treasury transaction type 필터. 정규 vocabulary"
                " ``allocate``, ``deallocate``, ``release``, ``fill``,"
                " ``bot_stopped_release`` (#1476) 외 값은 422로 거부된다 (#1477)."
                " 미지정 시 모든 type을 반환한다."
            ),
        ),
    ] = None,
    bot_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """자금 변동 이력 조회. 인증된 master/human 또는 ``treasury:read`` scope 를
    보유한 agent 만 호출 가능 (#1407).

    ``start_date``/``end_date``는 ISO ``YYYY-MM-DD`` (date-only)만 허용한다.
    파싱 실패 또는 캘린더 invalid는 422로 거부된다. 내부적으로 SQLite
    ``datetime('now')`` 저장 포맷(``YYYY-MM-DD HH:MM:SS``)에 맞춰
    ``start_date``는 ``00:00:00``, ``end_date``는 ``23:59:59``로 확장된 뒤
    SQL 텍스트 비교에 사용된다 (#1440).

    ``type`` query는 ``TRANSACTION_TYPE_VOCABULARY`` (#1476)를 SSOT로 하는
    ``Literal``로 좁혀, vocabulary 외 값을 FastAPI 단계에서 422로 거부한다
    (#1477). invalid 값이 200 + empty result로 통과하던 oracle A7 host probe
    회귀(fingerprint ``a4f6744a44f5``)를 차단한다.
    """
    start_bound = validate_iso_date_param_for_sql_datetime(
        start_date, "start_date", end_of_day=False
    )
    end_bound = validate_iso_date_param_for_sql_datetime(
        end_date, "end_date", end_of_day=True
    )
    # boundary str lexicographic 정합: start ``YYYY-MM-DD 00:00:00`` ≤ end
    # ``YYYY-MM-DD 23:59:59`` 이므로 동일 날짜는 통과, 역전만 422 거부 (#1595).
    reject_inverted_date_range(start_bound, end_bound)

    db = getattr(treasury, "_db", None)
    if db is None:
        return {"items": [], "total": 0}

    where_clauses: list[str] = []
    params: list[str | int] = []

    if account_id:
        where_clauses.append("account_id = ?")
        params.append(account_id)
    if type:
        where_clauses.append("transaction_type = ?")
        params.append(type)
    if bot_id:
        where_clauses.append("bot_id = ?")
        params.append(bot_id)
    if start_bound:
        where_clauses.append("created_at >= ?")
        params.append(start_bound)
    if end_bound:
        where_clauses.append("created_at <= ?")
        params.append(end_bound)

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    count_row = await db.fetch_one(
        f"SELECT COUNT(*) as cnt FROM treasury_transactions{where_sql}",
        tuple(params),
    )
    total = count_row["cnt"] if count_row else 0

    query = (
        f"SELECT * FROM treasury_transactions{where_sql}"
        " ORDER BY created_at DESC LIMIT ? OFFSET ?"
    )
    rows = await db.fetch_all(query, (*params, limit, offset))
    items = [
        {
            "id": r["id"],
            "type": r["transaction_type"],
            "bot_id": r["bot_id"],
            "amount": r["amount"],
            "description": r["description"],
            "created_at": r["created_at"],
        }
        for r in rows
    ]
    return {"items": items, "total": total}


@router.post(
    "/bots/{bot_id}/allocate",
    response_model=BudgetOperationResponse,
    responses={
        400: {
            "description": "Insufficient funds or invalid amount",
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
            "description": (
                "Permission denied (master, human 멤버 또는 treasury:admin "
                "scope 보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot not stopped",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, type mismatch, "
                "amount 누락, amount가 NaN/±Infinity/0/음수). 단, 인증이 실패하면 "
                "body validation은 실행되지 않고 401이 우선 반환된다(#1372, #1411)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
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
                    "schema": {"$ref": "#/components/schemas/BudgetChangeRequest"},
                },
            },
        },
    },
)
async def allocate(
    bot_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_treasury_admin)],
    treasury: Annotated[Any, Depends(get_treasury)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇에 예산 할당. 인증된 master/human 또는 ``treasury:admin`` scope 를
    보유한 agent 만 호출 가능 (#1407 — spec ``treasury:admin`` 정합, #1372
    master_caller 에서 마이그레이션).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: BudgetChangeRequest`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_treasury_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``BudgetChangeRequest.model_validate`` — ValidationError → 422.
    4. ``treasury.allocate`` 호출 (``BotNotStoppedError`` → 409).
    """
    from ante.treasury.exceptions import BotNotStoppedError

    # 1. raw body 읽기 + JSON 파싱 — 인증 통과 후에만 실행된다.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
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

    # 2. Pydantic 검증.
    try:
        body = BudgetChangeRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    if bot_manager is not None and bot_manager.get_bot(bot_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"봇을 찾을 수 없습니다: {bot_id}",
        )

    try:
        success = await treasury.allocate(bot_id, body.amount)
    except BotNotStoppedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not success:
        raise HTTPException(
            status_code=400,
            detail=(
                "예산 할당 실패: 미할당 자금 부족 또는 금액 오류"
                f" (요청: {body.amount:,.0f}원)"
            ),
        )

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="treasury.allocate",
            resource=f"bot:{bot_id}",
            detail=f"amount={body.amount:,.0f}",
            ip=request.client.host if request.client else "",
        )

    budget = treasury.get_budget(bot_id)
    return {
        "bot_id": bot_id,
        "allocated": budget.allocated if budget else 0.0,
        "available": budget.available if budget else 0.0,
    }


@router.post(
    "/bots/{bot_id}/deallocate",
    response_model=BudgetOperationResponse,
    responses={
        400: {
            "description": "Insufficient available budget",
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
            "description": (
                "Permission denied (master, human 멤버 또는 treasury:admin "
                "scope 보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Bot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        409: {
            "description": "Bot not stopped",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, type mismatch, "
                "amount 누락, amount가 NaN/±Infinity/0/음수). 단, 인증이 실패하면 "
                "body validation은 실행되지 않고 401이 우선 반환된다(#1372, #1411)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
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
                    "schema": {"$ref": "#/components/schemas/BudgetChangeRequest"},
                },
            },
        },
    },
)
async def deallocate(
    bot_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_treasury_admin)],
    treasury: Annotated[Any, Depends(get_treasury)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """봇 예산 회수. 인증된 master/human 또는 ``treasury:admin`` scope 를
    보유한 agent 만 호출 가능 (#1407 — spec ``treasury:admin`` 정합, #1372
    master_caller 에서 마이그레이션).

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_treasury_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``BudgetChangeRequest.model_validate`` — ValidationError → 422.
    4. ``treasury.deallocate`` 호출 (``BotNotStoppedError`` → 409).
    """
    from ante.treasury.exceptions import BotNotStoppedError

    # 1. raw body 읽기 + JSON 파싱 — 인증 통과 후에만 실행된다.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
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

    # 2. Pydantic 검증.
    try:
        body = BudgetChangeRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    if bot_manager is not None and bot_manager.get_bot(bot_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"봇을 찾을 수 없습니다: {bot_id}",
        )

    try:
        success = await treasury.deallocate(bot_id, body.amount)
    except BotNotStoppedError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"예산 회수 실패: 가용 예산 부족 (요청: {body.amount:,.0f}원)",
        )

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="treasury.deallocate",
            resource=f"bot:{bot_id}",
            detail=f"amount={body.amount:,.0f}",
            ip=request.client.host if request.client else "",
        )

    budget = treasury.get_budget(bot_id)
    return {
        "bot_id": bot_id,
        "allocated": budget.allocated if budget else 0.0,
        "available": budget.available if budget else 0.0,
    }


@router.get(
    "/budgets",
    response_model=BudgetListResponse,
    responses={
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_budgets(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """봇별 예산 목록 조회. 인증된 master/human 또는 ``treasury:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    from dataclasses import asdict

    budgets = treasury.list_budgets()
    items = []
    for b in budgets:
        d = asdict(b)
        # datetime → str 변환 (response_model 호환)
        if hasattr(b.last_updated, "isoformat"):
            d["last_updated"] = b.last_updated.isoformat()
        items.append(d)
    return {"budgets": items}


@router.post(
    "/balance",
    response_model=BalanceSetResponse,
    responses={
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
            "description": (
                "Permission denied (master, human 멤버 또는 treasury:admin "
                "scope 보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 미지정 필드, "
                "balance 음수/NaN/Inf). 단, 인증이 실패하면 body validation은 "
                "실행되지 않고 401이 우선 반환된다(#1352)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
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
                    "schema": {"$ref": "#/components/schemas/BalanceSetRequest"},
                },
            },
        },
    },
)
async def set_balance(
    request: Request,
    caller_id: Annotated[str, Depends(require_treasury_admin)],
    treasury: Annotated[Any, Depends(get_treasury)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """계좌 총 잔고 수동 설정. 인증된 master/human 또는 ``treasury:admin`` scope
    를 보유한 agent 만 호출 가능 (#1407 — spec ``treasury:admin`` 정합, #1352
    master_caller 에서 마이그레이션).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: BalanceSetRequest`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_treasury_admin)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``BalanceSetRequest.model_validate`` — ValidationError → 422.
    4. ``treasury.set_account_balance`` 호출.
    """
    # 1. raw body 읽기 + JSON 파싱.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(status_code=422, detail="요청 body가 비어 있습니다.")
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
        body = BalanceSetRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    await treasury.set_account_balance(body.balance)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="treasury.set_balance",
            resource="treasury",
            detail=f"balance={body.balance:,.0f}",
            ip=request.client.host if request.client else "",
        )

    return {
        "total_balance": treasury.account_balance,
        "updated_at": datetime.now(UTC).isoformat(),
    }


# ── 일별 자산 스냅샷 ──────────────────────────────────────


def _resolve_treasury(
    treasury: Any,
    treasury_manager: Any | None,
    account_id: str | None,
) -> Any:
    """account_id가 주어지면 해당 계좌의 Treasury를 반환한다."""
    if account_id and treasury_manager is not None:
        try:
            return treasury_manager.get(account_id)
        except KeyError:
            raise HTTPException(
                status_code=404,
                detail=f"계좌를 찾을 수 없습니다: {account_id}",
            )
    return treasury


@router.get(
    "/snapshots/latest",
    response_model=SnapshotResponse,
    responses={
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_latest_snapshot(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """가장 최근 일별 스냅샷 조회. 인증된 master/human 또는 ``treasury:read``
    scope 를 보유한 agent 만 호출 가능 (#1407)."""
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_latest_snapshot()
    if snapshot is not None:
        return {"snapshot": snapshot}

    # 스냅샷 미존재 시 get_summary() fallback (시스템 초기 구동)
    summary = target.get_summary()
    now = datetime.now(UTC)
    today = now.strftime("%Y-%m-%d")
    return {
        "snapshot": {
            "account_id": target.account_id,
            "snapshot_date": today,
            "total_asset": summary.get("total_evaluation", 0.0),
            "ante_eval_amount": summary.get("ante_eval_amount", 0.0),
            "ante_purchase_amount": summary.get("ante_purchase_amount", 0.0),
            "unallocated": summary.get("unallocated", 0.0),
            "account_balance": summary.get("account_balance", 0.0),
            "total_allocated": summary.get("total_allocated", 0.0),
            "bot_count": summary.get("bot_count", 0),
            "daily_pnl": 0.0,
            "daily_return": 0.0,
            "net_trade_amount": 0.0,
            "unrealized_pnl": 0.0,
            "created_at": now.isoformat(),
        }
    }


@router.get(
    "/snapshots",
    response_model=SnapshotListResponse,
    responses={
        422: {
            "description": (
                "Invalid ``start_date``/``end_date`` (ISO ``YYYY-MM-DD`` required). "
                "``treasury_daily_snapshots.snapshot_date`` 컬럼이 date-only로 "
                "저장되므로 임의 문자열을 허용하지 않는다 (#1440). "
                "``start_date > end_date`` (inverted range)도 422로 거부한다 "
                "(#1595)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_snapshots(
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict:
    """기간별 일별 스냅샷 목록. 인증된 master/human 또는 ``treasury:read`` scope
    를 보유한 agent 만 호출 가능 (#1407).

    ``start_date``/``end_date``는 ISO ``YYYY-MM-DD`` (date-only)만 허용한다.
    파싱 실패 또는 캘린더 invalid는 422로 거부된다 (#1440).
    """
    start_date = validate_iso_date_only(start_date, "start_date")
    end_date = validate_iso_date_only(end_date, "end_date")
    # default 적용 이전: 미지정(None)은 통과, start>end (inverted) 만 거부 (#1595).
    reject_inverted_date_range(start_date, end_date)

    target = _resolve_treasury(treasury, treasury_manager, account_id)

    if start_date is None:
        start_date = "2000-01-01"
    if end_date is None:
        end_date = datetime.now(UTC).strftime("%Y-%m-%d")

    snapshots = await target.get_snapshots(start_date, end_date)
    return {"snapshots": snapshots}


@router.get(
    "/snapshots/{date}",
    response_model=SnapshotResponse,
    responses={
        404: {
            "description": "Snapshot not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Invalid ``date`` path param (ISO ``YYYY-MM-DD`` required). "
                "malformed/캘린더 invalid path는 404가 아닌 422로 거부된다 (#1440)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Treasury not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_snapshot_by_date(
    date: Annotated[
        str,
        Path(
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description=(
                "ISO date-only (``YYYY-MM-DD``). 정규식은 형식만 막고, 캘린더 "
                "유효성(존재하지 않는 ``2026-13-32`` 등)은 handler 진입 시 "
                "``validate_iso_date_only``가 다시 검증한다 (defense-in-depth, "
                "#1440)."
            ),
        ),
    ],
    _caller_id: Annotated[str, Depends(require_treasury_read)],
    treasury: Annotated[Any, Depends(get_treasury)],
    treasury_manager: Annotated[Any | None, Depends(get_treasury_manager_optional)],
    account_id: str | None = None,
) -> dict:
    """특정일 스냅샷 조회. 인증된 master/human 또는 ``treasury:read`` scope 를
    보유한 agent 만 호출 가능 (#1407).

    ``date`` path param은 ISO ``YYYY-MM-DD``만 허용한다. FastAPI ``Path``의
    정규식 패턴이 형식을 일차 차단(422), handler 진입 시 캘린더 유효성을
    다시 검증한다 (e.g. ``2026-13-32``는 정규식은 통과하지만 캘린더 invalid
    → 422). 두 단계 모두 ``HTTPException(422)``으로 변환된다 (#1440).
    """
    date = validate_iso_date_only(date, "date") or date
    target = _resolve_treasury(treasury, treasury_manager, account_id)
    snapshot = await target.get_daily_snapshot(date)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail=f"스냅샷을 찾을 수 없습니다: {date}",
        )
    return {"snapshot": snapshot}
