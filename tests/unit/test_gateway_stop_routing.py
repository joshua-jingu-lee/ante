"""APIGateway stop order 라우팅 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.eventbus.events import (
    OrderApprovedEvent,
    OrderFailedEvent,
    OrderSubmittedEvent,
)
from ante.gateway.gateway import APIGateway


@pytest.fixture
def broker() -> MagicMock:
    """BrokerAdapter mock."""
    b = MagicMock()
    b.place_order = AsyncMock(return_value="BRK-001")
    return b


@pytest.fixture
def account_service(broker: MagicMock) -> MagicMock:
    """AccountService mock."""
    svc = MagicMock()
    svc.get_broker = AsyncMock(return_value=broker)
    return svc


@pytest.fixture
def eventbus() -> MagicMock:
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    bus.subscribe = MagicMock()
    return bus


@pytest.fixture
def stop_manager(eventbus: MagicMock) -> MagicMock:
    """StopOrderManager mock."""
    mgr = MagicMock()
    mgr.register = AsyncMock(return_value="stop-abc123")
    return mgr


@pytest.fixture
def gateway(
    account_service: MagicMock, eventbus: MagicMock, stop_manager: MagicMock
) -> APIGateway:
    """APIGateway with StopOrderManager."""
    return APIGateway(
        account_service=account_service,
        eventbus=eventbus,
        stop_order_manager=stop_manager,
    )


@pytest.fixture
def gateway_no_stop(account_service: MagicMock, eventbus: MagicMock) -> APIGateway:
    """APIGateway without StopOrderManager."""
    return APIGateway(account_service=account_service, eventbus=eventbus)


class TestStopOrderRouting:
    """Stop order 라우팅 테스트."""

    async def test_stop_order_routed_to_manager(
        self,
        gateway: APIGateway,
        stop_manager: MagicMock,
        broker: MagicMock,
        eventbus: MagicMock,
    ) -> None:
        """stop 주문은 StopOrderManager로 라우팅."""
        event = OrderApprovedEvent(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            price=None,
            exchange="KRX",
        )

        await gateway._on_order_approved(event)

        # StopOrderManager.register 호출
        stop_manager.register.assert_called_once_with(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            limit_price=None,
            exchange="KRX",
        )

        # broker.place_order는 호출 안 됨
        broker.place_order.assert_not_called()

    async def test_stop_limit_routed_to_manager(
        self,
        gateway: APIGateway,
        stop_manager: MagicMock,
    ) -> None:
        """stop_limit 주문도 StopOrderManager로 라우팅."""
        event = OrderApprovedEvent(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop_limit",
            stop_price=51000.0,
            price=51500.0,
            exchange="KRX",
        )

        await gateway._on_order_approved(event)

        stop_manager.register.assert_called_once()
        call_kwargs = stop_manager.register.call_args[1]
        assert call_kwargs["limit_price"] == 51500.0

    async def test_market_order_goes_to_broker(
        self,
        gateway: APIGateway,
        stop_manager: MagicMock,
        broker: MagicMock,
        eventbus: MagicMock,
    ) -> None:
        """일반 market 주문은 broker로 직접 전달."""
        event = OrderApprovedEvent(
            order_id="ord-003",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            exchange="KRX",
        )

        await gateway._on_order_approved(event)

        broker.place_order.assert_called_once()
        stop_manager.register.assert_not_called()
        eventbus.publish.assert_called_once()
        submitted = eventbus.publish.call_args[0][0]
        assert isinstance(submitted, OrderSubmittedEvent)

    async def test_stop_order_register_failure(
        self,
        gateway: APIGateway,
        stop_manager: MagicMock,
        eventbus: MagicMock,
    ) -> None:
        """StopOrderManager 등록 실패 시 OrderFailedEvent 발행."""
        stop_manager.register = AsyncMock(side_effect=RuntimeError("test error"))

        event = OrderApprovedEvent(
            order_id="ord-004",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            exchange="KRX",
        )

        await gateway._on_order_approved(event)

        eventbus.publish.assert_called_once()
        failed = eventbus.publish.call_args[0][0]
        assert isinstance(failed, OrderFailedEvent)
        assert "test error" in failed.error_message

    async def test_stop_order_without_manager(
        self,
        gateway_no_stop: APIGateway,
        broker: MagicMock,
        eventbus: MagicMock,
    ) -> None:
        """StopOrderManager 미설정 시 broker에 전달 (기존 동작)."""
        event = OrderApprovedEvent(
            order_id="ord-005",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            exchange="KRX",
        )

        await gateway_no_stop._on_order_approved(event)

        # stop_order_manager가 없으므로 broker에 직접 전달 시도
        broker.place_order.assert_called_once()
