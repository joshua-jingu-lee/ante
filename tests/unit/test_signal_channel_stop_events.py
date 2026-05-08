"""SignalChannel — stop 주문 이벤트 외부 전달 테스트 (#1336).

본 모듈은 다음을 잠근다:

- ``StopOrderRegisteredEvent`` / ``StopOrderTriggeredEvent`` /
  ``StopOrderExpiredEvent`` 가 외부 채널에 ``order_update`` 메시지로
  전달된다.
- dict shape는 기존 ``{"type": "order_update", "order_id": ..., "status":
  ..., "reason": ...}`` 패턴을 그대로 유지한다 (외부 소비자 파싱 호환).
- ``order_id`` 키에는 ``stop_order_id`` 값이 들어간다.
- ``status`` 는 ``"stop_registered"`` / ``"stop_triggered"`` /
  ``"stop_expired"`` 중 하나로 잠근다.
- ``reason`` 은 ``StopOrderExpiredEvent`` 일 때만 비어 있지 않다
  (``"session_ended"`` | ``"manager_stopped"``).
"""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.signal_channel import SignalChannel
from ante.eventbus.events import (
    StopOrderExpiredEvent,
    StopOrderRegisteredEvent,
    StopOrderTriggeredEvent,
)


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.bot_id = "bot-1336"
    return b


@pytest.fixture
def eventbus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    bus.unsubscribe = MagicMock()
    return bus


@pytest.fixture
def ctx() -> MagicMock:
    return MagicMock()


@pytest.fixture
def output() -> io.StringIO:
    return io.StringIO()


@pytest.fixture
def channel(
    bot: MagicMock,
    eventbus: MagicMock,
    ctx: MagicMock,
    output: io.StringIO,
) -> SignalChannel:
    return SignalChannel(
        bot=bot,
        eventbus=eventbus,
        ctx=ctx,
        output_stream=output,
    )


async def test_stop_registered_forwarded_as_order_update(
    channel: SignalChannel, output: io.StringIO
) -> None:
    event = StopOrderRegisteredEvent(
        account_id="acc-test",
        stop_order_id="stop-001",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=49000.0,
    )

    await channel._on_order_update(event)

    payload = output.getvalue().strip()
    assert payload, "외부 채널에 메시지가 기록되어야 한다"
    resp = json.loads(payload)

    assert resp["type"] == "order_update"
    assert resp["status"] == "stop_registered"
    assert resp["order_id"] == "stop-001"
    assert resp["reason"] == ""


async def test_stop_triggered_forwarded_as_order_update(
    channel: SignalChannel, output: io.StringIO
) -> None:
    event = StopOrderTriggeredEvent(
        account_id="acc-test",
        stop_order_id="stop-002",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        side="sell",
        quantity=10.0,
        trigger_price=48500.0,
        converted_order_type="market",
    )

    await channel._on_order_update(event)

    payload = output.getvalue().strip()
    assert payload, "외부 채널에 메시지가 기록되어야 한다"
    resp = json.loads(payload)

    assert resp["type"] == "order_update"
    assert resp["status"] == "stop_triggered"
    assert resp["order_id"] == "stop-002"
    assert resp["reason"] == ""


async def test_stop_expired_forwarded_with_reason(
    channel: SignalChannel, output: io.StringIO
) -> None:
    event = StopOrderExpiredEvent(
        account_id="acc-test",
        stop_order_id="stop-003",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        reason="session_ended",
    )

    await channel._on_order_update(event)

    payload = output.getvalue().strip()
    assert payload, "외부 채널에 메시지가 기록되어야 한다"
    resp = json.loads(payload)

    assert resp["type"] == "order_update"
    assert resp["status"] == "stop_expired"
    assert resp["order_id"] == "stop-003"
    assert resp["reason"] == "session_ended"


async def test_stop_expired_manager_stopped_reason(
    channel: SignalChannel, output: io.StringIO
) -> None:
    event = StopOrderExpiredEvent(
        account_id="acc-test",
        stop_order_id="stop-004",
        bot_id="bot-1336",
        strategy_id="strat-1336",
        symbol="005930",
        reason="manager_stopped",
    )

    await channel._on_order_update(event)

    resp = json.loads(output.getvalue().strip())
    assert resp["status"] == "stop_expired"
    assert resp["reason"] == "manager_stopped"


async def test_stop_event_for_other_bot_ignored(
    channel: SignalChannel, output: io.StringIO
) -> None:
    event = StopOrderRegisteredEvent(
        account_id="acc-test",
        stop_order_id="stop-005",
        bot_id="bot-other",
        strategy_id="strat-other",
        symbol="005930",
        side="sell",
        quantity=10.0,
        order_type="stop",
        stop_price=49000.0,
    )

    await channel._on_order_update(event)

    assert output.getvalue() == ""
