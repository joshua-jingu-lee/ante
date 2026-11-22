"""signal.connect 핸드셰이크 transport+ingress 테스트 (#2334/#2336 PR#1).

T1 — daemon handshake (server 경유 + 핸들러 단위): 4-게이트 성공/거부 →
stable code, ``_stream`` 센티넬 비노출, account_id 는 ``bot.config`` 유래.
T3 — framing/upgrade: ack 1프레임 round-trip(trailing ``'\n'`` 없음), idle
스트림이 timeout/close 하지 않음, MALFORMED 비-dict 첫 프레임 거부.

``test_server_client.py`` 의 unix-socket round-trip 패턴을 미러하되, MALFORMED
wire 직조와 Phase-C EOF 제어를 위해 raw ``asyncio.open_unix_connection`` 으로
프레임을 직접 다룬다. ``_run_signal_stream`` 은 PR#1 스켈레톤이며 routing 없음.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.config import BotStatus
from ante.bot.exceptions import (
    BotNotAcceptingSignals,
    BotNotFoundError,
    BotNotRunning,
    InvalidSignalKey,
    SignalKeyManagerNotConfigured,
)
from ante.core.registry import ServiceRegistry
from ante.ipc.registry import (
    CommandRegistry,
    _handle_signal_connect,
    register_all_handlers,
)
from ante.ipc.requests import SignalConnectRequest
from ante.ipc.server import IPCServer
from tests.unit.ipc.validation_messages import validation_message

pytestmark = pytest.mark.asyncio


# ── wire helpers (length-prefixed framing 직접 제어) ──────────────────


async def _read_frame(reader: asyncio.StreamReader) -> bytes:
    """1 length-prefixed 프레임의 raw payload bytes 를 읽는다."""
    raw_len = await reader.readexactly(4)
    (length,) = struct.unpack("!I", raw_len)
    return await reader.readexactly(length)


async def _write_json_frame(writer: asyncio.StreamWriter, obj: object) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    writer.write(struct.pack("!I", len(payload)) + payload)
    await writer.drain()


# ── fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def socket_path() -> str:
    td = tempfile.mkdtemp(prefix="ipc-sig", dir="/tmp")
    return str(Path(td) / "t.sock")


def _make_bot(
    *,
    account_id: str = "acc-live",
    status: BotStatus = BotStatus.RUNNING,
    accepts: bool = True,
) -> MagicMock:
    bot = MagicMock()
    bot.config.account_id = account_id
    bot.status = status
    bot.strategy.meta.accepts_external_signals = accepts
    return bot


def _make_service_registry(bot_manager: MagicMock) -> ServiceRegistry:
    return ServiceRegistry(
        account=MagicMock(),
        bot_manager=bot_manager,
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=MagicMock(),
    )


def _signal_only_registry() -> CommandRegistry:
    """``signal.connect`` 만 등록한 registry (전체 required_services 회피)."""
    reg = CommandRegistry()
    reg.register(
        "signal.connect",
        _handle_signal_connect,
        is_mutating=False,
        required_services=frozenset({"bot_manager"}),
        request_model=SignalConnectRequest,
    )
    return reg


async def _start_server(socket_path: str, bot_manager: MagicMock) -> IPCServer:
    svc = _make_service_registry(bot_manager)
    server = IPCServer(socket_path, svc, _signal_only_registry())
    await server.start()
    return server


# ── T1: handshake 성공 (server 경유) ─────────────────────────────────


async def test_handshake_ok_returns_envelope_without_stream_sentinel(
    socket_path: str,
) -> None:
    """4-게이트 성공 → ``{bot_id, account_id}`` ok envelope, ``_stream`` 비노출."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot(account_id="acc-live"))
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(
            writer,
            {"id": "h1", "command": "signal.connect", "args": {"key": "sk_x"}},
        )
        resp = json.loads((await _read_frame(reader)).decode("utf-8"))

        assert resp["id"] == "h1"
        assert resp["status"] == "ok"
        assert resp["result"]["bot_id"] == "bot-1"
        assert resp["result"]["account_id"] == "acc-live"
        # 센티넬 strip 불변 — wire 에 절대 노출 안 됨.
        assert "_stream" not in resp["result"]

        # client close → _run_signal_stream 이 EOF 로 return, 연결 task 무에러.
        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
    finally:
        await server.stop()


async def test_handshake_invalid_key_one_error_frame_no_upgrade(
    socket_path: str,
) -> None:
    """게이트① 거부 → 정확히 1 error 프레임(INVALID_SIGNAL_KEY) 후 EOF."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value=None)  # miss
    bm.get_bot = MagicMock()
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(
            writer,
            {"id": "h2", "command": "signal.connect", "args": {"key": "sk_bad"}},
        )
        resp = json.loads((await _read_frame(reader)).decode("utf-8"))

        assert resp["id"] == "h2"
        assert resp["status"] == "error"
        assert resp["error"]["code"] == "INVALID_SIGNAL_KEY"
        # 보안: 프레임/메시지에 키 prefix 미포함.
        assert "sk_" not in json.dumps(resp)
        # upgrade 미진입 — get_bot 미호출.
        bm.get_bot.assert_not_called()

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


async def test_handshake_malformed_non_dict_first_frame(socket_path: str) -> None:
    """첫 프레임이 비-dict(JSON list) → MALFORMED_REQUEST, id=None 후 close."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock()
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        # 4바이트 길이 + json.dumps([1, 2]) 직조.
        await _write_json_frame(writer, [1, 2])
        resp = json.loads((await _read_frame(reader)).decode("utf-8"))

        assert resp["id"] is None
        assert resp["status"] == "error"
        assert resp["error"]["code"] == "MALFORMED_REQUEST"
        # 핸들러 미도달 — key 검증 호출 안 됨.
        bm.validate_signal_key.assert_not_called()

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


# ── T3: framing / upgrade ────────────────────────────────────────────


async def test_ack_frame_has_no_trailing_newline(socket_path: str) -> None:
    """ack 가 1 length-prefixed 프레임이고 JSON payload 에 trailing '\\n' 없음."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot())
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(
            writer,
            {"id": "h3", "command": "signal.connect", "args": {"key": "sk_x"}},
        )
        raw = await _read_frame(reader)
        # 프레임 payload 자체에 embedded newline 이 없어야 한다(데몬 미부착).
        assert not raw.endswith(b"\n")
        assert b"\n" not in raw
        # 정상 decode 가능.
        json.loads(raw.decode("utf-8"))

        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


async def test_idle_stream_does_not_timeout_or_close(socket_path: str) -> None:
    """upgrade 후 idle 스트림(프레임 0개)에서 _run_signal_stream 이 close 안 함.

    daemon-side per-read timeout 부재 lock — idle 은 정상. client 가 닫기
    전까지 연결이 살아 있다.
    """
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot())
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(
            writer,
            {"id": "h4", "command": "signal.connect", "args": {"key": "sk_x"}},
        )
        await _read_frame(reader)  # ack

        # 아무것도 보내지 않고 대기 — daemon 이 close/EOF 하지 않아야 한다.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(1), timeout=0.3)
        # 연결이 여전히 살아 있음(EOF 아님).
        assert not reader.at_eof()

        writer.close()
        await writer.wait_closed()
        await asyncio.sleep(0.05)
    finally:
        await server.stop()


# ── 핸들러 단위 (4-게이트 + account_id 출처) ─────────────────────────


class TestHandleSignalConnectUnit:
    async def _svc(self, bm: MagicMock) -> ServiceRegistry:
        return _make_service_registry(bm)

    async def test_ok_returns_stream_sentinel_and_config_account_id(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot(account_id="acc-live"))
        svc = await self._svc(bm)

        result = await _handle_signal_connect(
            svc, SignalConnectRequest(key="sk_x"), "ipc"
        )

        assert result["bot_id"] == "bot-1"
        # account_id 는 bot.config 유래(요청 모델에 account_id 필드가 없다).
        assert result["account_id"] == "acc-live"
        assert result["_stream"] == "signal.connect"
        assert set(SignalConnectRequest.model_fields) == {"key"}

    async def test_empty_key_reaches_gate1_as_invalid_signal_key(self) -> None:
        """빈 문자열 키는 모델을 통과하고 게이트①이 ``InvalidSignalKey``로 거부한다."""
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value=None)
        bm.get_bot = MagicMock(return_value=_make_bot())
        svc = await self._svc(bm)

        with pytest.raises(InvalidSignalKey):
            await _handle_signal_connect(svc, SignalConnectRequest(key=""), "ipc")
        bm.validate_signal_key.assert_awaited_once_with("")
        bm.get_bot.assert_not_called()

    async def test_gate1_key_miss_raises_invalid_signal_key(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value=None)
        bm.get_bot = MagicMock()
        svc = await self._svc(bm)

        with pytest.raises(InvalidSignalKey) as ei:
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_bad"), "ipc")
        assert ei.value.code == "INVALID_SIGNAL_KEY"

    async def test_manager_not_configured_propagates(self) -> None:
        """manager None → SignalKeyManagerNotConfigured (게이트① 위임)."""
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(side_effect=SignalKeyManagerNotConfigured())
        svc = await self._svc(bm)

        with pytest.raises(SignalKeyManagerNotConfigured) as ei:
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")
        assert ei.value.code == "SERVICE_NOT_CONFIGURED"

    async def test_gate2_bot_not_found(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-x")
        bm.get_bot = MagicMock(return_value=None)
        svc = await self._svc(bm)

        with pytest.raises(BotNotFoundError) as ei:
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")
        assert ei.value.code == "BOT_NOT_FOUND"

    async def test_gate3_bot_not_running_uses_lowercase_status_value(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot(status=BotStatus.STOPPED))
        svc = await self._svc(bm)

        with pytest.raises(BotNotRunning) as ei:
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")
        assert ei.value.code == "BOT_NOT_RUNNING"
        # caller 가 bot.status.value(소문자)를 전달하는 계약 lock.
        assert str(ei.value) == "Bot is not running: bot-1 (status: stopped)"

    async def test_gate4_not_accepting_external_signals_english_literal(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot(accepts=False))
        svc = await self._svc(bm)

        with pytest.raises(BotNotAcceptingSignals) as ei:
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")
        assert ei.value.code == "BOT_NOT_ACCEPTING_SIGNALS"
        # raise-site 영어 리터럴(한국어 rotate 메시지 재사용 금지).
        assert str(ei.value) == "Bot bot-1 does not accept external signals"

    async def test_gate4_no_strategy_rejected(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bot = _make_bot()
        bot.strategy = None
        bm.get_bot = MagicMock(return_value=bot)
        svc = await self._svc(bm)

        with pytest.raises(BotNotAcceptingSignals):
            await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")


# ── dispatch 경유: 거부 코드·로그 수준·ack 실패 정리 ──────────────────


def _registered_commands() -> CommandRegistry:
    reg = CommandRegistry()
    register_all_handlers(reg)
    return reg


async def _start_registered_server(socket_path: str, svc: ServiceRegistry) -> IPCServer:
    server = IPCServer(socket_path, svc, _registered_commands())
    await server.start()
    return server


@pytest.mark.parametrize(
    ("args", "kind"),
    [
        ({}, "missing"),
        ({"key": None}, "string_type"),
        ({"key": 123}, "string_type"),
        ({"key": ["sk_x"]}, "string_type"),
        ({"key": {"k": "sk_x"}}, "string_type"),
    ],
)
async def test_non_str_key_rejected_by_the_request_model(
    socket_path: str, args: dict, kind: str
) -> None:
    """key 가 없거나 str 이 아니면 4-게이트 전에 ``VALIDATION_ERROR`` 다 (#2683).

    키 조회(게이트①)에 닿지 않는다.
    """
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot())
    server = await _start_registered_server(socket_path, _make_service_registry(bm))
    try:
        response = await server._dispatch(
            {"id": "k1", "command": "signal.connect", "args": args}
        )
        assert response == {
            "id": "k1",
            "status": "error",
            "error": {
                "code": "VALIDATION_ERROR",
                "message": validation_message("signal.connect", ("key", kind)),
            },
        }
        bm.validate_signal_key.assert_not_awaited()
        bm.get_bot.assert_not_called()
    finally:
        await server.stop()


async def test_manager_not_configured_surfaces_service_not_configured(
    socket_path: str,
) -> None:
    """키 관리자 미구성 예외는 핸들러가 바꾸지 않고 그 코드로 나간다."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(side_effect=SignalKeyManagerNotConfigured())
    server = await _start_registered_server(socket_path, _make_service_registry(bm))
    try:
        response = await server._dispatch(
            {"id": "k2", "command": "signal.connect", "args": {"key": "sk_x"}}
        )
        bm.validate_signal_key.assert_awaited_once_with("sk_x")
        assert response["status"] == "error"
        assert response["error"]["code"] == "SERVICE_NOT_CONFIGURED"
    finally:
        await server.stop()


def _busy_registry() -> object:
    from ante.bot.signal_channel_registry import ChannelHandle, SignalChannelRegistry

    reg = SignalChannelRegistry()
    reg.register(ChannelHandle(session_id="existing", bot_id="bot-1", generation=0))
    return reg


@pytest.mark.parametrize(
    ("scenario", "expected_code"),
    [
        ("key_miss", "INVALID_SIGNAL_KEY"),
        ("not_running", "BOT_NOT_RUNNING"),
        ("not_accepting", "BOT_NOT_ACCEPTING_SIGNALS"),
        ("busy", "BOT_SIGNAL_CHANNEL_BUSY"),
    ],
)
async def test_expected_handshake_rejects_log_warning_without_traceback(
    socket_path: str,
    caplog: pytest.LogCaptureFixture,
    scenario: str,
    expected_code: str,
) -> None:
    """예상된 핸드셰이크 거부는 traceback 없는 WARNING 한 건으로만 로깅된다."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(
        return_value=None if scenario == "key_miss" else "bot-1"
    )
    bm.get_bot = MagicMock(
        return_value=_make_bot(
            status=BotStatus.STOPPED
            if scenario == "not_running"
            else BotStatus.RUNNING,
            accepts=scenario != "not_accepting",
        )
    )
    svc = _make_service_registry(bm)
    if scenario == "busy":
        svc.signal_channel_registry = _busy_registry()
    server = await _start_registered_server(socket_path, svc)
    try:
        caplog.set_level("DEBUG", logger="ante.ipc.server")
        caplog.clear()
        response = await server._dispatch(
            {"id": "r1", "command": "signal.connect", "args": {"key": "sk_secret"}}
        )
        assert response["error"]["code"] == expected_code

        records = [
            r for r in caplog.records if r.name == "ante.ipc.server" and r.levelno >= 30
        ]
        assert [r.levelname for r in records] == ["WARNING"]
        assert records[0].exc_info is None
        assert "sk_" not in caplog.text
    finally:
        await server.stop()


async def test_unexpected_handshake_error_logs_exception_with_traceback(
    socket_path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """예상 밖의 예외는 traceback 이 붙은 ERROR 로 로깅된다."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(side_effect=RuntimeError("boom"))
    server = await _start_registered_server(socket_path, _make_service_registry(bm))
    try:
        caplog.set_level("DEBUG", logger="ante.ipc.server")
        caplog.clear()
        response = await server._dispatch(
            {"id": "r2", "command": "signal.connect", "args": {"key": "sk_x"}}
        )
        assert response["error"]["code"] == "EXECUTION_ERROR"
        bm.validate_signal_key.assert_awaited_once()

        records = [
            r for r in caplog.records if r.name == "ante.ipc.server" and r.levelno >= 30
        ]
        assert [r.levelname for r in records] == ["ERROR"]
        assert records[0].exc_info is not None
    finally:
        await server.stop()


@pytest.mark.parametrize("first_frame", [[1, 2], 42, "text", None])
async def test_malformed_first_frame_closes_connection(
    socket_path: str, first_frame: object
) -> None:
    """비-dict 첫 프레임에는 응답 1프레임 뒤 연결을 닫는다(다음 요청 미처리)."""
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock()
    server = await _start_server(socket_path, bm)

    try:
        reader, writer = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(writer, first_frame)
        resp = json.loads((await _read_frame(reader)).decode("utf-8"))
        assert resp["id"] is None
        assert resp["error"]["code"] == "MALFORMED_REQUEST"

        try:
            await _write_json_frame(
                writer,
                {"id": "next", "command": "signal.connect", "args": {"key": "sk_x"}},
            )
        except ConnectionError:
            pass
        with pytest.raises((asyncio.IncompleteReadError, ConnectionError)):
            await asyncio.wait_for(reader.readexactly(4), timeout=5.0)
        bm.validate_signal_key.assert_not_called()

        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass

        # 닫히는 것은 그 연결뿐이다. 새 연결의 요청은 계속 처리된다.
        reader2, writer2 = await asyncio.open_unix_connection(socket_path)
        await _write_json_frame(writer2, {"id": "n2", "command": "no.such"})
        resp2 = json.loads((await _read_frame(reader2)).decode("utf-8"))
        assert resp2["error"]["code"] == "UNKNOWN_COMMAND"
        writer2.close()
        await writer2.wait_closed()
    finally:
        await server.stop()


class _AckFailingWriter:
    def __init__(self) -> None:
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        raise ConnectionResetError("peer gone")

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


async def test_ack_write_failure_unregisters_handle(
    socket_path: str, caplog: pytest.LogCaptureFixture
) -> None:
    """ack 전송이 실패하면 등록을 해제한 뒤 그 예외를 연결 처리로 다시 던진다."""
    from ante.bot.signal_channel_registry import SignalChannelRegistry

    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot())
    svc = _make_service_registry(bm)
    from ante.bot.signal_channel_registry import ChannelHandle

    channel_registry = SignalChannelRegistry()
    channel_registry.register(
        ChannelHandle(session_id="other", bot_id="bot-2", generation=0)
    )
    svc.signal_channel_registry = channel_registry
    server = IPCServer(socket_path, svc, _signal_only_registry())
    await server.start()
    try:
        reader = asyncio.StreamReader()
        payload = json.dumps(
            {"id": "a1", "command": "signal.connect", "args": {"key": "sk_x"}}
        ).encode("utf-8")
        reader.feed_data(struct.pack("!I", len(payload)) + payload)
        writer = _AckFailingWriter()
        caplog.set_level("DEBUG", logger="ante.ipc.server")
        caplog.clear()

        await asyncio.wait_for(
            server._handle_connection(reader, writer),  # type: ignore[arg-type]
            timeout=5.0,
        )

        assert len(writer.writes) == 1
        ack = json.loads(writer.writes[0][4:].decode("utf-8"))
        assert ack["status"] == "ok"
        assert writer.closed is True
        assert channel_registry.has_active_session("bot-1") is False
        assert channel_registry.has_active_session("bot-2") is True
        errors = [
            r
            for r in caplog.records
            if r.name == "ante.ipc.server" and r.levelname == "ERROR"
        ]
        assert len(errors) == 1
        assert errors[0].exc_info is not None
        assert isinstance(errors[0].exc_info[1], ConnectionResetError)

        retry = await server._dispatch(
            {"id": "a2", "command": "signal.connect", "args": {"key": "sk_x"}}
        )
        assert retry["status"] == "ok"
    finally:
        await server.stop()


# ── registry 등록 메타데이터 lock ────────────────────────────────────


async def test_signal_connect_registered_metadata() -> None:
    """signal.connect 가 read-only/stream/account_id_policy=none/audit None."""
    reg = CommandRegistry()
    register_all_handlers(reg)
    spec = reg.get("signal.connect")
    assert spec is not None
    assert spec.is_mutating is False
    assert spec.required_services == frozenset({"bot_manager"})
    assert spec.account_id_policy == "none"
    assert spec.audit_action is None


# ── connect audit · 키 비노출 · placeholder generation ──────────────────

_SECRET_SIGNAL_KEY = "sk_SECRET-signal-key-0123456789abcdef"


def _connect_registry_with(
    *, audit_logger: MagicMock | None = None, channel_registry: object | None = None
) -> tuple[ServiceRegistry, MagicMock]:
    bm = MagicMock()
    bm.validate_signal_key = AsyncMock(return_value="bot-1")
    bm.get_bot = MagicMock(return_value=_make_bot(account_id="acc-live"))
    svc = _make_service_registry(bm)
    svc.audit_logger = audit_logger
    svc.signal_channel_registry = channel_registry  # type: ignore[assignment]
    return svc, bm


async def test_connect_audit_member_is_ipc_sentinel_not_caller(
    socket_path: str,
) -> None:
    """connect 감사는 호출자가 아니라 고정 sentinel ``ipc`` 로 1회 남는다."""
    audit_logger = MagicMock()
    audit_logger.log = AsyncMock(return_value=None)
    svc, _ = _connect_registry_with(audit_logger=audit_logger)
    server = IPCServer(socket_path, svc, _signal_only_registry())
    await server.start()
    try:
        response = await server._dispatch(
            {
                "id": "c1",
                "command": "signal.connect",
                "args": {"key": "sk_x"},
                "actor": "agent-caller",
            }
        )
    finally:
        await server.stop()

    assert response["status"] == "ok", response
    audit_logger.log.assert_awaited_once_with(
        member_id="ipc",
        action="signal.connect",
        resource="bot:bot-1",
        detail="",
        ip="",
    )


def _collect_text(value: object, out: list[str], depth: int = 0) -> None:
    """값과 그 안에 중첩된 dict·list·tuple·예외·객체 속성을 문자열로 모은다."""
    if depth > 8:
        return
    out.append(repr(value))
    if isinstance(value, str):
        out.append(value)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            _collect_text(key, out, depth + 1)
            _collect_text(item, out, depth + 1)
    elif isinstance(value, (list, tuple, set, frozenset)):
        for item in value:
            _collect_text(item, out, depth + 1)
    elif isinstance(value, BaseException):
        out.append(str(value))
        _collect_text(value.args, out, depth + 1)
        for chained in (value.__cause__, value.__context__):
            if chained is not None:
                _collect_text(chained, out, depth + 1)
    elif hasattr(value, "__dict__") and not isinstance(value, type):
        _collect_text(vars(value), out, depth + 1)


def _all_log_record_text(caplog: pytest.LogCaptureFixture) -> str:
    """로그 레코드마다 메시지, 모든 속성(extra 포함)의 중첩 값, 예외 traceback."""
    import traceback

    parts: list[str] = []
    for record in caplog.records:
        parts.append(record.getMessage())
        _collect_text(vars(record), parts)
        if record.exc_info and record.exc_info[1] is not None:
            parts.extend(traceback.format_exception(*record.exc_info))
    return "\n".join(parts)


_CONNECT_ENDINGS = {
    "ok": "ok",
    "key_not_str": "VALIDATION_ERROR",
    "key_unknown": "INVALID_SIGNAL_KEY",
    "key_manager_missing": "SERVICE_NOT_CONFIGURED",
    "key_validation_raises": "EXECUTION_ERROR",
    "bot_missing": "BOT_NOT_FOUND",
    "bot_not_running": "BOT_NOT_RUNNING",
    "no_strategy": "BOT_NOT_ACCEPTING_SIGNALS",
    "not_accepting": "BOT_NOT_ACCEPTING_SIGNALS",
    "audit_raises": "EXECUTION_ERROR",
    "channel_busy": "BOT_SIGNAL_CHANNEL_BUSY",
    "registry_frozen": "EXECUTION_ERROR",
}


@pytest.mark.parametrize("ending", list(_CONNECT_ENDINGS))
async def test_signal_key_absent_on_every_connect_ending(
    socket_path: str, caplog: pytest.LogCaptureFixture, ending: str
) -> None:
    """handshake 가 어느 gate 에서 끝나도 봉투·로그·감사에 signal key 가 없다."""
    from ante.bot.signal_channel_registry import ChannelHandle, SignalChannelRegistry

    audit_logger = MagicMock()
    audit_logger.log = AsyncMock(return_value=None)
    channel_registry = SignalChannelRegistry()
    svc, bm = _connect_registry_with(
        audit_logger=audit_logger, channel_registry=channel_registry
    )
    key: object = _SECRET_SIGNAL_KEY
    bot = _make_bot(account_id="acc-live")
    bm.get_bot = MagicMock(return_value=bot)
    if ending == "key_not_str":
        key = [_SECRET_SIGNAL_KEY]
    elif ending == "key_unknown":
        bm.validate_signal_key = AsyncMock(return_value=None)
    elif ending == "key_manager_missing":
        bm.validate_signal_key = AsyncMock(side_effect=SignalKeyManagerNotConfigured())
    elif ending == "key_validation_raises":
        bm.validate_signal_key = AsyncMock(side_effect=RuntimeError("key store down"))
    elif ending == "bot_missing":
        bm.get_bot = MagicMock(return_value=None)
    elif ending == "bot_not_running":
        bot.status = BotStatus.STOPPED
    elif ending == "no_strategy":
        bot.strategy = None
    elif ending == "not_accepting":
        bot.strategy.meta.accepts_external_signals = False
    elif ending == "audit_raises":
        audit_logger.log = AsyncMock(side_effect=RuntimeError("audit down"))
    elif ending == "channel_busy":
        channel_registry.register(
            ChannelHandle(session_id="other", bot_id="bot-1", generation=0)
        )
    elif ending == "registry_frozen":
        channel_registry.freeze()

    server = IPCServer(socket_path, svc, _signal_only_registry())
    await server.start()
    try:
        with caplog.at_level(logging.DEBUG):
            response = await server._dispatch(
                {
                    "id": "c2",
                    "command": "signal.connect",
                    "args": {"key": key},
                    "actor": "agent-caller",
                }
            )
            logging.getLogger("ante.ipc.registry").debug("capture probe")
    finally:
        await server.stop()

    expected = _CONNECT_ENDINGS[ending]
    if expected == "ok":
        assert response["status"] == "ok", response
        assert set(response["result"]) == {
            "bot_id",
            "account_id",
            "session_id",
            "_stream",
        }
    else:
        assert response["status"] == "error", response
        assert response["error"]["code"] == expected, response
        assert any(r.name == "ante.ipc.server" for r in caplog.records)
    if ending != "key_not_str":
        bm.validate_signal_key.assert_awaited_once_with(_SECRET_SIGNAL_KEY)
    assert any(r.getMessage() == "capture probe" for r in caplog.records)
    assert _SECRET_SIGNAL_KEY not in json.dumps(response, default=repr)
    assert _SECRET_SIGNAL_KEY not in _all_log_record_text(caplog)
    audit_parts: list[str] = []
    _collect_text(audit_logger.log.await_args_list, audit_parts)
    assert _SECRET_SIGNAL_KEY not in "\n".join(audit_parts)


async def test_connect_placeholder_handle_snapshots_current_generation() -> None:
    """등록되는 placeholder handle 은 그 시점의 generation 을 갖는다."""
    from ante.bot.signal_channel_registry import SignalChannelRegistry

    channel_registry = SignalChannelRegistry()
    channel_registry.bump_generation("bot-1")
    channel_registry.bump_generation("bot-1")
    current = channel_registry.current_generation("bot-1")
    assert current != 0
    svc, _ = _connect_registry_with(channel_registry=channel_registry)

    result = await _handle_signal_connect(svc, SignalConnectRequest(key="sk_x"), "ipc")

    handle = channel_registry.get("bot-1", result["session_id"])
    assert handle is not None
    assert handle.generation == current
