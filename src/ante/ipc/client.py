"""IPCClient — Unix 도메인 소켓 IPC 클라이언트.

실행 중인 Ante 서버에 명령을 전송하고 응답을 받는다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from pathlib import Path

from ante.ipc import protocol
from ante.ipc.exceptions import IPCTimeoutError, ServerNotRunningError

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0  # seconds


class IPCClient:
    """Unix 도메인 소켓 IPC 클라이언트."""

    def __init__(
        self,
        socket_path: str,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._socket_path = socket_path
        self._timeout = timeout

    async def send(
        self,
        command: str,
        args: dict | None = None,
        actor: str = "cli",
    ) -> dict:
        """커맨드를 서버에 전송하고 응답을 반환.

        Args:
            command: 실행할 커맨드 이름 (예: "system.halt")
            args: 커맨드 인자
            actor: 요청자 식별자

        Returns:
            서버 응답 dict

        Raises:
            ServerNotRunningError: 소켓 파일이 없거나 연결 거부
            IPCTimeoutError: 타임아웃 초과
        """
        path = Path(self._socket_path)
        if not path.exists():
            raise ServerNotRunningError(
                f"Ante 서버가 실행 중이지 않습니다 (소켓 없음: {self._socket_path})"
            )

        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_unix_connection(self._socket_path),
                timeout=self._timeout,
            )
        except (ConnectionRefusedError, OSError) as e:
            raise ServerNotRunningError(f"Ante 서버에 연결할 수 없습니다: {e}") from e
        except TimeoutError as e:
            raise IPCTimeoutError(f"서버 연결 타임아웃 ({self._timeout}초)") from e

        try:
            request = {
                "id": str(uuid.uuid4()),
                "command": command,
                "args": args or {},
                "actor": actor,
            }

            data = await protocol.encode(request)
            writer.write(data)
            await writer.drain()

            response = await asyncio.wait_for(
                protocol.decode(reader),
                timeout=self._timeout,
            )

            return response
        except TimeoutError as e:
            raise IPCTimeoutError(f"서버 응답 타임아웃 ({self._timeout}초)") from e
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass
