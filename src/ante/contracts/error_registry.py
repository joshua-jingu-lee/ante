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
- ``ReservedMemberIdError`` → ``MEMBER_ID_RESERVED`` / ``validation``
  (#2295; ``register`` 의 ``system:`` reserved-prefix guard — duplicate
  와 별개 fault, existing-member 조회 이전 거부. ``ValueError`` 다중상속
  으로 기존 generic fallback 회귀 없음.)
- ``MemberInvalidRecoveryCredentialError`` →
  ``MEMBER_INVALID_RECOVERY_CREDENTIAL`` / ``auth`` (#1826)

#1915 member domain 2 sub-class 추가 (실측 ``.code`` mirror, #1843 sub-PR 1
1:1 미러):

- ``MemberInvalidEmojiError`` → ``MEMBER_INVALID_EMOJI`` / ``validation``
  (#1915; ``_validate_emoji_format`` 형식 거부 — CLI ``set-emoji`` /
  ``register`` / master bootstrap 표면. ``ValueError`` 다중상속으로 기존
  generic fallback 회귀 없음.)
- ``MemberMasterProtectedError`` → ``MEMBER_MASTER_PROTECTED`` /
  ``permission`` (#1915; ``_assert_not_master`` 호출 — CLI ``suspend`` /
  ``revoke`` 표면. ``PermissionDeniedError`` (비-master 의 master-only
  operation 시도) 와 의미 분리 — master 본인을 대상으로 한 파괴적
  operation 거부. ``PermissionError`` 다중상속으로 기존 generic fallback
  회귀 없음.)

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

#2282 가 추가한 bot 불변 필드 lock (Account ``AccountImmutableFieldError`` 선례
미러):

- ``BotImmutableFieldError`` → ``BOT_IMMUTABLE_FIELD`` / ``validation``
  (#2282; ``update_bot`` 의 ``account_id`` 변경 거부 — treasury 예산·broker
  credential·포지션이 account-bound 라 생성 후 불변. ``ACCOUNT_IMMUTABLE_FIELD``
  / ``validation`` 동형 분류)

``BotError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 3 Non-Goals).

#1843 sub-PR 4 (treasury sweep) 가 추가한 treasury domain 7 sub-class lock
(실측 ``.code`` mirror; #1809 가 도입한 4건 + 본 PR 신규 부여 3건):

- ``TreasuryInvalidAmountError`` → ``TREASURY_INVALID_AMOUNT`` / ``validation``
  (#1809; ``allocate``/``deallocate`` 의 finite-positive 가드 위반)
- ``TreasuryInsufficientUnallocatedError`` → ``TREASURY_INSUFFICIENT_BALANCE``
  / ``validation`` (#1809; ``allocate`` 시 ``self._unallocated < amount``)
- ``TreasuryBudgetNotFoundError`` → ``TREASURY_BUDGET_NOT_FOUND`` /
  ``not_found`` (#1809; ``deallocate`` 시 budget record 부재)
- ``TreasuryDeallocateExceedsAvailableError`` →
  ``TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE`` / ``validation`` (#1809;
  over-deallocate)
- ``InsufficientFundsError`` → ``TREASURY_INSUFFICIENT_FUNDS`` / ``validation``
  (본 PR 신규 부여; ``update_budget`` caller-facing wrap fault —
  ``TREASURY_INSUFFICIENT_BALANCE`` 와 의미 분리)
- ``BotNotStoppedError`` → ``TREASURY_BOT_NOT_STOPPED`` / ``state_conflict``
  (본 PR 신규 부여; running 상태 봇의 예산 변경 거부)
- ``TreasuryNotConfiguredError`` → ``TREASURY_NOT_CONFIGURED`` /
  ``service_unavailable`` (본 PR 신규 부여; #1335 ``TreasuryManager`` 미주입
  / 등록된 Treasury 부재)

``TreasuryError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 1/2/3 Non-Goals 동형).

#1843 sub-PR 5 (broker sweep) 가 추가한 broker domain 6 sub-class lock
(실측 ``.code`` mirror, 본 PR 에서 신규 부여):

- ``AuthenticationError`` → ``BROKER_AUTH_FAILED`` / ``auth`` (KIS OAuth
  토큰 발급/갱신 실패; HTTP 401/403 또는 잘못된 app_key/secret)
- ``APIError`` → ``BROKER_API_ERROR`` / ``external`` (KIS API business/HTTP
  error; 원천 KIS ``msg_cd`` 는 ``APIError.error_code`` 필드에 log-only
  보존되며 envelope 에는 안정 코드만 노출 — Codex Plan Review v1 condition)
- ``OrderNotFoundError`` → ``BROKER_ORDER_NOT_FOUND`` / ``not_found``
  (broker side 에서 조회/취소 대상 주문 부재)
- ``RateLimitError`` → ``BROKER_RATE_LIMITED`` / ``external`` (KIS per-minute
  rate limit 초과)
- ``CircuitOpenError`` → ``BROKER_CIRCUIT_OPEN`` / ``service_unavailable``
  (연속 실패 임계 도달로 circuit breaker OPEN — broker 가용성 임시 차단)
- ``ante.broker.registry.InvalidBrokerTypeError`` → ``BROKER_INVALID_TYPE`` /
  ``validation`` (registry 미등록 broker_type 요청). 동명 별개 class 인
  ``ante.account.errors.InvalidBrokerTypeError`` 는 #1842 가 이미
  ``ACCOUNT_INVALID_BROKER_TYPE`` 로 등록한 다른 entry 다 — helper 의
  type-based MRO lookup 과 drift guard 의 ``(module, name)`` 2중 anchor 가
  두 class 를 정확히 분리한다.

``BrokerError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
``AccountError`` 와 동일 패턴, #1843 sub-PR 1/2/3/4 Non-Goals 동형).

#1843 sub-PR 6 (strategy/config/rule sweep + final allowlist clear) 가
추가한 도메인 sub-class lock (실측 ``.code`` mirror, 본 PR 에서 신규 부여):

- ``StrategyNotFoundError`` → ``STRATEGY_NOT_FOUND`` / ``not_found`` (#1796
  lock 그대로 보존)
- ``StrategyLoadError`` → ``STRATEGY_LOAD_ERROR`` / ``validation`` (전략
  파일 import/load 실패; CLI ``strategy submit`` 의 ``stage="load"`` envelope
  와 동일 SSOT)
- ``StrategyValidationError`` → ``STRATEGY_VALIDATION_ERROR`` / ``validation``
  (전략 정적/manifest 검증 거부; CLI ``strategy submit``/``validate`` /
  ``strategy list --status`` 의 동명 surface 와 동일 안정 코드)
- ``StrategyFileAccessError`` → ``STRATEGY_FILE_ACCESS_ERROR`` / ``external``
  (전략 파일 시스템 접근 실패 — 외부 의존성)
- ``IncompatibleExchangeError`` → ``STRATEGY_INCOMPATIBLE_EXCHANGE`` /
  ``validation`` (전략 ↔ 계좌 exchange 호환성 거부)
- ``ConfigValidationError`` → ``CONFIG_VALIDATION_ERROR`` / ``validation``
  (#1673 oracle A7; ``ValueError`` 다중상속을 보존하며 helper registry-first
  lookup 이 동일 안정 코드를 surface)
- ``RuleConfigError`` → ``RULE_CONFIG_ERROR`` / ``validation`` (룰 설정 입력
  invariant 위반)

``StrategyError`` / ``ConfigError`` / ``RuleError`` base 는 의도적으로
등록하지 않는다 — 사용 사례가 없으며 ``pending_migration`` allowlist 에
baseline 으로 그대로 유지된다 (#1842 ``AccountError`` 와 동일 패턴,
#1843 sub-PR 1/2/3/4/5 Non-Goals 동형).

#1974 R2 가 추가한 core 1 class lock:

- ``ReadOnlyDatabaseError`` → ``EXECUTION_ERROR`` / ``internal`` (read-only
  ``Database`` 에서 writer 경로 호출 시 발생하는 프로그래밍/사용 오류 guard.
  정상 경로에서는 발생하지 않으며, 발생 시 호출 코드 버그를 의미하므로
  taxonomy ``internal`` 로 명시 매핑 — 암묵적 fallback drift 가 아님을 lock).

추가로 ``SERVICE_NOT_CONFIGURED`` 는 module-level constant
(``_SERVICE_NOT_CONFIGURED_SPEC``) 로 보존한다 — taxonomy SSOT 가
``service_unavailable`` 카테고리로 lock 한 공통 안정 코드다. #2336 (PR#1) 이
``SignalKeyManagerNotConfigured`` (``.code="SERVICE_NOT_CONFIGURED"``) 를 도입해
이 상수를 ``EXCEPTION_TO_SPEC`` 한 줄 entry 로 wiring 한다(전용 코드 미발명).

#2336 (PR#1) / #2337 (PR#2) signal.connect 핸드셰이크 신규 4코드:

- ``INVALID_SIGNAL_KEY`` (validation) — ``InvalidSignalKey`` typed entry.
- ``BOT_NOT_RUNNING`` (state_conflict) — ``BotNotRunning`` typed entry.
- ``MALFORMED_REQUEST`` (validation) — server.py 가 비-dict 첫 프레임에 inline
  envelope 으로 발화. typed exception 없음 → 상수-only(entry 미등록).
- ``BOT_SIGNAL_CHANNEL_BUSY`` (state_conflict) — bot_id 당 단일 connect 거부.
  raiser 는 PR#2(#2337) ``SignalChannelRegistry.register`` 이며, PR#2 가
  ``BotSignalChannelBusy`` typed entry 를 추가한다(PR#1 은 상수-only 였음).

즉 PR#2 머지 후 typed-3(``INVALID_SIGNAL_KEY``/``BOT_NOT_RUNNING``/
``BOT_SIGNAL_CHANNEL_BUSY``) + inline-1(``MALFORMED_REQUEST``) split. typed-3 의
``EXCEPTION_TO_SPEC`` entry 는 helper 의 bare-``.code``→``internal`` wrap 을
회피해 category 정확성을 lock 하는 load-bearing 이다.

#2412 가 추가한 core 1 class lock:

- ``InvalidIsoDateError`` → ``VALIDATION_ERROR`` / ``validation``. 공개 표면
  ISO ``YYYY-MM-DD`` → broker 어댑터 경계 ``YYYYMMDD`` 변환 chokepoint
  (``ante.core.time.iso_to_kis_date``) 의 입력 검증 실패다. 코드는 #1633 SSOT
  (``InvalidAccountIdError.code``) 를 재사용하며 신 코드를 도입하지 않는다.
  entry 를 두는 이유는 signal typed-3 와 동일하다 — class-level ``.code`` 만
  있으면 helper 가 category 를 ``internal`` 로 wrap 해 validation 성격이
  taxonomy 에서 소실된다.

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
    BotImmutableFieldError,
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotNotRunning,
    BotSignalChannelBusy,
    BotStateConflict,
    BotStrategyAlreadyRunningError,
    InvalidSignalKey,
    SignalKeyManagerNotConfigured,
)
from ante.broker.exceptions import (
    APIError,
    AuthenticationError,
    CircuitOpenError,
    OrderNotFoundError,
    RateLimitError,
)
from ante.broker.registry import (
    InvalidBrokerTypeError as BrokerRegistryInvalidBrokerTypeError,
)
from ante.config.exceptions import ConfigValidationError
from ante.contracts.errors import ErrorSpec
from ante.core.database import ReadOnlyDatabaseError
from ante.core.time import InvalidIsoDateError
from ante.member.errors import (
    MemberAlreadyExistsError,
    MemberInvalidEmojiError,
    MemberInvalidRecoveryCredentialError,
    MemberMasterProtectedError,
    MemberNotFoundError,
    MemberStateConflictError,
    PermissionDeniedError,
    ReservedMemberIdError,
)
from ante.member.scopes import InvalidScopeError
from ante.rule.exceptions import RuleConfigError
from ante.strategy.exceptions import (
    IncompatibleExchangeError,
    StrategyFileAccessError,
    StrategyLoadError,
    StrategyNotFoundError,
    StrategyValidationError,
)
from ante.treasury.exceptions import (
    BotNotStoppedError,
    InsufficientFundsError,
    TreasuryBudgetNotFoundError,
    TreasuryDeallocateExceedsAvailableError,
    TreasuryInsufficientUnallocatedError,
    TreasuryInvalidAmountError,
    TreasuryNotConfiguredError,
)

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

# reserved ``system:`` prefix member_id 등록 거부 (#2295) 는 입력 네임스페이스
# 계약 위반이므로 taxonomy ``validation`` 카테고리. duplicate
# (``MEMBER_ALREADY_EXISTS`` / state_conflict) 와 별개 fault 로 분리한다 — register
# 의 reserved-prefix guard 가 existing-member 조회 이전에 배치되어 legacy
# ``system:*`` 행이 있어도 본 코드가 surface 된다.
_MEMBER_ID_RESERVED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_ID_RESERVED",
    category="validation",
)

# recovery credential validation 거부는 의미상 인증(auth) 카테고리.
# CLI 표면은 사용자 패스워드 / recovery key 미일치 (인증 실패) 를 의미한다.
_MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_RECOVERY_CREDENTIAL",
    category="auth",
)


# ── member #1915: emoji 형식 / master 보호 typed exception lock ──────────────

# emoji 형식 거부 (``_validate_emoji_format`` — 단일 이모지 외 입력)
# 는 입력 계약 위반이므로 taxonomy ``validation`` 카테고리. CLI
# ``set-emoji`` / ``register`` / master bootstrap 표면이 동일 안정 코드
# ``MEMBER_INVALID_EMOJI`` 를 surface 한다.
_MEMBER_INVALID_EMOJI_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_EMOJI",
    category="validation",
)

# master 보호 위반 (``_assert_not_master`` — master 본인을 대상으로 한
# suspend / revoke 거부) 는 권한 정책 거부이므로 taxonomy ``permission``
# 카테고리. ``PERMISSION_DENIED`` (비-master 의 master-only operation 시도)
# 와 의미 분리 — 본 코드는 master 본인을 대상으로 한 파괴적 operation
# 거부를 의미한다.
_MEMBER_MASTER_PROTECTED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_MASTER_PROTECTED",
    category="permission",
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

# ``update_bot`` 의 ``account_id`` 변경 거부 (#2282). treasury 예산·broker
# credential·포지션이 account-bound 라 생성 후 불변 — 입력 계약 위반이므로
# Account ``ACCOUNT_IMMUTABLE_FIELD`` 와 동형으로 ``validation`` 카테고리.
_BOT_IMMUTABLE_FIELD_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_IMMUTABLE_FIELD",
    category="validation",
)


# ── signal.connect 핸드셰이크 신규 코드(#2336/#2334 PR#1) ────────────────────
#
# error-taxonomy.md 가 신규 4코드를 분류한다: ``INVALID_SIGNAL_KEY``=validation,
# ``BOT_NOT_RUNNING``=state_conflict, ``MALFORMED_REQUEST``=validation,
# ``BOT_SIGNAL_CHANNEL_BUSY``=state_conflict. PR#2(#2337) 머지 후 typed
# exception 이 존재하는 3코드(``INVALID_SIGNAL_KEY``/``BOT_NOT_RUNNING``/
# ``BOT_SIGNAL_CHANNEL_BUSY``)가 ``EXCEPTION_TO_SPEC`` entry 를 갖고, 나머지
# 1코드(``MALFORMED_REQUEST``)는 상수-only(server.py 가 비-dict 첫 프레임에 대해
# inline envelope 으로 발화). ``BOT_SIGNAL_CHANNEL_BUSY`` 의 raiser 는 단일-connect
# 정책으로 PR#2 의 ``SignalChannelRegistry.register`` 다. ``_MALFORMED_REQUEST_SPEC``
# 는 ``_SERVICE_NOT_CONFIGURED_SPEC`` reserved 선례를 따른다(typed 없음).

# ``signal.connect`` 게이트① — signal key 검증 실패. 입력 계약 위반이므로
# ``validation`` 카테고리. server.py:446 ``getattr(e, "code", ...)`` 가
# ``InvalidSignalKey.code`` → ``INVALID_SIGNAL_KEY`` envelope 으로 변환하고,
# ``EXCEPTION_TO_SPEC`` entry 가 category 정확성(``internal`` wrap 회피)을 lock.
_INVALID_SIGNAL_KEY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INVALID_SIGNAL_KEY",
    category="validation",
)

# ``signal.connect`` 게이트③ — 봇이 RUNNING 아님. 운영 상태가 핸드셰이크
# 전이를 허용하지 않으므로 ``state_conflict`` (``_BOT_NOT_ACCEPTING_SIGNALS_SPEC``
# 1:1 미러).
_BOT_NOT_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_RUNNING",
    category="state_conflict",
)

# ``signal.connect`` 첫 프레임이 비-dict 로 decode 되면 server.py 가 inline
# envelope 으로 발화. JSON object 가 아닌 입력 계약 위반이므로 ``validation``.
# typed exception 없음 → ``EXCEPTION_TO_SPEC`` entry 없음(상수-only).
_MALFORMED_REQUEST_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MALFORMED_REQUEST",
    category="validation",
)

# 같은 봇에 이미 active session 이 있을 때 두 번째 핸드셰이크 거부 (bot_id 당
# 단일 connect). 운영 상태 충돌이므로 ``state_conflict``. raiser 는 PR#2
# (#2337) 의 ``SignalChannelRegistry.register`` (atomic check-and-insert) 이며,
# PR#2 가 ``BotSignalChannelBusy`` typed entry 를 ``EXCEPTION_TO_SPEC`` 에
# wiring 해 category 정확성(``internal`` wrap 회피)을 lock 한다(PR#1 상수-only).
_BOT_SIGNAL_CHANNEL_BUSY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_SIGNAL_CHANNEL_BUSY",
    category="state_conflict",
)


# ── treasury 7 sub-class lock (#1843 sub-PR 4, 실측 .code mirror) ────────────
#
# ``TreasuryError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
# ``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
# ``AccountError`` 와 동일 패턴, #1843 sub-PR 1/2/3 Non-Goals 동형).

# ``allocate``/``deallocate`` amount 가 finite-positive 가 아닐 때
# (NaN/±Inf/<=0). #1411 finite-positive 가드 위반. CLI ingress
# (``validate_positive_finite_amount``) 가 1차 거부하지만 service layer 가
# 2차 invariant 로 raise — IPC envelope 도 동일 코드 surface.
_TREASURY_INVALID_AMOUNT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INVALID_AMOUNT",
    category="validation",
)

# ``allocate`` 시 미할당 잔액 부족 (``self._unallocated < amount``).
# class-level ``.code = "TREASURY_INSUFFICIENT_BALANCE"`` (#1809) 와 정렬.
_TREASURY_INSUFFICIENT_BALANCE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INSUFFICIENT_BALANCE",
    category="validation",
)

# ``deallocate`` 시 budget record 부재. ``self._budgets`` 에 해당 ``bot_id``
# budget 이 없을 때 raise. IPC handler 가 ``BotNotFoundError`` 로 cross-module
# 검증을 선행하므로 budget record 만 없는 드문 경로이지만 invariant 명시.
_TREASURY_BUDGET_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_BUDGET_NOT_FOUND",
    category="not_found",
)

# ``deallocate`` 시 요청 amount 가 budget.available 초과 (over-deallocate).
_TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE",
    category="validation",
)

# ``update_budget`` 의 caller-facing wrap fault. ``allocate``/``deallocate``
# 가 reject 한 typed reason 을 caller invariant 보존을 위해 동일
# ``InsufficientFundsError`` 로 변환하는 경로 (treasury.py:599-606) 에서
# raise 된다. 본 PR 에서 class-level ``.code`` 신규 부여
# ``TREASURY_INSUFFICIENT_FUNDS`` — ``TREASURY_INSUFFICIENT_BALANCE``
# (allocate-side raw reject) 와 의미 분리 (semantic distinction 보존).
_TREASURY_INSUFFICIENT_FUNDS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INSUFFICIENT_FUNDS",
    category="validation",
)

# running 상태 봇의 예산 변경 거부 (운영 상태 머신 위반). 본 PR 에서
# class-level ``.code`` 신규 부여 ``TREASURY_BOT_NOT_STOPPED``.
_TREASURY_BOT_NOT_STOPPED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_BOT_NOT_STOPPED",
    category="state_conflict",
)

# ``TreasuryManager`` 미주입 / ``account_id`` 에 등록된 Treasury 부재로 인한
# budget 작업 거부 (#1335). 본 PR 에서 class-level ``.code`` 신규 부여
# ``TREASURY_NOT_CONFIGURED`` (service 인프라 부재 — ``service_unavailable``
# 카테고리).
_TREASURY_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_NOT_CONFIGURED",
    category="service_unavailable",
)


# ── broker 6 sub-class lock (#1843 sub-PR 5, 본 PR 신규 부여) ────────────────
#
# ``BrokerError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
# ``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
# ``AccountError`` 와 동일 패턴, #1843 sub-PR 1/2/3/4 Non-Goals 동형).

# KIS OAuth 토큰 발급/갱신 실패 (HTTP 401/403, 잘못된 app_key/app_secret).
# taxonomy ``auth`` 카테고리 — 인증 자격 거부.
_BROKER_AUTH_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_AUTH_FAILED",
    category="auth",
)

# KIS API 호출 시 broker side business / HTTP error. ``status_code`` 에 HTTP
# status, ``error_code`` 에 원천 KIS ``msg_cd`` (예: ``APBK0501``) 가
# log-only 채널로 보존된다. public envelope (CLI ``OutputFormatter.error`` /
# IPC envelope) 에는 안정 코드 ``BROKER_API_ERROR`` 만 노출하며 원천
# ``msg_cd`` 는 surface 하지 않는다 (#1843 sub-PR 5 Codex Plan Review v1
# condition; envelope SSOT 갱신 필요한 ``details.broker_code`` 필드 도입은
# 후속 spec PR 책임).
_BROKER_API_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_API_ERROR",
    category="external",
)

# broker side 에서 조회/취소 대상 주문이 존재하지 않을 때. taxonomy
# ``not_found`` 카테고리.
_BROKER_ORDER_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_ORDER_NOT_FOUND",
    category="not_found",
)

# KIS API per-minute rate limit 초과. retryable backoff 정책의 신호로
# 사용된다. taxonomy ``external`` 카테고리 (외부 시스템 throttling).
_BROKER_RATE_LIMITED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_RATE_LIMITED",
    category="external",
)

# 연속 실패 임계 도달 시 circuit breaker 가 OPEN 으로 전이해 API 호출을
# 차단한다. taxonomy ``service_unavailable`` 카테고리 (broker 가용성
# 임시 차단).
_BROKER_CIRCUIT_OPEN_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_CIRCUIT_OPEN",
    category="service_unavailable",
)

# ``ante.broker.registry`` 의 미등록 broker_type 요청 거부. 동명 별개 class
# 인 ``ante.account.errors.InvalidBrokerTypeError`` (#1842,
# ``ACCOUNT_INVALID_BROKER_TYPE``) 와는 별개의 module/code 다 — helper 의
# type-based MRO lookup 과 drift guard 의 ``(module, name)`` 2중 anchor 가
# 두 class 를 정확히 분리한다.
_BROKER_INVALID_TYPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_INVALID_TYPE",
    category="validation",
)


# ── strategy 5 sub-class lock (#1843 sub-PR 6, 실측 .code mirror) ────────────
#
# ``StrategyError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
# ``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
# ``AccountError`` 와 동일 패턴, #1843 sub-PR 1/2/3/4/5 Non-Goals 동형).

# ``StrategyRegistry.update_status`` 가 missing strategy 에 대해 raise.
# CLI ``strategy set-status`` 와 IPC ``strategy.set_status`` 가 동일 코드
# surface (#1796 lock 그대로 보존).
_STRATEGY_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_NOT_FOUND",
    category="not_found",
)

# 전략 파일 import/load 실패. CLI ``strategy submit`` 의 ``stage="load"`` /
# ``code="STRATEGY_LOAD_ERROR"`` envelope 와 동일 안정 코드 SSOT. 본 PR 에서
# class-level ``.code`` 신규 부여.
_STRATEGY_LOAD_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_LOAD_ERROR",
    category="validation",
)

# 전략 정적/manifest 검증 거부. CLI ``strategy submit``/``validate`` /
# ``strategy list --status`` invalid 표면이 동일 안정 코드를 surface 한다.
# 본 PR 에서 class-level ``.code`` 신규 부여.
_STRATEGY_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_VALIDATION_ERROR",
    category="validation",
)

# 전략 파일 시스템 접근 실패 (예: 권한/IO 오류). taxonomy ``external``
# 카테고리 — 파일 시스템은 외부 의존성. 본 PR 에서 class-level ``.code``
# 신규 부여.
_STRATEGY_FILE_ACCESS_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_FILE_ACCESS_ERROR",
    category="external",
)

# 전략 ↔ 계좌 exchange 호환성 거부 (예: KOSPI 전략 ↔ 미국 거래 계좌).
# 호환성 invariant 위반이므로 taxonomy ``validation`` 카테고리. 본 PR 에서
# class-level ``.code`` 신규 부여.
_STRATEGY_INCOMPATIBLE_EXCHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_INCOMPATIBLE_EXCHANGE",
    category="validation",
)


# ── config 1 sub-class lock (#1843 sub-PR 6, 실측 .code mirror) ──────────────
#
# ``ConfigError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
# ``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
# ``AccountError`` 와 동일 패턴).

# 동적 설정 키-invariant 위반 (#1673 oracle A7). ``ValueError`` 다중상속을
# 보존하므로 service-boundary 테스트는 영향 없으며, helper registry-first
# lookup 이 동일 ``CONFIG_VALIDATION_ERROR`` 안정 코드를 surface 한다.
# class-level ``.code`` 는 이미 ``ConfigValidationError`` 에 부여되어
# 있다 — 본 PR 은 registry entry 추가만 한다.
_CONFIG_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_VALIDATION_ERROR",
    category="validation",
)


# ── rule 1 sub-class lock (#1843 sub-PR 6, 실측 .code mirror) ────────────────
#
# ``RuleError`` base 는 의도적으로 등록하지 않는다 — 사용 사례가 없으며
# ``pending_migration`` allowlist 에 baseline 으로 그대로 유지된다 (#1842
# ``AccountError`` 와 동일 패턴).

# 룰 설정 입력 invariant 위반. taxonomy ``validation`` 카테고리. 본 PR 에서
# class-level ``.code`` 신규 부여.
_RULE_CONFIG_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="RULE_CONFIG_ERROR",
    category="validation",
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


# ── core 1 class lock (#1974 R2) ─────────────────────────────────────────────
#
# ``ReadOnlyDatabaseError`` 는 read-only ``Database`` (``read_only=True``) 에서
# writer 경로(``execute``/``execute_script``/``transaction`` 등)를 호출했을 때
# 발생하는 **프로그래밍/사용 오류** guard 다 (offline-factory.md §2 옵션 A). 정상
# 코드 경로에서는 발생하지 않으며, 발생 시 호출 코드의 버그를 의미한다. 따라서
# taxonomy SSOT (#1839) 의 ``EXECUTION_ERROR`` / ``internal`` (코드 버그 /
# unexpected programming error) 로 명시 매핑한다 — 암묵적 fallback drift 가
# 아니라 의도된 분류임을 registry 로 lock 한다.
_READ_ONLY_DATABASE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="EXECUTION_ERROR",
    category="internal",
)


# ── core 1 class lock (#2412) ────────────────────────────────────────────────
#
# ``InvalidIsoDateError`` 는 공개 표면 ISO ``YYYY-MM-DD`` → broker 어댑터 경계
# 압축 ``YYYYMMDD`` 변환 chokepoint (``ante.core.time.iso_to_kis_date``) 의 입력
# 검증 실패다. class-level ``.code`` 만으로도 안정 코드는 surface 되지만, helper
# 의 bare-``.code`` 경로는 category 를 ``internal`` 로 wrap 하므로 validation
# 성격이 taxonomy 에서 소실된다 — signal typed-3 (#2336) 와 동일한 사유로 entry
# 를 명시 등록한다. 코드 값은 #1633 SSOT (``InvalidAccountIdError.code``) 재사용.
_INVALID_ISO_DATE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="VALIDATION_ERROR",
    category="validation",
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
    # ── #2295 member reserved-prefix guard (실측 .code mirror) ────────────
    ReservedMemberIdError: _MEMBER_ID_RESERVED_SPEC,
    MemberInvalidRecoveryCredentialError: _MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC,
    # ── #1915 member 2 sub-class (emoji 형식 / master 보호) ───────────────
    MemberInvalidEmojiError: _MEMBER_INVALID_EMOJI_SPEC,
    MemberMasterProtectedError: _MEMBER_MASTER_PROTECTED_SPEC,
    # ── #1843 sub-PR 2 approval 2 sub-class (실측 .code mirror) ───────────
    ApprovalStatusConflictError: _APPROVAL_STATUS_CONFLICT_SPEC,
    ApprovalValidationError: _APPROVAL_VALIDATION_ERROR_SPEC,
    # ── #1843 sub-PR 3 bot 5 sub-class (실측 .code mirror) ────────────────
    BotAccountCredentialsNotConfigured: _BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_SPEC,
    BotStateConflict: _BOT_STATE_CONFLICT_SPEC,
    BotNotAcceptingSignals: _BOT_NOT_ACCEPTING_SIGNALS_SPEC,
    BotAlreadyExistsError: _BOT_ALREADY_EXISTS_SPEC,
    BotStrategyAlreadyRunningError: _BOT_STRATEGY_ALREADY_RUNNING_SPEC,
    # ── #2282 bot account_id 불변 lock (Account 선례 미러) ────────────────
    BotImmutableFieldError: _BOT_IMMUTABLE_FIELD_SPEC,
    # ── #2336/#2334 PR#1 + #2337 PR#2 signal.connect 핸드셰이크 (typed 3 + 재사용 1) ─
    # ``MALFORMED_REQUEST`` 만 typed exception 이 없어 entry 를 두지 않는다(상수-only,
    # ``_SERVICE_NOT_CONFIGURED_SPEC`` 선례 — server.py inline 발화). PR#2 가
    # ``BotSignalChannelBusy`` (``SignalChannelRegistry.register`` raiser) typed
    # entry 를 추가했다(PR#1 은 ``_BOT_SIGNAL_CHANNEL_BUSY_SPEC`` 상수-only).
    # ``SignalKeyManagerNotConfigured`` 는 기존 ``_SERVICE_NOT_CONFIGURED_SPEC`` 를
    # 재사용해 category 정확성을 wiring. ``SignalChannelRegistryFrozen`` 은
    # shutdown-only 내부 가드라 EXCEPTION_TO_SPEC 미등록(generic EXECUTION_ERROR).
    InvalidSignalKey: _INVALID_SIGNAL_KEY_SPEC,
    BotNotRunning: _BOT_NOT_RUNNING_SPEC,
    BotSignalChannelBusy: _BOT_SIGNAL_CHANNEL_BUSY_SPEC,
    SignalKeyManagerNotConfigured: _SERVICE_NOT_CONFIGURED_SPEC,
    # ── #1843 sub-PR 4 treasury 7 sub-class (실측 .code mirror) ───────────
    TreasuryInvalidAmountError: _TREASURY_INVALID_AMOUNT_SPEC,
    TreasuryInsufficientUnallocatedError: _TREASURY_INSUFFICIENT_BALANCE_SPEC,
    TreasuryBudgetNotFoundError: _TREASURY_BUDGET_NOT_FOUND_SPEC,
    TreasuryDeallocateExceedsAvailableError: (
        _TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE_SPEC
    ),
    InsufficientFundsError: _TREASURY_INSUFFICIENT_FUNDS_SPEC,
    BotNotStoppedError: _TREASURY_BOT_NOT_STOPPED_SPEC,
    TreasuryNotConfiguredError: _TREASURY_NOT_CONFIGURED_SPEC,
    # ── #1843 sub-PR 5 broker 6 sub-class (실측 .code mirror) ─────────────
    AuthenticationError: _BROKER_AUTH_FAILED_SPEC,
    APIError: _BROKER_API_ERROR_SPEC,
    OrderNotFoundError: _BROKER_ORDER_NOT_FOUND_SPEC,
    RateLimitError: _BROKER_RATE_LIMITED_SPEC,
    CircuitOpenError: _BROKER_CIRCUIT_OPEN_SPEC,
    BrokerRegistryInvalidBrokerTypeError: _BROKER_INVALID_TYPE_SPEC,
    # ── #1843 sub-PR 6 strategy 5 sub-class (실측 .code mirror) ───────────
    StrategyNotFoundError: _STRATEGY_NOT_FOUND_SPEC,
    StrategyLoadError: _STRATEGY_LOAD_ERROR_SPEC,
    StrategyValidationError: _STRATEGY_VALIDATION_ERROR_SPEC,
    StrategyFileAccessError: _STRATEGY_FILE_ACCESS_ERROR_SPEC,
    IncompatibleExchangeError: _STRATEGY_INCOMPATIBLE_EXCHANGE_SPEC,
    # ── #1843 sub-PR 6 config 1 sub-class (실측 .code mirror) ─────────────
    ConfigValidationError: _CONFIG_VALIDATION_ERROR_SPEC,
    # ── #1843 sub-PR 6 rule 1 sub-class (실측 .code mirror) ───────────────
    RuleConfigError: _RULE_CONFIG_ERROR_SPEC,
    # ── #1974 R2 core 1 class (read-only Database write-guard) ────────────
    ReadOnlyDatabaseError: _READ_ONLY_DATABASE_SPEC,
    # ── #2412 core 1 class (ISO→YYYYMMDD 변환 chokepoint 입력 검증) ───────
    InvalidIsoDateError: _INVALID_ISO_DATE_SPEC,
}
"""대표 fault lock registry (#1839 normative 4건).

``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__`` 순서로 본 dict를
조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` 활용 → ``EXECUTION_ERROR`` fallback 순서로
resolve 한다.
"""
