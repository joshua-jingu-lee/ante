"""IPC (Inter-Process Communication) 인프라.

Unix 도메인 소켓 기반의 프로세스 간 통신을 제공한다.
CLI, MCP 등 외부 프로세스가 실행 중인 Ante 서버에 명령을 보낼 때 사용한다.
"""

from ante.ipc.client import IPCClient
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError
from ante.ipc.server import IPCServer

__all__ = [
    "IPCClient",
    "IPCServer",
    "IPCTimeoutError",
    "ServerNotRunningError",
]
