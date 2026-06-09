"""IPCServer._run_signal_stream host 단위 (#2334/#2337 T2/T3).

in-memory reader/writer 로 host 를 구동해 ack 왕복, fill relay, finally
teardown(mark_closed→_unsubscribe→unregister 정확히 1회), daemon-initiated
close(rotated/draining) closed frame, EOF graceful 종료를 lock 한다. real
socket 은 integration(T4) 에서 검증. sleep 금지.
"""

from __future__ import annotations

import asyncio
import json
import struct
from unittest.mock import MagicMock

import pytest

from ante.bot.signal_channel_registry import ChannelHandle, SignalChannelRegistry
from ante.core.registry import ServiceRegistry
from ante.eventbus.bus import EventBus
from ante.eventbus.events import OrderFilledEvent
from ante.ipc.server import IPCServer

pytestmark = pytest.mark.asyncio


class _FakeWriter:
    """write+drain 캡처용 fake StreamWriter (frame bytes 누적)."""

    def __init__(self) -> None:
        self.buffer = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.buffer.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None

    def frames(self) -> list[dict]:
        """누적 buffer 를 length-prefixed 프레임 dict 리스트로 디코드."""
        out: list[dict] = []
        view = memoryview(self.buffer)
        i = 0
        while i + 4 <= len(view):
            (length,) = struct.unpack("!I", view[i : i + 4])
            i += 4
            if i + length > len(view):
                break
            out.append(json.loads(bytes(view[i : i + length]).decode("utf-8")))
            i += length
        return out


def _frame_bytes(obj: dict) -> bytes:
    payload = json.dumps(obj, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def _make_bot(bus: EventBus) -> MagicMock:
    bot = MagicMock()
    bot.bot_id = "bot-1"
    bot.config.account_id = "acc-test"
    bot._ctx = MagicMock()
    return bot


def _make_server(
    bus: EventBus, reg: SignalChannelRegistry | None, bot: MagicMock
) -> IPCServer:
    bm = MagicMock()
    bm.get_bot = MagicMock(return_value=bot)
    svc = ServiceRegistry(
        account=MagicMock(),
        bot_manager=bm,
        treasury_manager=MagicMock(),
        dynamic_config=MagicMock(),
        approval=MagicMock(),
        reconciler=MagicMock(),
        eventbus=bus,
        signal_channel_registry=reg,
    )
    return IPCServer("/tmp/unused.sock", svc, MagicMock())


# ── ack 왕복 + fill relay ────────────────────────────────────────────


async def test_signal_frame_acked_and_fill_relayed() -> None:
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    # 전략 on_external_signal 구독은 본 테스트 범위 밖 — daemon-side relay 만 검증.
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    # signal 프레임 1개 후 EOF.
    reader.feed_data(_frame_bytes({"type": "ping"}))

    async def _drive() -> None:
        await server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]

    task = asyncio.ensure_future(_drive())
    # ping → pong relay 가 buffer 에 나타날 때까지 폴링 대신 짧은 yield.
    for _ in range(50):
        await asyncio.sleep(0)
        if any(f.get("type") == "pong" for f in writer.frames()):
            break

    # fill publish → daemon relay 로 fill 프레임 enqueue.
    await bus.publish(
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
    for _ in range(50):
        await asyncio.sleep(0)
        if any(f.get("type") == "fill" for f in writer.frames()):
            break

    reader.feed_eof()
    await asyncio.wait_for(task, timeout=2.0)

    frames = writer.frames()
    assert any(f.get("type") == "pong" for f in frames)
    assert any(f.get("type") == "fill" and f.get("order_id") == "ORD-1" for f in frames)
    # finally: unregister 정확히 1회 → _sessions 비움.
    assert reg.has_active_session("bot-1") is False


# ── finally teardown — EOF 경로 정확히 1회 ───────────────────────────


async def test_eof_finally_unsubscribes_and_unregisters_once() -> None:
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    reader.feed_eof()  # 즉시 EOF.

    await asyncio.wait_for(
        server._run_signal_stream(reader, writer, "bot-1", "s1"),  # type: ignore[arg-type]
        timeout=2.0,
    )
    # unregister 1회 — 세션 비움. 잔여 핸들러 0(unsubscribe).
    assert reg.has_active_session("bot-1") is False
    assert len(bus._handlers.get(OrderFilledEvent, [])) == 0


# ── daemon-initiated close → closed frame ────────────────────────────


async def test_close_bot_emits_closed_frame_and_unregisters() -> None:
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()

    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    # adopt 가 끝날 때까지 yield(handle.out_queue 바인딩 대기).
    for _ in range(50):
        await asyncio.sleep(0)
        if handle.out_queue is not None:
            break

    # daemon-initiated close — closed frame force-slot + closing_event set.
    reg.close_bot("bot-1", "rotated")

    await asyncio.wait_for(task, timeout=2.0)
    frames = writer.frames()
    assert frames[-1] == {"type": "closed", "reason": "rotated"}
    assert reg.has_active_session("bot-1") is False


# ── adopt-time generation re-check self-close (F4) ───────────────────


async def test_rotate_in_window_self_close_on_adopt() -> None:
    """register 후 stream 진입 전 generation bump → adopt 가 self-close(rotated)."""
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    # register 시 generation 0 스냅샷.
    handle = ChannelHandle(
        session_id="s1", bot_id="bot-1", generation=reg.current_generation("bot-1")
    )
    reg.register(handle)
    # rotate-in-window: stream 진입 전 generation bump.
    reg.bump_generation("bot-1")
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()

    await asyncio.wait_for(
        server._run_signal_stream(reader, writer, "bot-1", "s1"),  # type: ignore[arg-type]
        timeout=2.0,
    )
    frames = writer.frames()
    # 풀 루프 미진입 — single closed frame(rotated) 후 종료.
    assert frames == [{"type": "closed", "reason": "rotated"}]
    assert reg.has_active_session("bot-1") is False
    assert len(bus._handlers.get(OrderFilledEvent, [])) == 0


# ── headless (reg=None) — adopt/unregister 스킵, crash 없음 ───────────


async def test_headless_no_registry_drives_and_eof() -> None:
    bus = EventBus()
    bot = _make_bot(bus)
    server = _make_server(bus, None, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    reader.feed_data(_frame_bytes({"type": "ping"}))

    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    for _ in range(50):
        await asyncio.sleep(0)
        if any(f.get("type") == "pong" for f in writer.frames()):
            break
    reader.feed_eof()
    await asyncio.wait_for(task, timeout=2.0)
    assert any(f.get("type") == "pong" for f in writer.frames())
