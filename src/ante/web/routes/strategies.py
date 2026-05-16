"""전략 관리 API."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from ante.web.deps import (
    get_bot_manager_optional,
    get_db,
    get_db_optional,
    get_strategy_registry,
    get_trade_service,
    get_trade_service_optional,
    require_strategy_read,
    require_strategy_write,
)
from ante.web.schemas import (
    DailySummaryResponse,
    MonthlySummaryResponse,
    StatusUpdateRequest,
    StrategyDetailResponse,
    StrategyListResponse,
    StrategyPerformanceResponse,
    StrategyTradesResponse,
    StrategyValidateRequest,
    StrategyValidateResponse,
    WeeklySummaryResponse,
)
from ante.web.utils.account_params import reject_invalid_account_id

router = APIRouter()

_STRATEGY_NOT_FOUND = "전략을 찾을 수 없습니다"
_VALID_STATUS_FILTERS = {"registered", "adopted", "archived"}
_logger = logging.getLogger(__name__)


# PATCH /api/strategies/{strategy_id}/status OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(#1378). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema 로 두면 frontend codegen 이 ``export type StatusUpdateRequest``
# 를 만들지 못한다. 따라서 라우트 ``openapi_extra`` 는 ``$ref`` 매핑만 노출하고
# 본체 schema 는 ``_install_openapi_customizer`` 가 ``components.schemas`` 에
# ``setdefault`` 등록한다(#1374 ``ReportSubmitRequest`` SSOT 패턴 답습).
#
# 본체 schema 는 Pydantic 모델 SSOT (``StatusUpdateRequest``) 의
# ``model_json_schema()`` 출력에서 파생한다. ``default=None`` 만 strip 해
# openapi-typescript 가 optional 필드를 ``?`` 마커로 노출하도록 보존한다 —
# ``required`` / ``additionalProperties`` invariants 는 모두 모델 정의 그대로
# 유지된다 (#1374 _build_report_submit_request_schema 와 동일 패턴).
def _build_status_update_request_schema() -> dict[str, Any]:
    schema = StatusUpdateRequest.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    return schema


STATUS_UPDATE_REQUEST_SCHEMA: dict[str, Any] = _build_status_update_request_schema()


# POST /api/strategies/validate OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다 (#1407). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema 로 두면 frontend codegen 이 ``export type
# StrategyValidateRequest`` 를 만들지 못해 generated client 의 requestBody
# 가 ``never`` 로 노출된다 (#1429). 따라서 라우트 ``openapi_extra`` 는
# ``$ref`` 매핑만 노출하고 본체 schema 는 ``_install_openapi_customizer`` 가
# ``components.schemas`` 에 ``setdefault`` 등록한다 (``StatusUpdateRequest``
# / ``ReportSubmitRequest`` SSOT 패턴 답습).
#
# 본체 schema 는 Pydantic 모델 SSOT (``StrategyValidateRequest``) 의
# ``model_json_schema()`` 출력에서 파생한다. ``default=None`` 만 strip 해
# openapi-typescript 가 optional 필드를 ``?`` 마커로 노출하도록 보존한다 —
# ``required`` / ``additionalProperties`` invariants 는 모두 모델 정의 그대로
# 유지된다.
def _build_strategy_validate_request_schema() -> dict[str, Any]:
    schema = StrategyValidateRequest.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    return schema


STRATEGY_VALIDATE_REQUEST_SCHEMA: dict[str, Any] = (
    _build_strategy_validate_request_schema()
)


def _find_bot_for_strategy(bot_manager: Any, strategy_id: str) -> dict | None:
    """bot_manager에서 strategy_id에 매칭되는 봇을 찾아 반환한다."""
    if bot_manager is None:
        return None
    for b in bot_manager.list_bots():
        if b.get("strategy_id") == strategy_id:
            return b
    return None


@router.post(
    "/validate",
    response_model=StrategyValidateResponse,
    responses={
        400: {
            "description": "Path is required",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization "
                "header AND missing or invalid ante_session cookie)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 strategy:write "
                "scope 보유 agent 만 허용)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Strategy file not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, non-string "
                "``path`` 같은 type mismatch — #1410 회귀 방지). 단, 인증이 "
                "실패하면 body validation 은 실행되지 않고 401 이 우선 반환된다 "
                "(#1407)."
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
                    "schema": {"$ref": "#/components/schemas/StrategyValidateRequest"},
                },
            },
        },
    },
)
async def validate_strategy(
    request: Request,
    _caller_id: Annotated[str, Depends(require_strategy_write)],
) -> dict:
    """전략 파일 정적 검증. 인증된 master/human 또는 ``strategy:write`` scope
    를 보유한 agent 만 호출 가능 (#1407 — spec ``strategy:write`` 정합).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. 핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_strategy_write)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``StrategyValidateRequest.model_validate`` — ValidationError → 422
       (#1410 — non-string ``path`` 같은 type mismatch 차단).
    4. ``path`` 필드 추출 — 빈 문자열은 400.
    5. 파일 존재 확인 → 404.
    6. ``StrategyValidator.validate`` 호출.

    Body: ``{"path": "/path/to/strategy.py"}``
    """
    from ante.strategy.validator import StrategyValidator

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

    # Pydantic 검증 — non-string ``path`` 입력은 422 로 거부된다 (#1410).
    try:
        body = StrategyValidateRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    filepath = body.path
    if not filepath:
        raise HTTPException(status_code=400, detail="path is required")

    path = Path(filepath)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Strategy file not found")

    validator = StrategyValidator()
    result = validator.validate(path)

    return {
        "valid": result.valid,
        "errors": result.errors,
        "warnings": result.warnings,
    }


@router.get(
    "",
    response_model=StrategyListResponse,
    responses={
        503: {
            "description": "Strategy registry not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_strategies(
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    db: Annotated[Any | None, Depends(get_db_optional)],
    status: str | None = Query(default=None),
) -> dict:
    """전략 목록 조회. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    if status is not None and status not in _VALID_STATUS_FILTERS:
        raise HTTPException(
            status_code=400,
            detail=f"허용되지 않은 status 값: {status} "
            f"(허용: {', '.join(sorted(_VALID_STATUS_FILTERS))})",
        )
    records = await registry.list_strategies(status=status)

    bots_by_strategy: dict[str, dict] = {}
    if bot_manager is not None:
        for bot_info in bot_manager.list_bots():
            sid = bot_info.get("strategy_id", "")
            if sid:
                bots_by_strategy[sid] = bot_info

    # 전략별 cumulative_return 일괄 조회
    cumulative_returns: dict[str, float | None] = {}
    if db is not None:
        from ante.trade.performance import PerformanceTracker

        tracker = PerformanceTracker(db)

        # N+1 해소: asyncio.gather 로 병렬 호출.
        # 봇이 없는 strategy는 account_id를 결정할 수 없으므로 calculate 호출
        # 자체를 skip하고 cumulative_return = None으로 응답한다
        # (`"default"` fallback 금지, #1218).
        def _account_id_for(r: Any) -> str | None:
            bi = bots_by_strategy.get(r.strategy_id)
            if bi is None:
                return None
            account_id = bi.get("account_id")
            return account_id if isinstance(account_id, str) and account_id else None

        records_with_account: list[tuple[Any, str]] = []
        for r in records:
            acc = _account_id_for(r)
            if acc is None:
                cumulative_returns[r.strategy_id] = None
            else:
                records_with_account.append((r, acc))

        tasks = [
            tracker.calculate(account_id=acc, strategy_id=r.strategy_id)
            for r, acc in records_with_account
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (r, _acc), result in zip(records_with_account, results):
            if isinstance(result, BaseException):
                _logger.debug(
                    "전략 %s cumulative_return 계산 실패",
                    r.strategy_id,
                    exc_info=result,
                )
                cumulative_returns[r.strategy_id] = None
            elif result.total_trades > 0:
                cumulative_returns[r.strategy_id] = result.net_pnl
            else:
                cumulative_returns[r.strategy_id] = None

    strategies = []
    for r in records:
        bot_info = bots_by_strategy.get(r.strategy_id)
        strategies.append(
            {
                "id": r.strategy_id,
                "name": r.name,
                "version": r.version,
                "status": r.status.value
                if hasattr(r.status, "value")
                else str(r.status),
                "author_name": r.author_name,
                "author_id": r.author_id,
                "bot_id": bot_info["bot_id"] if bot_info else None,
                "bot_status": bot_info["status"] if bot_info else None,
                "cumulative_return": cumulative_returns.get(r.strategy_id),
            }
        )

    return {"strategies": strategies}


@router.patch(
    "/{strategy_id}/status",
    status_code=204,
    responses={
        400: {
            "description": (
                "허용되지 않은 상태 전환 (예: ``archived`` → ``adopted``). "
                "registry transition rule 위반은 400, body validation 실패는 "
                "422 (#1441)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        401: {
            "description": (
                "Authentication required (missing or invalid Authorization "
                "header AND missing or invalid ante_session cookie). 대시보드 "
                "사용자는 로그인 후 ante_session 쿠키만 가지고 호출하며, "
                "에이전트 클라이언트는 Bearer 토큰만 가지고 호출한다. 둘 중 "
                "하나라도 유효하면 통과한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        403: {
            "description": (
                "Permission denied (master, human 멤버 또는 strategy:write "
                "scope 보유 agent 만 허용). spec require_scope predicate 정합."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 "
                "누락, type mismatch, extra key, status 값이 transition target "
                "이 아님). ``status`` 는 ``Literal['adopted','archived']`` 로 "
                "좁혀져 ``registered`` 같은 GET filter 전용 값도 PATCH 시 "
                "422 로 거부된다 (#1441). 단, 인증이 실패하면 body validation "
                "은 실행되지 않고 401 이 우선 반환된다(#1378)."
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
                    "schema": {"$ref": "#/components/schemas/StatusUpdateRequest"},
                },
            },
        },
    },
)
async def update_strategy_status(
    strategy_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_strategy_write)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
) -> None:
    """전략 상태 변경. 보관 전환용. 인증된 master/human 또는
    ``strategy:write`` scope 를 보유한 agent 만 호출 가능 (#1378).

    ``submit_report`` (#1374) / ``update_config`` (#1373) 와 동일한 raw body
    파싱 패턴을 적용해 인증 가드가 body validation 보다 우선 실행되도록 한다.
    FastAPI 가 ``body: StatusUpdateRequest`` 를 먼저 검증하면 unauth + bad-body
    시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_strategy_write)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``StatusUpdateRequest.model_validate`` — ValidationError → 422
       (#1441 — ``extra='forbid'`` + ``Literal['adopted','archived']`` 이
       임의 필드 / 임의 status 값 / ``registered`` transition 시도 / type
       mismatch 를 422 로 거부).
    4. ``StrategyStatus`` enum 변환 — Pydantic Literal 이 enum value 와 1:1
       매칭되므로 항상 성공한다 (defense 분기 없음, #1441).
    5. ``registry.update_status`` 호출 — 누락 strategy → 404, 전환 rule
       위반 (예: archived → adopted) → 400.
    """
    from ante.strategy.exceptions import StrategyError
    from ante.strategy.registry import StrategyStatus

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

    # 2. Pydantic 검증 — ``extra='forbid'`` + ``Literal['adopted','archived']``
    #    이 임의 필드 / invalid status / ``registered`` (transition target 아님)
    #    / type mismatch 를 422 로 거부한다 (#1441).
    try:
        body = StatusUpdateRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    # 3. enum 변환 — Pydantic Literal value 가 ``StrategyStatus`` enum value
    #    와 1:1 매칭이라 항상 성공한다 (#1441 — 기존 try/except ValueError
    #    분기는 Pydantic 단에서 차단되므로 dead-code 였음).
    new_status = StrategyStatus(body.status)

    try:
        await registry.update_status(strategy_id, new_status)
    except StrategyError:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)
    except ValueError as e:
        # transition rule 위반 (archived → adopted 등) 은 registry layer 에서
        # ValueError 로 시그널링된다 — 400 으로 매핑.
        raise HTTPException(status_code=400, detail=str(e))


@router.get(
    "/{strategy_id}",
    response_model=StrategyDetailResponse,
    responses={
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 상세 조회. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    strategy_dict = asdict(record)
    strategy_dict["status"] = (
        record.status.value if hasattr(record.status, "value") else str(record.status)
    )
    # datetime -> str 변환 (response_model 호환)
    if hasattr(record.registered_at, "isoformat"):
        strategy_dict["registered_at"] = record.registered_at.isoformat()

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)

    # 전략 클래스에서 params/param_schema 런타임 추출
    params: dict[str, Any] = {}
    param_schema: dict[str, str] = {}
    filepath = record.filepath
    if filepath:
        try:
            from ante.strategy.loader import StrategyLoader

            strategy_cls = StrategyLoader.load(Path(filepath))
            instance = strategy_cls(ctx=None)
            params = instance.get_params()
            param_schema = instance.get_param_schema()
        except Exception:
            _logger.debug(
                "전략 %s params 추출 실패 (filepath=%s)",
                strategy_id,
                filepath,
                exc_info=True,
            )

    # rationale, risks: StrategyRecord에서 추출
    rationale = getattr(record, "rationale", "") or ""
    risks = getattr(record, "risks", []) or []

    return {
        "strategy": strategy_dict,
        "bot": bot_info,
        "status": strategy_dict["status"],
        "params": params,
        "param_schema": param_schema,
        "rationale": rationale,
        "risks": risks,
    }


@router.get(
    "/{strategy_id}/performance",
    response_model=StrategyPerformanceResponse,
    responses={
        400: {
            "description": (
                "account_id를 결정할 수 없음 (``account_id`` 미지정 + 전략에 "
                "연결된 봇 없음). #1218 query 정책 — fallback 없이 명시 실패."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Invalid ``account_id`` query. 제공된 runtime-invalid 값"
                ' (``""``/``"default"``/``^[a-zA-Z0-9\\-]{3,30}$`` 불일치)은'
                " account 해석/lookup 이전에 422로 거부된다. ``account_id``"
                " 미지정(``None``)은 봇 추출 fallback으로 통과하며, 추출 불가 시"
                " 400이다 (#1218 omitted 정책 보존, #1624)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry or database not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy_performance(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
    trade_service: Annotated[Any | None, Depends(get_trade_service_optional)],
    account_id: str | None = None,
) -> dict:
    """전략 성과 지표 조회. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407).

    제공된 runtime-invalid ``account_id`` (``""``/``"default"``/패턴 위반)는
    account 해석/lookup **이전**에 422로 거부한다 (#1624). ``account_id``
    미지정(``None``)은 가드를 통과해 봇 추출 fallback → (추출 불가 시) 400으로
    이어진다 — #1218이 정렬한 omitted query 정책을 보존한다. valid-pattern
    but absent(``acc-9999``)는 가드를 통과해 기존 단건 존재 검증 404로
    이어진다 (invalid-format ↔ genuine not-found 분리).

    가드는 함수 진입 직후, strategy 레지스트리/봇 조회 **이전**에 실행한다.
    그래야 존재하지 않는 ``strategy_id`` + provided-invalid ``account_id``
    조합에서도 account_id 422 계약이 strategy 존재 여부에 종속되지 않는다
    (#1624 ingress invariant)."""
    reject_invalid_account_id(account_id)

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    # account_id 결정: 쿼리 파라미터 우선, 없으면 봇에서 추출.
    # 둘 다 실패하면 `"default"` fallback 없이 400으로 명시 실패한다 (#1218 query 정책).
    resolved_account_id = account_id
    if not resolved_account_id:
        bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
        if bot_info:
            resolved_account_id = bot_info.get("account_id")
    if not resolved_account_id:
        raise HTTPException(
            status_code=400,
            detail=(
                "account_id를 결정할 수 없습니다. "
                "?account_id=<id> 쿼리 파라미터를 지정하거나, "
                "해당 전략에 연결된 봇이 있어야 합니다."
            ),
        )

    # resolved_account_id 확정 후, performance 계산 전에 account 존재를
    # 검증한다. PerformanceTracker.calculate 는 다수 소비자가 쓰는 저수준
    # metric 계산이므로 검증을 넣지 않고(multi-consumer 불변), ingress
    # 라우트에서만 검증한다. 쿼리/봇 fallback 어느 경로로 결정됐든 동일한
    # resolved_account_id 를 lightweight 단건 존재 쿼리로 확인한다. 쿼리
    # 의미는 AccountService.get(account_id 단건, status 필터 없음)과
    # 일치하며, credentials 복호화를 트리거하지 않아 무관한 계좌의 복호화
    # 실패가 정상 사용을 깨뜨리지 않는다 (#1559 일관).
    #
    # ``accounts`` 테이블은 ``AccountService.initialize()`` 에서만 생성되며,
    # 부분 초기화/legacy DB 에서는 테이블 자체가 없어
    # ``sqlite3.OperationalError: no such table: accounts`` 가 전파될 수
    # 있다. 정의상 accounts 테이블 부재는 해당 account 미존재와 동치이므로
    # 동일한 404 로 정규화한다. 단, malformed db 같은 다른
    # ``OperationalError`` 까지 삼키지 않도록 "no such table" 메시지일
    # 때로만 좁힌다 (#1558/#1559 에서 검증된 패턴).
    try:
        account_row = await db.fetch_one(
            "SELECT 1 FROM accounts WHERE account_id = ?",
            (resolved_account_id,),
        )
        account_exists = account_row is not None
    except sqlite3.OperationalError as e:
        if "no such table" in str(e).lower():
            account_exists = False
        else:
            raise
    if not account_exists:
        raise HTTPException(
            status_code=404,
            detail=f"계좌를 찾을 수 없습니다: {resolved_account_id}",
        )

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)
    metrics = await tracker.calculate(
        account_id=resolved_account_id, strategy_id=strategy_id
    )

    result = asdict(metrics)
    # sharpe_ratio가 None이면 응답 모델(float)과 호환되도록 0.0으로 변환
    if result.get("sharpe_ratio") is None:
        result["sharpe_ratio"] = 0.0

    # equity curve: bot_id가 있으면 추가
    equity_curve: list[dict] = []
    if trade_service is not None:
        bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
        if bot_info:
            from ante.report.feedback import PerformanceFeedback

            assert bot_manager is not None  # guarded by bot_info check
            feedback = PerformanceFeedback(
                trade_service=trade_service,
                bot_manager=bot_manager,
            )
            equity_curve = await feedback.get_equity_curve(bot_info["bot_id"])

    result["equity_curve"] = equity_curve
    return result


@router.get(
    "/{strategy_id}/daily-summary",
    response_model=DailySummaryResponse,
    responses={
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry or database not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy_daily_summary(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 일별 성과 집계. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    # strategy에 연결된 bot_id 찾기
    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

    summaries = await tracker.get_daily_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "date": s.date,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/weekly-summary",
    response_model=WeeklySummaryResponse,
    responses={
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry or database not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy_weekly_summary(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 주별 성과 집계. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

    summaries = await tracker.get_weekly_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "week_start": s.week_start,
                "week_end": s.week_end,
                "week_label": s.week_label,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/monthly-summary",
    response_model=MonthlySummaryResponse,
    responses={
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry or database not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy_monthly_summary(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    db: Annotated[Any, Depends(get_db)],
    bot_manager: Annotated[Any | None, Depends(get_bot_manager_optional)],
) -> dict:
    """전략 월별 성과 집계. 인증된 master/human 또는 ``strategy:read`` scope 를
    보유한 agent 만 호출 가능 (#1407)."""
    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    from ante.trade.performance import PerformanceTracker

    tracker = PerformanceTracker(db)

    bot_info = _find_bot_for_strategy(bot_manager, strategy_id)
    bot_id = bot_info["bot_id"] if bot_info else None

    summaries = await tracker.get_monthly_summary(bot_id=bot_id)
    return {
        "items": [
            {
                "year": s.year,
                "month": s.month,
                "realized_pnl": s.realized_pnl,
                "trade_count": s.trade_count,
                "win_rate": s.win_rate,
            }
            for s in summaries
        ]
    }


@router.get(
    "/{strategy_id}/trades",
    response_model=StrategyTradesResponse,
    responses={
        404: {
            "description": "Strategy not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Strategy registry or trade service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_strategy_trades(
    strategy_id: str,
    _caller_id: Annotated[str, Depends(require_strategy_read)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
    trade_service: Annotated[Any, Depends(get_trade_service)],
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> dict:
    """전략 거래 내역 조회 (cursor 기반 페이지네이션). 인증된 master/human 또는
    ``strategy:read`` scope 를 보유한 agent 만 호출 가능 (#1407)."""
    from ante.web.pagination import paginate

    record = await registry.get(strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail=_STRATEGY_NOT_FOUND)

    trades = await trade_service.get_trades(
        strategy_id=strategy_id,
        limit=limit + 1,
    )

    items = [
        {
            "trade_id": str(t.trade_id),
            "bot_id": t.bot_id,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "price": t.price,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "timestamp": str(t.timestamp),
        }
        for t in trades
    ]

    result = paginate(items, cursor_field="trade_id", limit=limit, cursor=cursor)
    return {"trades": result["items"], "next_cursor": result["next_cursor"]}
