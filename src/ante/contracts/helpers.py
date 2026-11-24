"""CLI/IPC error helper functions."""

from __future__ import annotations

import re

from ante.contracts.error_registry import EXCEPTION_TO_SPEC, EXECUTION_ERROR_SPEC
from ante.contracts.errors import ErrorSpec

__all__ = [
    "error_spec_for_exception",
    "ipc_error_payload",
]


_SCREAMING_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def error_spec_for_exception(exc: BaseException) -> ErrorSpec:
    """Exception 인스턴스를 ``ErrorSpec`` 으로 resolve.

    resolver 우선순위:

    1. ``EXCEPTION_TO_SPEC`` registry 의 MRO lookup — ``type(exc).__mro__`` 를
       따라 첫 매치를 반환한다 (subclass 도 base class registry entry로 매칭).
    2. ``getattr(exc, "code", None)`` 이 SCREAMING_SNAKE_CASE 규약을 만족하면
       해당 코드를 ``category="internal"`` 으로 보수적 ErrorSpec 으로 wrap한다.
    3. 위 둘 다 매치되지 않으면 ``EXECUTION_ERROR_SPEC`` (internal fallback).
    """

    for klass in type(exc).__mro__:
        spec = EXCEPTION_TO_SPEC.get(klass)
        if spec is not None:
            return spec

    code_attr = getattr(exc, "code", None)
    if isinstance(code_attr, str) and _SCREAMING_SNAKE_RE.match(code_attr):
        return ErrorSpec(code=code_attr, category="internal")

    return EXECUTION_ERROR_SPEC


def _resolve_message(exc: BaseException, spec: ErrorSpec) -> str:
    """``ipc_error_payload`` 의 message resolution."""

    exc_text = str(exc)
    if exc_text:
        return exc_text
    if spec.default_message:
        return spec.default_message
    return ""


def ipc_error_payload(exc: BaseException) -> dict[str, str]:
    """``{"code", "message"}`` IPC error payload helper.

    IPC 서버 ``_dispatch`` 가 쓰는 helper.

    Returns:
        ``{"code": <ErrorSpec.code>, "message": <resolved message>}``. 양쪽
        모두 str 이다 — envelope shape (envelopes.md) 와 정렬.
    """

    spec = error_spec_for_exception(exc)
    message = _resolve_message(exc, spec)
    return {"code": spec.code, "message": message}
