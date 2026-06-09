"""signal.connect real-UDS 왕복 통합 (#2334/#2337 T4).

real ``asyncio.start_unix_server`` IPCServer 위에서 핸드셰이크 wire strip → ack
→ ping/pong, fill 왕복(타 bot_id 미도착·1:1 no-`\\n`), idle 무-timeout, daemon
close('rotated'/'draining') closed frame 후 EOF, writer grace join(no hang) 을
검증한다. sleep 동기화 금지(asyncio.Event/wait_for), /tmp UDS, settle teardown.
"""

from __future__ import annotations

import asyncio
import json
import struct
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ante.bot.config import BotConfig, BotStatus
from ante.bot.manager import BotManager
from ante.bot.signal_channel_registry import SignalChannelRegistry
from ante.core.database import Database
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.ipc.registry import CommandRegistry, _handle_signal_connect
from ante.ipc.server import IPCServer
from ante.strategy.base import Signal, Strategy, StrategyMeta

pytestmark = pytest.mark.asyncio


class _AcceptingStrategy(Strategy):
    meta = StrategyMeta(
        name="accepting",
        version="1.0.0",
        description="accepts external signals",
        accepts_external_signals=True,
    )

    async def on_step(self, context: dict) -> list[Signal]:
        return []

    async def on_data(self, data: dict) -> list[Signal]:
        return []


async def _read_frame(reader: asyncio.StreamReader) -> dict:
    raw = await reader.readexactly(4)
    (length,) = struct.unpack("!I", raw)
    body = await reader.readexactly(length)
    return json.loads(body.decode("utf-8"))


async def _read_frame_bytes(reader: asyncio.StreamReader) -> bytes:
    raw = await reader.readexactly(4)
    (length,) = struct.unpack("!I", raw)
    return await reader.readexactly(length)


async def _write_frame(writer: asyncio.StreamWriter, obj: dict) -> None:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    writer.write(struct.pack("!I", len(payload)) + payload)
    await writer.drain()


class _Harness:
    def __init__(self) -> None:
        self.db: Database | None = None
        self.server: IPCServer | None = None
        self.bus = EventBus()
        self.reg = SignalChannelRegistry()
        self.manager: BotManager | None = None

    async def setup(self, socket_path: str, *, signal_key: str = "sk_test") -> None:
        self.db = Database(":memory:")
        await self.db.connect()

        skm = MagicMock()
        skm.validate_signal_key = None  # 사용 안 함(아래 manager 직접 mock).
        self.manager = BotManager(
            eventbus=self.bus,
            db=self.db,
            signal_channel_registry=self.reg,
        )
        await self.manager.initialize()

        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {"available": 1_000_000.0}

        await self.manager.create_bot(
            config=BotConfig(
                bot_id="bot-1",
                strategy_id="stg-1",
                interval_seconds=60,
                account_id="acc-test",
            ),
            strategy_cls=_AcceptingStrategy,
            ctx=ctx,
        )
        bot = self.manager.get_bot("bot-1")
        bot.strategy = _AcceptingStrategy(ctx=ctx)
        bot.status = BotStatus.RUNNING

        # signal key 검증을 고정 키로 mock(키 관리는 본 테스트 범위 밖).
        async def _validate(key: str) -> str | None:
            return "bot-1" if key == signal_key else None

        self.manager.validate_signal_key = _validate  # type: ignore[method-assign]

        svc = ServiceRegistry(
            account=MagicMock(),
            bot_manager=self.manager,
            treasury_manager=MagicMock(),
            dynamic_config=MagicMock(),
            approval=MagicMock(),
            reconciler=MagicMock(),
            eventbus=self.bus,
            signal_channel_registry=self.reg,
            audit_logger=None,
        )
        cmd_reg = CommandRegistry()
        cmd_reg.register(
            "signal.connect",
            _handle_signal_connect,
            is_mutating=False,
            result_kind="stream",
            required_services=frozenset({"bot_manager"}),
            account_id_policy="none",
        )
        self.server = IPCServer(socket_path, svc, cmd_reg)
        await self.server.start()

    async def teardown(self) -> None:
        if self.server is not None:
            await self.server.stop()
        if self.db is not None:
            await self.db.close()


@pytest.fixture
def socket_path() -> str:
    td = tempfile.mkdtemp(prefix="sig-int", dir="/tmp")
    return str(Path(td) / "t.sock")


async def _handshake(
    socket_path: str, key: str = "sk_test"
) -> tuple[asyncio.StreamReader, asyncio.StreamWriter, dict]:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    await _write_frame(
        writer, {"id": "h1", "command": "signal.connect", "args": {"key": key}}
    )
    ack = await asyncio.wait_for(_read_frame(reader), timeout=2.0)
    return reader, writer, ack


# ── 핸드셰이크 + ping/pong ───────────────────────────────────────────


async def test_handshake_ack_then_ping_pong(socket_path: str) -> None:
    h = _Harness()
    await h.setup(socket_path)
    try:
        reader, writer, ack = await _handshake(socket_path)
        assert ack["status"] == "ok"
        assert ack["result"]["bot_id"] == "bot-1"
        assert "_stream" not in ack["result"]  # 센티넬 strip.

        await _write_frame(writer, {"type": "ping"})
        pong = await asyncio.wait_for(_read_frame(reader), timeout=2.0)
        assert pong["type"] == "pong"

        writer.close()
        await writer.wait_closed()
    finally:
        await h.teardown()


# ── fill 왕복(타 bot_id 미도착·1:1 no-newline) ───────────────────────


async def test_fill_roundtrip_isolated_by_bot_id(socket_path: str) -> None:
    h = _Harness()
    await h.setup(socket_path)
    try:
        reader, writer, _ = await _handshake(socket_path)

        # bot-1 fill → 도착.
        await h.bus.publish(
            OrderFilledEvent(
                order_id="ORD-1",
                bot_id="bot-1",
                symbol="005930",
                side="buy",
                quantity=10.0,
                price=58200.0,
                commission=1.0,
                account_id="acc-test",
                fill_dedup_key="K1",
            )
        )
        raw = await asyncio.wait_for(_read_frame_bytes(reader), timeout=2.0)
        # 1:1 framing — payload 에 embedded newline 없음.
        assert b"\n" not in raw
        frame = json.loads(raw.decode("utf-8"))
        assert frame["type"] == "fill"
        assert frame["order_id"] == "ORD-1"

        # 타 bot_id fill → 미도착(다음 read 가 timeout).
        await h.bus.publish(
            OrderFilledEvent(
                order_id="ORD-OTHER",
                bot_id="bot-999",
                symbol="000660",
                side="sell",
                quantity=5.0,
                price=100.0,
                commission=0.5,
                account_id="acc-test",
                fill_dedup_key="K2",
            )
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.readexactly(4), timeout=0.3)

        writer.close()
        await writer.wait_closed()
    finally:
        await h.teardown()


# ── idle 무-timeout ──────────────────────────────────────────────────


async def test_idle_stream_no_timeout(socket_path: str) -> None:
    h = _Harness()
    await h.setup(socket_path)
    try:
        reader, writer, _ = await _handshake(socket_path)
        # 무전송 idle — daemon 이 close/EOF 하지 않는다.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(reader.read(1), timeout=0.3)
        assert not reader.at_eof()
        writer.close()
        await writer.wait_closed()
    finally:
        await h.teardown()


# ── daemon close('rotated') → closed frame 후 EOF ────────────────────


async def test_close_bot_rotated_emits_closed_then_eof(socket_path: str) -> None:
    h = _Harness()
    await h.setup(socket_path)
    try:
        reader, writer, _ = await _handshake(socket_path)
        # adopt 완료 대기 — registry 에 active session.
        for _ in range(100):
            await asyncio.sleep(0)
            handle = h.reg.get("bot-1", next(iter(h.reg._sessions["bot-1"])))
            if handle is not None and handle.out_queue is not None:
                break

        h.reg.close_bot("bot-1", "rotated")
        closed = await asyncio.wait_for(_read_frame(reader), timeout=2.0)
        assert closed == {"type": "closed", "reason": "rotated"}
        # closed frame 후 EOF(서버측 read_task 종료 → 연결 정리).
        eof = await asyncio.wait_for(reader.read(), timeout=2.0)
        assert eof == b""
        writer.close()
        await writer.wait_closed()
    finally:
        await h.teardown()


# ── shutdown sweep → {closed,draining} + drain ───────────────────────


async def test_shutdown_sweep_draining(socket_path: str) -> None:
    h = _Harness()
    await h.setup(socket_path)
    try:
        reader, writer, _ = await _handshake(socket_path)
        for _ in range(100):
            await asyncio.sleep(0)
            if h.reg.has_active_session("bot-1"):
                handle = h.reg.get("bot-1", next(iter(h.reg._sessions["bot-1"])))
                if handle is not None and handle.out_queue is not None:
                    break

        # shutdown sweep: freeze → close_all('draining') await-to-completion.
        h.reg.freeze()
        await asyncio.wait_for(h.reg.close_all("draining"), timeout=2.0)

        closed = await asyncio.wait_for(_read_frame(reader), timeout=2.0)
        assert closed == {"type": "closed", "reason": "draining"}
        writer.close()
        await writer.wait_closed()
    finally:
        await h.teardown()
