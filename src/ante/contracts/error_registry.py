"""Domain exception → ErrorSpec mapping registry (#1840).

본 모듈은 ``docs/specs/contracts/error-taxonomy.md`` 가 lock 한 **대표 fault
lock** 4 건을 코드로 mapping 한다. helper
(``ante.contracts.helpers.error_spec_for_exception``) 는 본 registry 를 MRO
기반 lookup 하여 exception → ``ErrorSpec`` 을 resolve 한다.

본 PR(#1840) 범위에서 등록된 lock 4건:

- ``InvalidAccountIdError`` → ``VALIDATION_ERROR`` / ``validation``
- ``BotNotFoundError`` → ``BOT_NOT_FOUND`` / ``not_found``
- ``ApprovalNotFoundError`` → ``APPROVAL_NOT_FOUND`` / ``not_found``
- ``InvalidScopeError`` (member, code=``MEMBER_INVALID_SCOPE``) →
  ``MEMBER_INVALID_SCOPE`` / ``permission``

#1842 가 추가한 account domain 12 sub-class lock (실측 ``.code`` mirror,
category 정확화):

- ``AccountNotFoundError`` → ``ACCOUNT_NOT_FOUND`` / ``not_found``
- ``AccountAlreadyExistsError`` → ``ACCOUNT_ALREADY_EXISTS`` / ``state_conflict``
- ``InvalidBrokerTypeError`` → ``ACCOUNT_INVALID_BROKER_TYPE`` / ``validation``
- ``InvalidExchangeError`` → ``VALIDATION_ERROR`` / ``validation`` (실측
  ``.code = VALIDATION_ERROR``, ``InvalidAccountIdError`` 와 동일한 account
  검증 에러 SSOT)
- ``MissingCredentialsError`` → ``ACCOUNT_MISSING_CREDENTIALS`` / ``validation``
- ``AccountAlreadySuspendedError`` → ``ACCOUNT_ALREADY_SUSPENDED`` /
  ``state_conflict``
- ``AccountDeletedError`` → ``ACCOUNT_DELETED`` / ``state_conflict`` (CLI
  ``account delete`` 의 ``ACCOUNT_ALREADY_DELETED`` surface override 는 별개
  CLI UX layer 이며 ``except AccountDeletedError`` 명시 typed handling 으로
  보존된다)
- ``AccountSuspendedError`` → ``ACCOUNT_SUSPENDED`` / ``state_conflict``
- ``AccountImmutableFieldError`` → ``ACCOUNT_IMMUTABLE_FIELD`` / ``validation``
- ``BrokerReconnectFailedError`` → ``BROKER_RECONNECT_FAILED`` / ``external``
- ``AccountStructuralChangeRequiresStoppedServerError`` →
  ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER`` / ``state_conflict``
- ``AccountHasActiveBotsError`` → ``ACCOUNT_HAS_ACTIVE_BOTS`` /
  ``state_conflict``

``AccountError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
Non-Goals).

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

from ante.account.errors import (
    AccountAlreadyExistsError,
    AccountAlreadySuspendedError,
    AccountDeletedError,
    AccountHasActiveBotsError,
    AccountImmutableFieldError,
    AccountNotFoundError,
    AccountStructuralChangeRequiresStoppedServerError,
    AccountSuspendedError,
    BrokerReconnectFailedError,
    InvalidAccountIdError,
    InvalidBrokerTypeError,
    InvalidExchangeError,
    MissingCredentialsError,
)
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


# ── account 12 sub-class lock (#1842 normative, 실측 .code mirror) ───────────

_ACCOUNT_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_NOT_FOUND",
    category="not_found",
)

_ACCOUNT_ALREADY_EXISTS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_ALREADY_EXISTS",
    category="state_conflict",
)

_ACCOUNT_INVALID_BROKER_TYPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_INVALID_BROKER_TYPE",
    category="validation",
)

# ``InvalidExchangeError`` 의 실측 ``.code = "VALIDATION_ERROR"`` 와 동일
# 한 값. ``InvalidAccountIdError`` 와 코드를 공유하지만 ErrorSpec instance
# 는 의미상 별개의 entry 로 둔다 — registry MRO lookup 은 type 기반이므로
# instance identity 가 영향을 주지 않는다.
_ACCOUNT_INVALID_EXCHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="VALIDATION_ERROR",
    category="validation",
)

_ACCOUNT_MISSING_CREDENTIALS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_MISSING_CREDENTIALS",
    category="validation",
)

_ACCOUNT_ALREADY_SUSPENDED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_ALREADY_SUSPENDED",
    category="state_conflict",
)

# class-level ``.code = "ACCOUNT_DELETED"`` 와 정렬. CLI ``account delete``
# 의 ``except AccountDeletedError → fmt.error(code="ACCOUNT_ALREADY_DELETED")``
# surface override 는 CLI UX layer 의 별개 책임 — 명시 typed except 를
# 보존한다 (#1842 plan v2 Codex blocker #2 / errors.py:96-100 NOTE 정렬).
_ACCOUNT_DELETED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_DELETED",
    category="state_conflict",
)

_ACCOUNT_SUSPENDED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_SUSPENDED",
    category="state_conflict",
)

_ACCOUNT_IMMUTABLE_FIELD_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_IMMUTABLE_FIELD",
    category="validation",
)

_BROKER_RECONNECT_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_RECONNECT_FAILED",
    category="external",
)

_ACCOUNT_STRUCTURAL_CHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER",
    category="state_conflict",
)

_ACCOUNT_HAS_ACTIVE_BOTS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_HAS_ACTIVE_BOTS",
    category="state_conflict",
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
    # ── #1842 account 12 sub-class (실측 .code mirror) ────────────────────
    AccountNotFoundError: _ACCOUNT_NOT_FOUND_SPEC,
    AccountAlreadyExistsError: _ACCOUNT_ALREADY_EXISTS_SPEC,
    InvalidBrokerTypeError: _ACCOUNT_INVALID_BROKER_TYPE_SPEC,
    InvalidExchangeError: _ACCOUNT_INVALID_EXCHANGE_SPEC,
    MissingCredentialsError: _ACCOUNT_MISSING_CREDENTIALS_SPEC,
    AccountAlreadySuspendedError: _ACCOUNT_ALREADY_SUSPENDED_SPEC,
    AccountDeletedError: _ACCOUNT_DELETED_SPEC,
    AccountSuspendedError: _ACCOUNT_SUSPENDED_SPEC,
    AccountImmutableFieldError: _ACCOUNT_IMMUTABLE_FIELD_SPEC,
    BrokerReconnectFailedError: _BROKER_RECONNECT_FAILED_SPEC,
    AccountStructuralChangeRequiresStoppedServerError: _ACCOUNT_STRUCTURAL_CHANGE_SPEC,
    AccountHasActiveBotsError: _ACCOUNT_HAS_ACTIVE_BOTS_SPEC,
}
"""대표 fault lock registry (#1839 normative 4건).

``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__`` 순서로 본 dict를
조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` 활용 → ``EXECUTION_ERROR`` fallback 순서로
resolve 한다.
"""
