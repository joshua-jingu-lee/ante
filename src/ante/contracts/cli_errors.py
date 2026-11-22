from __future__ import annotations

__all__ = [
    "AccountMasterBootstrapFailedError",
    "AccountTestCreateFailedError",
    "AccountTestInactiveError",
    "AlreadyRunningError",
    "ApprovalInvalidStatusError",
    "ApprovalInvalidTypeError",
    "BacktestDataNotFoundError",
    "BacktestError",
    "BacktestInvalidExchangeError",
    "BacktestInvalidSymbolError",
    "BacktestInvalidTimeframeError",
    "BotInvalidParamError",
    "BotMissingRequiredAccountError",
    "CliAlreadyInitializedError",
    "CliBotNotFoundError",
    "CliConfirmationRequiredError",
    "CliMissingRequiredInputError",
    "CliOptionConflictError",
    "ConfigKeyNotFoundError",
    "DataError",
    "DataInvalidDatasetIdError",
    "DataInvalidFilterError",
    "DataValidateInvalidSymbolError",
    "DataValidateInvalidTimeframeError",
    "DatasetNotFoundError",
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
    "PidNotFoundError",
    "ProcessNotFoundError",
    "ReportError",
    "ReportInvalidStatusError",
    "ReportNotFoundError",
    "ReportValidationError",
    "RuleNotFoundError",
    "RuleUpdateError",
    "SignalKeyNotSetError",
    "TradeError",
    "TradeNotFoundError",
    "UpdateCheckFailedError",
    "UpdateInstallFailedError",
    "UpdateInsufficientDiskSpaceError",
    "UpdateMigrationFailedError",
    "UpdateRollbackFailedError",
    "UpdateServerRunningError",
]


class AccountMasterBootstrapFailedError(Exception):
    code = "ACCOUNT_MASTER_BOOTSTRAP_FAILED"


class AccountTestCreateFailedError(Exception):
    code = "ACCOUNT_TEST_CREATE_FAILED"


class AccountTestInactiveError(Exception):
    code = "ACCOUNT_TEST_INACTIVE"


class AlreadyRunningError(Exception):
    code = "ALREADY_RUNNING"


class ApprovalInvalidStatusError(Exception):
    code = "APPROVAL_INVALID_STATUS"


class ApprovalInvalidTypeError(Exception):
    code = "APPROVAL_INVALID_TYPE"


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


class BotInvalidParamError(Exception):
    code = "BOT_INVALID_PARAM"


class BotMissingRequiredAccountError(Exception):
    code = "BOT_MISSING_REQUIRED_ACCOUNT"


class CliAlreadyInitializedError(Exception):
    code = "CLI_ALREADY_INITIALIZED"


class CliBotNotFoundError(Exception):
    code = "BOT_NOT_FOUND"


class CliConfirmationRequiredError(Exception):
    code = "CLI_CONFIRMATION_REQUIRED"


class CliMissingRequiredInputError(Exception):
    code = "CLI_MISSING_REQUIRED_INPUT"


class CliOptionConflictError(Exception):
    code = "CLI_OPTION_CONFLICT"


class ConfigKeyNotFoundError(Exception):
    code = "CONFIG_KEY_NOT_FOUND"


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


class TradeError(Exception):
    code = "TRADE_ERROR"


class TradeNotFoundError(Exception):
    code = "TRADE_NOT_FOUND"


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
    AccountMasterBootstrapFailedError,
    AccountTestCreateFailedError,
    AccountTestInactiveError,
    AlreadyRunningError,
    ApprovalInvalidStatusError,
    ApprovalInvalidTypeError,
    BacktestDataNotFoundError,
    BacktestError,
    BacktestInvalidExchangeError,
    BacktestInvalidSymbolError,
    BacktestInvalidTimeframeError,
    BotInvalidParamError,
    BotMissingRequiredAccountError,
    CliAlreadyInitializedError,
    CliBotNotFoundError,
    CliConfirmationRequiredError,
    CliMissingRequiredInputError,
    CliOptionConflictError,
    ConfigKeyNotFoundError,
    DataError,
    DataInvalidDatasetIdError,
    DataInvalidFilterError,
    DataValidateInvalidSymbolError,
    DataValidateInvalidTimeframeError,
    DatasetNotFoundError,
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
    PidNotFoundError,
    ProcessNotFoundError,
    ReportError,
    ReportInvalidStatusError,
    ReportNotFoundError,
    ReportValidationError,
    RuleNotFoundError,
    RuleUpdateError,
    SignalKeyNotSetError,
    TradeError,
    TradeNotFoundError,
    UpdateCheckFailedError,
    UpdateInstallFailedError,
    UpdateInsufficientDiskSpaceError,
    UpdateMigrationFailedError,
    UpdateRollbackFailedError,
    UpdateServerRunningError,
)
