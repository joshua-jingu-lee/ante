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
    422: ("/errors/validation", "Validation Error"),
    500: ("/errors/internal", "Internal Server Error"),
    503: ("/errors/internal", "Service Unavailable"),
}

PROBLEM_JSON = "application/problem+json"


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
            detail=str(exc.errors()),
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
