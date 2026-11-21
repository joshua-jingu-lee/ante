"""Domain exception → ErrorSpec mapping registry."""

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
from ante.contracts.cli_errors import (
    CliOptionConflictError,
    ReportError,
    ReportInvalidStatusError,
    ReportNotFoundError,
    ReportValidationError,
    TradeError,
    TradeNotFoundError,
)
from ante.contracts.errors import ErrorSpec
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCServerNotRunningError,
)
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

_MEMBER_ID_RESERVED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_ID_RESERVED",
    category="validation",
)

_MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_RECOVERY_CREDENTIAL",
    category="auth",
)


_MEMBER_INVALID_EMOJI_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_INVALID_EMOJI",
    category="validation",
)

_MEMBER_MASTER_PROTECTED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_MASTER_PROTECTED",
    category="permission",
)


_APPROVAL_STATUS_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_STATUS_CONFLICT",
    category="state_conflict",
)

_APPROVAL_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_VALIDATION_ERROR",
    category="validation",
)


_BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED",
    category="validation",
)

_BOT_STATE_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_STATE_CONFLICT",
    category="state_conflict",
)

_BOT_NOT_ACCEPTING_SIGNALS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_ACCEPTING_SIGNALS",
    category="state_conflict",
)

_BOT_ALREADY_EXISTS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_ALREADY_EXISTS",
    category="state_conflict",
)

_BOT_STRATEGY_ALREADY_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_STRATEGY_ALREADY_RUNNING",
    category="state_conflict",
)

_BOT_IMMUTABLE_FIELD_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_IMMUTABLE_FIELD",
    category="validation",
)


_INVALID_SIGNAL_KEY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INVALID_SIGNAL_KEY",
    category="validation",
)

_BOT_NOT_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_RUNNING",
    category="state_conflict",
)

_MALFORMED_REQUEST_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MALFORMED_REQUEST",
    category="validation",
)

_BOT_SIGNAL_CHANNEL_BUSY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_SIGNAL_CHANNEL_BUSY",
    category="state_conflict",
)


_TREASURY_INVALID_AMOUNT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INVALID_AMOUNT",
    category="validation",
)

_TREASURY_INSUFFICIENT_BALANCE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INSUFFICIENT_BALANCE",
    category="validation",
)

_TREASURY_BUDGET_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_BUDGET_NOT_FOUND",
    category="not_found",
)

_TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE",
    category="validation",
)

_TREASURY_INSUFFICIENT_FUNDS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_INSUFFICIENT_FUNDS",
    category="validation",
)

_TREASURY_BOT_NOT_STOPPED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_BOT_NOT_STOPPED",
    category="state_conflict",
)

_TREASURY_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_NOT_CONFIGURED",
    category="service_unavailable",
)


_BROKER_AUTH_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_AUTH_FAILED",
    category="auth",
)

_BROKER_API_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_API_ERROR",
    category="external",
)

_BROKER_ORDER_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_ORDER_NOT_FOUND",
    category="not_found",
)

_BROKER_RATE_LIMITED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_RATE_LIMITED",
    category="external",
)

_BROKER_CIRCUIT_OPEN_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_CIRCUIT_OPEN",
    category="service_unavailable",
)

_BROKER_INVALID_TYPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_INVALID_TYPE",
    category="validation",
)


_STRATEGY_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_NOT_FOUND",
    category="not_found",
)

_STRATEGY_LOAD_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_LOAD_ERROR",
    category="validation",
)

_STRATEGY_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_VALIDATION_ERROR",
    category="validation",
)

_STRATEGY_FILE_ACCESS_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_FILE_ACCESS_ERROR",
    category="external",
)

_STRATEGY_INCOMPATIBLE_EXCHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_INCOMPATIBLE_EXCHANGE",
    category="validation",
)


_CONFIG_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_VALIDATION_ERROR",
    category="validation",
)


_RULE_CONFIG_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="RULE_CONFIG_ERROR",
    category="validation",
)


_SERVICE_NOT_CONFIGURED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="SERVICE_NOT_CONFIGURED",
    category="service_unavailable",
)


_READ_ONLY_DATABASE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="EXECUTION_ERROR",
    category="internal",
)


_INVALID_ISO_DATE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="VALIDATION_ERROR",
    category="validation",
)


_IPC_SERVER_NOT_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="IPC_SERVER_NOT_RUNNING",
    category="service_unavailable",
)

_IPC_TIMEOUT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="IPC_TIMEOUT",
    category="service_unavailable",
)


_CLI_OPTION_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_OPTION_CONFLICT",
    category="validation",
)

_REPORT_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="REPORT_ERROR",
    category="internal",
)

_REPORT_INVALID_STATUS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="REPORT_INVALID_STATUS",
    category="validation",
)

_REPORT_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="REPORT_NOT_FOUND",
    category="not_found",
)

_REPORT_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="REPORT_VALIDATION_ERROR",
    category="validation",
)

_TRADE_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TRADE_ERROR",
    category="internal",
)

_TRADE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TRADE_NOT_FOUND",
    category="not_found",
)


EXECUTION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="EXECUTION_ERROR",
    category="internal",
)
"""``error_spec_for_exception`` 의 최후 fallback ErrorSpec.
"""


EXCEPTION_TO_SPEC: Final[dict[type[BaseException], ErrorSpec]] = {
    InvalidAccountIdError: _INVALID_ACCOUNT_ID_SPEC,
    BotNotFoundError: _BOT_NOT_FOUND_SPEC,
    ApprovalNotFoundError: _APPROVAL_NOT_FOUND_SPEC,
    InvalidScopeError: _MEMBER_INVALID_SCOPE_SPEC,
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
    PermissionDeniedError: _MEMBER_PERMISSION_DENIED_SPEC,
    MemberNotFoundError: _MEMBER_NOT_FOUND_SPEC,
    MemberStateConflictError: _MEMBER_STATE_CONFLICT_SPEC,
    MemberAlreadyExistsError: _MEMBER_ALREADY_EXISTS_SPEC,
    ReservedMemberIdError: _MEMBER_ID_RESERVED_SPEC,
    MemberInvalidRecoveryCredentialError: _MEMBER_INVALID_RECOVERY_CREDENTIAL_SPEC,
    MemberInvalidEmojiError: _MEMBER_INVALID_EMOJI_SPEC,
    MemberMasterProtectedError: _MEMBER_MASTER_PROTECTED_SPEC,
    ApprovalStatusConflictError: _APPROVAL_STATUS_CONFLICT_SPEC,
    ApprovalValidationError: _APPROVAL_VALIDATION_ERROR_SPEC,
    BotAccountCredentialsNotConfigured: _BOT_ACCOUNT_CREDENTIALS_NOT_CONFIGURED_SPEC,
    BotStateConflict: _BOT_STATE_CONFLICT_SPEC,
    BotNotAcceptingSignals: _BOT_NOT_ACCEPTING_SIGNALS_SPEC,
    BotAlreadyExistsError: _BOT_ALREADY_EXISTS_SPEC,
    BotStrategyAlreadyRunningError: _BOT_STRATEGY_ALREADY_RUNNING_SPEC,
    BotImmutableFieldError: _BOT_IMMUTABLE_FIELD_SPEC,
    InvalidSignalKey: _INVALID_SIGNAL_KEY_SPEC,
    BotNotRunning: _BOT_NOT_RUNNING_SPEC,
    BotSignalChannelBusy: _BOT_SIGNAL_CHANNEL_BUSY_SPEC,
    SignalKeyManagerNotConfigured: _SERVICE_NOT_CONFIGURED_SPEC,
    TreasuryInvalidAmountError: _TREASURY_INVALID_AMOUNT_SPEC,
    TreasuryInsufficientUnallocatedError: _TREASURY_INSUFFICIENT_BALANCE_SPEC,
    TreasuryBudgetNotFoundError: _TREASURY_BUDGET_NOT_FOUND_SPEC,
    TreasuryDeallocateExceedsAvailableError: (
        _TREASURY_DEALLOCATE_EXCEEDS_AVAILABLE_SPEC
    ),
    InsufficientFundsError: _TREASURY_INSUFFICIENT_FUNDS_SPEC,
    BotNotStoppedError: _TREASURY_BOT_NOT_STOPPED_SPEC,
    TreasuryNotConfiguredError: _TREASURY_NOT_CONFIGURED_SPEC,
    AuthenticationError: _BROKER_AUTH_FAILED_SPEC,
    APIError: _BROKER_API_ERROR_SPEC,
    OrderNotFoundError: _BROKER_ORDER_NOT_FOUND_SPEC,
    RateLimitError: _BROKER_RATE_LIMITED_SPEC,
    CircuitOpenError: _BROKER_CIRCUIT_OPEN_SPEC,
    BrokerRegistryInvalidBrokerTypeError: _BROKER_INVALID_TYPE_SPEC,
    StrategyNotFoundError: _STRATEGY_NOT_FOUND_SPEC,
    StrategyLoadError: _STRATEGY_LOAD_ERROR_SPEC,
    StrategyValidationError: _STRATEGY_VALIDATION_ERROR_SPEC,
    StrategyFileAccessError: _STRATEGY_FILE_ACCESS_ERROR_SPEC,
    IncompatibleExchangeError: _STRATEGY_INCOMPATIBLE_EXCHANGE_SPEC,
    ConfigValidationError: _CONFIG_VALIDATION_ERROR_SPEC,
    RuleConfigError: _RULE_CONFIG_ERROR_SPEC,
    ReadOnlyDatabaseError: _READ_ONLY_DATABASE_SPEC,
    InvalidIsoDateError: _INVALID_ISO_DATE_SPEC,
    IPCServerNotRunningError: _IPC_SERVER_NOT_RUNNING_SPEC,
    IPCClientTimeoutError: _IPC_TIMEOUT_SPEC,
    CliOptionConflictError: _CLI_OPTION_CONFLICT_SPEC,
    ReportError: _REPORT_ERROR_SPEC,
    ReportInvalidStatusError: _REPORT_INVALID_STATUS_SPEC,
    ReportNotFoundError: _REPORT_NOT_FOUND_SPEC,
    ReportValidationError: _REPORT_VALIDATION_ERROR_SPEC,
    TradeError: _TRADE_ERROR_SPEC,
    TradeNotFoundError: _TRADE_NOT_FOUND_SPEC,
}
"""대표 fault lock registry (normative 4건).

``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__`` 순서로 본 dict를
조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` 활용 → ``EXECUTION_ERROR`` fallback 순서로
resolve 한다.
"""
