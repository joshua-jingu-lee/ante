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
from ante.ipc.server import IPCServer

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
        result_kind="stream",
        required_services=frozenset({"bot_manager"}),
        account_id_policy="none",
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
            svc, {"key": "sk_x", "account_id": "SPOOF"}, "ipc"
        )

        assert result["bot_id"] == "bot-1"
        # account_id 는 bot.config 유래 — args spoof 값 무시.
        assert result["account_id"] == "acc-live"
        assert result["_stream"] == "signal.connect"

    async def test_missing_key_raises_invalid_signal_key_not_keyerror(self) -> None:
        """``args={}`` (key 없음) → InvalidSignalKey (KeyError 아님)."""
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot())
        svc = await self._svc(bm)

        with pytest.raises(InvalidSignalKey):
            await _handle_signal_connect(svc, {}, "ipc")

    async def test_gate1_key_miss_raises_invalid_signal_key(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value=None)
        bm.get_bot = MagicMock()
        svc = await self._svc(bm)

        with pytest.raises(InvalidSignalKey) as ei:
            await _handle_signal_connect(svc, {"key": "sk_bad"}, "ipc")
        assert ei.value.code == "INVALID_SIGNAL_KEY"

    async def test_manager_not_configured_propagates(self) -> None:
        """manager None → SignalKeyManagerNotConfigured (게이트① 위임)."""
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(side_effect=SignalKeyManagerNotConfigured())
        svc = await self._svc(bm)

        with pytest.raises(SignalKeyManagerNotConfigured) as ei:
            await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
        assert ei.value.code == "SERVICE_NOT_CONFIGURED"

    async def test_gate2_bot_not_found(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-x")
        bm.get_bot = MagicMock(return_value=None)
        svc = await self._svc(bm)

        with pytest.raises(BotNotFoundError) as ei:
            await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
        assert ei.value.code == "BOT_NOT_FOUND"

    async def test_gate3_bot_not_running_uses_lowercase_status_value(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot(status=BotStatus.STOPPED))
        svc = await self._svc(bm)

        with pytest.raises(BotNotRunning) as ei:
            await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
        assert ei.value.code == "BOT_NOT_RUNNING"
        # caller 가 bot.status.value(소문자)를 전달하는 계약 lock.
        assert str(ei.value) == "Bot is not running: bot-1 (status: stopped)"

    async def test_gate4_not_accepting_external_signals_english_literal(self) -> None:
        bm = MagicMock()
        bm.validate_signal_key = AsyncMock(return_value="bot-1")
        bm.get_bot = MagicMock(return_value=_make_bot(accepts=False))
        svc = await self._svc(bm)

        with pytest.raises(BotNotAcceptingSignals) as ei:
            await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")
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
            await _handle_signal_connect(svc, {"key": "sk_x"}, "ipc")


# ── registry 등록 메타데이터 lock ────────────────────────────────────


async def test_signal_connect_registered_metadata() -> None:
    """signal.connect 가 read-only/stream/account_id_policy=none/audit None."""
    reg = CommandRegistry()
    register_all_handlers(reg)
    spec = reg.get("signal.connect")
    assert spec is not None
    assert spec.is_mutating is False
    assert spec.result_kind == "stream"
    assert spec.required_services == frozenset({"bot_manager"})
    assert spec.account_id_policy == "none"
    assert spec.audit_action is None
    assert spec.result_key is None
