from __future__ import annotations

__all__ = [
    "IPCClientTimeoutError",
    "IPCRemoteError",
    "IPCServerNotRunningError",
]


class IPCServerNotRunningError(Exception):
    code = "IPC_SERVER_NOT_RUNNING"


class IPCClientTimeoutError(Exception):
    code = "IPC_TIMEOUT"


class IPCRemoteError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

    def __str__(self) -> str:
        return self.message or f"{self.code}: "
