from __future__ import annotations

__all__ = [
    "AccountAlreadyDeletedError",
    "AccountCredentialEnvNotSetError",
    "AccountCredentialFileNotFoundError",
    "AccountDuplicateCredentialKeyError",
    "AccountInvalidStatusError",
    "AccountInvalidTimezoneError",
    "AccountMasterBootstrapFailedError",
    "AccountMissingRequiredCredentialError",
    "AccountTestCreateFailedError",
    "AccountTestInactiveError",
    "AccountUnknownCredentialKeyError",
    "AlreadyRunningError",
    "ApprovalInvalidStatusError",
    "ApprovalInvalidTypeError",
    "BackfillStopRequestedError",
    "BacktestDataNotFoundError",
    "BacktestError",
    "BacktestInvalidExchangeError",
    "BacktestInvalidSymbolError",
    "BacktestInvalidTimeframeError",
    "BotMissingRequiredAccountError",
    "CliAlreadyInitializedError",
    "CliAuthFailedError",
    "CliAuthRequiredError",
    "CliBotNotFoundError",
    "CliConfirmationRequiredError",
    "CliInvalidDateError",
    "CliInvalidScheduleTimeError",
    "CliMemberNotFoundError",
    "CliMissingRequiredInputError",
    "CliOptionConflictError",
    "CliPermissionDeniedError",
    "CliStrategyError",
    "ConfigInvalidGeneralError",
    "ConfigInvalidGuardError",
    "ConfigInvalidLogLevelError",
    "ConfigInvalidNiceValueError",
    "ConfigInvalidValueError",
    "ConfigKeyNotFoundError",
    "ConfigUnsupportedKeyError",
    "DataError",
    "DataInvalidDatasetIdError",
    "DataInvalidFilterError",
    "DataValidateInvalidSymbolError",
    "DataValidateInvalidTimeframeError",
    "DatasetNotFoundError",
    "FeedFileNotFoundError",
    "FeedInjectInvalidSymbolError",
    "FeedInjectInvalidTimeframeError",
    "FeedInjectValidationError",
    "FeedNotInitializedError",
    "GuardPermanentlyBlockedError",
    "InstrumentEmptyFileError",
    "InstrumentInvalidExchangeError",
    "InstrumentInvalidFileFormatError",
    "InstrumentInvalidJsonShapeError",
    "InstrumentInvalidSymbolError",
    "InstrumentIoError",
    "InstrumentMissingColumnsError",
    "InstrumentSyncFailedError",
    "InstrumentSyncSourceUnsupportedError",
    "InvalidDateError",
    "InvalidDateRangeError",
    "InvalidJsonError",
    "MemberPasswordEnvNotSetError",
    "MemberPasswordFileNotFoundError",
    "PidNotFoundError",
    "ProcessNotFoundError",
    "ReportError",
    "ReportInvalidStatusError",
    "ReportNotFoundError",
    "ReportValidationError",
    "RuleNotFoundError",
    "RuleUpdateError",
    "SignalKeyNotSetError",
    "SnapshotNotFoundError",
    "StrategyInvalidStatusTransitionError",
    "StrategyMissingRequiredAccountError",
    "StrategyValidationFailedError",
    "TradeError",
    "TradeNotFoundError",
    "TreasuryAllocateFailedError",
    "TreasuryDeallocateFailedError",
    "UpdateCheckFailedError",
    "UpdateInstallFailedError",
    "UpdateInsufficientDiskSpaceError",
    "UpdateMigrationFailedError",
    "UpdateRollbackFailedError",
    "UpdateServerRunningError",
]


class AccountAlreadyDeletedError(Exception):
    code = "ACCOUNT_ALREADY_DELETED"


class AccountCredentialEnvNotSetError(Exception):
    code = "ACCOUNT_CREDENTIAL_ENV_NOT_SET"


class AccountCredentialFileNotFoundError(Exception):
    code = "ACCOUNT_CREDENTIAL_FILE_NOT_FOUND"


class AccountDuplicateCredentialKeyError(Exception):
    code = "ACCOUNT_DUPLICATE_CREDENTIAL_KEY"


class AccountInvalidStatusError(Exception):
    code = "ACCOUNT_INVALID_STATUS"


class AccountInvalidTimezoneError(Exception):
    code = "ACCOUNT_INVALID_TIMEZONE"


class AccountMasterBootstrapFailedError(Exception):
    code = "ACCOUNT_MASTER_BOOTSTRAP_FAILED"


class AccountMissingRequiredCredentialError(Exception):
    code = "ACCOUNT_MISSING_REQUIRED_CREDENTIAL"


class AccountTestCreateFailedError(Exception):
    code = "ACCOUNT_TEST_CREATE_FAILED"


class AccountTestInactiveError(Exception):
    code = "ACCOUNT_TEST_INACTIVE"


class AccountUnknownCredentialKeyError(Exception):
    code = "ACCOUNT_UNKNOWN_CREDENTIAL_KEY"


class AlreadyRunningError(Exception):
    code = "ALREADY_RUNNING"


class ApprovalInvalidStatusError(Exception):
    code = "APPROVAL_INVALID_STATUS"


class ApprovalInvalidTypeError(Exception):
    code = "APPROVAL_INVALID_TYPE"


class BackfillStopRequestedError(Exception):
    code = "BACKFILL_STOP_REQUESTED"


class BacktestDataNotFoundError(Exception):
    code = "BACKTEST_DATA_NOT_FOUND"


class BacktestError(Exception):
    code = "BACKTEST_ERROR"


class BacktestInvalidExchangeError(Exception):
    code = "BACKTEST_INVALID_EXCHANGE"


class BacktestInvalidSymbolError(Exception):
    code = "BACKTEST_INVALID_SYMBOL"


class BacktestInvalidTimeframeError(Exception):
    code = "BACKTEST_INVALID_TIMEFRAME"


class BotMissingRequiredAccountError(Exception):
    code = "BOT_MISSING_REQUIRED_ACCOUNT"


class CliAlreadyInitializedError(Exception):
    code = "CLI_ALREADY_INITIALIZED"


class CliAuthFailedError(Exception):
    code = "auth_failed"


class CliAuthRequiredError(Exception):
    code = "auth_required"


class CliBotNotFoundError(Exception):
    code = "BOT_NOT_FOUND"


class CliConfirmationRequiredError(Exception):
    code = "CLI_CONFIRMATION_REQUIRED"


class CliInvalidDateError(Exception):
    code = "CLI_INVALID_DATE"


class CliInvalidScheduleTimeError(Exception):
    code = "CLI_INVALID_SCHEDULE_TIME"


class CliMemberNotFoundError(Exception):
    code = "MEMBER_NOT_FOUND"


class CliMissingRequiredInputError(Exception):
    code = "CLI_MISSING_REQUIRED_INPUT"


class CliOptionConflictError(Exception):
    code = "CLI_OPTION_CONFLICT"


class CliPermissionDeniedError(Exception):
    code = "permission_denied"


class CliStrategyError(Exception):
    code = "STRATEGY_ERROR"


class ConfigInvalidGeneralError(Exception):
    code = "CONFIG_INVALID_GENERAL"


class ConfigInvalidGuardError(Exception):
    code = "CONFIG_INVALID_GUARD"


class ConfigInvalidLogLevelError(Exception):
    code = "CONFIG_INVALID_LOG_LEVEL"


class ConfigInvalidNiceValueError(Exception):
    code = "CONFIG_INVALID_NICE_VALUE"


class ConfigInvalidValueError(Exception):
    code = "CONFIG_INVALID_VALUE"


class ConfigKeyNotFoundError(Exception):
    code = "CONFIG_KEY_NOT_FOUND"


class ConfigUnsupportedKeyError(Exception):
    code = "CONFIG_UNSUPPORTED_KEY"


class DataError(Exception):
    code = "DATA_ERROR"


class DataInvalidDatasetIdError(Exception):
    code = "DATA_INVALID_DATASET_ID"


class DataInvalidFilterError(Exception):
    code = "DATA_INVALID_FILTER"


class DataValidateInvalidSymbolError(Exception):
    code = "DATA_VALIDATE_INVALID_SYMBOL"


class DataValidateInvalidTimeframeError(Exception):
    code = "DATA_VALIDATE_INVALID_TIMEFRAME"


class DatasetNotFoundError(Exception):
    code = "DATASET_NOT_FOUND"


class FeedFileNotFoundError(Exception):
    code = "FILE_NOT_FOUND"


class FeedInjectInvalidSymbolError(Exception):
    code = "FEED_INJECT_INVALID_SYMBOL"


class FeedInjectInvalidTimeframeError(Exception):
    code = "FEED_INJECT_INVALID_TIMEFRAME"


class FeedInjectValidationError(Exception):
    code = "VALIDATION_ERROR"


class FeedNotInitializedError(Exception):
    code = "NOT_INITIALIZED"


class GuardPermanentlyBlockedError(Exception):
    code = "GUARD_PERMANENTLY_BLOCKED"


class InstrumentEmptyFileError(Exception):
    code = "INSTRUMENT_EMPTY_FILE"


class InstrumentInvalidExchangeError(Exception):
    code = "INSTRUMENT_INVALID_EXCHANGE"


class InstrumentInvalidFileFormatError(Exception):
    code = "INSTRUMENT_INVALID_FILE_FORMAT"


class InstrumentInvalidJsonShapeError(Exception):
    code = "INSTRUMENT_INVALID_JSON_SHAPE"


class InstrumentInvalidSymbolError(Exception):
    code = "INSTRUMENT_INVALID_SYMBOL"


class InstrumentIoError(Exception):
    code = "INSTRUMENT_IO_ERROR"


class InstrumentMissingColumnsError(Exception):
    code = "INSTRUMENT_MISSING_COLUMNS"


class InstrumentSyncFailedError(Exception):
    code = "INSTRUMENT_SYNC_FAILED"


class InstrumentSyncSourceUnsupportedError(Exception):
    code = "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED"


class InvalidDateError(Exception):
    code = "INVALID_DATE"


class InvalidDateRangeError(Exception):
    code = "INVALID_DATE_RANGE"


class InvalidJsonError(Exception):
    code = "INVALID_JSON"


class MemberPasswordEnvNotSetError(Exception):
    code = "MEMBER_PASSWORD_ENV_NOT_SET"


class MemberPasswordFileNotFoundError(Exception):
    code = "MEMBER_PASSWORD_FILE_NOT_FOUND"


class PidNotFoundError(Exception):
    code = "PID_NOT_FOUND"


class ProcessNotFoundError(Exception):
    code = "PROCESS_NOT_FOUND"


class ReportError(Exception):
    code = "REPORT_ERROR"


class ReportInvalidStatusError(Exception):
    code = "REPORT_INVALID_STATUS"


class ReportNotFoundError(Exception):
    code = "REPORT_NOT_FOUND"


class ReportValidationError(Exception):
    code = "REPORT_VALIDATION_ERROR"


class RuleNotFoundError(Exception):
    code = "RULE_NOT_FOUND"


class RuleUpdateError(Exception):
    code = "RULE_UPDATE_ERROR"


class SignalKeyNotSetError(Exception):
    code = "SIGNAL_KEY_NOT_SET"


class SnapshotNotFoundError(Exception):
    code = "SNAPSHOT_NOT_FOUND"


class StrategyInvalidStatusTransitionError(Exception):
    code = "STRATEGY_INVALID_STATUS_TRANSITION"


class StrategyMissingRequiredAccountError(Exception):
    code = "STRATEGY_MISSING_REQUIRED_ACCOUNT"


class StrategyValidationFailedError(Exception):
    code = "STRATEGY_VALIDATION_FAILED"


class TradeError(Exception):
    code = "TRADE_ERROR"


class TradeNotFoundError(Exception):
    code = "TRADE_NOT_FOUND"


class TreasuryAllocateFailedError(Exception):
    code = "TREASURY_ALLOCATE_FAILED"


class TreasuryDeallocateFailedError(Exception):
    code = "TREASURY_DEALLOCATE_FAILED"


class UpdateCheckFailedError(Exception):
    code = "UPDATE_CHECK_FAILED"


class UpdateInstallFailedError(Exception):
    code = "UPDATE_INSTALL_FAILED"


class UpdateInsufficientDiskSpaceError(Exception):
    code = "UPDATE_INSUFFICIENT_DISK_SPACE"


class UpdateMigrationFailedError(Exception):
    code = "UPDATE_MIGRATION_FAILED"


class UpdateRollbackFailedError(Exception):
    code = "UPDATE_ROLLBACK_FAILED"


class UpdateServerRunningError(Exception):
    code = "UPDATE_SERVER_RUNNING"


CLI_ERRORS: tuple[type[Exception], ...] = (
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
    DataValidateInvalidSymbolError,
    DataValidateInvalidTimeframeError,
    DatasetNotFoundError,
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
