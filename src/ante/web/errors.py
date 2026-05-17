"""RFC 7807 에러 처리 — exception handler 및 에러 유형 카탈로그."""

from __future__ import annotations

import logging
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from ante.web.schemas import ErrorResponse

logger = logging.getLogger(__name__)

# 에러 유형 카탈로그: HTTP 상태 코드 → (type URI, default title)
ERROR_CATALOG: dict[int, tuple[str, str]] = {
    400: ("/errors/validation", "Bad Request"),
    401: ("/errors/unauthorized", "Unauthorized"),
    403: ("/errors/forbidden", "Forbidden"),
    404: ("/errors/not-found", "Not Found"),
    409: ("/errors/conflict", "Conflict"),
    415: ("/errors/unsupported-media-type", "Unsupported Media Type"),
    422: ("/errors/validation", "Validation Error"),
    500: ("/errors/internal", "Internal Server Error"),
    503: ("/errors/internal", "Service Unavailable"),
}

PROBLEM_JSON = "application/problem+json"

# 422 validation 응답에서 거부된 입력 값을 노출하면 안 되는 top-level error 키.
# pydantic ``ValidationError.errors()`` 는 ``input``(거부된 원본 값) 과
# ``ctx``(``ValueError`` 객체 등 비-JSON repr) 를 포함한다.
_SANITIZED_ERROR_KEYS = ("input", "ctx")

# ``extra="forbid"`` 422 의 ``loc`` 말단(거부된 caller extra 필드 키)을
# caller-controlled segment 가 노출되지 않도록 치환하는 고정 placeholder
# 토큰. caller 가 제어할 수 없는 상수이며, 정규화 대상은 Pydantic
# ``error["type"] == "extra_forbidden"`` 항목의 ``loc[-1]`` 한정이다
# (#1650; 비-extra_forbidden caller-controlled loc 정책은 #1651).
_EXTRA_FORBIDDEN_LOC_PLACEHOLDER = "[extra]"


def _normalize_error_loc(errors: list[dict]) -> list[dict]:
    """``extra_forbidden`` 항목의 ``loc`` 말단 caller 키를 placeholder 로 치환.

    Pydantic ``error["type"] == "extra_forbidden"`` 인 항목의 ``loc`` 말단
    세그먼트는 거부된 caller extra 필드의 **키 이름**(예 ``api_secret``)이라
    caller-controlled 반사 벡터다 (#1643 → Split A #1650). 현 모든
    ``extra="forbid"`` 요청모델은 flat ``BaseModel`` 이라 extra 키는 항상
    ``loc`` 말단(요청모델 ``dict[str,<BaseModel>]``/nested forbid 0건 —
    #1643 v-series AST 실측)이므로 ``loc[-1]`` 만 고정 placeholder 로
    치환하면 caller 키가 사라진다. static ``loc`` prefix(``body`` 등)·
    ``type``/``msg``/``url``·기타 키는 보존하고, 원본 ``loc`` 컨테이너
    타입(글로벌 ``RequestValidationError`` = list, raw-body pydantic
    ``ValidationError`` = tuple)을 유지한다.

    **본 정규화는 ``type=='extra_forbidden'`` loc 벡터 한정**이다. 비-
    extra_forbidden caller-controlled loc(자유형 ``dict[str,*]`` 키,
    structured body, validator-합성 loc) 및 수동 unknown-key detail
    반사(``accounts.py`` PUT account update F3)는 본 함수가 정규화하지
    않으며 #1651(spec-first 종합 정책)에서 다룬다.
    """
    normalized: list[dict] = []
    for error in errors:
        if error.get("type") != "extra_forbidden":
            normalized.append(error)
            continue
        loc = error.get("loc")
        if not isinstance(loc, (list, tuple)) or len(loc) == 0:
            normalized.append(error)
            continue
        new_segments = list(loc[:-1]) + [_EXTRA_FORBIDDEN_LOC_PLACEHOLDER]
        new_loc: list | tuple = (
            tuple(new_segments) if isinstance(loc, tuple) else new_segments
        )
        normalized.append({**error, "loc": new_loc})
    return normalized


def _sanitize_pydantic_errors(errors: list[dict]) -> list[dict]:
    """글로벌 ``RequestValidationError`` 의 error dict 에서 입력 값 반사를 제거.

    ``fastapi.exceptions.RequestValidationError.errors()`` 는 FastAPI 0.135.1
    에서 ``include_input`` / ``include_context`` kwargs 를 지원하지 않으므로
    (pydantic ``ValidationError.errors()`` 와 시그니처가 다름) kwargs 를 쓰면
    핸들러가 ``TypeError`` 를 던져 422 대신 500 이 반환된다. 따라서 글로벌
    핸들러는 ``errors()`` 를 호출한 뒤 사후적으로 ``input``/``ctx`` 키만
    제거하고(보안 invariant #1629 L1: 거부된 입력 값/ctx 미반사), 이어서
    ``_normalize_error_loc`` 로 ``extra_forbidden`` 항목의 ``loc`` 말단
    caller 키를 placeholder 로 정규화한다 (#1650 L2; ``type``/``msg``/
    ``url``/static loc prefix 는 보존).
    """
    stripped = [
        {k: v for k, v in error.items() if k not in _SANITIZED_ERROR_KEYS}
        for error in errors
    ]
    return _normalize_error_loc(stripped)


def sanitize_validation_errors(exc: ValidationError) -> list[dict]:
    """raw-body pydantic ``ValidationError`` sanitization 공용 chokepoint.

    raw-body ``model_validate`` 사이트가 ``HTTPException(detail=...)`` 로
    422 를 던질 때 호출하는 단일 진입점이다. ``include_context=False,
    include_input=False`` 로 ``input``/``ctx`` 반사를 차단하고(보안
    invariant #1629 L1), ``_normalize_error_loc`` 로 ``extra_forbidden``
    항목의 ``loc`` 말단 caller 키를 placeholder 로 정규화한다 (#1650 L2).
    모든 raw-body 사이트가 ``e.errors(include_context=False,
    include_input=False)`` 직접호출 대신 본 helper 를 호출하여 sanitization
    동작을 단일 SSOT 로 고정한다(직접 호출 잔존 0 — discovery 게이트).
    """
    return _normalize_error_loc(
        cast(
            "list[dict[str, Any]]",
            list(exc.errors(include_context=False, include_input=False)),
        )
    )


def _build_error(status: int, detail: str, instance: str = "") -> ErrorResponse:
    """상태 코드에 맞는 RFC 7807 에러 응답 생성."""
    error_type, title = ERROR_CATALOG.get(status, ("/errors/internal", "Error"))
    return ErrorResponse(
        type=error_type,
        title=title,
        detail=detail,
        status=status,
        instance=instance,
    )


def register_exception_handlers(app: FastAPI) -> None:
    """FastAPI 앱에 RFC 7807 exception handler 등록."""

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        error = _build_error(
            status=exc.status_code,
            detail=str(exc.detail),
            instance=request.url.path,
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=error.model_dump(),
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error = _build_error(
            status=422,
            detail=str(_sanitize_pydantic_errors(list(exc.errors()))),
            instance=request.url.path,
        )
        return JSONResponse(
            status_code=422,
            content=error.model_dump(),
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        error = _build_error(
            status=400,
            detail=str(exc),
            instance=request.url.path,
        )
        return JSONResponse(
            status_code=400,
            content=error.model_dump(),
            media_type=PROBLEM_JSON,
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        logger.exception("처리되지 않은 예외: %s", request.url.path)
        error = _build_error(
            status=500,
            detail="An unexpected error occurred.",
            instance=request.url.path,
        )
        return JSONResponse(
            status_code=500,
            content=error.model_dump(),
            media_type=PROBLEM_JSON,
        )
