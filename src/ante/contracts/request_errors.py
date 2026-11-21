from __future__ import annotations

__all__ = ["RequestValidationError"]


class RequestValidationError(Exception):
    code = "VALIDATION_ERROR"
