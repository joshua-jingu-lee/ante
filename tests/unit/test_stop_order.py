"""StopOrderManager 단위 테스트."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch  # noqa: F811

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
    """EventBus mock."""
    bus = MagicMock()
    bus.publish = AsyncMock()
    return bus


@pytest.fixture
def manager(eventbus: MagicMock) -> StopOrderManager:
    """StopOrderManager 인스턴스."""
    return StopOrderManager(eventbus)


class TestRegister:
    """스탑 주문 등록 테스트."""

    async def test_register_stop_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """스탑 주문 등록."""
        stop_id = await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        assert stop_id.startswith("stop-")
        assert len(manager.active_orders) == 1
        assert "005930" in manager.monitored_symbols

        # 이벤트 발행 확인
        eventbus.publish.assert_called_once()
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderRegisteredEvent)
        assert event.stop_price == 49000.0

    async def test_register_stop_limit_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """스탑 리밋 주문 등록."""
        stop_id = await manager.register(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop_limit",
            stop_price=51000.0,
            limit_price=51500.0,
        )

        order = manager.get_order(stop_id)
        assert order is not None
        assert order.order_type == "stop_limit"
        assert order.limit_price == 51500.0


class TestTrigger:
    """트리거 판단 테스트."""

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_sell_stop_triggered(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매도 스탑: 현재가 <= stop_price 시 트리거."""
        await manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        eventbus.publish.reset_mock()

        # 가격이 stop_price 이하로 하락
        await manager.on_price_update("005930", 48500.0)

        # StopOrderTriggeredEvent + OrderRequestEvent 발행
        assert eventbus.publish.call_count == 2

        triggered_event = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered_event, StopOrderTriggeredEvent)
        assert triggered_event.trigger_price == 48500.0
        assert triggered_event.converted_order_type == "market"

        order_event = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_event, OrderRequestEvent)
        assert order_event.order_type == "market"
        assert order_event.side == "sell"

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_buy_stop_triggered(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매수 스탑: 현재가 >= stop_price 시 트리거."""
        await manager.start()

        await manager.register(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=51000.0,
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51500.0)

        assert eventbus.publish.call_count == 2
        triggered_event = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered_event, StopOrderTriggeredEvent)

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_stop_limit_converts_to_limit(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """stop_limit → limit 변환."""
        await manager.start()

        await manager.register(
            order_id="ord-003",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop_limit",
            stop_price=51000.0,
            limit_price=51500.0,
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51000.0)

        order_event = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_event, OrderRequestEvent)
        assert order_event.order_type == "limit"
        assert order_event.price == 51500.0

    async def test_not_triggered_below_threshold(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """트리거 조건 미충족 시 주문 유지."""
        await manager.start()

        await manager.register(
            order_id="ord-004",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 50000.0)  # > stop_price

        # 트리거 안 됨
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_different_symbol_ignored(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """다른 종목 시세는 무시."""
        await manager.start()

        await manager.register(
            order_id="ord-005",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("000660", 48000.0)

        assert eventbus.publish.call_count == 0

    async def test_not_running_ignores_price(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매니저 미시작 상태에서 시세 무시."""
        await manager.register(
            order_id="ord-006",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 48000.0)

        # running=False이므로 무시
        assert eventbus.publish.call_count == 0


class TestCancel:
    """스탑 주문 취소 테스트."""

    async def test_cancel_active_order(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """활성 주문 취소."""
        stop_id = await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        result = await manager.cancel(stop_id)
        assert result is True
        assert len(manager.active_orders) == 0

    async def test_cancel_nonexistent(self, manager: StopOrderManager) -> None:
        """존재하지 않는 주문 취소."""
        result = await manager.cancel("stop-nonexistent")
        assert result is False


class TestExpiry:
    """세션 종료 만료 테스트."""

    async def test_stop_expires_all_on_stop(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매니저 중지 시 모든 주문 만료."""
        await manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )

        eventbus.publish.reset_mock()
        await manager.stop()

        # StopOrderExpiredEvent 발행
        assert eventbus.publish.call_count == 1
        event = eventbus.publish.call_args[0][0]
        assert isinstance(event, StopOrderExpiredEvent)
        assert event.reason == "manager_stopped"


class TestBotOrders:
    """봇별 주문 조회 테스트."""

    async def test_get_orders_for_bot(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """봇별 활성 주문 필터링."""
        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
        )
        await manager.register(
            order_id="ord-002",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
        )

        bot1_orders = manager.get_orders_for_bot("bot-001")
        assert len(bot1_orders) == 1
        assert bot1_orders[0].symbol == "005930"


class TestSignalTradingSession:
    """Signal trading_session 필드 테스트."""

    def test_signal_default_session(self) -> None:
        """Signal 기본 trading_session은 regular."""
        from ante.strategy.base import Signal

        sig = Signal(symbol="005930", side="buy", quantity=10)
        assert sig.trading_session == "regular"

    def test_signal_extended_session(self) -> None:
        """Signal extended session 설정."""
        from ante.strategy.base import Signal

        sig = Signal(
            symbol="005930",
            side="buy",
            quantity=10,
            trading_session="extended",
        )
        assert sig.trading_session == "extended"
