"""ante signal — 외부 시그널 채널 관리 커맨드."""

from __future__ import annotations

import asyncio
import contextlib
import json
import sys
from pathlib import Path
from typing import NoReturn
from uuid import uuid4

import click

from ante.cli.commands.ipc_helpers import get_socket_path
from ante.cli.formatter import OutputFormatter, format_option
from ante.cli.middleware import get_member_id, require_auth
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
    """시그널 채널을 데몬으로 위임하는 thin IPC relay.

    본 명령은 in-process 로 ``Database``/``EventBus``/``BotManager``/
    ``SignalChannel`` 을 구성하지 않는다. 대신 실행 중인 데몬의
    ``ante.sock`` 으로 ``signal.connect`` 핸드셰이크를 보내고(Phase A/B), OK 면
    동일 연결을 long-lived 스트림으로 전환해 stdin↔socket(``_pump_in``) /
    socket↔stdout(``_pump_out``) 만 양방향 relay 한다(Phase C). 4-게이트 검증·
    봇 상태·이벤트 구독은 전부 데몬이 소유하며, 핸드셰이크 거부는 envelope
    을 그대로 ``_fail`` 로 passthrough 한다.
    """
    from ante.cli.main import get_config_dir, get_formatter

    fmt = get_formatter(ctx)
    actor = get_member_id(ctx)
    socket_path = get_socket_path(get_config_dir(ctx))

    if not Path(socket_path).exists():
        _fail(fmt, _SERVER_DOWN_MSG, "IPC_SERVER_NOT_RUNNING")

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
    except (ConnectionRefusedError, OSError):
        _fail(fmt, _SERVER_DOWN_MSG, "IPC_SERVER_NOT_RUNNING")

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
            _fail(fmt, "서버 응답 시간 초과", "IPC_TIMEOUT")
        except asyncio.IncompleteReadError:
            _fail(fmt, _SERVER_DOWN_MSG, "IPC_SERVER_NOT_RUNNING")

        if resp.get("status") == "error":
            err = resp["error"]
            _fail(fmt, err["message"], err["code"])

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
    """stdin → socket relay. JSON Lines 를 length-prefixed 프레임으로 전달한다.

    stdin 의 각 줄을 ``json.loads`` 로 검사(``JSONDecodeError`` 는 투명하게
    skip)한 뒤 ``protocol.encode`` 로 framing 해 socket 에 write 한다. stdin EOF
    면 ``write_eof`` 로 half-close 하여 ``_pump_out`` 은 유지한다. write 예외는
    swallow 해 exit 0 으로 종료한다.
    """
    loop = asyncio.get_event_loop()
    reader = asyncio.StreamReader()
    stdin_protocol = asyncio.StreamReaderProtocol(reader)
    try:
        transport, _ = await loop.connect_read_pipe(lambda: stdin_protocol, sys.stdin)
    except (ValueError, OSError):
        await asyncio.Event().wait()
        return

    try:
        while True:
            line = await reader.readline()
            if not line:
                with contextlib.suppress(
                    BrokenPipeError, ConnectionResetError, OSError
                ):
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
    finally:
        with contextlib.suppress(Exception):
            transport.close()


async def _pump_out(reader: asyncio.StreamReader) -> None:
    """socket → stdout relay. 데몬 프레임을 정확히 1개 ``\\n`` 부착해 출력한다.

    ``protocol.decode`` 는 **per-read timeout 없이** 호출한다(Phase-C idle
    스트림은 정상 — ipc.md Timeout 계약). socket EOF(``IncompleteReadError``)
    면 return(exit 0). ``{"type":"closed"}`` 프레임이면 informational stderr 후
    return(exit 0). mid-stream ``{"type":"error"}`` 프레임은 종료하지 않고 투명
    passthrough 한다.
    """
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


def _fail(fmt: OutputFormatter, msg: str, code: str) -> NoReturn:
    """validation/transport 오류 종료 (단일 chokepoint).

    JSON 모드는 stdout envelope (``{status,code,message}``),
    text 모드는 기존 ``_err()`` raw stderr 동작을 그대로 보존한다
    (no ``Error: `` prefix).
    """
    if fmt.is_json:
        fmt.error(msg, code=code)
    else:
        _err(msg)
    raise SystemExit(1)


def _err(msg: str) -> None:
    """stderr에 메시지 출력."""
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()
