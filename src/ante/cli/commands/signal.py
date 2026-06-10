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

# ``ipc_helpers.py:81`` SSOT verbatim — 서버 미기동/소켓 부재 시 사용자 메시지.
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

    본 명령은 더 이상 in-process 로 ``Database``/``EventBus``/``BotManager``/
    ``SignalChannel`` 을 구성하지 않는다(#2333 회귀 원인). 대신 실행 중인 데몬의
    ``ante.sock`` 으로 ``signal.connect`` 핸드셰이크를 보내고(Phase A/B), OK 면
    동일 연결을 long-lived 스트림으로 전환해 stdin↔socket(``_pump_in``) /
    socket↔stdout(``_pump_out``) 만 양방향 relay 한다(Phase C). 4-게이트 검증·
    봇 상태·이벤트 구독은 전부 데몬이 소유하며, 핸드셰이크 거부는 #1705 envelope
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
        # ``FileNotFoundError`` ⊂ ``OSError`` — 소켓 파일 부재/연결 거부 모두
        # 서버 미기동으로 매핑한다.
        _fail(fmt, _SERVER_DOWN_MSG, "IPC_SERVER_NOT_RUNNING")

    try:
        # Phase A — 핸드셰이크 요청 (key 는 args.key 에만, actor 동봉).
        req = {
            "id": str(uuid4()),
            "command": "signal.connect",
            "args": {"key": key},
            "actor": actor,
        }
        writer.write(await protocol.encode(req))
        await writer.drain()

        # Phase B — 핸드셰이크 응답. handshake decode 에만 30s bounded timeout.
        try:
            resp = await asyncio.wait_for(protocol.decode(reader), timeout=30.0)
        except TimeoutError:
            # py3.11+: ``asyncio.TimeoutError`` 는 builtin ``TimeoutError`` alias.
            _fail(fmt, "서버 응답 시간 초과", "IPC_TIMEOUT")
        except asyncio.IncompleteReadError:
            # 핸드셰이크 중 데몬이 연결을 닫음.
            _fail(fmt, _SERVER_DOWN_MSG, "IPC_SERVER_NOT_RUNNING")

        if resp.get("status") == "error":
            # 데몬 nested envelope ``{id,status:error,error:{code,message}}`` 를
            # #1705 flattened surface 로 추출 후 ``_fail`` 라우팅(raw echo 금지).
            err = resp["error"]
            _fail(fmt, err["message"], err["code"])

        # OK — 동일 연결을 Phase C 스트림으로 전환. informational stderr 2줄을
        # handshake OK **이후** 방출한다.
        bot_id = resp["result"]["bot_id"]
        _err(f"Connected to bot {bot_id}")
        _err("Ready for JSON Lines communication on stdin/stdout")

        # Phase C — 양방향 relay. teardown 은 **비대칭** 이다(plain gather 는 idle
        # stdin readline 에서 영구 hang, 대칭 cancel 은 잔여 프레임 drain 을 끊음).
        pump_in = asyncio.ensure_future(_pump_in(writer))
        pump_out = asyncio.ensure_future(_pump_out(reader))
        done, _pending = await asyncio.wait(
            {pump_in, pump_out}, return_when=asyncio.FIRST_COMPLETED
        )
        if pump_out in done:
            # ``_pump_out`` 이 먼저 종료(daemon closed 프레임 또는 socket EOF) →
            # idle stdin 무한 대기 방지를 위해 ``_pump_in`` 을 cancel 한다.
            pump_in.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await pump_in
        else:
            # stdin EOF(``write_eof`` half-close) 로 ``_pump_in`` 이 먼저 종료 →
            # ``_pump_out`` 을 cancel 하지 **않고** await 하여 데몬의 잔여 ack/
            # closed 프레임을 socket EOF 까지 drain 한 뒤 종료한다.
            await pump_out
        # ``_pump_in``/``_pump_out`` 은 write/read 예외를 내부에서 이미 swallow
        # (BrokenPipe/OSError/IncompleteReadError → 정상 return)하므로 정상 경로에서
        # 추가 예외는 없다. ``await pump_out`` 도 동일 swallow 로 예외 없이 종료한다.
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
        # stdin 이 실제 파이프/터미널이 아니거나(테스트 하니스 등) read pipe 로
        # 등록할 수 없는 경우, inbound relay 를 비활성화하고 ``_pump_out`` 이
        # 종료를 주도하도록 영구 대기한다(취소될 때까지). 데몬→stdout 단방향
        # relay 는 그대로 유지된다.
        await asyncio.Event().wait()
        return

    try:
        while True:
            line = await reader.readline()
            if not line:
                # stdin EOF → half-close. socket→stdout pump 는 계속 동작.
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
                # relay 투명성 — 비-JSON 줄은 그대로 무시한다.
                continue

            try:
                writer.write(await protocol.encode(msg))
                await writer.drain()
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
    finally:
        # cancel/return 양 경로 모두에서 stdin read transport 를 닫아 fd 누수와
        # ResourceWarning 을 방지한다.
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
            # socket EOF — 정상 종료.
            return

        try:
            # 데몬 프레임은 embedded newline 0 — stdout 에서 ``\n`` 정확히 1회.
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
