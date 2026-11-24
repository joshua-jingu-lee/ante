"""ante signal — 외부 시그널 채널 관리 커맨드."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import stat
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

import click

from ante.cli.commands.ipc_helpers import get_socket_path
from ante.cli.formatter import format_option
from ante.cli.middleware import get_member_id, require_auth
from ante.contracts.ipc_client_errors import (
    IPCClientTimeoutError,
    IPCRemoteError,
    IPCServerNotRunningError,
)
from ante.ipc import protocol

_SERVER_DOWN_MSG = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."


@click.group()
def signal() -> None:
    """외부 시그널 채널 관리."""


@signal.command("connect")
@click.option("--key", required=True, help="시그널 키 (sk_...)")
@format_option
@click.pass_context
@require_auth
def signal_connect(ctx: click.Context, key: str) -> None:
    """양방향 JSON Lines 시그널 채널 수립."""
    asyncio.run(_run_connect(ctx, key))


async def _run_connect(ctx: click.Context, key: str) -> None:
    """시그널 채널을 데몬으로 위임하는 thin IPC relay."""
    from ante.cli.main import get_config_dir

    actor = get_member_id(ctx)
    socket_path = get_socket_path(get_config_dir(ctx))

    if not Path(socket_path).exists():
        raise IPCServerNotRunningError(_SERVER_DOWN_MSG)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except (FileNotFoundError, ConnectionRefusedError):
        raise IPCServerNotRunningError(_SERVER_DOWN_MSG)

    try:
        req = {
            "id": str(uuid4()),
            "command": "signal.connect",
            "args": {"key": key},
            "actor": actor,
        }
        writer.write(await protocol.encode(req))
        await writer.drain()

        try:
            resp = await asyncio.wait_for(protocol.decode(reader), timeout=30.0)
        except TimeoutError:
            raise IPCClientTimeoutError("서버 응답 시간 초과")
        except asyncio.IncompleteReadError:
            raise IPCServerNotRunningError(_SERVER_DOWN_MSG)

        if resp.get("status") == "error":
            err = resp["error"]
            raise IPCRemoteError(err["code"], err["message"])

        bot_id = resp["result"]["bot_id"]
        _err(f"Connected to bot {bot_id}")
        _err("Ready for JSON Lines communication on stdin/stdout")

        pump_in = asyncio.ensure_future(_pump_in(writer))
        pump_out = asyncio.ensure_future(_pump_out(reader))
        done, _pending = await asyncio.wait(
            {pump_in, pump_out}, return_when=asyncio.FIRST_COMPLETED
        )
        if pump_out in done:
            pump_in.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_in
        else:
            await pump_out
    finally:
        writer.close()
        with contextlib.suppress(Exception):
            await writer.wait_closed()


async def _pump_in(writer: asyncio.StreamWriter) -> None:
    """stdin → socket relay. JSON Lines 를 length-prefixed 프레임으로 전달한다."""
    stdin = sys.stdin
    if _stdin_is_regular_file(stdin):
        await _relay_lines(lambda: asyncio.to_thread(_readline_or_eof, stdin), writer)
        return

    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    stdin_protocol = asyncio.StreamReaderProtocol(reader)
    try:
        transport, _ = await loop.connect_read_pipe(lambda: stdin_protocol, stdin)
    except (AttributeError, ValueError, OSError):
        await asyncio.Event().wait()
        return

    try:
        await _relay_lines(reader.readline, writer)
    finally:
        with contextlib.suppress(Exception):
            transport.close()


async def _relay_lines(
    readline: Callable[[], Awaitable[bytes]], writer: asyncio.StreamWriter
) -> None:
    """줄 원천을 입력의 끝까지 프레임으로 보내고, 끝에서 송신 쪽을 닫는다."""
    while True:
        line = await readline()
        if not line:
            with contextlib.suppress(BrokenPipeError, ConnectionResetError, OSError):
                writer.write_eof()
            return

        text = line.decode("utf-8").strip()
        if not text:
            continue
        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            continue

        try:
            writer.write(await protocol.encode(msg))
            await writer.drain()
        except (BrokenPipeError, ConnectionResetError, OSError):
            return


def _stdin_is_regular_file(stdin: Any) -> bool:
    """stdin 이 리다이렉트한 일반 파일인지 판정한다."""
    if stdin is None:
        return False
    try:
        return stat.S_ISREG(os.fstat(stdin.fileno()).st_mode)
    except (AttributeError, ValueError, OSError):
        return False


def _readline_or_eof(stdin: Any) -> bytes:
    """일반 파일에서 한 줄을 읽는다. 입출력 오류는 입력의 끝(빈 바이트)으로 본다."""
    try:
        line: bytes = getattr(stdin, "buffer", stdin).readline()
    except OSError:
        return b""
    return line


async def _pump_out(reader: asyncio.StreamReader) -> None:
    """socket → stdout relay. 데몬 프레임을 정확히 1개 ``\\n`` 부착해 출력한다."""
    while True:
        try:
            frame = await protocol.decode(reader)
        except asyncio.IncompleteReadError:
            return

        try:
            sys.stdout.write(json.dumps(frame) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            return

        if frame.get("type") == "closed":
            _err(f"channel closed: {frame.get('reason', '')}")
            return


def _err(msg: str) -> None:
    """stderr에 메시지 출력."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
