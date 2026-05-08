"""SignalChannel `OrderModifyRejectedEvent` 외부 전달 테스트 (#1331).

본 모듈은 다음을 잠근다:
- ``OrderModifyRejectedEvent`` 가 외부 채널에 ``order_update`` 메시지로
  전달된다.
- dict shape는 기존 패턴 ``{"type": "order_update", "order_id": ...,
  "status": ..., "reason": ...}`` 을 그대로 유지한다.
  ``type`` 을 ``"modify_rejected"`` 같은 새 값으로 바꾸지 않는다 — 외부
  소비자(stdin/stdout 기반 에이전트)의 파싱 호환을 보장한다 (Codex 2차
  review 피드백 반영).
- ``status`` 는 ``"modify_rejected"`` 로 잠근다 (신규 키).
"""

from __future__ import annotations

import io
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.bot.signal_channel import SignalChannel
from ante.eventbus.events import OrderModifyRejectedEvent


@pytest.fixture
def bot() -> MagicMock:
    b = MagicMock()
    b.bot_id = "bot-1331"
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


async def test_modify_rejected_forwarded_keeps_order_update_shape(
    channel: SignalChannel, output: io.StringIO
) -> None:
    """``OrderModifyRejectedEvent`` → 기존 ``order_update`` shape으로 직렬화."""
    event = OrderModifyRejectedEvent(
        account_id="acc-test",
        order_id="ord-mod-1",
        bot_id="bot-1331",
        strategy_id="strat-1331",
        symbol="005930",
        side="sell",
        quantity=2.0,
        price=51000.0,
        reason="modify_not_implemented",
    )

    await channel._on_order_update(event)

    payload = output.getvalue().strip()
    assert payload, "외부 채널에 메시지가 기록되어야 한다"
    resp = json.loads(payload)

    # 본 PR의 핵심 잠금: type은 기존 ``order_update`` 그대로.
    assert resp["type"] == "order_update"
    assert resp["status"] == "modify_rejected"
    assert resp["order_id"] == "ord-mod-1"
    assert resp["reason"] == "modify_not_implemented"


async def test_modify_rejected_other_bot_ignored(
    channel: SignalChannel, output: io.StringIO
) -> None:
    """다른 ``bot_id`` 거부 통보는 외부 채널에 기록되지 않는다."""
    event = OrderModifyRejectedEvent(
        account_id="acc-test",
        order_id="ord-mod-2",
        bot_id="bot-other",
        strategy_id="strat-other",
        symbol="005930",
        side="buy",
        quantity=1.0,
        price=1.0,
        reason="modify_not_implemented",
    )

    await channel._on_order_update(event)

    assert output.getvalue() == ""
