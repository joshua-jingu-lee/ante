"""Stable error taxonomy mapper data model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["ErrorCategory", "ErrorSpec"]


ErrorCategory = Literal[
    "validation",
    "auth",
    "permission",
    "not_found",
    "state_conflict",
    "service_unavailable",
    "external",
    "internal",
]
"""안정 에러 코드의 분류 vocabulary.
"""


@dataclass(frozen=True)
class ErrorSpec:
    """안정 에러 코드 한 건의 normative spec.

    Attributes:
        retryable: reserved. 1.0 시점에서 소비자 미정 — envelope에 직렬화하지
            않는다. 기본 ``False``.
        default_message: helper가 사용할 optional fallback 메시지. envelope의
            ``message`` slot은 호출자가 제공한 도메인 문구를 우선 사용하며,
            본 fallback은 그 우선순위가 비어 있을 때만 사용된다 (envelope shape
            변경 없음).
    """

    code: str
    category: ErrorCategory
    exit_code: int = 1
    retryable: bool = False
    default_message: str | None = None
