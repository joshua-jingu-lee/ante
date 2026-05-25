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

#1843 sub-PR 1 (member sweep) 가 추가한 member domain 5 sub-class lock
(실측 ``.code`` mirror, ``InvalidScopeError`` 는 #1840 lock 그대로 보존):

- ``PermissionDeniedError`` → ``PERMISSION_DENIED`` / ``permission`` (본
  PR 에서 ``.code`` 신규 부여 — master 검증 위반 fault 의 안정 코드)
- ``MemberNotFoundError`` → ``MEMBER_NOT_FOUND`` / ``not_found`` (#1817)
- ``MemberStateConflictError`` → ``MEMBER_STATE_CONFLICT`` /
  ``state_conflict`` (#1825)
- ``MemberAlreadyExistsError`` → ``MEMBER_ALREADY_EXISTS`` /
  ``state_conflict`` (#1826)
- ``MemberInvalidRecoveryCredentialError`` →
  ``MEMBER_INVALID_RECOVERY_CREDENTIAL`` / ``auth`` (#1826)

``MemberError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 1 Non-Goals).

#1843 sub-PR 2 (approval sweep) 가 추가한 approval domain 2 sub-class lock
(실측 ``.code`` mirror, ``ApprovalNotFoundError`` 는 #1840 lock 그대로 보존):

- ``ApprovalStatusConflictError`` → ``APPROVAL_STATUS_CONFLICT`` /
  ``state_conflict`` (#1813 Group Q sweep; ``approve``/``reject`` 표면의
  status flow 위반)
- ``ApprovalValidationError`` → ``APPROVAL_VALIDATION_ERROR`` /
  ``validation`` (``ApprovalService.create`` 사전검증 ``fail`` grade 거부;
  CLI ``approval request`` 의 ``--params`` / ``--type`` / ``--expires-in``
  ingress validation 과 동일한 안정 코드 surface — 본 PR 에서 class-level
  ``.code`` 신규 부여)

``ApprovalError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 2 Non-Goals).

#1843 sub-PR 3 (bot sweep) 가 추가한 bot domain 5 sub-class lock (실측 ``.code``
mirror, ``BotNotFoundError`` 는 #1840 lock 그대로 보존):

- ``BotAccountCredentialsNotConfigured`` →
  ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` / ``validation`` (#1712; ``bot
  start`` 표면 ``app_key`` preflight 거부 — 입력 계약/필수 정보 누락은
  taxonomy ``validation`` 카테고리)
- ``BotStateConflict`` → ``BOT_STATE_CONFLICT`` / ``state_conflict`` (#1712;
  ``start_bot``/``stop_bot`` 상태머신 거부)
- ``BotNotAcceptingSignals`` → ``BOT_NOT_ACCEPTING_SIGNALS`` /
  ``state_conflict`` (#1761; ``accepts_external_signals=False`` 전략이 외부
  시그널 발급 요청을 거부 — 운영 상태가 해당 전이를 허용하지 않음)
- ``BotAlreadyExistsError`` → ``BOT_ALREADY_EXISTS`` / ``state_conflict``
  (#1800; ``bot create`` 시 동일 ``bot_id`` 중복)
- ``BotStrategyAlreadyRunningError`` → ``BOT_STRATEGY_ALREADY_RUNNING`` /
  ``state_conflict`` (#1800; "1전략 1봇" 정책 거부)

``BotError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 3 Non-Goals).

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
from ante.approval.errors import ApprovalNotFoundError, ApprovalStatusConflictError
from ante.approval.models import ApprovalValidationError
from ante.bot.exceptions import (
    BotAccountCredentialsNotConfigured,
    BotAlreadyExistsError,
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotStateConflict,
    BotStrategyAlreadyRunningError,
)
from ante.contracts.errors import ErrorSpec
from ante.member.errors import (
    MemberAlreadyExistsError,
    MemberInvalidRecoveryCredentialError,
    MemberNotFoundError,
    MemberStateConflictError,
    PermissionDeniedError,
)
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


# ── member 5 sub-class lock (#1843 sub-PR 1, 실측 .code mirror) ──────────────

# master 검증 위반의 안정 코드. 본 PR 에서 class-level ``.code`` 신규 부여
# (errors.py:31 PermissionDeniedError) 와 동시에 registry 도 정렬한다 — IPC
# server.py:322 ``getattr(e, "code", ...)`` 와 helper registry-first 가 동일
# ``PERMISSION_DENIED`` 코드를 surface 한다.
_MEMBER_PERMISSION_DENIED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="PERMISSION_DENIED",
    category="permission",
)

_MEMBER_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_NOT_FOUND",
    category="not_found",
)

_MEMBER_STATE_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_STATE_CONFLICT",
    category="state_conflict",
)

_MEMBER_ALREADY_EXISTS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_ALREADY_EXISTS",
    category="state_conflict",
)

# recovery credential validation 거부는 의미상 인증(auth) 카테고리.
# CLI 표면은 사용자 패스워드 / recovery key 미일치 (인증 실패) 를 의미한다.
_MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_RECOVERY_CREDENTIAL",
    category="auth",
)


# ── approval 2 sub-class lock (#1843 sub-PR 2, 실측 .code mirror) ────────────

# ``approve``/``reject`` 표면의 status flow 위반 (rejected → 재reject,
# approved → 재approve 등). class-level ``.code = "APPROVAL_STATUS_CONFLICT"``
# (#1813 Group Q sweep) 와 정렬 — IPC server.py:322 ``getattr(e, "code", ...)``
# 와 helper registry-first 가 동일 코드를 surface 한다.
_APPROVAL_STATUS_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_STATUS_CONFLICT",
    category="state_conflict",
)

# ``ApprovalService.create`` 사전검증 ``fail`` grade 거부. CLI ``approval
# request`` 의 ingress validation (``--params`` JSON object 가드, ``--type``
# enum 검증, ``--expires-in`` 파싱) 과 동일한 안정 코드 ``APPROVAL_VALIDATION_ERROR``
# 를 service-side typed exception 도 surface 한다. 본 PR 에서 class-level
# ``.code`` 신규 부여 (``ante.approval.models.ApprovalValidationError``).
_APPROVAL_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_VALIDATION_ERROR",
    category="validation",
)


# ── bot 5 sub-class lock (#1843 sub-PR 3, 실측 .code mirror) ─────────────────
#
# ``BotNotFoundError`` 는 #1840 lock (`_BOT_NOT_FOUND_SPEC`) 을 그대로 보존
# 한다 — 본 PR 은 신규 5건만 추가한다 (account/member/approval sweep 1:1 동형).

# ``bot start`` 표면의 ``app_key`` preflight 거부. 입력 계약/필수 정보
# 누락이므로 taxonomy ``validation`` 카테고리. IPC server.py:322
# ``getattr(e, "code", ...)`` 와 helper registry-first 가 동일
# ``BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED`` 코드를 surface 한다.
_BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED",
    category="validation",
)

# ``start_bot``/``stop_bot`` 상태머신 거부 (running ↔ stopped 전이 위반).
# IPC ``bot.start``/``bot.stop`` 표면이 ``BotError`` → ``BotStateConflict``
# 로 감싸 raise 하며, 본 ErrorSpec 이 동일 코드를 envelope surface 한다.
_BOT_STATE_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_STATE_CONFLICT",
    category="state_conflict",
)

# ``accepts_external_signals=False`` 전략이 외부 시그널 발급 요청을 거부.
# 운영 상태가 해당 전이를 허용하지 않으므로 ``state_conflict``. CLI
# ``signal connect``/``bot signal-key --rotate`` 양쪽 표면이 동일 코드를
# surface 한다.
_BOT_NOT_ACCEPTING_SIGNALS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_ACCEPTING_SIGNALS",
    category="state_conflict",
)

# ``bot create`` 표면의 동일 ``bot_id`` 중복 등록 거부. resource 존재
# 충돌이므로 ``state_conflict`` (account ``ACCOUNT_ALREADY_EXISTS`` 동형).
_BOT_ALREADY_EXISTS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_ALREADY_EXISTS",
    category="state_conflict",
)

# "1전략 1봇" 정책 거부 (동일 ``strategy_id`` 가 이미 실행 중인 다른 봇이
# 보유). 운영 상태(running) 가 해당 전이를 허용하지 않으므로
# ``state_conflict``.
_BOT_STRATEGY_ALREADY_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_STRATEGY_ALREADY_RUNNING",
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
    # ── #1843 sub-PR 1 member 5 sub-class (실측 .code mirror) ─────────────
    PermissionDeniedError: _MEMBER_PERMISSION_DENIED_SPEC,
    MemberNotFoundError: _MEMBER_NOT_FOUND_SPEC,
    MemberStateConflictError: _MEMBER_STATE_CONFLICT_SPEC,
    MemberAlreadyExistsError: _MEMBER_ALREADY_EXISTS_SPEC,
    MemberInvalidRecoveryCredentialError: _MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC,
    # ── #1843 sub-PR 2 approval 2 sub-class (실측 .code mirror) ───────────
    ApprovalStatusConflictError: _APPROVAL_STATUS_CONFLICT_SPEC,
    ApprovalValidationError: _APPROVAL_VALIDATION_ERROR_SPEC,
    # ── #1843 sub-PR 3 bot 5 sub-class (실측 .code mirror) ────────────────
    BotAccountCredentialsNotConfigured: _BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_SPEC,
    BotStateConflict: _BOT_STATE_CONFLICT_SPEC,
    BotNotAcceptingSignals: _BOT_NOT_ACCEPTING_SIGNALS_SPEC,
    BotAlreadyExistsError: _BOT_ALREADY_EXISTS_SPEC,
    BotStrategyAlreadyRunningError: _BOT_STRATEGY_ALREADY_RUNNING_SPEC,
}
"""대표 fault lock registry (#1839 normative 4건).

``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__`` 순서로 본 dict를
조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` 활용 → ``EXECUTION_ERROR`` fallback 순서로
resolve 한다.
"""
