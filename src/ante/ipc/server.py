"""IPCServer — Unix 도메인 소켓 기반 IPC 서버."""

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

from ante.contracts.helpers import ipc_error_payload
from ante.ipc import protocol
from ante.ipc.exceptions import MessageTooLargeError

if TYPE_CHECKING:
    from ante.core.registry import ServiceRegistry
    from ante.ipc.registry import CommandRegistry

logger = logging.getLogger(__name__)

SIGNAL_OUT_QUEUE_MAX = 512
SIGNAL_INFLIGHT_GRACE = 2.0
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
    """signal.connect outbound 프레임을 length-prefixed 바이트로 직렬화."""
    payload = json.dumps(frame, default=str, ensure_ascii=False).encode("utf-8")
    if len(payload) > protocol.MAX_MESSAGE_SIZE:
        raise MessageTooLargeError(
            f"메시지 크기({len(payload)} bytes)가 "
            f"최대 제한({protocol.MAX_MESSAGE_SIZE} bytes)을 초과"
        )
    return struct.pack("!I", len(payload)) + payload


class IPCServerState(Enum):
    """IPCServer lifecycle state.

    * ``STOPPED`` → ``RUNNING``: ``start()`` 마지막에 전환.
    * ``RUNNING`` → ``SHUTTING_DOWN``: ``stop_accepting()`` 진입 직후
      (listener close 호출 **전**)에 전환. 이 시점부터 mutating dispatch는
      ``SERVICE_UNAVAILABLE``로 거부된다.
    * ``SHUTTING_DOWN`` → ``DRAINING``: ``stop_dispatching()`` 호출 시 전환.
    * ``DRAINING`` → ``STOPPED``: ``unlink_socket()`` 마지막에 전환.
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
        self._closing_server: asyncio.AbstractServer | None = None
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

        Python 3.13의 ``asyncio.start_unix_server``는 ``cleanup_socket`` 인자를
        받으며 기본값이 ``True``이다. 본 메서드는 ``cleanup_socket=False``를
        명시적으로 전달해 ``server.close()`` 시 socket 파일이 자동 unlink되지
        않게 만든다 — 이로써 cold-path guard(``PID alive AND socket exists``)가
        shutdown 동안에도 'active runtime'을 정확히 판정할 수 있는 race window
        차단 의도가 유지된다.
        """
        path = Path(self._socket_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)

        if path.exists():
            path.unlink()

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=self._socket_path,
            cleanup_socket=False,
        )

        os.chmod(self._socket_path, 0o600)

        self._state = IPCServerState.RUNNING

        logger.info("IPCServer 시작: %s", self._socket_path)

    async def stop_accepting(self) -> None:
        """새 연결 수락 중지. 소켓 파일과 active 연결은 유지.

        cold-path guard(``PID alive AND socket exists``)가 shutdown 동안에도
        'active runtime'으로 판정하도록, 소켓 파일은 ``unlink_socket()``이
        호출되기 전까지 유지된다.

        listener close 호출 **전**에 state를 ``SHUTTING_DOWN``으로
        전환한다. 이래야 close 진행 중에 들어오는 dispatch도 mutating이라면
        ``SERVICE_UNAVAILABLE``로 거부된다.
        """
        self._state = IPCServerState.SHUTTING_DOWN

        if self._server:
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

        메서드 종료 시 state를 ``STOPPED``으로 전환한다.
        """
        path = Path(self._socket_path)
        if path.exists():
            path.unlink()
        self._state = IPCServerState.STOPPED
        logger.info("IPCServer 소켓 파일 제거: %s", self._socket_path)

    async def stop(self) -> None:
        """기존 호출자 호환 facade. listener close → drain → unlink.

        내부 메서드들이 lifecycle state 전환을 담당한다 —
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

                if not isinstance(request, dict):
                    response = self._malformed_request("요청은 JSON object여야 합니다")
                    data = await protocol.encode(response)
                    writer.write(data)
                    await writer.drain()
                    break

                response = await self._dispatch(request)

                result = response.get("result")
                if (
                    response.get("status") == "ok"
                    and isinstance(result, dict)
                    and result.get("_stream") == "signal.connect"
                ):
                    result.pop("_stream", None)
                    session_id = result["session_id"]
                    bot_id = result["bot_id"]
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
        """``SERVICE_UNAVAILABLE`` error 응답 dict 생성."""
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
        """``MALFORMED_REQUEST`` error 응답 dict 생성."""
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
        """``SERVICE_NOT_CONFIGURED`` error 응답 dict 생성."""
        return {
            "id": request_id,
            "status": "error",
            "error": {
                "code": "SERVICE_NOT_CONFIGURED",
                "message": (f"의존 서비스가 구성되지 않았습니다: {service_name}"),
            },
        }

    def _missing_required_service(self, spec_required: frozenset[str]) -> str | None:
        """``required_services`` preflight — 부재한 첫 service 이름 반환."""
        for service_name in spec_required:
            if getattr(self._service_registry, service_name, None) is None:
                return service_name
        return None

    async def _dispatch(self, request: dict) -> dict:
        """요청을 적절한 핸들러로 라우팅."""
        request_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")
        args = request.get("args", {})
        actor = request.get("actor", "ipc")

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

        if self._state == IPCServerState.SHUTTING_DOWN and spec.is_mutating:
            return self._service_unavailable(
                request_id,
                "서버가 종료 중입니다. 변경 명령을 받지 않습니다.",
            )

        missing = self._missing_required_service(spec.required_services)
        if missing is not None:
            return self._service_not_configured(request_id, missing)

        try:
            if spec.account_id_policy == "required":
                from ante.account.scoping import require_account_id

                require_account_id(args.get("account_id"), context=f"ipc.{command}")
            elif spec.account_id_policy == "optional_filter":
                account_id_arg = args.get("account_id")
                if account_id_arg is not None:
                    from ante.account.scoping import require_account_id

                    require_account_id(account_id_arg, context=f"ipc.{command}")

            result = await spec.handler(self._service_registry, args, actor)
            audit_detail: dict | None = None
            if isinstance(result, dict):
                audit_detail = result.pop("_audit_detail", None)
            if spec.audit_action is not None:
                audit_logger = getattr(self._service_registry, "audit_logger", None)
                if audit_logger is not None:
                    if audit_detail is None:
                        audit_detail = {}
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
            error = ipc_error_payload(e)
            if error["code"] in _EXPECTED_DISPATCH_REJECT_CODES:
                logger.warning(
                    "IPC handshake rejected: %s (%s)", command, error["code"]
                )
            else:
                logger.exception("IPC 커맨드 실행 오류: %s", command)
            return {
                "id": request_id,
                "status": "error",
                "error": error,
            }

    async def _run_signal_stream(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        bot_id: str,
        session_id: str,
    ) -> None:
        """signal.connect Phase-C 스트림 host."""
        from ante.bot.signal_channel import SignalChannel

        reg = getattr(self._service_registry, "signal_channel_registry", None)
        svc = self._service_registry
        bot = svc.bot_manager.get_bot(bot_id)
        if bot is None:
            if reg is not None:
                reg.unregister(bot_id, session_id)
            return

        out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=SIGNAL_OUT_QUEUE_MAX)
        write_lock = asyncio.Lock()
        flush_done = asyncio.Event()
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
            """disconnect-laggard teardown (INV-OUT-6). idempotent."""
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

        handle = reg.get(bot_id, session_id) if reg is not None else None
        if handle is not None:
            handle.out_queue = out_queue
            handle.on_closed = channel.mark_closed
            handle.closing_event = closing_event

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
        """adopt-time self-close (F4) — single closed frame flush 후 정리."""
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
        """read_task + writer_task + closing supervisor 를 구동·정리한다."""

        async def _writer_loop() -> None:
            while True:
                frame = await out_queue.get()
                try:
                    data = _encode_signal_frame(frame)
                except MessageTooLargeError:
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
                    flush_done.set()
                    return

        async def _reader_loop() -> None:
            while True:
                try:
                    msg = await protocol.decode(reader)
                except asyncio.IncompleteReadError:
                    return
                except MessageTooLargeError:
                    return
                await channel._handle_message(msg)  # type: ignore[attr-defined]

        read_task = asyncio.ensure_future(_reader_loop())
        writer_task = asyncio.ensure_future(_writer_loop())
        if handle is not None:
            handle.read_task = read_task  # type: ignore[attr-defined]
            handle.writer_task = writer_task  # type: ignore[attr-defined]

        closing_waiter = asyncio.ensure_future(closing_event.wait())
        try:
            await asyncio.wait(
                [read_task, writer_task, closing_waiter],
                return_when=asyncio.FIRST_COMPLETED,
            )

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
        """teardown async 순서 (F2, INV-OUT-8)."""
        channel.mark_closed()  # type: ignore[attr-defined]

        inflight = getattr(channel, "_inflight", None)
        if inflight is not None and not inflight.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(inflight), timeout=SIGNAL_INFLIGHT_GRACE
                )
            except (TimeoutError, Exception):
                pass

        if not read_task.done():
            read_task.cancel()

        if daemon_close and not writer_task.done():
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
            writer_task.cancel()

        with contextlib.suppress(asyncio.CancelledError, Exception):
            await read_task
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await writer_task
