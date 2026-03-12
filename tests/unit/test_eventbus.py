"""EventBus 단위 테스트."""

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import (
    BotStartedEvent,
    OrderRequestEvent,
)


@pytest.fixture
def bus():
    return EventBus(history_size=50)


# ── 발행/구독 ─────────────────────────────────────


async def test_publish_subscribe(bus):
    """이벤트 발행 시 구독자가 수신한다."""
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(OrderRequestEvent, handler)
    event = OrderRequestEvent(symbol="005930", side="buy", quantity=10.0)
    await bus.publish(event)

    assert len(received) == 1
    assert received[0].symbol == "005930"


async def test_multiple_handlers(bus):
    """같은 이벤트에 여러 핸들러가 모두 호출된다."""
    calls = []

    async def h1(event):
        calls.append("h1")

    async def h2(event):
        calls.append("h2")

    bus.subscribe(OrderRequestEvent, h1)
    bus.subscribe(OrderRequestEvent, h2)
    await bus.publish(OrderRequestEvent())

    assert len(calls) == 2


async def test_no_subscribers(bus):
    """구독자 없는 이벤트 발행 시 에러 없음."""
    await bus.publish(OrderRequestEvent())


async def test_type_isolation(bus):
    """다른 타입의 이벤트는 수신하지 않는다."""
    received = []

    async def handler(event):
        received.append(event)

    bus.subscribe(OrderRequestEvent, handler)
    await bus.publish(BotStartedEvent(bot_id="bot1"))

    assert len(received) == 0


# ── 우선순위 ──────────────────────────────────────


async def test_priority_order(bus):
    """priority가 높은 핸들러가 먼저 실행된다."""
    order = []

    async def low(event):
        order.append("low")

    async def high(event):
        order.append("high")

    async def mid(event):
        order.append("mid")

    bus.subscribe(OrderRequestEvent, low, priority=0)
    bus.subscribe(OrderRequestEvent, high, priority=100)
    bus.subscribe(OrderRequestEvent, mid, priority=50)

    await bus.publish(OrderRequestEvent())

    assert order == ["high", "mid", "low"]


# ── 에러 격리 ─────────────────────────────────────


async def test_handler_error_isolation(bus):
    """한 핸들러의 예외가 다른 핸들러를 막지 않는다."""
    calls = []

    async def failing(event):
        raise ValueError("boom")

    async def succeeding(event):
        calls.append("ok")

    bus.subscribe(OrderRequestEvent, failing, priority=100)
    bus.subscribe(OrderRequestEvent, succeeding, priority=0)

    await bus.publish(OrderRequestEvent())

    assert calls == ["ok"]


# ── 동기 핸들러 ───────────────────────────────────


async def test_sync_handler(bus):
    """동기 핸들러도 지원한다."""
    received = []

    def sync_handler(event):
        received.append(event)

    bus.subscribe(OrderRequestEvent, sync_handler)
    await bus.publish(OrderRequestEvent(symbol="sync"))

    assert len(received) == 1
    assert received[0].symbol == "sync"


# ── 구독 해제 ─────────────────────────────────────


async def test_unsubscribe(bus):
    """핸들러 등록 해제 후 호출되지 않는다."""
    calls = []

    async def handler(event):
        calls.append(1)

    bus.subscribe(OrderRequestEvent, handler)
    await bus.publish(OrderRequestEvent())
    assert len(calls) == 1

    bus.unsubscribe(OrderRequestEvent, handler)
    await bus.publish(OrderRequestEvent())
    assert len(calls) == 1


# ── 히스토리 ──────────────────────────────────────


async def test_history_records_events(bus):
    """발행된 이벤트가 히스토리에 기록된다."""
    await bus.publish(OrderRequestEvent(symbol="A"))
    await bus.publish(OrderRequestEvent(symbol="B"))

    history = bus.get_history()
    assert len(history) == 2
    assert history[0].symbol == "B"  # 최신순
    assert history[1].symbol == "A"


async def test_history_type_filter(bus):
    """히스토리를 이벤트 타입으로 필터링한다."""
    await bus.publish(OrderRequestEvent(symbol="X"))
    await bus.publish(BotStartedEvent(bot_id="b"))
    await bus.publish(OrderRequestEvent(symbol="Y"))

    filtered = bus.get_history(event_type=OrderRequestEvent)
    assert len(filtered) == 2
    assert all(isinstance(e, OrderRequestEvent) for e in filtered)


async def test_history_ring_buffer(bus):
    """히스토리 크기가 제한된다."""
    for i in range(100):
        await bus.publish(OrderRequestEvent(symbol=str(i)))

    history = bus.get_history(limit=200)
    assert len(history) == 50  # history_size=50


async def test_history_limit(bus):
    """limit으로 반환 건수를 제한한다."""
    for i in range(10):
        await bus.publish(OrderRequestEvent(symbol=str(i)))

    history = bus.get_history(limit=3)
    assert len(history) == 3


# ── get_handlers ──────────────────────────────────


async def test_get_handlers(bus):
    """등록된 핸들러 목록을 조회한다."""

    async def h1(event):
        pass

    async def h2(event):
        pass

    bus.subscribe(OrderRequestEvent, h1, priority=10)
    bus.subscribe(OrderRequestEvent, h2, priority=20)

    handlers = bus.get_handlers(OrderRequestEvent)
    assert len(handlers) == 2
    assert handlers[0][0] == 20  # priority 높은 것이 먼저
    assert handlers[1][0] == 10


# ── 이벤트 불변성 ─────────────────────────────────


async def test_event_immutability():
    """frozen 이벤트는 변경할 수 없다."""
    event = OrderRequestEvent(symbol="005930")
    with pytest.raises(AttributeError):
        event.symbol = "other"  # type: ignore[misc]
