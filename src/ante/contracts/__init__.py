"""Contract SSOT 공통 인프라."""

from __future__ import annotations

from ante.contracts.cli_registry import (
    CLI_COMMAND_REGISTRY,
    AuthContract,
    CliCommandContract,
    OutputContract,
    all_contracts,
    get_contract,
)
from ante.contracts.errors import ErrorCategory, ErrorSpec
from ante.contracts.helpers import (
    emit_cli_error,
    error_spec_for_exception,
    ipc_error_payload,
)

__all__ = [
    "CLI_COMMAND_REGISTRY",
    "AuthContract",
    "CliCommandContract",
    "ErrorCategory",
    "ErrorSpec",
    "OutputContract",
    "all_contracts",
    "emit_cli_error",
    "error_spec_for_exception",
    "get_contract",
    "ipc_error_payload",
]
