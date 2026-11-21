from __future__ import annotations

import click

__all__ = [
    "IPCClientTimeoutError",
    "IPCRemoteError",
    "IPCServerNotRunningError",
]


class IPCServerNotRunningError(click.ClickException):
    code = "IPC_SERVER_NOT_RUNNING"
    ipc_error_code = code

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.ipc_error_message = message


class IPCClientTimeoutError(click.ClickException):
    code = "IPC_TIMEOUT"
    ipc_error_code = code

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.ipc_error_message = message


class IPCRemoteError(click.ClickException):
    code = "IPC_ERROR"
    ipc_error_code = code

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.ipc_error_code = code
        self.ipc_error_message = message
