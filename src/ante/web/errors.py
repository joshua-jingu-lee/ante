"""RFC 7807 에러 처리 — exception handler 및 에러 유형 카탈로그."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
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


def _sanitize_pydantic_errors(errors: list[dict]) -> list[dict]:
    """글로벌 ``RequestValidationError`` 의 error dict 에서 입력 값 반사를 제거.

    ``fastapi.exceptions.RequestValidationError.errors()`` 는 FastAPI 0.135.1
    에서 ``include_input`` / ``include_context`` kwargs 를 지원하지 않으므로
    (pydantic ``ValidationError.errors()`` 와 시그니처가 다름) kwargs 를 쓰면
    핸들러가 ``TypeError`` 를 던져 422 대신 500 이 반환된다. 따라서 글로벌
    핸들러는 ``errors()`` 를 호출한 뒤 사후적으로 ``input``/``ctx`` 키만
    제거하고 ``loc``/``type``/``msg``/``url`` 은 보존한다 (보안 invariant
    #1629 L1: 거부된 입력 값/ctx 미반사; ``loc`` 키 정규화는 #1643).
    """
    return [
        {k: v for k, v in error.items() if k not in _SANITIZED_ERROR_KEYS}
        for error in errors
    ]


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
