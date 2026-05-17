"""멤버 관리 API."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from ante.member.errors import PermissionDeniedError
from ante.member.models import MemberRole, MemberStatus, MemberType
from ante.member.scopes import SCOPE_VOCABULARY, InvalidScopeError
from ante.web.deps import (
    get_audit_logger_optional,
    get_member_service,
    require_master_caller,
    require_member_read,
)
from ante.web.schemas import (
    MemberCreateResponse,
    MemberDetailResponse,
    MemberListResponse,
    MemberScopesResponse,
    MemberTokenResponse,
    OkResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# 공개 API 응답 노출 계약 (docs/specs/member/03-member-model.md). credential
# verifier material(`token_hash`/`password_hash`/`recovery_key_hash`)은 어떤
# member 응답에도 포함하지 않는다. `MemberInfo`(extra="ignore")와 더불어
# defense-in-depth 의 route 계층 allowlist (#1627).
_PUBLIC_MEMBER_FIELDS: tuple[str, ...] = (
    "member_id",
    "type",
    "role",
    "org",
    "name",
    "emoji",
    "status",
    "scopes",
    "created_at",
    "created_by",
    "last_active_at",
    "suspended_at",
    "revoked_at",
    "token_expires_at",
)


def _public_member(member: Any) -> dict[str, Any]:
    """Member dataclass 를 공개 응답 노출 계약 필드만 담은 dict 로 변환한다.

    `token_hash`/`password_hash`/`recovery_key_hash` 등 노출 계약에 없는
    필드는 절대 포함하지 않는다(스키마/config 회귀 시에도 누출 불가).
    """
    raw = asdict(member)
    return {key: raw[key] for key in _PUBLIC_MEMBER_FIELDS if key in raw}


_AUTH_REQUIRED_RESPONSE_DESCRIPTION = (
    "Authentication required (missing or invalid Authorization header "
    "AND missing or invalid ante_session cookie). 대시보드 사용자는 "
    "로그인 후 ante_session 쿠키만 가지고 호출하며, 에이전트 클라이언트는 "
    "Bearer 토큰만 가지고 호출한다. 둘 중 하나라도 유효하면 통과한다."
)


_AUTH_REQUIRED_RESPONSE: dict[str, Any] = {
    "description": _AUTH_REQUIRED_RESPONSE_DESCRIPTION,
    "content": {
        "application/problem+json": {
            "schema": {"$ref": "#/components/schemas/ErrorResponse"},
        },
    },
}


def _validate_scopes_vocabulary(value: list[str]) -> list[str]:
    """scopes 필드 element 가 ``SCOPE_VOCABULARY`` 에 등록되어 있는지 검증한다.

    SSOT 는 ``src/ante/member/scopes.py`` (#1439 — Codex Plan Review r1 결정).
    invalid 시 ``ValueError`` 를 raise 하여 Pydantic 이 422 로 자동 변환하게
    한다. ``MemberCreateRequest.scopes`` 와 ``ScopesUpdateRequest.scopes`` 양쪽에
    동일 invariant 를 강제한다.

    인증 가드 이후에 실행되어야 한다 (#1339 / #1351 — auth-first 순서). 본
    validator 는 Pydantic ``model_validate`` 단계에서 실행되며, 라우트는 raw
    body 파싱 패턴으로 인증 가드를 먼저 통과시킨 뒤 ``model_validate`` 를
    호출하므로 unauth + invalid scope 케이스에서도 401 이 먼저 반환되어
    contract 가 보존된다.
    """
    for scope in value:
        if scope not in SCOPE_VOCABULARY:
            # 거부된 raw scope 값을 msg 에 interpolation 하지 않는다 (보안
            # invariant #1629 L1 반사 경로 2 — include_input=False 후에도
            # custom validator msg 가 거부값을 반사함). 실패 위치는 ``loc``
            # 가 제공. SSOT: src/ante/member/scopes.py.
            msg = "scopes에 SCOPE_VOCABULARY 미등록 값이 포함되어 있습니다"
            raise ValueError(msg)
    return value


class MemberCreateRequest(BaseModel):
    """멤버 등록 요청.

    ``member_type`` 은 ``MemberType`` enum SSOT(``human`` / ``agent``) 로,
    ``role`` 은 ``MemberRole`` enum SSOT(``master`` / ``admin`` / ``default``)
    로 강제한다 (#1465 — split #1417/A; #1628 — ``member_type`` 동형 미러).
    알 수 없는 member_type / role 문자열은 Pydantic 이 자동으로 422 로
    거부하므로 service / token 생성 전에 차단된다.
    """

    model_config = ConfigDict(extra="forbid")

    member_id: str
    member_type: MemberType
    role: MemberRole = MemberRole.DEFAULT
    org: str = "default"
    name: str = ""
    scopes: list[str] = []

    _validate_scopes = field_validator("scopes")(_validate_scopes_vocabulary)


# POST /api/members OpenAPI request body 문서.
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작하지만(이슈 #1339 P2 — Codex finding), Swagger UI / agent client / SDK는
# 정확한 입력 contract를 발견할 수 있어야 한다.
#
# ``MemberCreateRequest.model_json_schema()`` 직접 노출은 가능하지만 본 dict 상수로
# manual schema를 두는 편이 OpenAPI 표면 안정성과 spec 정합성 측면에서 더 안전하다.
MEMBER_CREATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "MemberCreateRequest",
    "description": (
        "POST /api/members 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1339, #1543). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    ),
    "additionalProperties": False,
    "required": ["member_id", "member_type"],
    "properties": {
        "member_id": {
            "type": "string",
            "description": "고유 식별자.",
        },
        "member_type": {
            "type": "string",
            "enum": ["human", "agent"],
            "description": "멤버 타입.",
        },
        "role": {
            "type": "string",
            "enum": ["master", "admin", "default"],
            "default": "default",
            "description": (
                "멤버 역할. ``MemberRole`` enum SSOT 에 따라 ``master`` / "
                "``admin`` / ``default`` 중 하나여야 한다 (#1465, SSOT: "
                "``src/ante/member/models.py``). 알 수 없는 문자열은 422 로 "
                "거부된다."
            ),
        },
        "org": {
            "type": "string",
            "default": "default",
            "description": "소속 조직.",
        },
        "name": {
            "type": "string",
            "default": "",
            "description": "사용자에게 표시되는 이름.",
        },
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "default": [],
            "description": (
                "권한 범위 목록. 각 원소는 SCOPE_VOCABULARY (#1439, SSOT: "
                "``src/ante/member/scopes.py``) 에 등록된 문자열이어야 한다. "
                "미등록 문자열은 422 로 거부된다."
            ),
        },
    },
}


class PasswordChangeRequest(BaseModel):
    """비밀번호 변경 요청.

    OpenAPI ``PASSWORD_CHANGE_REQUEST_SCHEMA``는 ``additionalProperties:
    false``를 선언한다. 런타임 모델도 ``extra="forbid"``로 동일하게 강제해
    OpenAPI contract와 동작을 일치시킨다(#1351 패턴 답습 — Finding P2:
    request schema contract drift 방지).
    """

    model_config = ConfigDict(extra="forbid")

    old_password: str
    new_password: str


# PATCH /api/members/{member_id}/password OpenAPI request body 문서 (#1377).
#
# 라우트는 raw body 파싱 패턴(인증 가드 우선, body validation 후행)으로
# 동작한다(이슈 #1377 — oracle A7 finding: 인증 없이 credential check 까지 도달).
# FastAPI 자동 components 등록 경로를 거치지 않으므로 inline schema로 두면
# frontend codegen이 ``export type PasswordChangeRequest`` 를 만들지 못한다.
# 따라서 라우트 ``openapi_extra`` 는 ``$ref`` 매핑만 노출하고 본체 schema 는
# ``_install_openapi_customizer`` 가 ``components.schemas`` 에 ``setdefault``
# 등록한다 (#1351 ``ScopesUpdateRequest`` SSOT 패턴).
#
# 본체 schema 는 Pydantic 모델 SSOT (``PasswordChangeRequest``) 의
# ``model_json_schema()`` 출력에서 파생한다. 수동 dict 정의는 invariants 를
# 매번 재구성해야 해서 회귀 위험이 있어 폐기한다 (#1374 / #1375 패턴 답습).
def _build_password_change_request_schema() -> dict[str, Any]:
    """``PasswordChangeRequest`` 를 OpenAPI components schema 로 변환.

    ``default: None`` 만 있는 optional 필드는 openapi-typescript 가
    ``T | null`` 필수 필드로 잘못 생성하는 회귀가 있어 (#1374), strip 후처리로
    정리한다. 현재 모델은 default 가 있는 필드가 없지만 패턴 일관성을 위해
    동일 helper 로직을 사용한다.
    """
    schema = PasswordChangeRequest.model_json_schema()
    properties = schema.get("properties", {})
    for prop in properties.values():
        if isinstance(prop, dict) and prop.get("default") is None and "default" in prop:
            prop.pop("default")
    schema["title"] = "PasswordChangeRequest"
    schema["description"] = (
        "PATCH /api/members/{member_id}/password 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1377, #1543). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    )
    return schema


PASSWORD_CHANGE_REQUEST_SCHEMA: dict[str, Any] = _build_password_change_request_schema()


class ScopesUpdateRequest(BaseModel):
    """권한 범위 변경 요청.

    OpenAPI ``MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA``는 ``additionalProperties:
    false``를 선언한다. 런타임 모델도 ``extra="forbid"``로 동일하게 강제해
    OpenAPI contract와 동작을 일치시킨다(#1351 2차 Codex review FAIL — Finding
    P2: ScopesUpdateRequest contract drift). ``MemberCreateRequest`` SSOT.

    ``scopes`` 각 원소는 ``SCOPE_VOCABULARY`` (``src/ante/member/scopes.py``)
    에 등록되어야 한다(#1439). 위반 시 Pydantic 이 자동으로 422 를 반환한다.
    """

    model_config = ConfigDict(extra="forbid")

    scopes: list[str]

    _validate_scopes = field_validator("scopes")(_validate_scopes_vocabulary)


# PUT /api/members/{member_id}/scopes OpenAPI request body 문서.
#
# ``update_scopes``는 ``create_member``와 동일하게 raw body 파싱 패턴을 쓰며
# (인증 가드 우선, body validation 후행 — 이슈 #1351 P1) ``body:
# ScopesUpdateRequest`` 인자를 라우트 시그니처에서 제거했다. 그 결과 FastAPI
# 자동 components 등록 경로를 거치지 않아 inline schema로 노출하면 frontend
# codegen이 ``export type ScopesUpdateRequest``를 만들지 못한다(이슈 #1351 1차
# Codex review FAIL — Finding 1).
#
# 따라서 라우트 ``openapi_extra``는 ``$ref`` 매핑만 노출하고 본체 schema는
# ``_install_openapi_customizer``가 ``components.schemas``에 등록한다.
MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "title": "ScopesUpdateRequest",
    "description": (
        "PUT /api/members/{member_id}/scopes 입력 contract. "
        "인증된 master 호출자만 사용할 수 있다(#1351, #1543). "
        "Bearer 토큰 또는 유효한 ante_session 쿠키 중 하나라도 있어야 하며, "
        "둘 다 없거나 둘 다 invalid면 body validation 전에 401로 차단된다."
    ),
    "additionalProperties": False,
    "required": ["scopes"],
    "properties": {
        "scopes": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "변경할 권한 범위 목록. 각 원소는 SCOPE_VOCABULARY (#1439, "
                "SSOT: ``src/ante/member/scopes.py``) 에 등록된 문자열이어야 "
                "한다. 미등록 문자열은 422 로 거부된다."
            ),
        },
    },
}


@router.get(
    "",
    response_model=MemberListResponse,
    responses={
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_members(
    _caller_id: Annotated[str, Depends(require_member_read)],
    svc: Annotated[Any, Depends(get_member_service)],
    type: MemberType | None = Query(default=None),
    org: str | None = Query(default=None),
    status: MemberStatus | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """멤버 목록 조회.

    ``type``과 ``status``는 도메인 enum SSOT(``MemberType`` /
    ``MemberStatus``)로 강제한다(#1358 — Codex Plan Review). 알 수 없는 값은
    FastAPI/Pydantic이 자동으로 422를 반환하므로 "200 빈 목록"으로 가려지지
    않는다. ``MemberService.list_members`` / ``count``는 ``str | None``을
    받으므로 ``StrEnum`` 인스턴스를 그대로 전달해도 SQL 비교(``type = ?`` /
    ``status = ?``)에서 문자열로 동작한다.
    """
    try:
        members = await svc.list_members(
            member_type=type, org=org, status=status, limit=limit, offset=offset
        )
        total = await svc.count(member_type=type, org=org, status=status)
    except Exception:
        logger.exception(
            "멤버 목록 조회 실패 (type=%s, org=%s, status=%s, limit=%d, offset=%d)",
            type,
            org,
            status,
            limit,
            offset,
        )
        raise HTTPException(
            status_code=503, detail="멤버 목록을 조회할 수 없습니다"
        ) from None
    return {"members": [_public_member(m) for m in members], "total": total}


@router.post(
    "",
    status_code=201,
    response_model=MemberCreateResponse,
    responses={
        400: {
            "description": "Invalid member data",
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
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, Authorization 헤더와 ante_session 쿠키 모두 "
                "유효하지 않으면 body validation은 실행되지 않고 401이 우선 "
                "반환된다(#1339 P2 / P1 cookie auth)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        # ``$ref`` 매핑을 사용해 ``components.schemas.MemberCreateRequest``를
        # 외부 노출한다(이슈 #1339 P1 — Codex finding). inline schema로 두면
        # FastAPI 자동 components 등록 경로를 거치지 않아 frontend codegen이
        # ``MemberCreateRequest`` 타입을 export하지 않는다. 실제 schema 본체는
        # ``_install_openapi_customizer``가 ``MEMBER_CREATE_REQUEST_SCHEMA``로
        # ``components.schemas``에 등록한다(``app.py``).
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/MemberCreateRequest"},
                },
            },
        },
    },
)
async def create_member(
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 등록. 토큰 1회 반환. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT
    ``docs/specs/web-api/11-route-scope-table.md``). ``member:admin`` scope 를
    보유한 agent 도 표면 가드에서 거부된다 (#1511 oracle drift 수렴).

    인증 가드는 body validation보다 **반드시 먼저** 실행된다(#1339 P2). FastAPI
    가 ``body: MemberCreateRequest`` 파라미터를 먼저 파싱하면 Authorization
    헤더 미존재 + 필수 필드 누락 케이스에서 401 이 아니라 422 가 먼저 응답되어
    "missing or invalid Authorization header는 401" 계약이 깨진다. 이 이유로
    본 라우트는 ``request: Request`` 와 ``require_master_caller`` 만 받고 raw
    body 를 직접 파싱한다 (``update_account`` SSOT 패턴 일치).

    핸들러 단계 순서:
    1. **인증 가드 (최우선, ``Depends(require_master_caller)``)** — caller 빈
       → 401, master 아님 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽고 JSON 파싱 — 실패 시 422.
    3. ``MemberCreateRequest.model_validate`` — ValidationError → 422.
    4. ``svc.register`` 호출. ``PermissionError`` → 403, ``ValueError`` → 400.
    """
    # 1. 인증 가드 — ``require_master_caller`` dependency 가 이미 통과시킴.

    # 2. raw body 읽기 + JSON 파싱.
    raw = await request.body()
    if raw == b"":
        raise HTTPException(
            status_code=422,
            detail="요청 body가 비어 있습니다.",
        )
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=422,
            detail="요청 body의 JSON 파싱에 실패했습니다.",
        ) from None
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=422,
            detail="요청 body는 JSON object여야 합니다.",
        )

    # 3. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = MemberCreateRequest.model_validate(payload)
    except ValidationError as e:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant #1629 L1; bots.py:433
        # / accounts.py:1307 선례와 동일 sanitizer).
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_context=False, include_input=False),
        ) from None

    # 4. service 호출.
    try:
        member, token = await svc.register(
            member_id=body.member_id,
            member_type=body.member_type,
            role=body.role,
            org=body.org,
            name=body.name,
            scopes=body.scopes,
            registered_by=caller,
        )
    except InvalidScopeError as e:
        # ingress(Pydantic field_validator) 가 통상 차단하지만 service 가
        # 별도 경로에서 raise 한 경우 422 로 매핑한다 (#1439 — Codex Plan
        # Review r1 defense-in-depth). ``ValueError`` 분기보다 먼저 catch
        # 해야 동일 super class 매칭에서 400 으로 가려지지 않는다.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.create",
            resource=f"member:{body.member_id}",
            detail=f"type={body.member_type}, role={body.role}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member), "token": token}


@router.get(
    "/{member_id}",
    response_model=MemberDetailResponse,
    responses={
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def get_member(
    member_id: str,
    _caller_id: Annotated[str, Depends(require_member_read)],
    svc: Annotated[Any, Depends(get_member_service)],
) -> dict:
    """멤버 상세 조회. 인증된 master/human 또는 ``member:read`` scope 를 보유한
    agent 만 호출 가능 (#1407)."""
    try:
        member = await svc.get(member_id)
    except Exception:
        logger.exception("멤버 상세 조회 실패 (member_id=%s)", member_id)
        raise HTTPException(
            status_code=503, detail="멤버 정보를 조회할 수 없습니다"
        ) from None
    if member is None:
        raise HTTPException(status_code=404, detail="멤버를 찾을 수 없습니다")
    return {"member": _public_member(member)}


@router.post(
    "/{member_id}/suspend",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def suspend_member(
    member_id: str,
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 일시 정지. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT)."""
    try:
        member = await svc.suspend(member_id, suspended_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.suspend",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member)}


@router.post(
    "/{member_id}/reactivate",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def reactivate_member(
    member_id: str,
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 재활성화. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT)."""
    try:
        member = await svc.reactivate(member_id, reactivated_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.reactivate",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member)}


@router.post(
    "/{member_id}/revoke",
    response_model=MemberDetailResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def revoke_member(
    member_id: str,
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """멤버 영구 폐기. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT)."""
    try:
        member = await svc.revoke(member_id, revoked_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.revoke",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member)}


@router.post(
    "/{member_id}/rotate-token",
    response_model=MemberTokenResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def rotate_token(
    member_id: str,
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """토큰 재발급. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT).

    인증 없이 token rotation 응답에 접근하면 token 값 자체가 노출되므로,
    가장 먼저 차단해야 한다.
    """
    try:
        member, token = await svc.rotate_token(member_id, rotated_by=caller)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.rotate_token",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member), "token": token}


@router.patch(
    "/{member_id}/password",
    response_model=OkResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": (
                "Permission denied (master 만 허용 — #1543, #1542 SSOT). "
                "``member:admin`` scope 를 보유한 agent 도 거부된다."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, 인증이 실패하면 body validation은 실행되지 "
                "않고 401이 우선 반환된다(#1377)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        # ``$ref`` 매핑을 사용해 ``components.schemas.PasswordChangeRequest``를
        # 외부 노출한다(이슈 #1377). raw body 패턴으로 라우트 시그니처에서
        # ``body: PasswordChangeRequest`` 인자를 제거하면서 FastAPI 자동
        # components 등록 경로가 사라졌다. 본체 schema는
        # ``_install_openapi_customizer``가 ``PASSWORD_CHANGE_REQUEST_SCHEMA``로
        # ``components.schemas``에 등록한다(``app.py``).
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/PasswordChangeRequest"},
                },
            },
        },
    },
)
async def change_password(
    member_id: str,
    request: Request,
    caller_id: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """비밀번호 변경 (human 멤버 전용). 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT, #1377 master_caller 에서
    마이그레이션 후 #1407 ``member:admin`` 표면 가드 회귀 → #1543 master-only
    재정렬).

    배경: oracle A7 finding (#1377) — 본 라우트는 인증 없이 credential check
    (``svc.change_password``의 old-password 비교) 까지 도달했다. ``_caller_id``
    만으로 audit 주체만 기록하고 인증 가드는 적용하지 않았기 때문이다. 본
    패치는 ``require_master_caller`` 의존성을 적용하고 ``update_scopes``와
    동일한 raw body 파싱 + auth-first 패턴을 따른다 (#1351 / #1352 SSOT).

    범위 결정:
    - master-only (보수). self-change use case (caller_id == member_id 허용)는
      follow-up 이슈에서 별도 다룬다 (Issue #1377 Non-Goals).

    인증 → raw-body → credential check 순서를 보장한다. FastAPI가
    ``body: PasswordChangeRequest``를 먼저 검증하면 unauth + bad-body 시 401이
    아닌 422가 먼저 반환되어 contract가 깨진다 — 본 라우트는 oracle A7
    finding의 핵심 시그니처이므로 인증 가드 우선이 가장 중요하다.

    핸들러 단계 순서:

    1. 인증 가드 (``Depends(require_master_caller)``) — caller 빈 → 401,
       master 아님 → 403, 비활성 멤버 → 403. credential check 도달 전에 모두
       차단된다.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``PasswordChangeRequest.model_validate`` — ValidationError → 422.
    4. ``svc.change_password`` 호출. ``ValueError`` → 404,
       ``PermissionError``/``PermissionDeniedError`` → 403.

    Audit 로그의 ``member_id``는 ``caller_id``로 기록한다(SSOT). 대상 멤버는
    ``resource=member:{member_id}``로 분리해 추적한다.
    """
    # 1. 인증 가드는 ``require_master_caller`` 의존성에 의해 이미 통과 상태.

    # 2. raw body 읽기 + JSON 파싱 — 인증 통과 후에만 실행된다.
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

    # 3. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = PasswordChangeRequest.model_validate(payload)
    except ValidationError as e:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant #1629 L1 probe 표면 —
        # password-adjacent secret 노출 차단; bots.py:433 선례 sanitizer).
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_context=False, include_input=False),
        ) from None

    # 4. credential check (svc.change_password 내부의 old-password 비교).
    try:
        await svc.change_password(member_id, body.old_password, body.new_password)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller_id,
            action="member.change_password",
            resource=f"member:{member_id}",
            ip=request.client.host if request.client else "",
        )

    return {"ok": True}


@router.put(
    "/{member_id}/scopes",
    response_model=MemberScopesResponse,
    responses={
        401: _AUTH_REQUIRED_RESPONSE,
        403: {
            "description": "Permission denied",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        404: {
            "description": "Member not found",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        422: {
            "description": (
                "Body validation 실패 (JSON 파싱 실패, 빈 body, 필수 필드 누락, "
                "type mismatch). 단, 인증이 실패하면 body validation은 실행되지 "
                "않고 401이 우선 반환된다(#1351)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Member service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
    openapi_extra={
        # ``$ref`` 매핑을 사용해 ``components.schemas.ScopesUpdateRequest``를
        # 외부 노출한다(이슈 #1351 1차 Codex review FAIL — Finding 1). raw body
        # 패턴으로 라우트 시그니처에서 ``body: ScopesUpdateRequest`` 인자를
        # 제거하면서 FastAPI 자동 components 등록 경로가 사라졌고, 본 schema
        # ref가 없으면 frontend codegen이 ``ScopesUpdateRequest`` 타입을
        # export하지 않는다. ``frontend/src/api/members.ts``는 이 타입을
        # import하므로 ``tsc -b`` 빌드가 깨진다. 본체 schema는
        # ``_install_openapi_customizer``가 ``MEMBER_SCOPES_UPDATE_REQUEST_SCHEMA``로
        # ``components.schemas``에 등록한다(``app.py``).
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {"$ref": "#/components/schemas/ScopesUpdateRequest"},
                },
            },
        },
    },
)
async def update_scopes(
    member_id: str,
    request: Request,
    caller: Annotated[str, Depends(require_master_caller)],
    svc: Annotated[Any, Depends(get_member_service)],
    audit_logger: Annotated[Any | None, Depends(get_audit_logger_optional)],
) -> dict:
    """권한 범위 변경. 인증된 master 만 호출 가능
    (#1543 — spec ``master-only`` 정합, #1542 SSOT).

    Raw body 파싱 패턴으로 인증 가드가 body validation 보다 우선 실행되도록
    한다. FastAPI 가 ``body: ScopesUpdateRequest`` 를 먼저 검증하면 unauth +
    bad-body 시 401 이 아닌 422 가 먼저 반환되어 contract 가 깨진다.

    핸들러 단계 순서:
    1. 인증 가드 (``Depends(require_master_caller)``) — caller 빈 → 401,
       master 아님 → 403, 비활성 멤버 → 403.
    2. raw bytes 읽기 + JSON 파싱 — 실패 시 422.
    3. ``ScopesUpdateRequest.model_validate`` — ValidationError → 422.
    4. ``svc.update_scopes`` 호출. ``ValueError`` → 404,
       ``PermissionError``/``PermissionDeniedError`` → 403.
    """
    # 1. 인증 가드 — ``require_master_caller`` 가 이미 통과시킴.

    # 2. raw body 읽기 + JSON 파싱.
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

    # 3. Pydantic 검증 — 인증 통과 후에만 실행된다.
    try:
        body = ScopesUpdateRequest.model_validate(payload)
    except ValidationError as e:
        # 거부된 입력 값/ctx 반사 금지 (보안 invariant #1629 L1; bots.py:433
        # / accounts.py:1307 선례와 동일 sanitizer).
        raise HTTPException(
            status_code=422,
            detail=e.errors(include_context=False, include_input=False),
        ) from None

    # 4. service 호출.
    try:
        member = await svc.update_scopes(member_id, body.scopes, updated_by=caller)
    except InvalidScopeError as e:
        # ingress(Pydantic field_validator) 가 통상 차단하지만 service 가
        # 별도 경로에서 raise 한 경우 422 로 매핑한다 (#1439). 매트릭스에서
        # ``ValueError`` 분기보다 먼저 catch 해야 ``InvalidScopeError`` 가
        # ``ValueError`` 의 서브클래스인 점이 404 로 새지 않는다.
        raise HTTPException(status_code=422, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (PermissionError, PermissionDeniedError) as e:
        raise HTTPException(status_code=403, detail=str(e)) from e

    if audit_logger:
        await audit_logger.log(
            member_id=caller or "anonymous",
            action="member.update_scopes",
            resource=f"member:{member_id}",
            detail=f"scopes={body.scopes}",
            ip=request.client.host if request.client else "",
        )

    return {"member": _public_member(member)}
