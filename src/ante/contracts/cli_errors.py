from __future__ import annotations

__all__ = [
    "BacktestDataNotFoundError",
    "BacktestError",
    "BacktestInvalidExchangeError",
    "BacktestInvalidSymbolError",
    "BacktestInvalidTimeframeError",
    "CliConfirmationRequiredError",
    "CliOptionConflictError",
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
    "InstrumentSyncSourceUnsupportedError",
    "InvalidDateError",
    "InvalidDateRangeError",
    "ReportError",
    "ReportInvalidStatusError",
    "ReportNotFoundError",
    "ReportValidationError",
    "TradeError",
    "TradeNotFoundError",
]


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


class CliConfirmationRequiredError(Exception):
    code = "CLI_CONFIRMATION_REQUIRED"


class CliOptionConflictError(Exception):
    code = "CLI_OPTION_CONFLICT"


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


class InstrumentSyncSourceUnsupportedError(Exception):
    code = "INSTRUMENT_SYNC_SOURCE_UNSUPPORTED"


class InvalidDateError(Exception):
    code = "INVALID_DATE"


class InvalidDateRangeError(Exception):
    code = "INVALID_DATE_RANGE"


class ReportError(Exception):
    code = "REPORT_ERROR"


class ReportInvalidStatusError(Exception):
    code = "REPORT_INVALID_STATUS"


class ReportNotFoundError(Exception):
    code = "REPORT_NOT_FOUND"


class ReportValidationError(Exception):
    code = "REPORT_VALIDATION_ERROR"


class TradeError(Exception):
    code = "TRADE_ERROR"


class TradeNotFoundError(Exception):
    code = "TRADE_NOT_FOUND"
