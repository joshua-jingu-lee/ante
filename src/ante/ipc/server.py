"""IPCServer — Unix 도메인 소켓 기반 IPC 서버.

asyncio.start_unix_server를 사용하여 외부 프로세스(CLI, MCP)의
명령을 수신하고 처리한다.

Refs #1184: lifecycle state machine을 도입해 shutdown 중 mutating
명령이 SERVICE_UNAVAILABLE로 거부되도록 한다.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import struct
import uuid
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from ante.ipc import protocol
from ante.ipc.exceptions import MessageTooLargeError

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry

logger = logging.getLogger(__name__)

# Refs #2334 §14 (#2337): signal.connect outbound out_queue 의 bounded 상한.
# 초과(laggard)면 disconnect-laggard 로 ``{closed,reason:lagged}`` 후 종료한다.
# config 화는 §14 follow-up(본 PR 은 상수, known-limitation).
SIGNAL_OUT_QUEUE_MAX = 512
# Refs #2337 F2: daemon-initiated close 가 in-flight on_data publish 를 grace
# 동안 await 한 뒤 read_task 를 cancel 한다(at-most-one trailing). 초과분은
# 백그라운드 publish 계속 + read_task cancel(§14 tunable, known-limitation).
SIGNAL_INFLIGHT_GRACE = 2.0
# Refs #2337: signal.connect 핸드셰이크의 expected typed-validation 거부 코드.
# ``_dispatch`` 가 이 집합의 코드는 traceback 없는 구조화 WARNING 으로 로깅해
# 키/args 노출과 가짜 ERROR traceback 을 회피한다(그 외는 logger.exception).
_EXPECTED_DISPATCH_REJECT_CODES = frozenset(
    {
        "INVALID_SIGNAL_KEY",
        "BOT_NOT_RUNNING",
        "BOT_NOT_ACCEPTING_SIGNALS",
        "BOT_SIGNAL_CHANNEL_BUSY",
        "MALFORMED_REQUEST",
    }
)


def _encode_signal_frame(frame: dict) -> bytes:
    """signal.connect outbound 프레임을 length-prefixed 바이트로 직렬화 (#2337).

    ``protocol.encode`` 와 동일한 ``[4바이트 빅엔디안 길이][JSON]`` framing 이되,
    legacy ``SignalChannel._write`` 와 byte-identical 한 페이로드를 위해
    ``json.dumps(..., default=str)`` 를 쓴다(``timestamp`` 등 datetime 을 ISO
    문자열로 — legacy stdout 경로의 ``default=str`` 와 정합, INV-OUT-1). 1MB
    초과는 ``MessageTooLargeError`` (outbound non-fatal 처리 대상).
    """
    payload = json.dumps(frame, default=str, ensure_ascii=False).encode("utf-8")
    if len(payload) > protocol.MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(
            f"메시지 크기({len(payload)} bytes)가 "
            f"최대 제한({protocol.MAX_MESSAGE_SIZE} bytes)을 초과"
        )
    return struct.pack("!I", len(payload)) + payload


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

        Refs #1185, #1187: Ante는 Python 3.13 단일 런타임을 공식 계약으로 한다.
        Python 3.13의 ``asyncio.start_unix_server``는 ``cleanup_socket`` 인자를
        받으며 기본값이 ``True``이다. 본 메서드는 ``cleanup_socket=False``를
        명시적으로 전달해 ``server.close()`` 시 socket 파일이 자동 unlink되지
        않게 만든다 — 이로써 cold-path guard(``PID alive AND socket exists``)가
        shutdown 동안에도 'active runtime'을 정확히 판정할 수 있는 race window
        차단 의도가 유지된다 (Refs #1159).
        """
        path = Path(self._socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Refs #2334 §보안 (#2337): runtime dir 0o700(소유자만 접근). umask
        # 독립적으로 기존 dir 에도 재적용한다 — server.start 가 단독 0o700
        # 소유자다(main.py 의 mkdir 은 chmod 하지 않음). socket 0o600 과 함께
        # 외부 프로세스의 signal.connect UDS 접근면을 닫는다.
        os.chmod(path.parent, 0o700)

        # 잔존 소켓 파일 정리
        if path.exists():
            path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
            cleanup_socket=False,
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

                # Refs #2334 (#2336 PR#1): 첫 프레임이 JSON object 가 아니면
                # (list/scalar 등) MALFORMED_REQUEST 1프레임 후 close. 비-dict 는
                # usable id 가 없어 id=None (MESSAGE_TOO_LARGE 블록 미러).
                if not isinstance(request, dict):
                    response = self._malformed_request("요청은 JSON object여야 합니다")
                    data = await protocol.encode(response)
                    writer.write(data)
                    await writer.drain()
                    break

                response = await self._dispatch(request)

                # Refs #2334 (#2336 PR#1): signal.connect 핸드셰이크 OK 응답이면
                # 동일 연결을 long-lived 스트림으로 connection-upgrade 한다.
                # 센티넬은 ``response["result"]["_stream"]`` (중첩) — 최상위로
                # 읽으면 silent fall-through 로 센티넬이 누출된다.
                result = response.get("result")
                if (
                    response.get("status") == "ok"
                    and isinstance(result, dict)
                    and result.get("_stream") == "signal.connect"
                ):
                    # wire 전송 직전 센티넬 strip (절대 노출 안 됨).
                    result.pop("_stream", None)
                    session_id = result["session_id"]
                    bot_id = result["bot_id"]
                    # #2337 F1+F4 (3): ack write/drain 실패 시 register 누수 차단.
                    # register 는 핸드셰이크 핸들러(ack 전 happen-before)에서 이미
                    # 성공했으나, ack write 실패 시 ``_run_signal_stream`` 미진입
                    # → finally 부재 → handle 누수. 여기서 unregister(missing-key
                    # no-op 라 stream finally 와 멱등)로 차단한 뒤 re-raise 해
                    # ``_handle_connection`` finally 가 writer teardown 을 소유한다.
                    reg = getattr(
                        self._service_registry, "signal_channel_registry", None
                    )
                    try:
                        ack = await protocol.encode(response)
                        writer.write(ack)
                        await writer.drain()
                    except Exception:
                        if reg is not None:
                            reg.unregister(bot_id, session_id)
                        raise
                    await self._run_signal_stream(reader, writer, bot_id, session_id)
                    # break 아님 — hijack 연결은 lockstep 재진입 금지. finally 가
                    # teardown(writer close) 를 단일 소유한다.
                    return

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
        구조를 사용해 다른 IPC consumer(CLI/MCP)가 별도 처리 없이
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

    @staticmethod
    def _malformed_request(message: str) -> dict:
        """``MALFORMED_REQUEST`` error 응답 dict 생성.

        Refs #2334 (#2336 PR#1): 첫 프레임이 JSON object 가 아닐 때 사용한다.
        비-dict 입력은 usable ``id`` 가 없어 ``id=None`` 으로 고정한다
        (``MESSAGE_TOO_LARGE`` 블록 동형). taxonomy SSOT
        (``docs/specs/contracts/error-taxonomy.md``) 의 ``validation`` 카테고리
        안정 코드. ``_service_unavailable`` 와 동일 envelope shape 으로 다른 IPC
        consumer(CLI/MCP)가 기존 generic error path 로 흘러가게 한다.
        """
        return {
            "id": None,
            "status": "error",
            "error": {
                "code": "MALFORMED_REQUEST",
                "message": message,
            },
        }

    @staticmethod
    def _service_not_configured(request_id: str, service_name: str) -> dict:
        """``SERVICE_NOT_CONFIGURED`` error 응답 dict 생성.

        Refs #1850 / #1816: dispatch wrapper의 ``required_services`` preflight 가
        ``ServiceRegistry`` 에 의존 service 가 부재한 경우 사용한다. taxonomy
        SSOT(``docs/specs/contracts/error-taxonomy.md``) 의 ``service_unavailable``
        category 안정 코드. ``SERVICE_UNAVAILABLE``(lifecycle 상태) 와는 의미가
        분리된다 — 본 코드는 영구적 misconfiguration 을 가리킨다.
        """
        return {
            "id": request_id,
            "status": "error",
            "error": {
                "code": "SERVICE_NOT_CONFIGURED",
                "message": (f"의존 서비스가 구성되지 않았습니다: {service_name}"),
            },
        }

    def _missing_required_service(self, spec_required: frozenset[str]) -> str | None:
        """``required_services`` preflight — 부재한 첫 service 이름 반환.

        Refs #1850: ``CommandSpec.required_services`` 의 각 attribute 이름을
        ``ServiceRegistry`` 에서 ``getattr(..., None)`` 으로 조회한다.
        ``ServiceRegistry`` 는 dataclass 이고 optional service(예: ``audit_logger``,
        ``member_service``, ``trade_service``, ``strategy_registry``)는 default
        ``None`` 을 가지므로 ``None`` 도 부재로 판정한다. 모두 존재하면 ``None``
        반환. 부재 발생 시 등록 순서가 frozenset 이라 비결정적이므로 단일 결정
        결과(첫 발견)만 사용한다.
        """
        for service_name in spec_required:
            if getattr(self._service_registry, service_name, None) is None:
                return service_name
        return None

    async def _dispatch(self, request: dict) -> dict:
        """요청을 적절한 핸들러로 라우팅.

        Refs #1184: lifecycle state-aware reject 분기를 추가한다.

        * ``DRAINING``/``STOPPED``: 모든 명령(mutating + read-only)
          ``SERVICE_UNAVAILABLE``. 서비스 리소스 종료 구간 또는 종료 이후이므로
          read-only도 closed resource 접근 위험.
        * ``SHUTTING_DOWN`` + mutating: ``SERVICE_UNAVAILABLE``.
        * ``SHUTTING_DOWN`` + read-only: 통과 (BotManager/DB 살아있음 가정).
        * ``RUNNING``: 정상 dispatch.

        Refs #1850 (#1819 부모 epic): lifecycle gate 통과 후 handler 호출 전에
        ``CommandSpec`` metadata 기반 preflight 두 단계를 수행한다.

        1. ``required_services`` 부재 시 ``SERVICE_NOT_CONFIGURED`` envelope
           으로 거부한다 — handler 가 ``svc.<name>`` 접근에서 ``None`` /
           ``AttributeError`` 로 폭주하기 전에 차단한다.
        2. ``account_id_policy`` 검증 — try 블록 내부에서
           ``require_account_id`` 를 호출해 ``InvalidAccountIdError``
           (``code="VALIDATION_ERROR"``) 를 raise 시키고, 기존 except 가
           ``getattr(e, "code", ...)`` 로 ``VALIDATION_ERROR`` envelope 으로
           변환하게 한다(handler 본문의 기존 ``require_account_id`` 호출과
           1:1 동형 매핑).

        lifecycle gate 가 preflight 보다 항상 먼저 — DRAINING/STOPPED 또는
        SHUTTING_DOWN+mutating 인 경우 preflight 에 도달하지 않는다(Codex v2
        condition 3).

        Refs #1851 (#1819 부모 epic): handler 가 정상 종료된 후
        ``CommandSpec.audit_action`` 이 ``None`` 이 아니면 ``audit_logger`` 를
        통해 자동으로 audit 로그를 1회 남긴다. handler 는 반환 dict 안의
        ``_audit_detail`` reserved key 로 ``{resource, detail, ip}`` 를 wrapper
        에 전달할 수 있으며, public envelope 으로 새 나가지 않도록 wrapper 가
        ``pop`` 으로 strip 한 뒤 envelope ``result`` 에 담는다. handler 가
        예외로 종료되면 audit 호출은 일어나지 않는다(실패 시 audit invariant).
        ``audit_action`` 이 부여된 commands(현재 10개 — #1852 / #1853 포함)는
        ``required_services`` 에 ``audit_logger`` 가 명시되어 있어 preflight
        단계에서 부재가 차단된다 (#1849 등록 시 동형 lock).
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

        # Refs #1850: required_services preflight — handler 호출 전에 검증.
        # ServiceRegistry 는 dataclass 이며 optional service 는 default=None
        # 이므로 ``getattr(..., None) is None`` 이면 부재로 판정한다.
        missing = self._missing_required_service(spec.required_services)
        if missing is not None:
            return self._service_not_configured(request_id, missing)

        try:
            # Refs #1850: account_id_policy preflight — try 블록 내부에서
            # ``require_account_id`` 를 호출해 ``InvalidAccountIdError``
            # (``code="VALIDATION_ERROR"``) 가 아래 except 에서
            # ``VALIDATION_ERROR`` envelope 으로 자동 변환되도록 한다.
            # ``required``: account_id 가 반드시 존재해야 하므로 ``args.get``
            # 결과(부재 시 ``None``) 를 그대로 require_account_id 에 넘긴다.
            # ``optional_filter``: filter 인자로 사용되며 부재면 skip, 존재
            # 하면 검증한다. ``none``: skip. handler 본문의 기존
            # ``require_account_id`` 호출은 본 PR scope 외 — valid 값에서는
            # 멱등하므로 중복 호출이어도 안전(#1852 후속에서 제거 가능).
            if spec.account_id_policy == "required":
                from ante.account.scoping import require_account_id

                require_account_id(args.get("account_id"), context=f"ipc.{command}")
            elif spec.account_id_policy == "optional_filter":
                account_id_arg = args.get("account_id")
                if account_id_arg is not None:
                    from ante.account.scoping import require_account_id

                    require_account_id(account_id_arg, context=f"ipc.{command}")

            result = await spec.handler(self._service_registry, args, actor)
            # Refs #1851: handler 정상 종료 후 audit_action 자동 발화.
            # ``_audit_detail`` reserved key 는 ``pop`` 으로 envelope 노출
            # 전에 strip 된다 (public payload 누출 invariant).
            # ``audit_action`` 부여 commands(현재 10개 — #1852 / #1853 포함)는
            # ``required_services`` 에 ``audit_logger`` 가 포함되어 있어
            # preflight 단계에서 부재가 이미 차단됨 — 여기서는 ``getattr``
            # safe-access 로 한 번 더 방어한다 (handler 가 dict 가 아닌 다른
            # shape 을 반환하는 경우에도 strip 시도가 실패하지 않도록
            # isinstance 가드).
            audit_detail: dict | None = None
            if isinstance(result, dict):
                audit_detail = result.pop("_audit_detail", None)
            if spec.audit_action is not None:
                audit_logger = getattr(self._service_registry, "audit_logger", None)
                if audit_logger is not None:
                    if audit_detail is None:
                        audit_detail = {}
                    # Refs #2113: auth-exempt member 명령(reset_password /
                    # regenerate_recovery_key)은 client 가 actor 를 임의로 보낼
                    # 수 있으므로(스푸핑 가능) audit member_id 를 client actor 가
                    # 아니라 handler 가 ``_audit_detail["member_id"]`` 로 고정한
                    # sentinel 상수로 기록해야 한다. handler 가 member_id 를
                    # 명시하지 않으면 기존 동작(``actor`` 사용)을 그대로 유지한다
                    # (순수 additive override — 기존 audit_action 명령 회귀 없음).
                    audit_member_id = audit_detail.get("member_id") or actor
                    await audit_logger.log(
                        member_id=audit_member_id,
                        action=spec.audit_action,
                        resource=audit_detail.get("resource") or "",
                        detail=audit_detail.get("detail") or "",
                        ip=audit_detail.get("ip") or "",
                    )
            return {
                "id": request_id,
                "status": "ok",
                "result": result,
            }
        except Exception as e:
            # 예외 인스턴스/클래스에 ``code`` 속성이 있으면 안정 코드로
            # 노출한다 (#1144 invariant S5). 기존 예외(account.suspend/activate
            # 등)는 ``code`` 속성이 없어 자동으로 ``EXECUTION_ERROR``로
            # 폴백된다 — 회귀 없음. Refs #1850: ``InvalidAccountIdError``
            # (``code="VALIDATION_ERROR"``) 도 본 경로로 envelope 변환된다.
            error_code = getattr(e, "code", "EXECUTION_ERROR")
            # Refs #2337: signal.connect 핸드셰이크의 expected typed-validation
            # 거부는 traceback/args 를 노출하지 않는 구조화 WARNING 으로 로깅한다
            # (invalid-key caplog 에 ``sk_`` 부재, expected-exc ERROR traceback
            # 부재). 그 외(internal/unexpected)는 기존 ``logger.exception`` 유지.
            if error_code in _EXPECTED_DISPATCH_REJECT_CODES:
                logger.warning("IPC handshake rejected: %s (%s)", command, error_code)
            else:
                logger.exception("IPC 커맨드 실행 오류: %s", command)
            return {
                "id": request_id,
                "status": "error",
                "error": {
                    "code": error_code,
                    "message": str(e),
                },
            }

    async def _run_signal_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        bot_id: str,
        session_id: str,
    ) -> None:
        """signal.connect Phase-C 스트림 host (#2334 §6/§7, #2337 PR#2).

        핸드셰이크 OK 후 동일 연결을 hijack 해 long-lived 양방향 스트림으로
        운반한다. host 구성:

        - **bounded out_queue + 단일 writer_task**: ``asyncio.Queue(maxsize=
          SIGNAL_OUT_QUEUE_MAX)`` + write_lock 으로 ack(inbound)·fill(eventbus)
          프레임 순서를 보존한다(INV-OUT-3). writer 는 FIFO drain →
          ``protocol.encode`` → write+drain.
        - **read_task**: ``protocol.decode`` → ``channel._handle_message``. per-read
          timeout 없음(idle 정상). inbound >1MB 는 **terminal close**(decode 가
          body read 전 raise → framing desync, continue 금지, INV-OUT-7).
        - **adopt + self-close re-check (F1+F4)**: register 된 placeholder handle
          을 회수해 데이터플레인을 채운다. adopt 시점에 ``handle.closed`` 또는
          generation 불일치(rotate-in-window)면 read/writer 풀 루프 미진입 →
          single closed frame flush 후 self-close.
        - **closing supervisor (F2)**: ``handle.close()``(동기, daemon-initiated)
          가 set 한 ``closing_event`` 를 감지하면 ``_initiate_close`` async 순서를
          실행(await-inflight grace → read_task cancel → writer join).
        - **finally(INV-OUT-9)**: ``mark_closed`` → ``_unsubscribe_events`` →
          ``reg.unregister`` 정확히 1회(register 성공 후 모든 경로). writer 는
          **절대 직접 close 안 함** — ``_handle_connection`` finally 단독 소유.

        Phase-C read 에는 per-read timeout 을 **절대** 적용하지 않는다 — idle
        스트림은 정상이며 liveness 는 app-level ``{ping→pong}`` 로 확인한다.

        headless(reg=None): adopt/self-close/unregister 를 스킵하고 channel
        데이터플레인만 구동한다.
        """
        from ante.bot.signal_channel import SignalChannel

        reg = getattr(self._service_registry, "signal_channel_registry", None)
        svc = self._service_registry
        bot = svc.bot_manager.get_bot(bot_id)
        if bot is None:
            # 핸드셰이크와 stream 진입 사이에 봇이 사라진 극단 race — register
            # 누수만 정리하고 종료(writer 는 _handle_connection finally 소유).
            if reg is not None:
                reg.unregister(bot_id, session_id)
            return

        out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=SIGNAL_OUT_QUEUE_MAX)
        write_lock = asyncio.Lock()
        flush_done = asyncio.Event()
        # daemon-initiated close ↔ async teardown 브릿지(F2). handle.close(sync)
        # 와 laggard 가 이 event 를 set 하고, supervisor 가 _initiate_close 를
        # 실행한다. headless(reg=None)에서도 laggard teardown 이 동작하도록 항상
        # 생성한다.
        closing_event = asyncio.Event()

        def _force_closed_frame(reason: str) -> None:
            """``{closed,reason}`` force-slot enqueue(QueueFull→1 drop 후 재시도)."""
            frame = {"type": "closed", "reason": reason}
            try:
                out_queue.put_nowait(frame)
            except asyncio.QueueFull:
                try:
                    out_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                with contextlib.suppress(asyncio.QueueFull):
                    out_queue.put_nowait(frame)

        def _trigger_lagged() -> None:
            """disconnect-laggard teardown (INV-OUT-6). idempotent.

            out_queue full 로 프레임 drop 시 1회 호출. channel ``_closed`` flip
            (이후 _on_fill/_on_order_update no-op) + ``{error,stream_lagged}``
            best-effort(QueueFull drop 허용) + ``{closed,lagged}`` force-slot +
            closing_event set 으로 supervisor 의 daemon_close teardown 진입.
            socket I/O await 없음(bus 핸들러 inline 안전).
            """
            if closing_event.is_set():
                return
            channel.mark_closed()
            with contextlib.suppress(asyncio.QueueFull):
                out_queue.put_nowait({"type": "error", "message": "stream_lagged"})
            _force_closed_frame("lagged")
            closing_event.set()

        def _enqueue(frame: dict) -> None:
            """sink 콜백 — newline-free dict 를 out_queue 에 put_nowait.

            laggard-aware: QueueFull 이면 채널 laggard teardown 을 트리거한다
            (raw put_nowait 금지 — INV-OUT-6 backpressure swallow 우회 명시체크).
            """
            try:
                out_queue.put_nowait(frame)
            except asyncio.QueueFull:
                _trigger_lagged()

        channel = SignalChannel(
            bot,
            svc.eventbus,
            bot._ctx,
            sink=_enqueue,
            is_full=out_queue.full,
            on_lagged=_trigger_lagged,
        )
        channel._subscribe_events()

        # adopt (F1+F4 step 4) — placeholder handle 데이터플레인 채우기. handle.
        # closing_event 를 stream-local event 와 동일 객체로 바인딩해 sync
        # handle.close()가 supervisor 를 깨우게 한다.
        handle = reg.get(bot_id, session_id) if reg is not None else None
        if handle is not None:
            handle.out_queue = out_queue
            handle.on_closed = channel.mark_closed
            handle.closing_event = closing_event

        # F4 self-close 재확인: adopt 직후 이미 닫혔거나(register 후 ack 전
        # close_bot/rotate) generation 불일치(rotate-in-window)면 풀 루프 미진입.
        # handle is not None ⇒ reg is not None(handle 은 reg.get 유래)이나 명시
        # 가드로 mypy union-attr 을 좁힌다.
        if reg is not None and handle is not None:
            rotated = reg.current_generation(bot_id) != handle.generation
            if handle.closed or rotated:
                if rotated and not handle.closed:
                    handle.close("rotated")
                reason = (
                    handle._pending_close_reason or handle.close_reason or "rotated"
                )
                await self._self_close_signal_stream(
                    channel, writer, reason, reg, bot_id, session_id
                )
                return

        try:
            await self._drive_signal_stream(
                reader,
                writer,
                channel,
                out_queue,
                write_lock,
                flush_done,
                closing_event,
                handle,
            )
        finally:
            # INV-OUT-9: 모든 종료 경로 정확히 1회.
            channel.mark_closed()
            channel._unsubscribe_events()
            if reg is not None:
                reg.unregister(bot_id, session_id)

    async def _self_close_signal_stream(
        self,
        channel: object,
        writer: asyncio.StreamWriter,
        reason: str,
        reg: object,
        bot_id: str,
        session_id: str,
    ) -> None:
        """adopt-time self-close (F4) — single closed frame flush 후 정리.

        read/writer 풀 루프를 띄우지 않고 ``{type:closed,reason}`` 1프레임만
        wire 로 내보낸 뒤 ``mark_closed`` → ``_unsubscribe_events`` →
        ``unregister`` 한다(INV-OUT-9 정확히 1회). writer 는 직접 close 안 함.
        """
        try:
            try:
                frame = _encode_signal_frame({"type": "closed", "reason": reason})
                writer.write(frame)
                await writer.drain()
            except (BrokenPipeError, OSError, MessageTooLargeError):
                pass
        finally:
            channel.mark_closed()  # type: ignore[attr-defined]
            channel._unsubscribe_events()  # type: ignore[attr-defined]
            if reg is not None:
                reg.unregister(bot_id, session_id)  # type: ignore[attr-defined]

    async def _drive_signal_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        channel: object,
        out_queue: asyncio.Queue[dict],
        write_lock: asyncio.Lock,
        flush_done: asyncio.Event,
        closing_event: asyncio.Event,
        handle: object,
    ) -> None:
        """read_task + writer_task + closing supervisor 를 구동·정리한다.

        writer 는 FIFO drain → encode → write. ``frame.type=='closed'`` 면 write
        후 ``flush_done.set()`` + return(INV-OUT-8 flush-before-cancel).
        outbound >1MB 는 ``{type:error,result_too_large}`` non-fatal continue
        (INV-OUT-7). read_task 는 EOF/inbound-1MB 에 return. closing supervisor 는
        ``handle.closing_event`` 또는 read/writer 완료를 감지해 ``_initiate_close``
        async teardown 을 실행한다(F2 sync close ↔ async teardown 브릿지).
        """

        async def _writer_loop() -> None:
            while True:
                frame = await out_queue.get()
                try:
                    data = _encode_signal_frame(frame)
                except MessageTooLargeError:
                    # outbound >1MB 비치명: result_too_large 후 stream 유지.
                    try:
                        data = _encode_signal_frame(
                            {"type": "error", "message": "result_too_large"}
                        )
                    except MessageTooLargeError:
                        continue
                    async with write_lock:
                        writer.write(data)
                        await writer.drain()
                    continue
                async with write_lock:
                    writer.write(data)
                    await writer.drain()
                if frame.get("type") == "closed":
                    # teardown frame write 완료 → grace supervisor 깨우고 종료.
                    flush_done.set()
                    return

        async def _reader_loop() -> None:
            while True:
                try:
                    msg = await protocol.decode(reader)
                except asyncio.IncompleteReadError:
                    return  # EOF — graceful 종료.
                except MessageTooLargeError:
                    return  # inbound >1MB — terminal close(framing desync 회피).
                await channel._handle_message(msg)  # type: ignore[attr-defined]

        read_task = asyncio.ensure_future(_reader_loop())
        writer_task = asyncio.ensure_future(_writer_loop())
        if handle is not None:
            handle.read_task = read_task  # type: ignore[attr-defined]
            handle.writer_task = writer_task  # type: ignore[attr-defined]

        closing_waiter = asyncio.ensure_future(closing_event.wait())
        try:
            # read/writer 중 하나라도 종료하거나, daemon-initiated close(또는
            # laggard)가 closing_event 를 set 하면 teardown 으로 진입한다.
            await asyncio.wait(
                [read_task, writer_task, closing_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )

            # daemon-initiated close 여부: closing_event 가 set 됐으면(rotate/
            # close_bot/shutdown/laggard — closed frame force-slot 됨) flush-
            # before-cancel grace 순서, 아니면 자연 종료(EOF/writer-exit)라 즉시
            # sibling cancel.
            daemon_close = closing_event.is_set()
            await self._initiate_close(
                channel,
                read_task,
                writer_task,
                flush_done,
                daemon_close=daemon_close,
            )
        finally:
            if not closing_waiter.done():
                closing_waiter.cancel()
            # 남은 task 강제 정리(중복 cancel/await 는 멱등).
            for task in (read_task, writer_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(
                read_task,
                writer_task,
                closing_waiter,
                return_exceptions=True,
            )

    async def _initiate_close(
        self,
        channel: object,
        read_task: asyncio.Task,
        writer_task: asyncio.Task,
        flush_done: asyncio.Event,
        *,
        daemon_close: bool,
    ) -> None:
        """teardown async 순서 (F2, INV-OUT-8).

        ``daemon_close=True`` (rotate/close_bot/shutdown — ``handle.close`` 가
        ``closing_event`` set + closed frame force-slot):

        1. channel ``_accepting``/``_closed`` set(sync close 가 이미 했을 수
           있으나 멱등) — NEW admit 거부 + ``_on_fill`` no-op.
        2. in-flight on_data publish 를 grace 동안 await(``asyncio.shield`` 로
           grace 타임아웃이 publish 자체를 중단시키지 않게 방어). 초과면 publish
           는 백그라운드 계속, read_task 만 cancel(at-most-one trailing).
        3. read_task cancel.
        4. writer 가 closed frame 을 flush(``flush_done``)할 때까지 grace 대기 후
           writer join(flush-before-cancel). 미flush 면 grace 후 cancel.

        ``daemon_close=False`` (자연 종료 — EOF/writer-exit/laggard): flush 할
        teardown frame 이 없으므로 in-flight 만 grace await 후 sibling 을 즉시
        cancel(불필요한 grace 대기 회피).
        """
        channel.mark_closed()  # type: ignore[attr-defined]

        inflight = getattr(channel, "_inflight", None)
        if inflight is not None and not inflight.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(inflight), timeout=SIGNAL_INFLIGHT_GRACE
                )
            except (TimeoutError, Exception):  # noqa: BLE001
                # grace 초과/publish 예외 — publish 는 백그라운드 계속, 진행.
                pass

        if not read_task.done():
            read_task.cancel()

        if daemon_close and not writer_task.done():
            # closed frame flush-before-cancel(INV-OUT-8). flush_done 은 writer 가
            # closed frame 을 write 한 직후 set 된다 — grace 안에 set 되면 join,
            # 아니면(극단 stall) cancel.
            if flush_done.is_set():
                with contextlib.suppress(Exception):
                    await writer_task
            else:
                try:
                    await asyncio.wait_for(
                        asyncio.shield(flush_done.wait()),
                        timeout=SIGNAL_INFLIGHT_GRACE,
                    )
                    with contextlib.suppress(Exception):
                        await writer_task
                except TimeoutError:
                    writer_task.cancel()
        elif not writer_task.done():
            # 자연 종료 — flush 할 frame 없음. 즉시 cancel.
            writer_task.cancel()

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await read_task
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await writer_task
