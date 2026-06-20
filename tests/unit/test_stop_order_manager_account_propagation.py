"""StopOrderManager → stop 이벤트 ``account_id`` 보존 (#1336).

``register`` / ``_trigger_order`` / ``_expire_order`` 가 발행하는
이벤트에 ``account_id`` 가 누락되거나 fallback 으로 채워지지 않는지를
회귀로 보호한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from ante.eventbus.events import (
    OrderRequestEvent,
    StopOrderExpiredEvent,
    StopOrderRegisteredEvent,
    StopOrderTriggeredEvent,
)
from ante.gateway.stop_order import StopOrderManager


@pytest.fixture
def eventbus() -> MagicMock:
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def manager(eventbus: MagicMock) -> StopOrderManager:
    return StopOrderManager(eventbus)


class TestRegisterPropagation:
    async def test_register_preserves_account_id(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        manager.start()
        await manager.register(
            order_id="ord-001",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderRegisteredEvent)
        assert event.account_id == "acc-test"
        assert event.stop_order_id.startswith("stop-")

    async def test_register_preserves_distinct_account_ids(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        manager.start()
        await manager.register(
            order_id="ord-1",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-1",
        )
        await manager.register(
            order_id="ord-2",
            bot_id="bot-2",
            strategy_id="stg-2",
            symbol="005930",
            side="sell",
            quantity=5.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-2",
        )

        events = [c.args[0] for c in eventbus.publish.call_args_list]
        accounts = sorted(
            e.account_id for e in events if isinstance(e, StopOrderRegisteredEvent)
        )
        assert accounts == ["acc-1", "acc-2"]


class TestTriggerPropagation:
    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_trigger_preserves_account_id(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        manager.start()
        await manager.register(
            order_id="ord-1",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 48500.0, account_id="acc-test")

        # StopOrderTriggeredEvent + OrderRequestEvent
        assert eventbus.publish.call_count == 2

        triggered = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered, StopOrderTriggeredEvent)
        assert triggered.account_id == "acc-test"

        order_req = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_req, OrderRequestEvent)
        assert order_req.account_id == "acc-test"


class TestExpiryPropagation:
    async def test_manager_stop_propagates_account_id(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        manager.start()
        await manager.register(
            order_id="ord-1",
            bot_id="bot-1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.stop()

        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.account_id == "acc-test"
        assert event.reason == "manager_stopped"

    async def test_session_expiry_propagates_account_id(
        self,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        manager.start()
        # #2405 (attempt2 P2): 세션활동 마킹은 manager-level 이며 in-session **틱**
        # 에서만 일어난다. 시각 강제(True)로 register + in-session 틱으로 세션을
        # active 표시, 이후 False(세션 종료) sweep 으로 expiry 검증.
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=True
        ):
            await manager.register(
                order_id="ord-1",
                bot_id="bot-1",
                strategy_id="stg-1",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="acc-test",
            )
            # in-session 틱(트리거 미달 가격) → 세션 active 마킹.
            await manager.on_price_update("005930", 50000.0, account_id="acc-test")

        eventbus.publish.reset_mock()
        with patch.object(
            StopOrderManager, "_is_session_type_active_now", return_value=False
        ):
            await manager.check_session_expiry()

        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.account_id == "acc-test"
        assert event.reason == "session_ended"
