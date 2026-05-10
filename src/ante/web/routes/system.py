"""시스템 상태 API."""

from __future__ import annotations

import json
import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from ante import __version__
from ante.web.deps import (
    get_account_service,
    get_account_service_optional,
    get_audit_logger_optional,
    get_db_optional,
    require_master_caller,
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


# POST /api/system/halt OpenAPI request body 문서 (#1375).
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1375). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type HaltRequest`` /
# ``export type ClearHaltRequest`` 를 만들지 못한다. 따라서 라우트
# ``openapi_extra`` 는 ``$ref`` 매핑만 노출하고 본체 schema 는
# ``_install_openapi_customizer`` 가 ``components.schemas`` 에 ``setdefault``
# 등록한다 (#1351 ``ScopesUpdateRequest`` SSOT 패턴).
#
# 본체 schema 는 Pydantic 모델 SSOT (``HaltRequest`` / ``ClearHaltRequest``) 의
# ``model_json_schema()`` 출력에서 파생한다. 수동 dict 정의는 default 가 있는
# 필드 (``reason: str = ""``) 를 ``required`` 에서 빼는 등의 invariants 를
# 매번 재구성해야 해서 회귀 위험이 있어 폐기한다 (#1374 ReportSubmitRequest
# 패턴 답습). ``reason`` 의 default 는 ``""`` 이고 ``None`` 이 아니므로 strip
# 후처리 영향은 없지만, 패턴 일관성을 위해 동일 helper 를 통과시킨다.
def _build_request_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Pydantic 모델을 OpenAPI components schema 로 변환.

    ``default: None`` 만 있는 optional 필드는 openapi-typescript 가
    ``T | null`` 필수 필드로 잘못 생성하는 회귀가 있어 (#1374), strip 후처리로
    정리한다. ``HaltRequest`` 는 default 가 ``""`` 라 영향 없지만 패턴
    일관성을 위해 동일 helper 를 사용한다.
    """
    schema = model.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    return schema


HALT_REQUEST_SCHEMA: dict[str, Any] = _build_request_schema(HaltRequest)
CLEAR_HALT_REQUEST_SCHEMA: dict[str, Any] = _build_request_schema(ClearHaltRequest)


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


async def _parse_optional_request_body(
    request: Request, model: type[BaseModel]
) -> BaseModel:
    """raw body 파싱 + 인증 후 Pydantic 검증 (kill switch 전용).

    halt / clear_halt 는 ``reason`` 이 optional 이라 빈 body 를 200 으로
    허용한다(기존 동작 보존). 단, ``None`` JSON literal / non-object JSON /
    malformed JSON 은 422 로 거부한다.

    1. ``await request.body()`` 로 raw bytes 읽기 — 인증 통과 후에만 실행.
    2. 빈 body 이면 default 인스턴스 반환 (``reason=""``).
    3. JSON 파싱 실패 / non-object → 422.
    4. ``model.model_validate`` ValidationError → 422.
    """
    raw = await request.body()
    if raw == b"":
        return model()
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
    try:
        return model.model_validate(payload)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors()) from None


@router.post(
    "/halt",
    response_model=KillSwitchResponse,
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
            "description": "Permission denied (master 권한 필요).",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (malformed JSON, non-object JSON, type "
                'mismatch). 빈 body 는 기본 ``reason=""`` 로 허용된다 (기존 '
                "동작 보존). 단, 인증이 실패하면 body validation 은 실행되지 "
                "않고 401 이 우선 반환된다 (#1375)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Account service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/HaltRequest"},
                },
            },
        },
    },
)
async def halt(
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전체 거래 중지 (모든 ACTIVE 계좌 SUSPENDED). 인증된 master 만 호출 가능
    (#1375).

    ``submit_report`` (#1374) 와 동일한 raw body 파싱 패턴을 적용해 인증 가드가
    body validation 보다 우선 실행되도록 한다. FastAPI 가
    ``body: HaltRequest`` 를 먼저 검증하면 unauth + bad-body 시 401 이 아닌
    422 가 먼저 반환되어 contract 가 깨진다 — 본 라우트는 oracle A7 finding
    의 핵심 시그니처 이므로 인증 가드 우선이 가장 중요하다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_master_caller)``) — caller 빈 → 401,
       non-master → 403.
    2. raw bytes 읽기 + JSON 파싱 — 빈 body 는 default 허용, 그 외 실패 시 422.
    3. ``HaltRequest.model_validate`` — ValidationError → 422.
    4. ``account_service.suspend_all`` 호출 + audit 기록
       (``halted_by`` / ``member_id`` = caller_id).
    """
    body_obj = await _parse_optional_request_body(request, HaltRequest)
    assert isinstance(body_obj, HaltRequest)
    body: HaltRequest = body_obj

    reason = body.reason or "dashboard"
    accounts = await account_service.suspend_all(reason=reason, suspended_by=caller_id)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
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
            "description": "Permission denied (master 권한 필요).",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (malformed JSON, non-object JSON, type "
                'mismatch). 빈 body 는 기본 ``reason=""`` 로 허용된다 (기존 '
                "동작 보존). 단, 인증이 실패하면 body validation 은 실행되지 "
                "않고 401 이 우선 반환된다 (#1375)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Account service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        "requestBody": {
            "required": False,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ClearHaltRequest"},
                },
            },
        },
    },
)
async def clear_halt(
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    account_service: Annotated[Any, Depends(get_account_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """전역 정지 해제 (모든 SUSPENDED 계좌 ACTIVE). 인증된 master 만 호출 가능
    (#1375).

    계좌 상태만 ACTIVE 로 복구하며 봇을 자동 재시작하지 않는다.

    ``halt`` 와 동일한 raw body 파싱 + auth-first 패턴을 따른다 (#1375).
    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_master_caller)``) — caller 빈 → 401,
       non-master → 403.
    2. raw bytes 읽기 + JSON 파싱 — 빈 body 는 default 허용, 그 외 실패 시 422.
    3. ``ClearHaltRequest.model_validate`` — ValidationError → 422.
    4. ``account_service.activate_all`` 호출 + audit 기록
       (``activated_by`` / ``member_id`` = caller_id).
    """
    body_obj = await _parse_optional_request_body(request, ClearHaltRequest)
    assert isinstance(body_obj, ClearHaltRequest)
    body: ClearHaltRequest = body_obj

    accounts = await account_service.activate_all(activated_by=caller_id)

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="system.clear_halt",
            resource="system:kill_switch",
            detail=body.reason,
            ip=request.client.host if request.client else "",
        )

    return _kill_switch_payload("halt_cleared", accounts)
