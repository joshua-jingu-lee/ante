"""Domain exception → ErrorSpec mapping registry."""

from __future__ import annotations

from typing import Final

from ante.account.crypto import (
    EncryptionKeyError,
    EncryptionKeyInvalidError,
    EncryptionKeyMissingError,
)
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
    ModifyOrgnoUnavailableError,
    OrderNotFoundError,
    RateLimitError,
)
from ante.broker.registry import (
    InvalidBrokerTypeError as BrokerRegistryInvalidBrokerTypeError,
)
from ante.config.exceptions import ConfigValidationError
from ante.contracts.cli_errors import (
    AccountAlreadyDeletedError,
    AccountCredentialEnvNotSetError,
    AccountCredentialFileNotFoundError,
    AccountDuplicateCredentialKeyError,
    AccountInvalidStatusError,
    AccountInvalidTimezoneError,
    AccountMasterBootstrapFailedError,
    AccountMissingRequiredCredentialError,
    AccountTestCreateFailedError,
    AccountTestInactiveError,
    AccountUnknownCredentialKeyError,
    AlreadyRunningError,
    ApprovalInvalidStatusError,
    ApprovalInvalidTypeError,
    BackfillStopRequestedError,
    BacktestDataNotFoundError,
    BacktestError,
    BacktestInvalidExchangeError,
    BacktestInvalidSymbolError,
    BacktestInvalidTimeframeError,
    BotInvalidParamError,
    BotMissingRequiredAccountError,
    CliAlreadyInitializedError,
    CliAuthFailedError,
    CliAuthRequiredError,
    CliBotNotFoundError,
    CliConfirmationRequiredError,
    CliInvalidDateError,
    CliInvalidScheduleTimeError,
    CliMemberNotFoundError,
    CliMissingRequiredInputError,
    CliOptionConflictError,
    CliPermissionDeniedError,
    CliStrategyError,
    ConfigInvalidGeneralError,
    ConfigInvalidGuardError,
    ConfigInvalidLogLevelError,
    ConfigInvalidNiceValueError,
    ConfigInvalidValueError,
    ConfigKeyNotFoundError,
    ConfigUnsupportedKeyError,
    DataError,
    DataInvalidDatasetIdError,
    DataInvalidFilterError,
    DatasetNotFoundError,
    DataValidateInvalidSymbolError,
    DataValidateInvalidTimeframeError,
    FeedFileNotFoundError,
    FeedInjectInvalidSymbolError,
    FeedInjectInvalidTimeframeError,
    FeedInjectValidationError,
    FeedNotInitializedError,
    GuardPermanentlyBlockedError,
    InstrumentEmptyFileError,
    InstrumentInvalidExchangeError,
    InstrumentInvalidFileFormatError,
    InstrumentInvalidJsonShapeError,
    InstrumentInvalidSymbolError,
    InstrumentIoError,
    InstrumentMissingColumnsError,
    InstrumentSyncFailedError,
    InstrumentSyncSourceUnsupportedError,
    InvalidDateError,
    InvalidDateRangeError,
    InvalidJsonError,
    MemberPasswordEnvNotSetError,
    MemberPasswordFileNotFoundError,
    PidNotFoundError,
    ProcessNotFoundError,
    ReportError,
    ReportInvalidStatusError,
    ReportNotFoundError,
    ReportValidationError,
    RuleNotFoundError,
    RuleUpdateError,
    SignalKeyNotSetError,
    SnapshotNotFoundError,
    StrategyInvalidStatusTransitionError,
    StrategyMissingRequiredAccountError,
    StrategyValidationFailedError,
    TradeError,
    TradeNotFoundError,
    TreasuryAllocateFailedError,
    TreasuryDeallocateFailedError,
    UpdateCheckFailedError,
    UpdateInstallFailedError,
    UpdateInsufficientDiskSpaceError,
    UpdateMigrationFailedError,
    UpdateRollbackFailedError,
    UpdateServerRunningError,
)
from ante.contracts.errors import ErrorSpec
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCServerNotRunningError,
)
from ante.contracts.request_errors import RequestValidationError
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
    description="`approval request --type` 값이 SSOT enum에 없음",
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
    description=(
        "핸드셰이크 게이트 1 — signal key 검증 실패(`validate_signal_key` → None)"
    ),
)

_BOT_NOT_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_NOT_RUNNING",
    category="state_conflict",
    description="핸드셰이크 게이트 3 — 봇 존재하나 `status != RUNNING`",
)

_MALFORMED_REQUEST_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MALFORMED_REQUEST",
    category="validation",
    description="핸드셰이크 첫 프레임이 비-dict로 decode(`_handle_connection` 가드)",
)

_BOT_SIGNAL_CHANNEL_BUSY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_SIGNAL_CHANNEL_BUSY",
    category="state_conflict",
    description=(
        "bot_id당 단일 active session 정책 — 2번째 `signal.connect` 핸드셰이크 거부"
    ),
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

_BROKER_MODIFY_ORGNO_UNAVAILABLE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BROKER_MODIFY_ORGNO_UNAVAILABLE",
    category="state_conflict",
)

_STOP_ORDER_MANAGER_STOPPED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STOP_ORDER_MANAGER_STOPPED",
    category="service_unavailable",
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
    description="strategy 명령 인자(예: `--status`) 값이 SSOT enum에 없음",
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
    description=(
        "`config set <key> <value>` 의 key-invariant 위반 (enum SSOT가 정의된 키에 "
        "invalid 값, 예 `system.log_level` 이 `_VALID_LOG_LEVELS` 비멤버)"
    ),
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


_REQUEST_VALIDATION_SPEC: Final[ErrorSpec] = ErrorSpec(
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

_IPC_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="IPC_ERROR",
    category="internal",
)

_IPC_UNKNOWN_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UNKNOWN",
    category="internal",
)

_MESSAGE_TOO_LARGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MESSAGE_TOO_LARGE",
    category="validation",
)

_SERVICE_UNAVAILABLE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="SERVICE_UNAVAILABLE",
    category="service_unavailable",
)

_UNKNOWN_COMMAND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UNKNOWN_COMMAND",
    category="internal",
)


_CLI_OPTION_CONFLICT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_OPTION_CONFLICT",
    category="validation",
    description=(
        "상호 배타적인 옵션을 동시 사용 (period별 전용 옵션을 다른 period와 함께 사용 "
        "등)"
    ),
)

_CLI_USAGE_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_USAGE_ERROR",
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
    description=(
        "report 명령 입력 계약 위반 (제출 리포트 JSON/스키마 위반, `report performance "
        "--period monthly --year` 가 비양수 calendar year)"
    ),
)

_TRADE_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TRADE_ERROR",
    category="internal",
)

_TRADE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TRADE_NOT_FOUND",
    category="not_found",
)

_BACKTEST_DATA_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKTEST_DATA_NOT_FOUND",
    category="not_found",
)

_BACKTEST_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKTEST_ERROR",
    category="internal",
)

_BACKTEST_INVALID_EXCHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKTEST_INVALID_EXCHANGE",
    category="validation",
)

_BACKTEST_INVALID_SYMBOL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKTEST_INVALID_SYMBOL",
    category="validation",
)

_BACKTEST_INVALID_TIMEFRAME_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKTEST_INVALID_TIMEFRAME",
    category="validation",
)

_CLI_CONFIRMATION_REQUIRED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_CONFIRMATION_REQUIRED",
    category="validation",
    description="위험 명령에 `--yes`/`--force` 누락",
)

_DATASET_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATASET_NOT_FOUND",
    category="not_found",
)

_DATA_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATA_ERROR",
    category="internal",
)

_DATA_INVALID_DATASET_ID_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATA_INVALID_DATASET_ID",
    category="validation",
)

_DATA_INVALID_FILTER_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATA_INVALID_FILTER",
    category="validation",
)

_DATA_VALIDATE_INVALID_SYMBOL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATA_VALIDATE_INVALID_SYMBOL",
    category="validation",
)

_DATA_VALIDATE_INVALID_TIMEFRAME_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DATA_VALIDATE_INVALID_TIMEFRAME",
    category="validation",
)

_INSTRUMENT_EMPTY_FILE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_EMPTY_FILE",
    category="validation",
)

_INSTRUMENT_INVALID_EXCHANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_INVALID_EXCHANGE",
    category="validation",
)

_INSTRUMENT_INVALID_FILE_FORMAT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_INVALID_FILE_FORMAT",
    category="validation",
)

_INSTRUMENT_INVALID_JSON_SHAPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_INVALID_JSON_SHAPE",
    category="validation",
)

_INSTRUMENT_INVALID_SYMBOL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_INVALID_SYMBOL",
    category="validation",
)

_INSTRUMENT_IO_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_IO_ERROR",
    category="internal",
)

_INSTRUMENT_MISSING_COLUMNS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_MISSING_COLUMNS",
    category="validation",
)

_INSTRUMENT_SYNC_SOURCE_UNSUPPORTED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_SYNC_SOURCE_UNSUPPORTED",
    category="validation",
)

_INVALID_DATE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INVALID_DATE",
    category="validation",
)

_INVALID_DATE_RANGE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INVALID_DATE_RANGE",
    category="validation",
    description=(
        "시작일 > 종료일 (inverted date range) 또는 effective 시작일이 미래(`feed run "
        "backfill --since` / `[schedule].backfill_since` > today)"
    ),
)

_ACCOUNT_MASTER_BOOTSTRAP_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_MASTER_BOOTSTRAP_FAILED",
    category="state_conflict",
)

_ACCOUNT_TEST_CREATE_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_TEST_CREATE_FAILED",
    category="internal",
)

_ACCOUNT_TEST_INACTIVE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_TEST_INACTIVE",
    category="state_conflict",
)

_ACCOUNT_ALREADY_DELETED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_ALREADY_DELETED",
    category="state_conflict",
)

_ACCOUNT_INVALID_STATUS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_INVALID_STATUS",
    category="validation",
)

_MEMBER_PASSWORD_ENV_NOT_SET_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_PASSWORD_ENV_NOT_SET",
    category="validation",
    description=(
        "`--password-env`/`--new-password-env`이 참조한 환경변수가 설정되지 않음"
    ),
)

_MEMBER_PASSWORD_FILE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="MEMBER_PASSWORD_FILE_NOT_FOUND",
    category="validation",
    description=(
        "`--password-file`/`--new-password-file`이 가리키는 파일이 존재하지 않음"
    ),
)

_ACCOUNT_CREDENTIAL_ENV_NOT_SET_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_CREDENTIAL_ENV_NOT_SET",
    category="validation",
    description="`--credential-env`이 참조한 환경변수가 설정되지 않음",
)

_ACCOUNT_CREDENTIAL_FILE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_CREDENTIAL_FILE_NOT_FOUND",
    category="validation",
    description="`--credential-file`이 가리키는 파일이 존재하지 않음",
)

_ACCOUNT_DUPLICATE_CREDENTIAL_KEY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_DUPLICATE_CREDENTIAL_KEY",
    category="validation",
    description=(
        "같은 credential key를 `--credential`/`--credential-env`/`--credential-file` "
        "중 둘 이상 채널로 중복 제공"
    ),
)

_ACCOUNT_INVALID_TIMEZONE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_INVALID_TIMEZONE",
    category="validation",
)

_ACCOUNT_MISSING_REQUIRED_CREDENTIAL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_MISSING_REQUIRED_CREDENTIAL",
    category="validation",
    description="`BrokerPreset.required_credentials`에 정의된 credential key 누락",
)

_ACCOUNT_UNKNOWN_CREDENTIAL_KEY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ACCOUNT_UNKNOWN_CREDENTIAL_KEY",
    category="validation",
    description=(
        "broker preset의 `required_credentials`에 정의되지 않은 credential key 제공"
    ),
)

_ALREADY_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="ALREADY_RUNNING",
    category="state_conflict",
)

_CLI_ALREADY_INITIALIZED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_ALREADY_INITIALIZED",
    category="state_conflict",
)

_CONFIG_KEY_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_KEY_NOT_FOUND",
    category="not_found",
)

_INSTRUMENT_SYNC_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INSTRUMENT_SYNC_FAILED",
    category="external",
)

_PID_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="PID_NOT_FOUND",
    category="not_found",
)

_PROCESS_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="PROCESS_NOT_FOUND",
    category="not_found",
)

_RULE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="RULE_NOT_FOUND",
    category="not_found",
)

_RULE_UPDATE_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="RULE_UPDATE_ERROR",
    category="internal",
)

_UPDATE_CHECK_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_CHECK_FAILED",
    category="external",
)

_UPDATE_INSTALL_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_INSTALL_FAILED",
    category="external",
)

_UPDATE_INSUFFICIENT_DISK_SPACE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_INSUFFICIENT_DISK_SPACE",
    category="state_conflict",
)

_UPDATE_MIGRATION_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_MIGRATION_FAILED",
    category="internal",
)

_UPDATE_ROLLBACK_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_ROLLBACK_FAILED",
    category="internal",
)

_UPDATE_SERVER_RUNNING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="UPDATE_SERVER_RUNNING",
    category="state_conflict",
    description="`ante update --force` 없이 서버가 실행 중",
)

_APPROVAL_INVALID_STATUS_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_INVALID_STATUS",
    category="validation",
)

_APPROVAL_INVALID_TYPE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="APPROVAL_INVALID_TYPE",
    category="validation",
)

_BOT_INVALID_PARAM_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_INVALID_PARAM",
    category="validation",
)

_BOT_MISSING_REQUIRED_ACCOUNT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BOT_MISSING_REQUIRED_ACCOUNT",
    category="validation",
    description="`--account` 생략 시 active 계좌가 0개 또는 2개 이상",
)

_CLI_MISSING_REQUIRED_INPUT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_MISSING_REQUIRED_INPUT",
    category="validation",
    description="필수 옵션·인자 누락 (도메인 명확 시 도메인 prefix specialize)",
)

_INVALID_JSON_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="INVALID_JSON",
    category="validation",
)

_SIGNAL_KEY_NOT_SET_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="SIGNAL_KEY_NOT_SET",
    category="not_found",
)

_SNAPSHOT_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="SNAPSHOT_NOT_FOUND",
    category="not_found",
)

_STRATEGY_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_ERROR",
    category="internal",
)

_STRATEGY_INVALID_STATUS_TRANSITION_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_INVALID_STATUS_TRANSITION",
    category="state_conflict",
)

_STRATEGY_MISSING_REQUIRED_ACCOUNT_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_MISSING_REQUIRED_ACCOUNT",
    category="validation",
)

_STRATEGY_VALIDATION_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="STRATEGY_VALIDATION_FAILED",
    category="validation",
)

_TREASURY_ALLOCATE_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_ALLOCATE_FAILED",
    category="validation",
)

_TREASURY_DEALLOCATE_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="TREASURY_DEALLOCATE_FAILED",
    category="validation",
)

_AUTH_REQUIRED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="auth_required",
    category="auth",
    description='`@require_auth` 미충족 (`ctx.obj["member"] is None`)',
)

_AUTH_FAILED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="auth_failed",
    category="auth",
    description="`ANTE_MEMBER_TOKEN`의 토큰 판정 거부와 DB `connect()` 실패",
)

_PERMISSION_DENIED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="permission_denied",
    category="permission",
    description="인증 OK이나 scope 부족",
)

_DB_ENCRYPTION_KEY_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DB_ENCRYPTION_KEY_ERROR",
    category="internal",
)

_DB_ENCRYPTION_KEY_MISSING_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DB_ENCRYPTION_KEY_MISSING",
    category="internal",
)

_DB_ENCRYPTION_KEY_INVALID_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="DB_ENCRYPTION_KEY_INVALID",
    category="internal",
)

_BACKFILL_STOP_REQUESTED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="BACKFILL_STOP_REQUESTED",
    category="state_conflict",
)

_CLI_INVALID_DATE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_INVALID_DATE",
    category="validation",
)

_CLI_INVALID_SCHEDULE_TIME_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CLI_INVALID_SCHEDULE_TIME",
    category="validation",
)

_CONFIG_INVALID_GENERAL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_INVALID_GENERAL",
    category="validation",
)

_CONFIG_INVALID_GUARD_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_INVALID_GUARD",
    category="validation",
)

_CONFIG_INVALID_LOG_LEVEL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_INVALID_LOG_LEVEL",
    category="validation",
)

_CONFIG_INVALID_NICE_VALUE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_INVALID_NICE_VALUE",
    category="validation",
)

_CONFIG_INVALID_VALUE_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_INVALID_VALUE",
    category="validation",
)

_CONFIG_UNSUPPORTED_KEY_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="CONFIG_UNSUPPORTED_KEY",
    category="validation",
)

_FEED_INJECT_VALIDATION_ERROR_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="VALIDATION_ERROR",
    category="validation",
)

_FILE_NOT_FOUND_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="FILE_NOT_FOUND",
    category="validation",
)

_FEED_INJECT_INVALID_SYMBOL_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="FEED_INJECT_INVALID_SYMBOL",
    category="validation",
)

_FEED_INJECT_INVALID_TIMEFRAME_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="FEED_INJECT_INVALID_TIMEFRAME",
    category="validation",
)

_NOT_INITIALIZED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="NOT_INITIALIZED",
    category="state_conflict",
)

_GUARD_PERMANENTLY_BLOCKED_SPEC: Final[ErrorSpec] = ErrorSpec(
    code="GUARD_PERMANENTLY_BLOCKED",
    category="validation",
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
    RequestValidationError: _REQUEST_VALIDATION_SPEC,
    IPCServerNotRunningError: _IPC_SERVER_NOT_RUNNING_SPEC,
    IPCClientTimeoutError: _IPC_TIMEOUT_SPEC,
    CliOptionConflictError: _CLI_OPTION_CONFLICT_SPEC,
    ReportError: _REPORT_ERROR_SPEC,
    ReportInvalidStatusError: _REPORT_INVALID_STATUS_SPEC,
    ReportNotFoundError: _REPORT_NOT_FOUND_SPEC,
    ReportValidationError: _REPORT_VALIDATION_ERROR_SPEC,
    TradeError: _TRADE_ERROR_SPEC,
    TradeNotFoundError: _TRADE_NOT_FOUND_SPEC,
    BacktestDataNotFoundError: _BACKTEST_DATA_NOT_FOUND_SPEC,
    BacktestError: _BACKTEST_ERROR_SPEC,
    BacktestInvalidExchangeError: _BACKTEST_INVALID_EXCHANGE_SPEC,
    BacktestInvalidSymbolError: _BACKTEST_INVALID_SYMBOL_SPEC,
    BacktestInvalidTimeframeError: _BACKTEST_INVALID_TIMEFRAME_SPEC,
    CliConfirmationRequiredError: _CLI_CONFIRMATION_REQUIRED_SPEC,
    DatasetNotFoundError: _DATASET_NOT_FOUND_SPEC,
    DataError: _DATA_ERROR_SPEC,
    DataInvalidDatasetIdError: _DATA_INVALID_DATASET_ID_SPEC,
    DataInvalidFilterError: _DATA_INVALID_FILTER_SPEC,
    DataValidateInvalidSymbolError: _DATA_VALIDATE_INVALID_SYMBOL_SPEC,
    DataValidateInvalidTimeframeError: _DATA_VALIDATE_INVALID_TIMEFRAME_SPEC,
    InstrumentEmptyFileError: _INSTRUMENT_EMPTY_FILE_SPEC,
    InstrumentInvalidExchangeError: _INSTRUMENT_INVALID_EXCHANGE_SPEC,
    InstrumentInvalidFileFormatError: _INSTRUMENT_INVALID_FILE_FORMAT_SPEC,
    InstrumentInvalidJsonShapeError: _INSTRUMENT_INVALID_JSON_SHAPE_SPEC,
    InstrumentInvalidSymbolError: _INSTRUMENT_INVALID_SYMBOL_SPEC,
    InstrumentIoError: _INSTRUMENT_IO_ERROR_SPEC,
    InstrumentMissingColumnsError: _INSTRUMENT_MISSING_COLUMNS_SPEC,
    InstrumentSyncSourceUnsupportedError: _INSTRUMENT_SYNC_SOURCE_UNSUPPORTED_SPEC,
    InvalidDateError: _INVALID_DATE_SPEC,
    InvalidDateRangeError: _INVALID_DATE_RANGE_SPEC,
    AccountMasterBootstrapFailedError: _ACCOUNT_MASTER_BOOTSTRAP_FAILED_SPEC,
    AccountTestCreateFailedError: _ACCOUNT_TEST_CREATE_FAILED_SPEC,
    AccountTestInactiveError: _ACCOUNT_TEST_INACTIVE_SPEC,
    AlreadyRunningError: _ALREADY_RUNNING_SPEC,
    CliAlreadyInitializedError: _CLI_ALREADY_INITIALIZED_SPEC,
    ConfigKeyNotFoundError: _CONFIG_KEY_NOT_FOUND_SPEC,
    InstrumentSyncFailedError: _INSTRUMENT_SYNC_FAILED_SPEC,
    PidNotFoundError: _PID_NOT_FOUND_SPEC,
    ProcessNotFoundError: _PROCESS_NOT_FOUND_SPEC,
    RuleNotFoundError: _RULE_NOT_FOUND_SPEC,
    RuleUpdateError: _RULE_UPDATE_ERROR_SPEC,
    UpdateCheckFailedError: _UPDATE_CHECK_FAILED_SPEC,
    UpdateInstallFailedError: _UPDATE_INSTALL_FAILED_SPEC,
    UpdateInsufficientDiskSpaceError: _UPDATE_INSUFFICIENT_DISK_SPACE_SPEC,
    UpdateMigrationFailedError: _UPDATE_MIGRATION_FAILED_SPEC,
    UpdateRollbackFailedError: _UPDATE_ROLLBACK_FAILED_SPEC,
    UpdateServerRunningError: _UPDATE_SERVER_RUNNING_SPEC,
    ApprovalInvalidStatusError: _APPROVAL_INVALID_STATUS_SPEC,
    ApprovalInvalidTypeError: _APPROVAL_INVALID_TYPE_SPEC,
    BotInvalidParamError: _BOT_INVALID_PARAM_SPEC,
    BotMissingRequiredAccountError: _BOT_MISSING_REQUIRED_ACCOUNT_SPEC,
    CliBotNotFoundError: _BOT_NOT_FOUND_SPEC,
    CliMissingRequiredInputError: _CLI_MISSING_REQUIRED_INPUT_SPEC,
    InvalidJsonError: _INVALID_JSON_SPEC,
    SignalKeyNotSetError: _SIGNAL_KEY_NOT_SET_SPEC,
    SnapshotNotFoundError: _SNAPSHOT_NOT_FOUND_SPEC,
    CliStrategyError: _STRATEGY_ERROR_SPEC,
    StrategyInvalidStatusTransitionError: _STRATEGY_INVALID_STATUS_TRANSITION_SPEC,
    StrategyMissingRequiredAccountError: _STRATEGY_MISSING_REQUIRED_ACCOUNT_SPEC,
    StrategyValidationFailedError: _STRATEGY_VALIDATION_FAILED_SPEC,
    TreasuryAllocateFailedError: _TREASURY_ALLOCATE_FAILED_SPEC,
    TreasuryDeallocateFailedError: _TREASURY_DEALLOCATE_FAILED_SPEC,
    AccountAlreadyDeletedError: _ACCOUNT_ALREADY_DELETED_SPEC,
    AccountInvalidStatusError: _ACCOUNT_INVALID_STATUS_SPEC,
    CliMemberNotFoundError: _MEMBER_NOT_FOUND_SPEC,
    MemberPasswordEnvNotSetError: _MEMBER_PASSWORD_ENV_NOT_SET_SPEC,
    MemberPasswordFileNotFoundError: _MEMBER_PASSWORD_FILE_NOT_FOUND_SPEC,
    AccountCredentialEnvNotSetError: _ACCOUNT_CREDENTIAL_ENV_NOT_SET_SPEC,
    AccountCredentialFileNotFoundError: _ACCOUNT_CREDENTIAL_FILE_NOT_FOUND_SPEC,
    AccountDuplicateCredentialKeyError: _ACCOUNT_DUPLICATE_CREDENTIAL_KEY_SPEC,
    AccountInvalidTimezoneError: _ACCOUNT_INVALID_TIMEZONE_SPEC,
    AccountMissingRequiredCredentialError: _ACCOUNT_MISSING_REQUIRED_CREDENTIAL_SPEC,
    AccountUnknownCredentialKeyError: _ACCOUNT_UNKNOWN_CREDENTIAL_KEY_SPEC,
    CliAuthRequiredError: _AUTH_REQUIRED_SPEC,
    CliAuthFailedError: _AUTH_FAILED_SPEC,
    CliPermissionDeniedError: _PERMISSION_DENIED_SPEC,
    EncryptionKeyError: _DB_ENCRYPTION_KEY_ERROR_SPEC,
    EncryptionKeyMissingError: _DB_ENCRYPTION_KEY_MISSING_SPEC,
    EncryptionKeyInvalidError: _DB_ENCRYPTION_KEY_INVALID_SPEC,
    BackfillStopRequestedError: _BACKFILL_STOP_REQUESTED_SPEC,
    CliInvalidDateError: _CLI_INVALID_DATE_SPEC,
    CliInvalidScheduleTimeError: _CLI_INVALID_SCHEDULE_TIME_SPEC,
    ConfigInvalidGeneralError: _CONFIG_INVALID_GENERAL_SPEC,
    ConfigInvalidGuardError: _CONFIG_INVALID_GUARD_SPEC,
    ConfigInvalidLogLevelError: _CONFIG_INVALID_LOG_LEVEL_SPEC,
    ConfigInvalidNiceValueError: _CONFIG_INVALID_NICE_VALUE_SPEC,
    ConfigInvalidValueError: _CONFIG_INVALID_VALUE_SPEC,
    ConfigUnsupportedKeyError: _CONFIG_UNSUPPORTED_KEY_SPEC,
    FeedFileNotFoundError: _FILE_NOT_FOUND_SPEC,
    FeedInjectInvalidSymbolError: _FEED_INJECT_INVALID_SYMBOL_SPEC,
    FeedInjectInvalidTimeframeError: _FEED_INJECT_INVALID_TIMEFRAME_SPEC,
    FeedInjectValidationError: _FEED_INJECT_VALIDATION_ERROR_SPEC,
    FeedNotInitializedError: _NOT_INITIALIZED_SPEC,
    GuardPermanentlyBlockedError: _GUARD_PERMANENTLY_BLOCKED_SPEC,
    ModifyOrgnoUnavailableError: _BROKER_MODIFY_ORGNO_UNAVAILABLE_SPEC,
}
"""fault lock registry. ``error_spec_for_exception(exc)`` 는 ``type(exc).__mro__``
순서로 본 dict를 조회하여 첫 매치 ErrorSpec을 반환한다. registry miss 시 helper 는
``getattr(exc, "code", None)`` → ``EXECUTION_ERROR`` fallback 순서로 resolve 한다."""
