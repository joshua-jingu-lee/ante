"""CLI ``ante signal connect`` thin IPC relay 회귀 (#1705 + #2338).

#2338 에서 ``signal connect`` 가 in-process ``Database``/``BotManager``/
``SignalChannel`` 구성에서 **데몬-위임 thin IPC relay** 로 재작성됐다. 4-게이트
검증은 데몬이 소유하고, CLI 는 ``signal.connect`` 핸드셰이크(Phase A/B)를 보낸
뒤 OK 면 stdin↔socket / socket↔stdout 양방향 relay 만 수행한다(Phase C).

본 파일은 in-process mock 을 **IPC-layer mock** 으로 마이그레이트한다:
``asyncio.open_unix_connection`` 을 fake reader/writer 로 교체하고, 데몬 Phase-B
응답 프레임을 직접 주입해 #1705 의 11 관측 출력(4 validation JSON + 4 text-no-
``Error:`` prefix + 2 informational + auth_required)을 **byte-identical** 로
회귀 lock 한다. 추가로 신규 transport terminal(IPC_SERVER_NOT_RUNNING /
IPC_TIMEOUT)을 JSON/text 양 모드에서 lock 한다.

``runner`` 인증 fixture 는 #1701 ``test_cli_format_option.py`` 패턴을 미러해
``ante.cli.main.authenticate_member`` 를 monkeypatch 한다.
"""

from __future__ import annotations

import asyncio
import json
import struct
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from ante.cli.main import cli
from ante.member.models import Member, MemberRole, MemberType

_MOCK_MASTER = Member(
    member_id="test-master",
    type=MemberType.HUMAN,
    role=MemberRole.MASTER,
    org="default",
    name="Test Master",
    status="active",
    scopes=[],
)

# patch site SSOT — 재작성된 signal.py 의 실제 binding 과 일치해야 한다.
_OPEN_CONN_TARGET = "asyncio.open_unix_connection"
_SOCKET_TARGET = "ante.cli.commands.signal.get_socket_path"
_PATH_EXISTS_TARGET = "ante.cli.commands.signal.Path.exists"


@pytest.fixture()
def runner() -> CliRunner:
    """인증된 상태의 CliRunner — ``mix_stderr=False`` 로 stderr 분리."""
    r = CliRunner(mix_stderr=False)
    original_invoke = r.invoke

    def _invoke_with_auth(cli_cmd, args=None, **kwargs):  # noqa: ANN001, ANN202
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _set_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = _MOCK_MASTER

            mock_auth.side_effect = _set_member
            return original_invoke(cli_cmd, args, **kwargs)

    r.invoke = _invoke_with_auth
    return r


# ──────────────────────────────────────────────────────────────
# IPC-layer fakes — protocol.decode/encode wire framing 재현
# ──────────────────────────────────────────────────────────────


def _frame(d: dict) -> bytes:
    """dict → length-prefixed wire 프레임 ([4B big-endian len][UTF-8 JSON])."""
    payload = json.dumps(d, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


class FakeReader:
    """미리 framed bytes 버퍼를 슬라이스로 제공하는 ``StreamReader`` 대역.

    ``protocol.decode`` 는 ``readexactly(4)`` 로 길이를 읽고 ``readexactly(n)``
    로 payload 를 읽는다. 버퍼가 소진되면 ``IncompleteReadError`` 를 raise 해
    socket EOF 를 모사한다.
    """

    def __init__(self, frames: list[bytes]) -> None:
        self._buf = b"".join(frames)
        self._pos = 0

    async def readexactly(self, n: int) -> bytes:
        if self._pos + n > len(self._buf):
            partial = self._buf[self._pos :]
            self._pos = len(self._buf)
            raise asyncio.IncompleteReadError(partial, n)
        chunk = self._buf[self._pos : self._pos + n]
        self._pos += n
        return chunk


class HangingReader(FakeReader):
    """handshake 응답을 영구 보류해 Phase-B ``wait_for`` timeout 을 유발."""

    async def readexactly(self, n: int) -> bytes:
        await asyncio.Event().wait()  # 영원히 대기 → wait_for TimeoutError.
        raise AssertionError("unreachable")


class DeferredFrameReader(FakeReader):
    """handshake OK 이후의 Phase-C 프레임을 ``_pump_in`` 완료 **뒤** 에 도착시키는
    ``StreamReader`` 대역.

    ``boundary_pos`` (handshake 프레임 끝 byte offset) 이후의 첫 read 마다 짧은
    ``asyncio.sleep(0)`` 양보를 끼워, 데몬 잔여 프레임이 stdin EOF(=``_pump_in``
    완료) 직후 비동기적으로 도착하는 현실 타이밍을 모사한다. 이로써 **비대칭
    teardown** (pump_in 먼저 done → pump_out drain) 이 실제로 잔여 프레임을 stdout
    으로 흘려보내는지 회귀-lock 한다. 대칭 cancel 회귀였다면 이 프레임들이 누락된다.
    """

    def __init__(self, frames: list[bytes], boundary_pos: int) -> None:
        super().__init__(frames)
        self._boundary = boundary_pos

    async def readexactly(self, n: int) -> bytes:
        if self._pos >= self._boundary:
            # Phase-C 영역 — 잔여 프레임 도착을 이벤트루프 양보 뒤로 미룬다.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        return await super().readexactly(n)


class FakeWriter:
    """write/drain/write_eof/close/wait_closed no-op ``StreamWriter`` 대역."""

    def __init__(self) -> None:
        self.written = bytearray()

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        return None

    def write_eof(self) -> None:
        return None

    def close(self) -> None:
        return None

    async def wait_closed(self) -> None:
        return None


@contextmanager
def _patch_ipc(
    *,
    response_frames: list[dict] | None = None,
    connect_exc: BaseException | None = None,
    handshake_timeout: bool = False,
) -> Iterator[FakeWriter]:
    """IPC transport 를 mock 하는 컨텍스트.

    - ``Path.exists`` → True (server-down pre-check 통과).
    - ``get_socket_path`` → 고정 경로.
    - ``open_unix_connection`` → (FakeReader, FakeWriter) 또는 ``connect_exc``.
    - ``handshake_timeout`` → HangingReader 로 Phase-B ``wait_for`` timeout.
    """
    writer = FakeWriter()

    if connect_exc is not None:

        async def _open(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
            raise connect_exc
    else:
        if handshake_timeout:
            reader: FakeReader = HangingReader([])
        else:
            frames = [_frame(d) for d in (response_frames or [])]
            reader = FakeReader(frames)

        async def _open(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
            return reader, writer

    with (
        patch(_PATH_EXISTS_TARGET, return_value=True),
        patch(_SOCKET_TARGET, return_value="/tmp/test-ante.sock"),
        patch(_OPEN_CONN_TARGET, _open),
    ):
        yield writer


def _error_frame(code: str, message: str) -> dict:
    """데몬 Phase-B nested error envelope."""
    return {"id": "h1", "status": "error", "error": {"code": code, "message": message}}


def _ok_frame(bot_id: str = "bot-1705") -> dict:
    """데몬 Phase-B OK envelope (result 에 bot_id/account_id/session_id)."""
    return {
        "id": "h1",
        "status": "ok",
        "result": {"bot_id": bot_id, "account_id": "acct", "session_id": "s1"},
    }


_CLOSED_FRAME = {"type": "closed", "reason": "eof"}


# ──────────────────────────────────────────────────────────────
# A. 4 validation × JSON mode (#1705 byte-lock)
# ──────────────────────────────────────────────────────────────


class TestSignalConnectJsonEnvelope1705:
    """``--format json`` 모드: stdout JSON envelope + stderr empty + exit 1."""

    def test_invalid_key(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[_error_frame("INVALID_SIGNAL_KEY", "Invalid signal key")]
        ):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_invalid", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "INVALID_SIGNAL_KEY",
            "message": "Invalid signal key",
        }
        assert result.stderr == ""

    def test_bot_not_found(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame("BOT_NOT_FOUND", "Bot not found: bot-missing")
            ]
        ):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_FOUND",
            "message": "Bot not found: bot-missing",
        }
        assert result.stderr == ""

    def test_bot_not_running(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame(
                    "BOT_NOT_RUNNING",
                    "Bot is not running: bot-1705 (status: stopped)",
                )
            ]
        ):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_RUNNING",
            "message": "Bot is not running: bot-1705 (status: stopped)",
        }
        assert result.stderr == ""

    def test_bot_not_accepting_signals(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame(
                    "BOT_NOT_ACCEPTING_SIGNALS",
                    "Bot bot-1705 does not accept external signals",
                )
            ]
        ):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "BOT_NOT_ACCEPTING_SIGNALS",
            "message": "Bot bot-1705 does not accept external signals",
        }
        assert result.stderr == ""


# ──────────────────────────────────────────────────────────────
# B. 4 validation × text mode (default — no Error: prefix)
# ──────────────────────────────────────────────────────────────


class TestSignalConnectTextMode1705:
    """default text 모드: stderr raw text + stdout empty + exit 1.

    ``Error: `` prefix 가 붙지 않아야 하며, ``_err()`` raw stderr + ``\\n``
    동작을 회귀 lock 한다.
    """

    def test_invalid_key_text(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[_error_frame("INVALID_SIGNAL_KEY", "Invalid signal key")]
        ):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_invalid"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Invalid signal key\n"
        assert result.stdout == ""

    def test_bot_not_found_text(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame("BOT_NOT_FOUND", "Bot not found: bot-missing")
            ]
        ):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot not found: bot-missing\n"
        assert result.stdout == ""

    def test_bot_not_running_text(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame(
                    "BOT_NOT_RUNNING",
                    "Bot is not running: bot-1705 (status: stopped)",
                )
            ]
        ):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot is not running: bot-1705 (status: stopped)\n"
        assert result.stdout == ""

    def test_bot_not_accepting_signals_text(self, runner: CliRunner) -> None:
        with _patch_ipc(
            response_frames=[
                _error_frame(
                    "BOT_NOT_ACCEPTING_SIGNALS",
                    "Bot bot-1705 does not accept external signals",
                )
            ]
        ):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "Bot bot-1705 does not accept external signals\n"
        assert result.stdout == ""


# ──────────────────────────────────────────────────────────────
# C. Informational stderr regression — 정상 path 의 2 informational 메시지
# ──────────────────────────────────────────────────────────────


class TestSignalConnectInformationalStderr1705:
    """정상 path (handshake OK) 에서 ``Connected to bot ...`` / ``Ready for
    JSON Lines ...`` 메시지가 stderr 에 그대로 출력됨을 lock.

    Phase-B OK frame 다음에 ``{type:closed}`` frame 을 주입해 ``_pump_out`` 이
    즉시 break(exit 0) 하도록 한다. ``_pump_in`` 은 빈 stdin EOF 로 종료한다.
    """

    def test_informational_messages_to_stderr(self, runner: CliRunner) -> None:
        # ``_pump_in`` 은 stub(영구 대기)으로 패치 — 테스트 하니스의 가짜 stdin
        # 을 ``connect_read_pipe`` 로 등록하면 broken transport 가 생긴다. 본
        # 케이스의 lock 대상은 inbound relay 가 아니라 handshake OK 후 2
        # informational stderr 와 exit 0 이므로, ``_pump_out`` 이 closed frame
        # 으로 종료를 주도하게 한다(현실 프로덕션 경로와 동형).
        async def _idle_pump_in(_writer):  # noqa: ANN001, ANN202
            await asyncio.Event().wait()

        with _patch_ipc(response_frames=[_ok_frame("bot-1705"), _CLOSED_FRAME]):
            with patch("ante.cli.commands.signal._pump_in", _idle_pump_in):
                result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 0, (result.stdout, result.stderr)
        assert "Connected to bot bot-1705\n" in result.stderr
        assert "Ready for JSON Lines communication on stdin/stdout\n" in result.stderr


# ──────────────────────────────────────────────────────────────
# C2. EOF-drain regression — pump_in 먼저 종료 시 pump_out 잔여 프레임 drain
# ──────────────────────────────────────────────────────────────


class TestSignalConnectEofDrain2338:
    """**비대칭** Phase-C teardown 회귀 lock (#2338 Codex 브랜치 리뷰 FAIL).

    stdin EOF 로 ``_pump_in`` 이 먼저 완료해도 ``_pump_out`` 을 cancel 하지 않고
    await 하여, 데몬의 잔여 ack/``{type:closed}`` 프레임을 socket EOF 까지 stdout
    으로 drain 한 뒤 exit 0 임을 단언한다.

    회귀(대칭 ``for task in pending: task.cancel()``) 였다면 ``_pump_in`` 이 먼저
    done 인 순간 ``_pump_out`` 이 즉시 cancel 되어 잔여 프레임이 stdout 에 누락된다.
    ``_pump_in`` 은 **idle stub 으로 가리지 않고** stdin EOF 를 실제로 모사하는
    stub(``write_eof`` 후 즉시 return)으로 패치해 EOF→drain 경로를 노출한다.
    """

    def test_residual_frames_drained_after_stdin_eof(self, runner: CliRunner) -> None:
        ack_frame = {"type": "ack", "signal_id": "sig-1"}

        # OK handshake 프레임 끝 byte offset = boundary. 이후(ack/closed)는
        # ``_pump_in`` 완료 뒤 비동기 도착(DeferredFrameReader).
        ok = _frame(_ok_frame("bot-1705"))
        boundary = len(ok)
        frames = [ok, _frame(ack_frame), _frame(_CLOSED_FRAME)]
        reader = DeferredFrameReader(frames, boundary_pos=boundary)
        writer = FakeWriter()

        async def _open(*_a, **_k):  # noqa: ANN002, ANN003, ANN202
            return reader, writer

        # stdin EOF 를 실제로 모사: half-close 후 즉시 return → ``_pump_in`` 이
        # ``_pump_out`` 보다 먼저 done 이 되어 비대칭 else-분기(await pump_out)를
        # 트리거한다.
        async def _eof_pump_in(w):  # noqa: ANN001, ANN202
            w.write_eof()

        with (
            patch(_PATH_EXISTS_TARGET, return_value=True),
            patch(_SOCKET_TARGET, return_value="/tmp/test-ante.sock"),
            patch(_OPEN_CONN_TARGET, _open),
            patch("ante.cli.commands.signal._pump_in", _eof_pump_in),
        ):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 0, (result.stdout, result.stderr)

        # stdin EOF 이후에도 잔여 ack 프레임이 stdout 으로 drain 되어야 한다.
        out_lines = [ln for ln in result.stdout.splitlines() if ln]
        decoded = [json.loads(ln) for ln in out_lines]
        assert ack_frame in decoded, result.stdout
        assert _CLOSED_FRAME in decoded, result.stdout
        # closed 프레임 informational stderr 도 방출된다.
        assert "channel closed: eof\n" in result.stderr


# ──────────────────────────────────────────────────────────────
# D. auth-fail regression — root-level --format json (pre-IPC)
# ──────────────────────────────────────────────────────────────


class TestSignalConnectAuthFail1705:
    """no-token + root-level ``--format json signal connect`` →
    stdout ``auth_required`` JSON envelope. ``@require_auth`` 가 socket 열기
    전에 발화하므로 IPC mock 불필요.
    """

    def test_auth_required_json_envelope(self) -> None:
        r = CliRunner(mix_stderr=False)
        with patch("ante.cli.main.authenticate_member") as mock_auth:

            def _no_member(ctx):  # noqa: ANN001
                ctx.obj = ctx.obj or {}
                ctx.obj["member"] = None

            mock_auth.side_effect = _no_member
            result = r.invoke(
                cli,
                [
                    "--format",
                    "json",
                    "signal",
                    "connect",
                    "--key",
                    "sk_anything",
                ],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload["status"] == "error"
        assert payload["code"] == "auth_required"


# ──────────────────────────────────────────────────────────────
# E. 신규 transport terminal (#2338) — IPC_SERVER_NOT_RUNNING / IPC_TIMEOUT
# ──────────────────────────────────────────────────────────────


_SERVER_DOWN_MSG = "서버가 실행 중이 아닙니다. 'ante system start'로 시작하세요."


class TestSignalConnectIpcTerminals:
    """thin relay 가 추가한 transport 종료 — server-absent / handshake timeout.

    과거 broken-but-non-erroring 데몬-down 경로를 명시적 exit 1 terminal 로
    잠근다(#2334 §10). #1705 외 신규 (code,message) lock 이다.
    """

    def test_server_not_running_connection_refused_json(
        self, runner: CliRunner
    ) -> None:
        with _patch_ipc(connect_exc=ConnectionRefusedError()):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "IPC_SERVER_NOT_RUNNING",
            "message": _SERVER_DOWN_MSG,
        }
        assert result.stderr == ""

    def test_server_not_running_connection_refused_text(
        self, runner: CliRunner
    ) -> None:
        with _patch_ipc(connect_exc=ConnectionRefusedError()):
            result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == _SERVER_DOWN_MSG + "\n"
        assert result.stdout == ""

    def test_server_not_running_file_not_found_json(self, runner: CliRunner) -> None:
        # ``FileNotFoundError`` ⊂ ``OSError`` — 동일 terminal 로 매핑.
        with _patch_ipc(connect_exc=FileNotFoundError()):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload["code"] == "IPC_SERVER_NOT_RUNNING"
        assert payload["message"] == _SERVER_DOWN_MSG
        assert result.stderr == ""

    def test_server_missing_socket_precheck_json(self, runner: CliRunner) -> None:
        # ``Path.exists`` False → open_unix_connection 도달 전 pre-check terminal.
        with (
            patch(_PATH_EXISTS_TARGET, return_value=False),
            patch(_SOCKET_TARGET, return_value="/tmp/test-ante.sock"),
        ):
            result = runner.invoke(
                cli,
                ["signal", "connect", "--key", "sk_ok", "--format", "json"],
            )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload["code"] == "IPC_SERVER_NOT_RUNNING"
        assert payload["message"] == _SERVER_DOWN_MSG

    def test_handshake_timeout_json(self, runner: CliRunner) -> None:
        with _patch_ipc(handshake_timeout=True):
            with patch("asyncio.wait_for", side_effect=_immediate_timeout):
                result = runner.invoke(
                    cli,
                    ["signal", "connect", "--key", "sk_ok", "--format", "json"],
                )

        assert result.exit_code == 1, (result.stdout, result.stderr)
        payload = json.loads(result.stdout)
        assert payload == {
            "status": "error",
            "code": "IPC_TIMEOUT",
            "message": "서버 응답 시간 초과",
        }
        assert result.stderr == ""

    def test_handshake_timeout_text(self, runner: CliRunner) -> None:
        with _patch_ipc(handshake_timeout=True):
            with patch("asyncio.wait_for", side_effect=_immediate_timeout):
                result = runner.invoke(cli, ["signal", "connect", "--key", "sk_ok"])

        assert result.exit_code == 1, (result.stdout, result.stderr)
        assert result.stderr == "서버 응답 시간 초과\n"
        assert result.stdout == ""


async def _immediate_timeout(coro, timeout):  # noqa: ANN001, ANN202
    """``asyncio.wait_for`` 대역 — 즉시 ``TimeoutError`` (HangingReader 대기 회피).

    실제 30s 대기 없이 Phase-B timeout 분기를 결정적으로 검증한다. 보류 중인
    coroutine 은 close 해 ``RuntimeWarning`` 을 피한다.
    """
    coro.close()
    raise TimeoutError
