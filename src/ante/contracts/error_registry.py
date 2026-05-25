"""Domain exception → ErrorSpec mapping registry (#1840).

본 모듈은 ``docs/specs/contracts/error-taxonomy.md`` 가 lock 한 **대표 fault
lock** 4 건을 코드로 mapping 한다. helper
(``ante.contracts.helpers.error_spec_for_exception``) 는 본 registry 를 MRO
기반 lookup 하여 exception → ``ErrorSpec`` 을 resolve 한다.

본 PR(#1840) 범위에서 등록되는 lock 4건:

- ``InvalidAccountIdError`` → ``VALIDATION_ERROR`` / ``validation``
- ``BotNotFoundError`` → ``BOT_NOT_FOUND`` / ``not_found``
- ``ApprovalNotFoundError`` → ``APPROVAL_NOT_FOUND`` / ``not_found``
- ``InvalidScopeError`` (member, code=``MEMBER_INVALID_SCOPE``) →
  ``MEMBER_INVALID_SCOPE`` / ``permission``

추가로 ``SERVICE_NOT_CONFIGURED`` 는 #1819 dispatch wrapper 가 도입할 예정인
``ServiceNotConfiguredError`` 의 ErrorSpec value 를 module-level constant
(``_SERVICE_NOT_CONFIGURED_SPEC``) 로 reserved 보존한다. 해당 exception class
는 본 PR 에서 import 하지 않으며 (#1819 가 도입할 책임), 후속 PR 이 class 를
추가하면 한 줄 entry 추가로 mapping 을 연결할 수 있다.

본 모듈은 helper-internal 로 취급한다 — ``ante.contracts.__init__`` 에서
re-export 하지 않으며, 외부 소비자는 ``error_spec_for_exception(exc)`` 를
호출한다.
"""

from __future__ import annotations

from typing import Final

from ante.account.errors import InvalidAccountIdError
from ante.approval.errors import ApprovalNotFoundError
from ante.bot.exceptions import BotNotFoundError
from ante.contracts.errors import ErrorSpec
from ante.member.scopes import InvalidScopeError

__all__ = [
    "EXCEPTION_TO_SPEC",
    "EXECUTION_ERROR_SPEC",
]


# ── 대표 lock 4건 (#1839 normative) ──────────────────────────────────────────

_INVALID_ACCOUNT_ID_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="VALIDATION_ERROR",
    category="validation",
)

_BOT_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_FOUND",
    category="not_found",
)

_APPROVAL_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_NOT_FOUND",
    category="not_found",
)

_MEMBER_INVALID_SCOPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_SCOPE",
    category="permission",
)


# ── reserved entry (#1819 후속 도입) ─────────────────────────────────────────
#
# ``SERVICE_NOT_CONFIGURED`` 는 taxonomy SSOT 가 ``service_unavailable`` 카테고리
# 안정 코드로 lock 한 값이다. 해당 fault를 raise하는 도메인 exception class는
# #1819 IPC CommandSpec metadata epic 이 ``ServiceNotConfiguredError`` 로 도입할
# 예정이다. 본 PR 은 ErrorSpec value 만 module-level constant 로 reserved 보존
# 하며, exception class 는 import 하지 않는다 — 후속 PR 이 class 를 추가하면
# ``EXCEPTION_TO_SPEC`` 에 한 줄 entry 를 더하는 것으로 연결할 수 있다.
_SERVICE_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="SERVICE_NOT_CONFIGURED",
    category="service_unavailable",
)


# ── fallback (registry miss + .code 도 없을 때) ──────────────────────────────

EXECUTION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="EXECUTION_ERROR",
    category="internal",
)
"""``error_spec_for_exception`` 의 최후 fallback ErrorSpec.

taxonomy SSOT (#1839) ``EXECUTION_ERROR 허용 범위`` 절이 명시한 두 경우 —
코드 버그 / unexpected programming error, 또는 외부 라이브러리 미분류 예외 —
에 적용된다. domain exception 이 ``code`` 미부여로 본 fallback 에 접히는 것은
taxonomy drift로 분류되며, drift test guard (#1841) 가 별도 책임으로 검출한다.
"""


# ── exception → spec mapping ─────────────────────────────────────────────────

EXCEPTION_TO_SPEC: Final[dict[type[BaseException], ErrorSpec]] = {
    InvalidAccountIdError: _INVALID_ACCOUNT_ID_SPEC,
    BotNotFoundError: _BOT_NOT_FOUND_SPEC,
    ApprovalNotFoundError: _APPROVAL_NOT_FOUND_SPEC,
    InvalidScopeError: _MEMBER_INVALID_SCOPE_SPEC,
}
"""대표 fault lock registry (#1839 normative 4건).

``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__`` 순서로 본 dict를
조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` 활용 → ``EXECUTION_ERROR`` fallback 순서로
resolve 한다.
"""
