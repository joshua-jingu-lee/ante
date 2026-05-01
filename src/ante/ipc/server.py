"""IPCServer — Unix 도메인 소켓 기반 IPC 서버.

asyncio.start_unix_server를 사용하여 외부 프로세스(CLI, MCP)의
명령을 수신하고 처리한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
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
        # Refs #1159: stop_accepting()이 self._server를 None으로 비워도
        # drain_connections()이 wait_closed()를 호출할 수 있도록
        # closing reference를 별도 슬롯에 보존한다.
        self._closing_server: asyncio.AbstractServer | None = None

    @property
    def socket_path(self) -> str:
        return self._socket_path

    async def start(self) -> None:
        """서버 시작. 기존 소켓 파일이 있으면 삭제 후 재생성.

        Refs #1159: socket 파일 lifecycle은 ``unlink_socket()``이 단독으로
        책임진다 — cold-path guard가 shutdown 동안 'PID alive AND socket
        exists'로 active runtime을 판정해야 race window를 회피할 수 있기
        때문이다.

        Python 버전별 동작 차이:

        * **Python 3.11 / 3.12**: ``loop.create_unix_server``는 ``server.close()``
          시 socket 파일을 자동으로 unlink하지 **않는다** (해당 동작 자체가
          stdlib에 없다). 따라서 별도 옵션 없이도 본 모듈의 lifecycle 가정이
          성립한다.
        * **Python 3.13+**: ``loop.create_unix_server``에 ``cleanup_socket``
          인자가 추가되었고 **기본값이 ``True``** 이다 — 즉 ``server.close()``
          가 socket 파일을 자동으로 unlink하므로 race window 회귀가 깨진다.
          이를 막기 위해 3.13+에서만 ``cleanup_socket=False``를 명시적으로
          전달한다.

        ``cleanup_socket`` 인자를 무조건 전달하면 3.11/3.12에서
        ``TypeError: create_unix_server() got an unexpected keyword argument
        'cleanup_socket'`` 으로 부팅이 실패한다 (#1159 attempt 1 회귀). 따라서
        ``sys.version_info`` 분기로 3.13+에서만 인자를 추가한다.
        """
        path = Path(self._socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # 잔존 소켓 파일 정리
        if path.exists():
            path.unlink()

        kwargs: dict[str, object] = {"path": self._socket_path}
        if sys.version_info >= (3, 13):
            kwargs["cleanup_socket"] = False

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            **kwargs,
        )

        # 소켓 파일 권한 설정 (소유자만 접근)
        os.chmod(self._socket_path, 0o600)

        logger.info("IPCServer 시작: %s", self._socket_path)

    async def stop_accepting(self) -> None:
        """새 연결 수락 중지. 소켓 파일과 active 연결은 유지.

        ``asyncio.Server.wait_closed``는 detach된 연결까지 모두 기다리므로
        ``_handle_connection``이 ``while True`` 루프인 IPCServer에서는 hang
        위험이 있다 (Refs #1159 Codex Plan v1 [high]). 따라서 본 메서드는
        ``close()``만 호출하고 wait는 별도 ``drain_connections()``이 담당한다.

        cold-path guard(``PID alive AND socket exists``)가 shutdown 동안에도
        'active runtime'으로 판정하도록, 소켓 파일은 ``unlink_socket()``이
        호출되기 전까지 유지된다.
        """
        if self._server:
            # drain_connections에서 wait_closed를 호출할 수 있도록 reference 보존
            self._closing_server = self._server
            self._server.close()
            self._server = None
        logger.info("IPCServer 새 연결 수락 중지: %s", self._socket_path)

    async def drain_connections(self, timeout: float = 5.0) -> None:
        """active 연결을 timeout 안에 drain 시도. TimeoutError 삼키고 진행.

        ``stop_accepting()``이 보존한 ``_closing_server`` reference를 사용해
        ``wait_closed()``를 호출한다. timeout 초과 시 경고 로그를 남기고
        lifecycle은 계속 진행한다 (강제 종료는 asyncio 루프가 처리).
        """
        closing = self._closing_server
        if closing is None:
            return
        try:
            await asyncio.wait_for(closing.wait_closed(), timeout=timeout)
        except TimeoutError:
            logger.warning(
                "IPCServer drain_connections 타임아웃: %s (%.1fs) — 강제 진행",
                self._socket_path,
                timeout,
            )
        finally:
            self._closing_server = None

    def unlink_socket(self) -> None:
        """소켓 파일 제거. lifecycle 마지막 단계에서 호출."""
        path = Path(self._socket_path)
        if path.exists():
            path.unlink()
        logger.info("IPCServer 소켓 파일 제거: %s", self._socket_path)

    async def stop(self) -> None:
        """기존 호출자 호환 facade. listener close → drain → unlink."""
        await self.stop_accepting()
        await self.drain_connections()
        self.unlink_socket()

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
            # 예외 인스턴스/클래스에 ``code`` 속성이 있으면 안정 코드로
            # 노출한다 (#1144 invariant S5). 기존 예외(account.suspend/activate
            # 등)는 ``code`` 속성이 없어 자동으로 ``EXECUTION_ERROR``로
            # 폴백된다 — 회귀 없음.
            error_code = getattr(e, "code", "EXECUTION_ERROR")
            return {
                "id": request_id,
                "status": "error",
                "error": {
                    "code": error_code,
                    "message": str(e),
                },
            }
