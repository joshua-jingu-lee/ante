"""Stable error taxonomy mapper data model (#1840).

이 모듈은 ``docs/specs/contracts/error-taxonomy.md`` 가 normative 로 lock 한
``ErrorSpec`` shape 의 코드 SSOT 다. CLI (``--format json``) 와 IPC (Unix domain
socket) 표면이 같은 안정 에러 코드 taxonomy 를 공유하도록 helper
(``ante.contracts.helpers``) 가 본 모듈의 dataclass 를 소비한다.


본 모듈은 runtime behavior 를 가지지 않는다 — Literal alias + frozen dataclass
만 제공한다.
"""

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

``docs/specs/contracts/error-taxonomy.md`` (#1839 normative) 의 ``Category 의미``
표가 lock한 8종 분류와 정확히 일치한다. 새 카테고리 도입은 taxonomy SSOT의
선행 갱신이 필요하다.
"""


@dataclass(frozen=True)
class ErrorSpec:
    """안정 에러 코드 한 건의 normative spec (#1839/#1840).

    Attributes:
        code: SCREAMING_SNAKE_CASE 안정 코드. envelope의 ``code``/``error.code``에
            그대로 직렬화된다. 도메인 prefix(``ACCOUNT_*``/``BOT_*``/``APPROVAL_*``/
            ``MEMBER_*`` 등) 또는 공통 코드(``VALIDATION_ERROR``/``EXECUTION_ERROR``/
            ``SERVICE_NOT_CONFIGURED`` 등)를 사용한다.
        category: ``ErrorCategory`` 8종 중 하나.
        exit_code: CLI 종료 코드. 기본 ``1``. click usage exit 2 전면 정렬은
            taxonomy SSOT 범위 밖(별도 이슈).
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
