"""IPCServer — Unix 도메인 소켓 기반 IPC 서버.

asyncio.start_unix_server를 사용하여 외부 프로세스(CLI, MCP)의
명령을 수신하고 처리한다.

Refs #1184: lifecycle state machine을 도입해 shutdown 중 mutating
명령이 SERVICE_UNAVAILABLE로 거부되도록 한다.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import uuid
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ante.ipc import protocol
from ante.ipc.exceptions import MessageTooLargeError

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry

logger = logging.getLogger(__name__)


class IPCServerState(Enum):
    """IPCServer lifecycle state.

    Refs #1184: shutdown 중 mutating 명령을 reject하기 위한 명시적 상태 기계.

    State 전이:

    * ``STOPPED`` → ``RUNNING``: ``start()`` 마지막에 전환.
    * ``RUNNING`` → ``SHUTTING_DOWN``: ``stop_accepting()`` 진입 직후
      (listener close 호출 **전**)에 전환. 이 시점부터 mutating dispatch는
      ``SERVICE_UNAVAILABLE``로 거부된다.
    * ``SHUTTING_DOWN`` → ``DRAINING``: ``stop_dispatching()`` 호출 시 전환.
      이 시점부터는 read-only를 포함한 모든 명령이 거부된다 — broker/db 등
      서비스 리소스 종료 구간에 들어가기 때문이다.
    * ``DRAINING`` → ``STOPPED``: ``unlink_socket()`` 마지막에 전환.

    초기 값은 ``STOPPED`` (start 이전 상태).
    """

    RUNNING = "running"
    SHUTTING_DOWN = "shutting_down"
    DRAINING = "draining"
    STOPPED = "stopped"


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
        # Refs #1184: lifecycle state machine. 초기 상태는 STOPPED.
        self._state: IPCServerState = IPCServerState.STOPPED

    @property
    def socket_path(self) -> str:
        return self._socket_path

    @property
    def state(self) -> IPCServerState:
        """현재 lifecycle state (test/debug용 read-only view)."""
        return self._state

    async def start(self) -> None:
        """서버 시작. 기존 소켓 파일이 있으면 삭제 후 재생성.

        Refs #1159: socket 파일 lifecycle은 ``unlink_socket()``이 단독으로
        책임진다 — cold-path guard가 shutdown 동안 'PID alive AND socket
        exists'로 active runtime을 판정해야 race window를 회피할 수 있기
        때문이다.

        Refs #1184: 메서드 종료 시 state를 ``RUNNING``으로 전환한다.

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

        kwargs: dict[str, Any] = {"path": self._socket_path}
        if sys.version_info >= (3, 13):
            kwargs["cleanup_socket"] = False

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            **kwargs,
        )

        # 소켓 파일 권한 설정 (소유자만 접근)
        os.chmod(self._socket_path, 0o600)

        # Refs #1184: listener 준비 완료 후 RUNNING으로 전환.
        self._state = IPCServerState.RUNNING

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

        Refs #1184: listener close 호출 **전**에 state를 ``SHUTTING_DOWN``으로
        전환한다. 이래야 close 진행 중에 들어오는 dispatch도 mutating이라면
        ``SERVICE_UNAVAILABLE``로 거부된다.
        """
        # Refs #1184: 즉시 SHUTTING_DOWN으로 전환 — close 호출 전에 dispatch
        # gate가 활성화되어야 race window가 닫힌다.
        self._state = IPCServerState.SHUTTING_DOWN

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

    def stop_dispatching(self) -> None:
        """active connection의 추가 dispatch를 모두 거부하도록 전환.

        ``stop_accepting()`` 이후에도 기존 연결은 살아 있을 수 있다.
        ``SHUTTING_DOWN`` 초기 구간에서는 read-only 조회를 허용하지만, broker
        disconnect/DB close 같은 리소스 종료 직전에는 read-only도 closed
        resource를 밟을 수 있으므로 이 메서드로 전 명령 reject 상태에 들어간다.
        """
        self._state = IPCServerState.DRAINING
        logger.info("IPCServer dispatch 거부 시작: %s", self._socket_path)

    def unlink_socket(self) -> None:
        """소켓 파일 제거. lifecycle 마지막 단계에서 호출.

        Refs #1184: 메서드 종료 시 state를 ``STOPPED``으로 전환한다.
        """
        path = Path(self._socket_path)
        if path.exists():
            path.unlink()
        # Refs #1184: 모든 cleanup 종료 후 STOPPED 전환.
        self._state = IPCServerState.STOPPED
        logger.info("IPCServer 소켓 파일 제거: %s", self._socket_path)

    async def stop(self) -> None:
        """기존 호출자 호환 facade. listener close → drain → unlink.

        Refs #1184: 내부 메서드들이 lifecycle state 전환을 담당한다 —
        ``stop_accepting()``이 SHUTTING_DOWN, ``stop_dispatching()``이 DRAINING,
        ``unlink_socket()``이 STOPPED.
        """
        await self.stop_accepting()
        self.stop_dispatching()
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

    @staticmethod
    def _service_unavailable(request_id: str, message: str) -> dict:
        """``SERVICE_UNAVAILABLE`` error 응답 dict 생성.

        Refs #1184: 기존 error 응답 포맷
        ``{"id", "status": "error", "error": {"code", "message"}}``과 동일한
        구조를 사용해 다른 IPC consumer(CLI/MCP/dashboard)가 별도 처리 없이
        기존 generic error path로 흘러가도록 한다.
        """
        return {
            "id": request_id,
            "status": "error",
            "error": {
                "code": "SERVICE_UNAVAILABLE",
                "message": message,
            },
        }

    async def _dispatch(self, request: dict) -> dict:
        """요청을 적절한 핸들러로 라우팅.

        Refs #1184: lifecycle state-aware reject 분기를 추가한다.

        * ``DRAINING``/``STOPPED``: 모든 명령(mutating + read-only)
          ``SERVICE_UNAVAILABLE``. 서비스 리소스 종료 구간 또는 종료 이후이므로
          read-only도 closed resource 접근 위험.
        * ``SHUTTING_DOWN`` + mutating: ``SERVICE_UNAVAILABLE``.
        * ``SHUTTING_DOWN`` + read-only: 통과 (BotManager/DB 살아있음 가정,
          dashboard 가시성 보존).
        * ``RUNNING``: 정상 dispatch.
        """
        request_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")
        args = request.get("args", {})
        actor = request.get("actor", "ipc")

        # Refs #1184: 리소스 drain/종료 단계에서는 모든 명령을 즉시 거부.
        if self._state in {IPCServerState.DRAINING, IPCServerState.STOPPED}:
            message = (
                "서버 리소스 종료 중입니다. IPC 명령을 받지 않습니다."
                if self._state == IPCServerState.DRAINING
                else "서버가 종료되었습니다."
            )
            return self._service_unavailable(request_id, message)

        spec = self._command_registry.get(command)
        if spec is None:
            return {
                "id": request_id,
                "status": "error",
                "error": {
                    "code": "UNKNOWN_COMMAND",
                    "message": f"미등록 커맨드: {command}",
                },
            }

        # Refs #1184: SHUTTING_DOWN 단계에서는 mutating 명령만 거부.
        # read-only는 통과 (BotManager/DB 아직 살아 있음).
        if self._state == IPCServerState.SHUTTING_DOWN and spec.is_mutating:
            return self._service_unavailable(
                request_id,
                "서버가 종료 중입니다. 변경 명령을 받지 않습니다.",
            )

        try:
            result = await spec.handler(self._service_registry, args, actor)
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
