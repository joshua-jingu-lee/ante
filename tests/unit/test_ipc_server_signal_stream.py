"""IPCServer._run_signal_stream host 단위 (#2334/#2337 T2/T3).

in-memory reader/writer 로 host 를 구동해 ack 왕복, fill relay, finally
teardown(mark_closed→_unsubscribe→unregister 정확히 1회), daemon-initiated
close(rotated/draining) closed frame, EOF graceful 종료를 lock 한다. real
socket 은 integration(T4) 에서 검증. sleep 금지.
"""

from __future__ import annotations

import asyncio
import contextlib
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


# ── bounded out_queue — 상한 초과 시 laggard close ────────────────────────


async def test_out_queue_overflow_closes_stream_as_lagged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """outbound 프레임이 SIGNAL_OUT_QUEUE_MAX 를 넘게 쌓이면 스트림은
    ``{closed, reason: lagged}`` 로 끝나고, 상한을 넘는 프레임은 내보내지 않는다."""
    from ante.bot import signal_channel as signal_channel_module
    from ante.ipc.server import SIGNAL_OUT_QUEUE_MAX

    sinks: list = []

    class _SinkCapturingChannel(signal_channel_module.SignalChannel):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            sinks.append(kwargs["sink"])

    monkeypatch.setattr(signal_channel_module, "SignalChannel", _SinkCapturingChannel)
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
    for _ in range(50):
        await asyncio.sleep(0)
        if handle.out_queue is not None:
            break
    assert len(sinks) == 1
    sink = sinks[0]
    for i in range(SIGNAL_OUT_QUEUE_MAX + 1):
        sink({"type": "probe", "seq": i})
    reader.feed_eof()
    await asyncio.wait_for(task, timeout=2.0)

    frames = writer.frames()
    probes = [f for f in frames if f.get("type") == "probe"]
    assert frames[-1] == {"type": "closed", "reason": "lagged"}
    assert len(probes) < SIGNAL_OUT_QUEUE_MAX + 1
    assert reg.has_active_session("bot-1") is False


# ── teardown 순서: in-flight publish·closing_event·flush-before-cancel ──────


class _GatedWriter(_FakeWriter):
    """``drain`` 이 ``gate`` 가 열릴 때까지 멈추는 writer (느린 client 모사)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = asyncio.Event()
        self.drain_calls = 0

    async def drain(self) -> None:
        self.drain_calls += 1
        await self.gate.wait()


async def _yield_until(predicate, limit: int = 200) -> bool:  # noqa: ANN001
    for _ in range(limit):
        if predicate():
            return True
        await asyncio.sleep(0)
    return predicate()


def _capture_sinks(monkeypatch: pytest.MonkeyPatch) -> list:
    from ante.bot import signal_channel as signal_channel_module

    sinks: list = []

    class _SinkCapturingChannel(signal_channel_module.SignalChannel):
        def __init__(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
            super().__init__(*args, **kwargs)
            sinks.append(kwargs["sink"])

    monkeypatch.setattr(signal_channel_module, "SignalChannel", _SinkCapturingChannel)
    return sinks


def _blocking_signal_subscriber(
    bus: EventBus,
) -> tuple[asyncio.Event, asyncio.Event, list[str]]:
    from ante.eventbus.events import ExternalSignalEvent

    entered = asyncio.Event()
    release = asyncio.Event()
    outcome: list[str] = []

    async def _slow_on_data(event: object) -> None:
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            outcome.append("cancelled")
            raise
        outcome.append("completed")

    bus.subscribe(ExternalSignalEvent, _slow_on_data)
    return entered, release, outcome


_SIGNAL_FRAME = {"type": "signal", "symbol": "005930", "side": "buy"}


async def test_daemon_close_waits_for_inflight_publish_before_ending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """daemon close 는 진행 중인 publish 가 끝날 때까지 스트림을 끝내지 않는다."""
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 3600.0)
    bus = EventBus()
    entered, release, outcome = _blocking_signal_subscriber(bus)
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    reader.feed_data(_frame_bytes(_SIGNAL_FRAME))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(entered.is_set)

        reg.close_bot("bot-1", "rotated")
        reader.feed_data(_frame_bytes(_SIGNAL_FRAME))
        assert not await _yield_until(task.done)
        assert outcome == []

        release.set()
        await asyncio.wait_for(task, timeout=5.0)
        for _ in range(50):
            await asyncio.sleep(0)
        assert outcome == ["completed"]
        assert reg.has_active_session("bot-1") is False
    finally:
        release.set()
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_inflight_publish_survives_grace_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """grace 가 지나도 in-flight publish 자체는 취소되지 않고 백그라운드에서 끝난다."""
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 0)
    bus = EventBus()
    entered, release, outcome = _blocking_signal_subscriber(bus)
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    reader.feed_data(_frame_bytes(_SIGNAL_FRAME))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(entered.is_set)

        reg.close_bot("bot-1", "rotated")
        await asyncio.wait_for(task, timeout=5.0)
        assert outcome == []

        release.set()
        assert await _yield_until(lambda: bool(outcome))
        assert outcome == ["completed"]
    finally:
        release.set()
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_headless_lagged_teardown_ends_stream_with_stalled_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """registry 없는 스트림도 laggard 가 supervisor 를 깨워 EOF 없이 끝난다."""
    from ante.ipc import server as server_module
    from ante.ipc.server import SIGNAL_OUT_QUEUE_MAX

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 0)
    sinks = _capture_sinks(monkeypatch)
    bus = EventBus()
    bot = _make_bot(bus)
    server = _make_server(bus, None, bot)

    reader = asyncio.StreamReader()
    writer = _GatedWriter()
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(lambda: len(sinks) == 1)
        sink = sinks[0]
        sink({"type": "probe", "seq": -1})
        assert await _yield_until(lambda: writer.drain_calls == 1)

        for i in range(SIGNAL_OUT_QUEUE_MAX + 1):
            sink({"type": "probe", "seq": i})

        assert await _yield_until(task.done)
        assert len(bus._handlers.get(OrderFilledEvent, [])) == 0
    finally:
        writer.gate.set()
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_handle_close_wakes_supervisor_with_stalled_writer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """adopt 된 handle 의 동기 close 가 writer 가 막혀 있어도 스트림을 끝낸다."""
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 0)
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _GatedWriter()
    reader.feed_data(_frame_bytes({"type": "ping"}))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(lambda: writer.drain_calls == 1)
        assert writer.frames() == [{"type": "pong"}]

        reg.close_bot("bot-1", "rotated")

        assert await _yield_until(task.done)
        assert reg.has_active_session("bot-1") is False
    finally:
        writer.gate.set()
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_handle_closed_before_adopt_self_closes_without_eof() -> None:
    """adopt 전에 닫힌 handle 은 풀 루프 없이 closed 1프레임으로 끝난다."""
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    handle.close("bot_stopped")
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(task.done)
        assert writer.frames() == [{"type": "closed", "reason": "bot_stopped"}]
        assert reg.has_active_session("bot-1") is False
    finally:
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_daemon_close_flushes_closed_frame_behind_pending_drain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """daemon close 는 앞 프레임 drain 중에도 closed 프레임을 보낸 뒤 끝낸다."""
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 3600.0)
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _GatedWriter()
    reader.feed_data(_frame_bytes({"type": "ping"}))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(lambda: writer.drain_calls == 1)

        reg.close_bot("bot-1", "rotated")
        assert not await _yield_until(task.done)
        writer.gate.set()
        await asyncio.wait_for(task, timeout=5.0)

        assert writer.frames() == [
            {"type": "pong"},
            {"type": "closed", "reason": "rotated"},
        ]
        assert reg.has_active_session("bot-1") is False
    finally:
        writer.gate.set()
        reader.feed_eof()
        await asyncio.wait_for(task, timeout=5.0)


async def test_natural_eof_ends_stream_without_grace_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """closing_event 없이 EOF 로 끝나면 grace 를 기다리지 않고 바로 정리한다."""
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 3600.0)
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
    try:
        assert await _yield_until(lambda: handle.out_queue is not None)
        reader.feed_eof()
        assert await _yield_until(task.done)
        assert writer.frames() == []
        assert reg.has_active_session("bot-1") is False
    finally:
        reader.feed_eof()
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


# ── 프레임 크기 상한 · 순서 · read timeout 부재 ───────────────────────────────

_ONE_MIB = 1_048_576


def _frame_with_payload_size(size: int) -> dict:
    """직렬화 결과가 정확히 ``size`` 바이트인 프레임."""
    overhead = len(json.dumps({"type": "probe", "pad": ""}).encode("utf-8"))
    return {"type": "probe", "pad": "x" * (size - overhead)}


async def _finish(task: asyncio.Future, reader: asyncio.StreamReader) -> None:
    reader.feed_eof()
    if not await _yield_until(task.done):
        task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def test_encode_signal_frame_accepts_one_mib_and_rejects_one_more_byte() -> None:
    """signal outbound 프레임도 페이로드 1_048_576 바이트가 상한이다."""
    from ante.ipc.exceptions import MessageTooLargeError
    from ante.ipc.server import _encode_signal_frame

    data = _encode_signal_frame(_frame_with_payload_size(_ONE_MIB))
    (length,) = struct.unpack("!I", data[:4])
    assert length == _ONE_MIB

    with pytest.raises(MessageTooLargeError):
        _encode_signal_frame(_frame_with_payload_size(_ONE_MIB + 1))


async def test_oversized_outbound_frame_reports_error_and_stream_stays_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """1MB 초과 outbound 프레임은 result_too_large 오류로 바뀌고 스트림은 계속된다."""
    sinks = _capture_sinks(monkeypatch)
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
    try:
        assert await _yield_until(lambda: len(sinks) == 1)
        sinks[0](_frame_with_payload_size(_ONE_MIB + 1))
        assert await _yield_until(lambda: len(writer.frames()) == 1)
        assert writer.frames() == [{"type": "error", "message": "result_too_large"}]

        reader.feed_data(_frame_bytes({"type": "ping"}))
        assert await _yield_until(lambda: len(writer.frames()) == 2)
        assert writer.frames()[1] == {"type": "pong"}
        assert not task.done()
        assert reg.has_active_session("bot-1") is True
    finally:
        await _finish(task, reader)


async def test_outbound_frames_are_written_in_enqueue_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """writer 가 밀려 쌓인 outbound 프레임은 넣은 순서대로 나간다."""
    sinks = _capture_sinks(monkeypatch)
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _GatedWriter()
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(lambda: len(sinks) == 1)
        sinks[0]({"type": "probe", "seq": -1})
        assert await _yield_until(lambda: writer.drain_calls == 1)
        for i in range(5):
            sinks[0]({"type": "probe", "seq": i})
        writer.gate.set()
        assert await _yield_until(lambda: len(writer.frames()) == 6)
        assert [f["seq"] for f in writer.frames()] == [-1, 0, 1, 2, 3, 4]
    finally:
        writer.gate.set()
        await _finish(task, reader)


async def test_idle_stream_survives_when_every_finite_timeout_expires_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """유한 timeout 이 즉시 만료되는 시계에서도 idle 스트림의 read 는 끊기지 않는다."""
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)
    real_wait_for = asyncio.wait_for
    expired: list[object] = []

    async def _expire_immediately(aw, timeout=None):  # noqa: ANN001, ANN202
        if timeout is None:
            return await real_wait_for(aw, None)
        expired.append(aw)
        if asyncio.iscoroutine(aw):
            aw.close()
        raise TimeoutError

    class _ExpiredTimeout:
        def __init__(self, delay: float | None) -> None:
            self._delay = delay

        async def __aenter__(self) -> None:
            if self._delay is not None:
                raise TimeoutError

        async def __aexit__(self, *exc: object) -> bool:
            return False

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    with monkeypatch.context() as m:
        m.setattr(asyncio, "wait_for", _expire_immediately)
        m.setattr(asyncio, "timeout", _ExpiredTimeout)
        task = asyncio.ensure_future(
            server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
        )
        assert await _yield_until(lambda: handle.out_queue is not None)
        assert not await _yield_until(task.done)
        reader.feed_data(_frame_bytes({"type": "ping"}))
        assert await _yield_until(lambda: writer.frames() == [{"type": "pong"}])
        assert not task.done()
        assert expired == []
        reader.feed_eof()
        assert await _yield_until(task.done)
    await task


async def test_oversized_inbound_frame_ends_stream_without_reading_further() -> None:
    """1MB 를 넘는 inbound 길이 접두사를 받으면 뒤따르는 프레임을 읽지 않고 끝낸다."""
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    reader.feed_data(struct.pack("!I", _ONE_MIB + 1) + _frame_bytes({"type": "ping"}))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(task.done)
        assert writer.frames() == []
        assert reg.has_active_session("bot-1") is False
        assert len(bus._handlers.get(OrderFilledEvent, [])) == 0
    finally:
        await _finish(task, reader)


# ── writer 소유: 스트림 host 는 writer 를 닫지 않는다 ─────────────────────────


@pytest.mark.parametrize("ending", ["eof", "daemon_close"])
async def test_stream_host_leaves_writer_open_for_connection_owner(
    ending: str,
) -> None:
    """스트림이 끝나도 writer close 는 연결 처리부의 몫으로 남긴다."""
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
    try:
        assert await _yield_until(lambda: handle.out_queue is not None)
        if ending == "eof":
            reader.feed_eof()
        else:
            reg.close_bot("bot-1", "rotated")
        assert await _yield_until(task.done)
        assert reg.has_active_session("bot-1") is False
        assert writer.closed is False
    finally:
        await _finish(task, reader)


async def test_adopt_self_close_leaves_writer_open_for_connection_owner() -> None:
    """adopt 시점 self-close 도 closed 프레임만 쓰고 writer 는 닫지 않는다."""
    bus = EventBus()
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(
        session_id="s1", bot_id="bot-1", generation=reg.current_generation("bot-1")
    )
    reg.register(handle)
    reg.bump_generation("bot-1")
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _FakeWriter()
    await asyncio.wait_for(
        server._run_signal_stream(reader, writer, "bot-1", "s1"),  # type: ignore[arg-type]
        timeout=5.0,
    )
    assert writer.frames() == [{"type": "closed", "reason": "rotated"}]
    assert reg.has_active_session("bot-1") is False
    assert writer.closed is False


# ── teardown 이 채널을 닫는 시점 ─────────────────────────────────────────────


def _recording_signal_subscriber(bus: EventBus) -> list[object]:
    from ante.eventbus.events import ExternalSignalEvent

    received: list[object] = []

    async def _on_signal(event: object) -> None:
        received.append(event)

    bus.subscribe(ExternalSignalEvent, _on_signal)
    return received


async def test_lagged_teardown_rejects_inbound_signal_before_supervisor_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """laggard teardown 이 시작되면 같은 read 루프의 다음 signal 도 발행하지 않는다."""
    from ante.ipc import server as server_module
    from ante.ipc.server import SIGNAL_OUT_QUEUE_MAX

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 0)
    sinks = _capture_sinks(monkeypatch)
    bus = EventBus()
    received = _recording_signal_subscriber(bus)
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _GatedWriter()
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(lambda: len(sinks) == 1)
        sinks[0]({"type": "probe", "seq": -1})
        assert await _yield_until(lambda: writer.drain_calls == 1)
        for i in range(SIGNAL_OUT_QUEUE_MAX):
            sinks[0]({"type": "probe", "seq": i})
        assert handle.out_queue is not None and handle.out_queue.full()

        reader.feed_data(_frame_bytes({"type": "ping"}) + _frame_bytes(_SIGNAL_FRAME))
        assert await _yield_until(task.done)
        for _ in range(50):
            await asyncio.sleep(0)

        assert handle.closing_event is not None and handle.closing_event.is_set()
        assert received == []
        assert reg.has_active_session("bot-1") is False
    finally:
        writer.gate.set()
        await _finish(task, reader)


class _DeadWriter(_FakeWriter):
    """첫 drain 에서 연결이 끊긴 writer."""

    async def drain(self) -> None:
        raise ConnectionResetError("peer gone")


async def test_natural_teardown_closes_channel_before_awaiting_inflight_publish(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """writer 가 죽은 스트림은 in-flight publish 를 기다리기 전에 채널부터 닫는다.

    채널이 닫힌 뒤에는 버퍼에 남은 다음 signal 프레임을 발행하지 않는다.
    """
    from ante.ipc import server as server_module

    monkeypatch.setattr(server_module, "SIGNAL_INFLIGHT_GRACE", 3600.0)
    sinks = _capture_sinks(monkeypatch)
    bus = EventBus()
    entered, release, outcome = _blocking_signal_subscriber(bus)
    reg = SignalChannelRegistry()
    bot = _make_bot(bus)
    handle = ChannelHandle(session_id="s1", bot_id="bot-1", generation=0)
    reg.register(handle)
    server = _make_server(bus, reg, bot)

    reader = asyncio.StreamReader()
    writer = _DeadWriter()
    reader.feed_data(_frame_bytes(_SIGNAL_FRAME) + _frame_bytes(_SIGNAL_FRAME))
    task = asyncio.ensure_future(
        server._run_signal_stream(reader, writer, "bot-1", "s1")  # type: ignore[arg-type]
    )
    try:
        assert await _yield_until(entered.is_set)
        sinks[0]({"type": "probe"})
        assert await _yield_until(
            lambda: handle.writer_task is not None and handle.writer_task.done()
        )
        assert not await _yield_until(task.done)
        assert outcome == []

        release.set()
        assert await _yield_until(task.done)
        for _ in range(50):
            await asyncio.sleep(0)

        assert outcome == ["completed"]
        assert reg.has_active_session("bot-1") is False
        assert writer.closed is False
    finally:
        release.set()
        await _finish(task, reader)
