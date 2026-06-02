"""APIGateway 주문 취소 실패 이벤트의 account/strategy attribution 보존 테스트.

#1332: ``ctx.cancel_order()`` 경로에서 broker 예외가 발생할 때
``OrderCancelFailedEvent``가 ``account_id``와 ``strategy_id`` 맥락을 모두
유지하는지 검증한다. 또한 ``OrderCancelFailedEvent``의 account_id 검증이
``_requires_account_id`` 마커로 활성화되어 있는지 확인한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.errors import InvalidAccountIdError
from ante.eventbus import EventBus
from ante.eventbus.events import (
    OrderCancelEvent,
    OrderCancelFailedEvent,
    OrderCancelledEvent,
)
from ante.gateway import APIGateway


def _order_tracker_mock(
    *,
    order_id: str = "ord1",
    broker_order_id: str = "brk-ord1",
    account_id: str,
    symbol: str = "005930",
    side: str = "buy",
) -> AsyncMock:
    """#2134/#2044: cancel_order broker_order_id 변환을 통과시키는 OrderTracker mock.

    ``get(order_id)`` → 주어진 broker_order_id/account_id/symbol/side 레코드를
    반환한다. ``symbol``/``side`` 는 #2044 의 취소 이벤트 채움 검증에 사용된다.
    """
    tracker = AsyncMock()
    record = MagicMock()
    record.order_id = order_id
    record.broker_order_id = broker_order_id
    record.account_id = account_id
    record.symbol = symbol
    record.side = side
    tracker.get = AsyncMock(return_value=record)
    return tracker


@pytest.mark.asyncio
async def test_cancel_failed_preserves_account_id() -> None:
    """브로커 cancel 예외 → 발행된 OrderCancelFailedEvent.account_id 보존."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(side_effect=Exception("network error"))
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(account_id="acc-test"),
    )
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

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(account_id="acc-test"),
    )
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


@pytest.mark.asyncio
async def test_cancel_broker_returns_false_emits_failed_event() -> None:
    """broker.cancel_order가 False 반환 → 성공 이벤트 미발행, 실패 이벤트 발행.

    #2142: caller가 cancel_order 반환값을 확인하지 않아 broker가 False(취소 실패)를
    반환해도 OrderCancelledEvent(성공)가 발행되던 회귀를 잠근다.
    """
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=False)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(account_id="acc-test"),
    )
    gw.start()

    failed: list[OrderCancelFailedEvent] = []
    cancelled: list[OrderCancelledEvent] = []
    eventbus.subscribe(OrderCancelFailedEvent, lambda e: failed.append(e))
    eventbus.subscribe(OrderCancelledEvent, lambda e: cancelled.append(e))

    await eventbus.publish(
        OrderCancelEvent(
            account_id="acc-test",
            bot_id="bot1",
            strategy_id="strategy-xyz",
            order_id="ord1",
            reason="test cancel",
        )
    )

    # 성공 이벤트는 발행되지 않아야 한다.
    assert cancelled == []
    # 실패 이벤트가 1건 발행되며 attribution이 보존된다.
    assert len(failed) == 1
    assert failed[0].account_id == "acc-test"
    assert failed[0].order_id == "ord1"
    assert failed[0].bot_id == "bot1"
    assert failed[0].strategy_id == "strategy-xyz"
    assert failed[0].error_message == "브로커가 취소 실패(False)를 반환함"


@pytest.mark.asyncio
async def test_cancel_broker_returns_true_emits_cancelled_event() -> None:
    """broker.cancel_order가 True를 반환 → OrderCancelledEvent 발행, 실패 이벤트 미발행.

    #2142: 정상 취소 경로 회귀 잠금.
    """
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=True)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(account_id="acc-test"),
    )
    gw.start()

    failed: list[OrderCancelFailedEvent] = []
    cancelled: list[OrderCancelledEvent] = []
    eventbus.subscribe(OrderCancelFailedEvent, lambda e: failed.append(e))
    eventbus.subscribe(OrderCancelledEvent, lambda e: cancelled.append(e))

    await eventbus.publish(
        OrderCancelEvent(
            account_id="acc-test",
            bot_id="bot1",
            strategy_id="strategy-xyz",
            order_id="ord1",
            reason="test cancel",
        )
    )

    assert failed == []
    assert len(cancelled) == 1
    assert cancelled[0].account_id == "acc-test"
    assert cancelled[0].order_id == "ord1"
    assert cancelled[0].reason == "test cancel"


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


# ── #2044: 취소 완료/실패 이벤트의 symbol/side 채움 ─────────────────


async def _publish_cancel(
    gw: APIGateway,
    eventbus: EventBus,
) -> tuple[list[OrderCancelledEvent], list[OrderCancelFailedEvent]]:
    """OrderCancelEvent 를 발행하고 발행된 성공/실패 이벤트를 수집한다."""
    cancelled: list[OrderCancelledEvent] = []
    failed: list[OrderCancelFailedEvent] = []
    eventbus.subscribe(OrderCancelledEvent, lambda e: cancelled.append(e))
    eventbus.subscribe(OrderCancelFailedEvent, lambda e: failed.append(e))

    await eventbus.publish(
        OrderCancelEvent(
            account_id="acc-test",
            bot_id="bot1",
            strategy_id="strategy-xyz",
            order_id="ord1",
            reason="test cancel",
        )
    )
    return cancelled, failed


@pytest.mark.asyncio
async def test_cancel_success_fills_symbol_side_from_record() -> None:
    """(a) 취소 성공 → OrderCancelledEvent.symbol/side 가 record 값으로 채워진다."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=True)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(
            account_id="acc-test", symbol="005930", side="buy"
        ),
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    assert failed == []
    assert len(cancelled) == 1
    assert cancelled[0].symbol == "005930"
    assert cancelled[0].side == "buy"


@pytest.mark.asyncio
async def test_cancel_broker_false_fills_symbol_side_from_record() -> None:
    """(b) 취소 실패(broker False) → OrderCancelFailedEvent.symbol/side 채워짐."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=False)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(
            account_id="acc-test", symbol="005930", side="sell"
        ),
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    assert cancelled == []
    assert len(failed) == 1
    assert failed[0].symbol == "005930"
    assert failed[0].side == "sell"


@pytest.mark.asyncio
async def test_cancel_broker_exception_fills_symbol_side_from_record() -> None:
    """(c) 취소 실패(예외) → OrderCancelFailedEvent.symbol/side 채워짐."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(side_effect=Exception("network error"))
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=_order_tracker_mock(
            account_id="acc-test", symbol="005930", side="buy"
        ),
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    assert cancelled == []
    assert len(failed) == 1
    assert failed[0].symbol == "005930"
    assert failed[0].side == "buy"


@pytest.mark.asyncio
async def test_cancel_cross_account_blanks_symbol_side() -> None:
    """(d) record.account_id != event.account_id → symbol/side leak 방지로 "".

    cross-account record 는 ``cancel_order`` 가 fail-closed 로 broker 를
    호출하지 않고 False 를 반환하므로 OrderCancelFailedEvent 가 발행되며,
    핸들러의 account 가드가 다른 계정 record 의 symbol/side 노출을 막는다.
    """
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=True)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        # record 는 다른 계정 소유 — leak 되어선 안 된다.
        order_tracker=_order_tracker_mock(
            account_id="other-acc", symbol="005930", side="buy"
        ),
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    # cross-account 는 broker 미호출 → 성공 이벤트 없음.
    assert cancelled == []
    assert len(failed) == 1
    # 다른 계정 record 의 symbol/side 가 노출되지 않아야 한다.
    assert failed[0].symbol == ""
    assert failed[0].side == ""
    # broker 는 호출되지 않았다 (fail-closed).
    mock_broker.cancel_order.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_record_none_blanks_symbol_side_gracefully() -> None:
    """(e-1) record None → symbol/side "" graceful, 예외 없음."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=True)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    tracker = AsyncMock()
    tracker.get = AsyncMock(return_value=None)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=tracker,
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    # record None → cancel_order fail-closed False → 실패 이벤트.
    assert cancelled == []
    assert len(failed) == 1
    assert failed[0].symbol == ""
    assert failed[0].side == ""


@pytest.mark.asyncio
async def test_cancel_order_tracker_none_blanks_symbol_side_gracefully() -> None:
    """(e-2) order_tracker 미주입 → symbol/side "" graceful, 예외 없음."""
    eventbus = EventBus()
    mock_broker = AsyncMock()
    mock_broker.cancel_order = AsyncMock(return_value=True)
    mock_account_service = AsyncMock()
    mock_account_service.get_broker = AsyncMock(return_value=mock_broker)

    gw = APIGateway(
        account_service=mock_account_service,
        eventbus=eventbus,
        order_tracker=None,
    )
    gw.start()

    cancelled, failed = await _publish_cancel(gw, eventbus)

    # order_tracker None → cancel_order fail-closed False → 실패 이벤트.
    assert cancelled == []
    assert len(failed) == 1
    assert failed[0].symbol == ""
    assert failed[0].side == ""


def test_cancel_failed_event_symbol_side_default_blank() -> None:
    """(g) OrderCancelFailedEvent 신규 필드 default 빈값 — 기존 발행처 무회귀.

    symbol/side 를 지정하지 않은 기존 호출 형태도 그대로 생성 가능해야 한다.
    """
    evt = OrderCancelFailedEvent(
        account_id="acc-test",
        order_id="ord1",
        bot_id="bot1",
        strategy_id="s1",
        error_message="boom",
    )
    assert evt.symbol == ""
    assert evt.side == ""
