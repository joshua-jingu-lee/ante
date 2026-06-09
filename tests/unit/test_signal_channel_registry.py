"""SignalChannelRegistry / ChannelHandle 단위 테스트 (#2334/#2337 T2).

register atomic check-and-insert(단일-connect), unregister inner-dict 정리,
close_bot snapshot 순회·idempotent, freeze, generation, ChannelHandle 2단계
생명주기(placeholder close → reason 래치, adopted close → frame+event), close_all
join-to-completion 을 lock 한다. sleep 금지(asyncio.Event/Queue + wait_for).
"""

from __future__ import annotations

import asyncio

import pytest

from ante.bot.exceptions import BotSignalChannelBusy, SignalChannelRegistryFrozen
from ante.bot.signal_channel_registry import ChannelHandle, SignalChannelRegistry

pytestmark = pytest.mark.asyncio


def _handle(
    bot_id: str = "bot-1", session_id: str = "s1", generation: int = 0
) -> ChannelHandle:
    return ChannelHandle(session_id=session_id, bot_id=bot_id, generation=generation)


# ── register / has_active_session / unregister ───────────────────────


async def test_register_then_has_active_session() -> None:
    reg = SignalChannelRegistry()
    assert reg.has_active_session("bot-1") is False
    reg.register(_handle())
    assert reg.has_active_session("bot-1") is True
    assert reg.get("bot-1", "s1") is not None


async def test_second_same_bot_register_raises_busy() -> None:
    reg = SignalChannelRegistry()
    reg.register(_handle(session_id="s1"))
    with pytest.raises(BotSignalChannelBusy) as ei:
        reg.register(_handle(session_id="s2"))
    # keyless 메시지(bot_id/session_id 비노출) + stable code.
    assert ei.value.code == "BOT_SIGNAL_CHANNEL_BUSY"
    assert "bot-1" not in str(ei.value)
    assert "s2" not in str(ei.value)


async def test_register_frozen_raises() -> None:
    reg = SignalChannelRegistry()
    reg.freeze()
    with pytest.raises(SignalChannelRegistryFrozen):
        reg.register(_handle())
    # 누수 0 — 등록 안 됨.
    assert reg.has_active_session("bot-1") is False


async def test_unregister_cleans_inner_dict() -> None:
    reg = SignalChannelRegistry()
    reg.register(_handle())
    reg.unregister("bot-1", "s1")
    assert reg.has_active_session("bot-1") is False
    # inner dict 정리로 같은 bot 재등록 가능(BUSY 아님).
    reg.register(_handle())
    assert reg.has_active_session("bot-1") is True


async def test_unregister_missing_key_no_op() -> None:
    reg = SignalChannelRegistry()
    # 미등록 bot/session — raise 안 함(멱등).
    reg.unregister("bot-x", "s-x")
    reg.register(_handle())
    reg.unregister("bot-1", "s1")
    # 두 번째 unregister 도 no-op.
    reg.unregister("bot-1", "s1")
    assert reg.has_active_session("bot-1") is False


# ── generation (rotate-in-window) ────────────────────────────────────


async def test_generation_starts_zero_and_bumps() -> None:
    reg = SignalChannelRegistry()
    assert reg.current_generation("bot-1") == 0
    reg.bump_generation("bot-1")
    assert reg.current_generation("bot-1") == 1
    reg.bump_generation("bot-1")
    assert reg.current_generation("bot-1") == 2


# ── close_bot (snapshot·idempotent·unregister 안 함) ──────────────────


async def test_close_bot_counts_and_idempotent() -> None:
    reg = SignalChannelRegistry()
    reg.register(_handle())
    assert reg.close_bot("bot-1", "rotated") == 1
    # 2nd close — first-wins, 0건.
    assert reg.close_bot("bot-1", "rotated") == 0
    # close_bot 은 unregister 하지 않는다(스트림 finally 소유).
    assert reg.has_active_session("bot-1") is True


async def test_close_bot_missing_bot_returns_zero() -> None:
    reg = SignalChannelRegistry()
    assert reg.close_bot("bot-x", "deleted") == 0


# ── ChannelHandle 2단계 생명주기 ─────────────────────────────────────


async def test_placeholder_close_latches_pending_reason() -> None:
    """adopt 전(데이터플레인 None) close → reason 만 래치(frame/event 없음)."""
    handle = _handle()
    assert handle.out_queue is None
    assert handle.close("rotated") is True
    assert handle.closed is True
    assert handle.close_reason == "rotated"
    assert handle._pending_close_reason == "rotated"
    # 2nd close — first-wins.
    assert handle.close("deleted") is False
    assert handle.close_reason == "rotated"


async def test_adopted_close_force_slots_frame_and_sets_event() -> None:
    """adopt 후 close → on_closed 호출 + closed frame force-slot + closing_event."""
    handle = _handle()
    out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=4)
    closing_event = asyncio.Event()
    closed_flag = {"called": False}

    def _on_closed() -> None:
        closed_flag["called"] = True

    handle.out_queue = out_queue
    handle.on_closed = _on_closed
    handle.closing_event = closing_event

    assert handle.close("rotated") is True
    assert closed_flag["called"] is True
    assert closing_event.is_set() is True
    frame = out_queue.get_nowait()
    assert frame == {"type": "closed", "reason": "rotated"}


async def test_adopted_close_queue_full_drops_one_then_enqueues() -> None:
    """out_queue full 이어도 closed frame 은 force-slot(1 drop 후 enqueue)."""
    handle = _handle()
    out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=2)
    out_queue.put_nowait({"type": "fill", "n": 1})
    out_queue.put_nowait({"type": "fill", "n": 2})
    handle.out_queue = out_queue
    handle.closing_event = asyncio.Event()

    assert handle.close("lagged") is True
    # 가장 오래된 1개 drop → 두 번째 fill + closed frame.
    frames = [out_queue.get_nowait(), out_queue.get_nowait()]
    assert {"type": "fill", "n": 2} in frames
    assert {"type": "closed", "reason": "lagged"} in frames


# ── close_all (await-to-completion) ──────────────────────────────────


async def test_close_all_closes_and_joins_to_completion() -> None:
    """close_all → 각 handle close(draining) + read/writer task join-to-completion.

    supervisor 를 모사해 ``closing_event`` set 시 read_task 가 자연 종료하도록
    한다(flush-before-cancel 양보). join 은 grace 안에 자연 정리를 await 한다.
    """
    reg = SignalChannelRegistry()
    handle = _handle()
    handle.out_queue = asyncio.Queue(maxsize=8)
    closing_event = asyncio.Event()
    handle.closing_event = closing_event

    started = asyncio.Event()
    naturally_exited = asyncio.Event()

    async def _fake_read() -> None:
        started.set()
        # supervisor 모사 — closing_event set 되면 자연 종료.
        await closing_event.wait()
        naturally_exited.set()

    read_task = asyncio.ensure_future(_fake_read())
    handle.read_task = read_task
    reg.register(handle)

    await asyncio.wait_for(started.wait(), timeout=1.0)
    # close_all 은 close(draining)(closing_event set) + join(자연 정리 await).
    await asyncio.wait_for(reg.close_all("draining"), timeout=2.0)

    assert handle.closed is True
    assert handle.close_reason == "draining"
    assert read_task.done()
    assert naturally_exited.is_set() is True


async def test_close_all_empty_registry_no_error() -> None:
    reg = SignalChannelRegistry()
    await asyncio.wait_for(reg.close_all("draining"), timeout=1.0)
