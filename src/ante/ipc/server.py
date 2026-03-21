"""IPCServer — Unix 도메인 소켓 기반 IPC 서버.

asyncio.start_unix_server를 사용하여 외부 프로세스(CLI, MCP)의
명령을 수신하고 처리한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid
from pathlib import Path
from typing import TYPE_CHECKING

from ante.ipc import protocol
from ante.ipc.exceptions import MessageTooLargeError

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry

logger = logging.getLogger(__name__)


class IPCServer:
    """Unix 도메인 소켓 IPC 서버."""

    def __init__(
        self,
        socket_path: str,
        service_registry: ServiceRegistry,
        command_registry: CommandRegistry,
    ) -> None:
        self._socket_path = socket_path
        self._service_registry = service_registry
        self._command_registry = command_registry
        self._server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        """서버 시작. 기존 소켓 파일이 있으면 삭제 후 재생성."""
        path = Path(self._socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 잔존 소켓 파일 정리
        if path.exists():
            path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
        )

        # 소켓 파일 권한 설정 (소유자만 접근)
        os.chmod(self._socket_path, 0o600)

        logger.info("IPCServer 시작: %s", self._socket_path)

    async def stop(self) -> None:
        """서버 종료 및 소켓 파일 삭제."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

        path = Path(self._socket_path)
        if path.exists():
            path.unlink()

        logger.info("IPCServer 종료: %s", self._socket_path)

    async def _handle_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        """클라이언트 연결 처리. 요청을 읽고 응답을 보낸다."""
        try:
            while True:
                try:
                    request = await protocol.decode(reader)
                except asyncio.IncompleteReadError:
                    # 클라이언트 연결 종료
                    break
                except MessageTooLargeError as e:
                    response = {
                        "id": None,
                        "status": "error",
                        "error": {
                            "code": "MESSAGE_TOO_LARGE",
                            "message": str(e),
                        },
                    }
                    data = await protocol.encode(response)
                    writer.write(data)
                    await writer.drain()
                    break

                response = await self._dispatch(request)
                data = await protocol.encode(response)
                writer.write(data)
                await writer.drain()
        except Exception:
            logger.exception("IPC 연결 처리 중 오류")
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    async def _dispatch(self, request: dict) -> dict:
        """요청을 적절한 핸들러로 라우팅."""
        request_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")
        args = request.get("args", {})
        actor = request.get("actor", "ipc")

        handler = self._command_registry.get(command)
        if handler is None:
            return {
                "id": request_id,
                "status": "error",
                "error": {
                    "code": "UNKNOWN_COMMAND",
                    "message": f"미등록 커맨드: {command}",
                },
            }

        try:
            result = await handler(self._service_registry, args, actor)
            return {
                "id": request_id,
                "status": "ok",
                "result": result,
            }
        except Exception as e:
            logger.exception("IPC 커맨드 실행 오류: %s", command)
            return {
                "id": request_id,
                "status": "error",
                "error": {
                    "code": "EXECUTION_ERROR",
                    "message": str(e),
                },
            }
