"""SignalChannel 데몬 outbound 데이터플레인 단위 (#2334/#2337 T3).

sink/is_full/on_lagged seam, ``_closed`` no-op(stale-publish layer2), full-laggard
(seen 미마킹·재전달 보존), ``__contains__`` non-mutating, dedup-after-enqueue,
real EventBus + full queue 무stall(INV-OUT-2/6) 를 lock 한다. sleep 금지.
"""

from __future__ import annotations

import asyncio

import pytest

from ante.bot.signal_channel import SignalChannel
from ante.eventbus.bus import EventBus
from ante.eventbus.events import OrderFilledEvent, OrderRejectedEvent
from ante.eventbus.fill_dedup_guard import FillDedupGuard

pytestmark = pytest.mark.asyncio


def _make_channel(
    *,
    sink: list[dict] | None = None,
    is_full: bool = False,
    on_lagged_calls: list[int] | None = None,
):
    """sink 콜백을 list append 로, is_full 을 상수 콜백으로 주입한 채널."""
    from unittest.mock import AsyncMock, MagicMock

    bot = MagicMock()
    bot.bot_id = "bot-001"
    bot.config.account_id = "acc-test"
    eventbus = MagicMock()
    eventbus.publish = AsyncMock()
    eventbus.subscribe = MagicMock()
    eventbus.unsubscribe = MagicMock()
    ctx = MagicMock()

    captured = sink if sink is not None else []
    lagged = on_lagged_calls if on_lagged_calls is not None else []

    def _on_lagged() -> None:
        lagged.append(1)

    ch = SignalChannel(
        bot,
        eventbus,
        ctx,
        sink=captured.append,
        is_full=lambda: is_full,
        on_lagged=_on_lagged,
    )
    return ch, captured, lagged


def _fill(key: str = "K1") -> OrderFilledEvent:
    return OrderFilledEvent(
        order_id="ORD-1",
        bot_id="bot-001",
        symbol="005930",
        side="buy",
        quantity=10.0,
        price=58200.0,
        commission=87.3,
        account_id="acc-test",
        fill_dedup_key=key,
    )


# ── _closed no-op (stale-publish layer2) ─────────────────────────────


async def test_closed_channel_on_fill_no_op() -> None:
    ch, captured, _ = _make_channel()
    ch.mark_closed()
    await ch._on_fill(_fill())
    assert captured == []  # sink 미호출.


async def test_closed_channel_on_order_update_no_op() -> None:
    ch, captured, _ = _make_channel()
    ch.mark_closed()
    await ch._on_order_update(
        OrderRejectedEvent(
            order_id="ORD-2", bot_id="bot-001", reason="x", account_id="acc-test"
        )
    )
    assert captured == []


# ── full-laggard (seen 미마킹·재전달 보존) ───────────────────────────


async def test_full_queue_schedules_lagged_and_does_not_mark_seen() -> None:
    lagged: list[int] = []
    ch, captured, lagged = _make_channel(is_full=True, on_lagged_calls=lagged)
    await ch._on_fill(_fill(key="K1"))
    # full → schedule_lagged 1회, sink 미호출, seen 미마킹.
    assert captured == []
    assert len(lagged) == 1
    assert "K1" not in ch._fill_dedup_guard  # 재전달 보존.


async def test_lagged_redelivery_after_recovery() -> None:
    """full 로 drop 됐던 fill 은 seen 미마킹이라 큐 회복 후 재전달된다."""
    captured: list[dict] = []
    # 1차: full → drop(미마킹).
    ch, captured, _ = _make_channel(sink=captured, is_full=True)
    await ch._on_fill(_fill(key="K1"))
    assert captured == []
    # _schedule_lagged 가 _closed 를 flip 하므로 회복 재현은 새 채널로 검증.
    ch2, captured2, _ = _make_channel(is_full=False)
    await ch2._on_fill(_fill(key="K1"))
    assert len(captured2) == 1
    assert captured2[0]["fill_dedup_key"] == "K1"


# ── __contains__ non-mutating ────────────────────────────────────────


async def test_contains_is_non_mutating() -> None:
    guard = FillDedupGuard()
    assert ("K1" in guard) is False
    # 단순 멤버십 조회는 상태를 바꾸지 않는다 — 반복 조회 후에도 미마킹.
    assert ("K1" in guard) is False
    assert guard.seen_or_add("K1") is False  # 처음 추가.
    assert ("K1" in guard) is True
    assert guard.seen_or_add("K1") is True  # 이미 처리됨.


# ── dedup-after-enqueue (INV-OUT-4) ──────────────────────────────────


async def test_dedup_mark_after_enqueue_commits_on_success() -> None:
    ch, captured, _ = _make_channel(is_full=False)
    await ch._on_fill(_fill(key="K1"))
    await ch._on_fill(_fill(key="K1"))
    # enqueue 성공 후 seen 커밋 → 두 번째는 read-only 게이트에서 skip.
    assert len(captured) == 1
    assert "K1" in ch._fill_dedup_guard


async def test_empty_key_not_deduped() -> None:
    ch, captured, _ = _make_channel(is_full=False)
    await ch._on_fill(_fill(key=""))
    await ch._on_fill(_fill(key=""))
    assert len(captured) == 2  # 빈키는 dedup 비대상.


# ── real EventBus + full queue 무stall (INV-OUT-2/6) ─────────────────


async def test_real_eventbus_full_queue_does_not_stall_publish() -> None:
    """real EventBus 핸들러 inline 에서 out_queue full 이어도 publish 무stall·미전파."""
    bus = EventBus()

    from unittest.mock import MagicMock

    bot = MagicMock()
    bot.bot_id = "bot-001"
    bot.config.account_id = "acc-test"
    ctx = MagicMock()

    out_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1)
    out_queue.put_nowait({"type": "filler"})  # 미리 채워 full.
    lagged: list[int] = []

    def _enqueue(frame: dict) -> None:
        try:
            out_queue.put_nowait(frame)
        except asyncio.QueueFull:
            lagged.append(1)

    ch = SignalChannel(
        bot,
        bus,
        ctx,
        sink=_enqueue,
        is_full=out_queue.full,
        on_lagged=lambda: lagged.append(1),
    )
    ch._subscribe_events()

    # full queue 에서 fill publish — 핸들러 inline 이 QueueFull 을 격리(미전파).
    await asyncio.wait_for(bus.publish(_fill(key="K1")), timeout=1.0)
    # publish 가 정상 완료(예외 미전파) + is_full 게이트가 schedule_lagged 발화.
    assert len(lagged) >= 1
    ch._unsubscribe_events()


# ── writer MessageTooLargeError non-fatal (INV-OUT-7) ────────────────


async def test_metadata_too_large_dropped_non_fatal() -> None:
    """거대 metadata signal 은 publish 안 하고 비치명 error 후 채널 유지."""
    ch, captured, _ = _make_channel(is_full=False)
    huge = {"type": "signal", "symbol": "005930", "side": "buy"}
    # 64 keys 초과 metadata.
    for i in range(100):
        huge[f"k{i}"] = i
    await ch._handle_message(huge)
    # publish 안 함 — eventbus.publish 미호출.
    ch._eventbus.publish.assert_not_called()  # type: ignore[attr-defined]
    # 비치명 error 1프레임.
    assert any(f.get("type") == "error" for f in captured)
