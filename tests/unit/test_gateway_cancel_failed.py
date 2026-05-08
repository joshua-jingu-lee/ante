"""APIGateway 주문 취소 실패 이벤트의 account/strategy attribution 보존 테스트.

#1332: ``ctx.cancel_order()`` 경로에서 broker 예외가 발생할 때
``OrderCancelFailedEvent``가 ``account_id``와 ``strategy_id`` 맥락을 모두
유지하는지 검증한다. 또한 ``OrderCancelFailedEvent``의 account_id 검증이
``_requires_account_id`` 마커로 활성화되어 있는지 확인한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderCancelEvent,
    OrderCancelFailedEvent,
)
from ante.gateway import APIGateway


@pytest.mark.asyncio
async def test_cancel_failed_preserves_account_id() -> None:
    """브로커 cancel 예외 → 발행된 OrderCancelFailedEvent.account_id 보존."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(side_effect=Exception("network error"))
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(account_service=mock_account_service, eventbus=eventbus)
    gw.start()

    received: list[OrderCancelFailedEvent] = []
    eventbus.subscribe(OrderCancelFailedEvent, lambda e: received.append(e))

    await eventbus.publish(
        OrderCancelEvent(
            account_id="acc-test",
            bot_id="bot1",
            strategy_id="s1",
            order_id="ord1",
            reason="test cancel",
        )
    )

    assert len(received) == 1
    assert received[0].account_id == "acc-test"


@pytest.mark.asyncio
async def test_cancel_failed_includes_strategy_id() -> None:
    """브로커 cancel 예외 → 발행된 OrderCancelFailedEvent.strategy_id 보존.

    #1331과의 end-to-end 잠금: OrderCancelEvent.strategy_id가 채워진 상태에서
    실패 이벤트도 동일 strategy_id를 보존해야 한다.
    """
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(side_effect=Exception("network error"))
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(account_service=mock_account_service, eventbus=eventbus)
    gw.start()

    received: list[OrderCancelFailedEvent] = []
    eventbus.subscribe(OrderCancelFailedEvent, lambda e: received.append(e))

    await eventbus.publish(
        OrderCancelEvent(
            account_id="acc-test",
            bot_id="bot1",
            strategy_id="strategy-xyz",
            order_id="ord1",
            reason="test cancel",
        )
    )

    assert len(received) == 1
    assert received[0].strategy_id == "strategy-xyz"
    assert received[0].order_id == "ord1"
    assert received[0].bot_id == "bot1"


def test_cancel_failed_account_id_required() -> None:
    """invalid account_id (빈 문자열, "default")로 직접 생성 시 검증 실패."""
    # 빈 문자열은 invalid (default 값이 그대로 들어가는 경우 차단)
    with pytest.raises(InvalidAccountIdError):
        OrderCancelFailedEvent(
            account_id="",
            order_id="ord1",
            bot_id="bot1",
            strategy_id="s1",
            error_message="boom",
        )

    # "default" 예약어는 invalid
    with pytest.raises(InvalidAccountIdError):
        OrderCancelFailedEvent(
            account_id="default",
            order_id="ord1",
            bot_id="bot1",
            strategy_id="s1",
            error_message="boom",
        )
