"""동적 설정 API."""

from __future__ import annotations

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ValidationError

from ante.config.exceptions import ConfigError
from ante.web.deps import (
    get_audit_logger_optional,
    get_dynamic_config,
    require_config_read,
    require_config_write,
)
from ante.web.schemas import ConfigListResponse, ConfigUpdateResponse

router = APIRouter()


class ConfigUpdateRequest(BaseModel):
    """설정 값 변경 요청."""

    value: Any
    category: str = ""


# PUT /api/config/{key} OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(#1373). FastAPI 자동 components 등록 경로를 거치지 않으므로
# inline schema로 두면 frontend codegen이 ``export type ConfigUpdateRequest``
# 를 만들지 못한다. 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고
# 본체 schema는 ``_install_openapi_customizer``가 ``components.schemas``에
# 등록한다(#1351 ``ScopesUpdateRequest`` SSOT 패턴, #1371/#1372 답습).
CONFIG_UPDATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "ConfigUpdateRequest",
    "description": (
        "PUT /api/config/{key} 입력 contract. "
        "인증된 master/human 또는 config:write scope 를 보유한 agent 만 사용할 "
        "수 있다(#1373). Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 "
        "있어야 하며, 둘 다 없거나 둘 다 invalid면 body validation 전에 401로 "
        "차단된다."
    ),
    "required": ["value"],
    "properties": {
        "value": {
            "description": (
                "변경할 설정 값. 타입은 키마다 다르다 — "
                "DynamicConfigService 가 키별 schema 검증을 담당한다."
            ),
        },
        "category": {
            "type": "string",
            "default": "",
            "description": (
                "설정 카테고리. 비우면 key 의 dot-prefix(예: ``risk.max_mdd`` "
                "→ ``risk``)에서 자동 추출된다."
            ),
        },
    },
}


@router.get(
    "",
    response_model=ConfigListResponse,
    responses={
        422: {
            "description": (
                "저장된 dynamic config 값이 invariant 를 위반한 경우 (예: legacy "
                "non-finite numeric row — #1412). 서비스 read 경계가 ConfigError "
                "로 격리한 결과를 422 problem+json 으로 변환한다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Config service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_configs(
    _caller_id: Annotated[str, Depends(require_config_read)],
    config_service: Annotated[Any, Depends(get_dynamic_config)],
) -> dict:
    """동적 설정 전체 조회. 인증된 master/human 또는 ``config:read`` scope 를
    보유한 agent 만 호출 가능 (#1407).

    저장된 값이 read invariant(예: numeric finite, #1412)를 위반하면 서비스
    경계가 ``ConfigError`` 를 raise 하며, 라우트는 이를 422 로 변환한다.
    """
    try:
        configs = await config_service.get_all()
    except ConfigError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None
    return {"configs": configs}


@router.put(
    "/{key:path}",
    response_model=ConfigUpdateResponse,
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
                "Permission denied (master, human 멤버 또는 config:write scope "
                "보유 agent 만 허용)"
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Config key not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, value 누락, "
                "type mismatch) 또는 키별 invariant 위반 (예: "
                "``system.log_level`` 가 ``_VALID_LOG_LEVELS`` 멤버가 아닌 "
                "경우 — 대소문자 구분, #1379). 단, 인증이 실패하면 body "
                "validation은 실행되지 않고 401이 우선 반환된다(#1373)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Config service not available",
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
                    "schema": {"$ref": "#/components/schemas/ConfigUpdateRequest"},
                },
            },
        },
    },
)
async def update_config(
    key: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_config_write)],
    config_service: Annotated[Any, Depends(get_dynamic_config)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """동적 설정 값 변경. 인증된 master/human 또는 config:write scope 보유
    agent 만 호출 가능 (#1373).

    ``update_bot`` (#1352) / ``create_bot`` (#1371) / ``allocate`` (#1372)
    와 동일한 raw body 파싱 패턴을 적용해 인증 가드가 body validation 보다
    우선 실행되도록 한다. FastAPI 가 ``body: ConfigUpdateRequest`` 를 먼저
    검증하면 unauth + bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract
    가 깨진다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_config_write)``) — caller 빈 → 401,
       권한 없음 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``ConfigUpdateRequest.model_validate`` — ValidationError → 422.
    4. config 키 존재 확인 → 404.
    5. ``config_service.set`` 호출 + audit 기록 (changed_by = caller_id).
       서비스 경계에서 ``validate_value`` 가 키별 invariant 를 검증하므로
       ``ValueError`` 가 올라오면 422 로 변환한다 (#1379).
    """
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
        body = ConfigUpdateRequest.model_validate(payload)
    except ValidationError as e:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant #1629 L1; bots.py:433
        # / accounts.py:1307 선례와 동일 sanitizer).
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_context=False, include_input=False),
        ) from None

    # 3. 키 존재 확인.
    if not await config_service.exists(key):
        raise HTTPException(status_code=404, detail=f"설정을 찾을 수 없습니다: {key}")

    # legacy non-finite numeric row 는 read 경계에서 ConfigError 로 격리되지만
    # (#1412), PUT 으로 정상 값을 덮어쓰는 self-healing 경로는 허용한다.
    # ``old_value`` 는 None 으로 두고 새 값으로 set 한다.
    try:
        old_value = await config_service.get(key)
    except ConfigError:
        old_value = None

    # category: 요청에 없으면 key에서 추출 (예: "risk.max_mdd" -> "risk")
    category = body.category or key.split(".")[0]

    # changed_by 를 caller_id 로 통일 (이전: 하드코딩된 "dashboard").
    # DynamicConfigService.set 는 키별 invariant 검증 실패 시 ValueError 를
    # raise 한다 (#1379 oracle A7 — system.log_level enum 검증). 422 변환.
    try:
        await config_service.set(
            key, body.value, category=category, changed_by=caller_id
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from None

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="config.update",
            resource=f"config:{key}",
            detail=f"{old_value!r} -> {body.value!r}",
            ip=request.client.host if request.client else "",
        )

    return {"key": key, "old_value": old_value, "new_value": body.value}
