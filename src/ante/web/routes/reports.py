"""리포트 관리 API."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from ante.report.models import ReportStatus
from ante.web.deps import (
    get_audit_logger_optional,
    get_report_store,
    require_report_write,
)
from ante.web.schemas import (
    ReportDetailResponse,
    ReportListResponse,
    ReportSchemaResponse,
    ReportSubmitRequest,
    ReportSubmitResponse,
)

router = APIRouter()


# POST /api/reports OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(#1374). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema 로 두면 frontend codegen 이 ``export type ReportSubmitRequest``
# 를 만들지 못한다. 따라서 라우트 ``openapi_extra`` 는 ``$ref`` 매핑만 노출하고
# 본체 schema 는 ``_install_openapi_customizer`` 가 ``components.schemas`` 에
# ``setdefault`` 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴).
#
# 본체 schema 는 Pydantic 모델 SSOT (``ReportSubmitRequest``) 의
# ``model_json_schema()`` 출력에서 파생한다. 수동 dict 정의는 다음 두 회귀를
# 만들어 폐기한다:
#
# - optional 메트릭(``sharpe_ratio``/``max_drawdown_pct``/``win_rate``) 에
#   ``"default": None`` 만 있고 ``required`` 에서 빠지지 않으면
#   openapi-typescript 가 ``number | null`` 필수 필드로 생성해 (``?`` 마커 없음),
#   메트릭을 생략하는 정상 제출이 타입 오류로 막힌다.
# - ``sections`` 가 런타임에 ``dict[str, Any] | None`` 인데 schema 에
#   ``additionalProperties`` 를 명시하지 않으면 generated type 이
#   ``Record<string, never> | null`` 이 되어 임의 section payload 를 보낼 수 없다.
#
# Pydantic 의 ``model_json_schema()`` 는 default 가 있는 필드를 ``required`` 에서
# 자동으로 빼고, ``dict[str, Any]`` 를 ``additionalProperties: true`` 로 노출하며,
# ``model_config = ConfigDict(extra="forbid")`` 를 top-level
# ``additionalProperties: false`` 로 반영한다. 다만 ``default=None`` 을 키 안에
# 그대로 남기면 openapi-typescript 가 ``?`` 마커 대신 ``T | null`` 필수 필드로
# 생성한다. FastAPI 자동 schema (``ReportSubmitRequest`` 가 라우트 시그니처에
# 살아 있던 #1374 이전 main 에서 노출되던 모양) 는 ``Optional[T] = None`` 의
# null default 를 한 단계 strip 해서 generated 타입이 ``field?: T | null`` 로
# 떨어지게 했었다. 동일 동작을 보존하기 위해 ``default: None`` 만 정리한다 —
# ``required`` / ``additionalProperties`` / numeric range / extra=forbid 같은
# invariants (#1353) 는 모두 모델 정의 그대로 보존된다.
def _build_report_submit_request_schema() -> dict[str, Any]:
    schema = ReportSubmitRequest.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    return schema


REPORT_SUBMIT_REQUEST_SCHEMA: dict[str, Any] = _build_report_submit_request_schema()


@router.get("/schema", response_model=ReportSchemaResponse)
async def get_report_schema() -> dict:
    """리포트 제출 스키마 조회."""
    from ante.report import ReportStore

    store = ReportStore.__new__(ReportStore)
    return store.get_schema()


@router.post(
    "",
    status_code=201,
    response_model=ReportSubmitResponse,
    responses={
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
                "Permission denied (master, human 멤버 또는 report:write scope "
                "보유 agent 만 허용). spec require_scope predicate 정합."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch, NaN/Inf, extra key). 단, 인증이 실패하면 body "
                "validation 은 실행되지 않고 401 이 우선 반환된다(#1374)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Report store not available",
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
                    "schema": {"$ref": "#/components/schemas/ReportSubmitRequest"},
                },
            },
        },
    },
)
async def submit_report(
    request: Request,
    caller_id: Annotated[str, Depends(require_report_write)],
    report_store: Annotated[Any, Depends(get_report_store)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """리포트 제출. 인증된 master/human 또는 ``report:write`` scope 를 보유한
    agent 만 호출 가능 (#1374).

    ``update_config`` (#1373) 와 동일한 raw body 파싱 패턴을 적용해 인증 가드가
    body validation 보다 우선 실행되도록 한다. FastAPI 가
    ``body: ReportSubmitRequest`` 를 먼저 검증하면 unauth + bad-body 시 401 이
    아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_report_write)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``ReportSubmitRequest.model_validate`` — ValidationError → 422.
    4. ``report_store.submit`` 호출 + audit 기록 (submitted_by = caller_id).
    """
    import uuid
    from datetime import UTC, datetime

    from ante.report.models import ReportStatus, StrategyReport

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

    # 2. Pydantic 검증 (#1353 invariants 보존).
    try:
        body = ReportSubmitRequest.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None

    # 3. submitted_by = caller_id (이전: request.state.member_id 또는 "agent").
    report = StrategyReport(
        report_id=f"rpt-{uuid.uuid4().hex[:12]}",
        strategy_name=body.strategy_name,
        strategy_version=body.strategy_version,
        strategy_path=body.strategy_path,
        status=ReportStatus.SUBMITTED,
        submitted_at=datetime.now(UTC),
        submitted_by=caller_id,
        backtest_period=body.backtest_period,
        total_return_pct=body.total_return_pct,
        total_trades=body.total_trades,
        sharpe_ratio=body.sharpe_ratio,
        max_drawdown_pct=body.max_drawdown_pct,
        win_rate=body.win_rate,
        summary=body.summary,
        rationale=body.rationale,
        risks=body.risks,
        recommendations=body.recommendations,
        detail_json=body.detail_json,
    )
    await report_store.submit(report)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="report.submit",
            resource=f"report:{report.report_id}",
            detail=f"strategy={report.strategy_name}",
            ip=request.client.host if request.client else "",
        )

    return {
        "report_id": report.report_id,
        "strategy": report.strategy_name,
        "status": report.status.value,
    }


@router.get(
    "/{report_id}",
    response_model=ReportDetailResponse,
    responses={
        404: {
            "description": "Report not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Report store not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def report_view(
    report_id: str,
    report_store: Annotated[Any, Depends(get_report_store)],
) -> dict:
    """리포트 단건 조회."""
    import json

    report = await report_store.get(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다")

    try:
        detail = json.loads(report.detail_json)
    except (json.JSONDecodeError, TypeError):
        detail = {}

    return {
        "report_id": report.report_id,
        "strategy_name": report.strategy_name,
        "strategy_version": report.strategy_version,
        "strategy_path": report.strategy_path,
        "status": report.status.value,
        "submitted_at": str(report.submitted_at),
        "submitted_by": report.submitted_by,
        "backtest_period": report.backtest_period,
        "total_return_pct": report.total_return_pct,
        "total_trades": report.total_trades,
        "sharpe_ratio": report.sharpe_ratio,
        "max_drawdown_pct": report.max_drawdown_pct,
        "win_rate": report.win_rate,
        "summary": report.summary,
        "rationale": report.rationale,
        "risks": report.risks,
        "recommendations": report.recommendations,
        "equity_curve": detail.get("equity_curve", []),
        "metrics": detail.get("metrics", {}),
        "initial_balance": detail.get("initial_balance"),
        "final_balance": detail.get("final_balance"),
        "config": detail.get("config"),
        "datasets": detail.get("datasets", []),
        "symbols": detail.get("symbols", []),
        "user_notes": report.user_notes,
        "reviewed_at": str(report.reviewed_at) if report.reviewed_at else None,
    }


@router.get(
    "",
    response_model=ReportListResponse,
    responses={
        503: {
            "description": "Report store not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_reports(
    report_store: Annotated[Any, Depends(get_report_store)],
    status: ReportStatus | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    """리포트 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    reports = await report_store.list_reports(status=status)
    items = [
        {
            "report_id": r.report_id,
            "strategy": r.strategy_name,
            "status": r.status.value,
            "submitted_at": str(r.submitted_at),
        }
        for r in reports
    ]

    result = paginate(items, cursor_field="report_id", limit=limit, cursor=cursor)
    return {"reports": result["items"], "next_cursor": result["next_cursor"]}
