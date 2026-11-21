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


HANG_GUARD_SECONDS = 5.0


async def test_join_waits_for_tasks_to_finish_on_their_own_before_cancelling(
    monkeypatch,
) -> None:
    """grace 안에 끝나는 read·writer task 는 취소하지 않고 끝날 때까지 기다린다."""
    monkeypatch.setattr(ChannelHandle, "JOIN_GRACE_SECONDS", 1e6)
    handle = _handle()
    release = asyncio.Event()
    flushed: list[str] = []

    async def _task(name: str) -> None:
        await release.wait()
        flushed.append(name)

    handle.read_task = asyncio.ensure_future(_task("read"))
    handle.writer_task = asyncio.ensure_future(_task("writer"))

    joiner = asyncio.ensure_future(handle.join())
    for _ in range(20):
        await asyncio.sleep(0)
    assert not joiner.done()
    assert not handle.read_task.cancelled()
    assert not handle.writer_task.cancelled()

    release.set()
    await asyncio.wait_for(joiner, timeout=HANG_GUARD_SECONDS)

    assert sorted(flushed) == ["read", "writer"]
    assert not handle.read_task.cancelled()
    assert not handle.writer_task.cancelled()


async def test_join_cancels_tasks_still_running_after_grace(monkeypatch) -> None:
    """grace 가 지나도 끝나지 않는 task 는 join 이 직접 cancel 하고 끝까지 기다린다."""
    monkeypatch.setattr(ChannelHandle, "JOIN_GRACE_SECONDS", 0)
    handle = _handle()
    never = asyncio.Event()
    handle.read_task = asyncio.ensure_future(never.wait())
    handle.writer_task = asyncio.ensure_future(never.wait())

    await asyncio.wait_for(handle.join(), timeout=HANG_GUARD_SECONDS)

    assert handle.read_task.cancelled()
    assert handle.writer_task.cancelled()


async def test_close_all_empty_registry_no_error() -> None:
    reg = SignalChannelRegistry()
    await asyncio.wait_for(reg.close_all("draining"), timeout=1.0)


# ── BotManager 수명주기 → close_bot / bump_generation ─────────────────


def _external_strategy_cls():
    """accepts_external_signals=True 전략(시그널 키 자동 발급·rotate 허용)."""
    from ante.strategy.base import Signal, Strategy, StrategyMeta

    class ExternalStrategy(Strategy):
        meta = StrategyMeta(
            name="external",
            version="1.0.0",
            description="test",
            accepts_external_signals=True,
        )

        async def on_step(self, context: dict) -> list[Signal]:
            return []

        async def on_data(self, data: dict) -> list[Signal]:
            return []

    return ExternalStrategy


@pytest.fixture
async def lifecycle(tmp_path):
    """registry·SignalKeyManager 를 주입한 BotManager 와 등록된 placeholder 핸들."""
    from unittest.mock import MagicMock

    from ante.bot import BotConfig, BotManager
    from ante.bot.signal_key import SignalKeyManager
    from ante.core import Database
    from ante.eventbus import EventBus
    from ante.eventbus.events import BotStoppedEvent, NotificationEvent

    db = Database(str(tmp_path / "lifecycle.db"))
    await db.connect()
    bus = EventBus()
    keys = SignalKeyManager(db)
    await keys.initialize()
    reg = SignalChannelRegistry()
    manager = BotManager(
        eventbus=bus,
        db=db,
        signal_key_manager=keys,
        signal_channel_registry=reg,
    )
    await manager.initialize()

    notifications: list[NotificationEvent] = []
    stopped: list[BotStoppedEvent] = []
    bus.subscribe(NotificationEvent, lambda e: notifications.append(e))
    bus.subscribe(BotStoppedEvent, lambda e: stopped.append(e))

    async def make_bot(*, auto_restart: bool = False):
        ctx = MagicMock()
        ctx.get_positions.return_value = {}
        ctx.get_balance.return_value = {}
        ctx._drain_actions.return_value = []
        config = BotConfig(
            bot_id="bot-1",
            strategy_id="external",
            account_id="acc-test",
            interval_seconds=999,
            auto_restart=auto_restart,
        )
        await manager.create_bot(config, _external_strategy_cls(), ctx)
        handle = _handle(bot_id="bot-1")
        reg.register(handle)
        return handle

    state = {
        "manager": manager,
        "bus": bus,
        "reg": reg,
        "keys": keys,
        "make_bot": make_bot,
        "notifications": notifications,
        "stopped": stopped,
    }
    yield state
    for task in list(manager._restart_tasks.values()):
        task.cancel()
    await asyncio.wait_for(manager.stop_all(), timeout=5.0)
    await asyncio.wait_for(db.close(), timeout=5.0)


async def test_delete_running_bot_closes_channel_as_deleted(lifecycle) -> None:
    """delete_bot 은 정지보다 먼저 채널을 'deleted' 로 닫는다."""
    manager = lifecycle["manager"]
    handle = await lifecycle["make_bot"]()
    await manager.start_bot("bot-1")

    await manager.delete_bot("bot-1")

    assert len(lifecycle["stopped"]) == 1
    assert manager.get_bot("bot-1") is None
    assert handle.closed is True
    assert handle.close_reason == "deleted"
    assert lifecycle["reg"].current_generation("bot-1") == 0


async def test_suppressed_stop_still_closes_channel(lifecycle) -> None:
    """알림을 억제한 정지도 채널을 'bot_stopped' 로 닫는다."""
    manager = lifecycle["manager"]
    handle = await lifecycle["make_bot"]()
    await manager.start_bot("bot-1")

    await manager.stop_bot("bot-1", suppress_notification=True)

    assert len(lifecycle["stopped"]) == 1
    assert [n.title for n in lifecycle["notifications"]] == ["봇 시작"]
    assert handle.closed is True
    assert handle.close_reason == "bot_stopped"


@pytest.mark.parametrize("auto_restart", [False, True])
async def test_bot_error_closes_channel_as_bot_stopped(
    lifecycle, auto_restart: bool
) -> None:
    """BotErrorEvent 는 auto_restart 와 무관하게 채널을 'bot_stopped' 로 닫는다."""
    from ante.eventbus.events import BotErrorEvent

    manager = lifecycle["manager"]
    handle = await lifecycle["make_bot"](auto_restart=auto_restart)

    await lifecycle["bus"].publish(
        BotErrorEvent(account_id="acc-test", bot_id="bot-1", error_message="boom")
    )

    assert [n.title for n in lifecycle["notifications"]] == ["봇 에러"]
    assert manager.get_restart_count("bot-1") == (1 if auto_restart else 0)
    assert handle.closed is True
    assert handle.close_reason == "bot_stopped"


async def test_rotate_bumps_generation_and_closes_channel_as_rotated(
    lifecycle,
) -> None:
    """rotate 성공 뒤 generation 을 올리고 채널을 'rotated' 로 닫는다."""
    manager = lifecycle["manager"]
    handle = await lifecycle["make_bot"]()
    old_key = await lifecycle["keys"].get_key("bot-1")
    assert old_key is not None

    new_key = await manager.rotate_signal_key("bot-1")

    assert new_key != old_key
    assert await lifecycle["keys"].get_key("bot-1") == new_key
    assert lifecycle["reg"].current_generation("bot-1") == 1
    assert handle.closed is True
    assert handle.close_reason == "rotated"
