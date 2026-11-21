from __future__ import annotations

__all__ = [
    "CliOptionConflictError",
    "ReportError",
    "ReportInvalidStatusError",
    "ReportNotFoundError",
    "ReportValidationError",
    "TradeError",
    "TradeNotFoundError",
]


class CliOptionConflictError(Exception):
    code = "CLI_OPTION_CONFLICT"


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
