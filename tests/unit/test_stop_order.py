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
            account_id="acc-test",
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
            account_id="acc-test",
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
        manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()

        # 가격이 stop_price 이하로 하락
        await manager.on_price_update("005930", 48500.0, account_id="acc-test")

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
        manager.start()

        await manager.register(
            order_id="ord-002",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51500.0, account_id="acc-test")

        assert eventbus.publish.call_count == 2
        triggered_event = eventbus.publish.call_args_list[0][0][0]
        assert isinstance(triggered_event, StopOrderTriggeredEvent)

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_stop_limit_converts_to_limit(
        self, _mock_session: MagicMock, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """stop_limit → limit 변환."""
        manager.start()

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
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 51000.0, account_id="acc-test")

        order_event = eventbus.publish.call_args_list[1][0][0]
        assert isinstance(order_event, OrderRequestEvent)
        assert order_event.order_type == "limit"
        assert order_event.price == 51500.0

    async def test_not_triggered_below_threshold(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """트리거 조건 미충족 시 주문 유지."""
        manager.start()

        await manager.register(
            order_id="ord-004",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update(
            "005930", 50000.0, account_id="acc-test"
        )  # > stop_price

        # 트리거 안 됨
        assert eventbus.publish.call_count == 0
        assert len(manager.active_orders) == 1

    async def test_different_symbol_ignored(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """다른 종목 시세는 무시."""
        manager.start()

        await manager.register(
            order_id="ord-005",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("000660", 48000.0, account_id="acc-test")

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
            account_id="acc-test",
        )

        eventbus.publish.reset_mock()
        await manager.on_price_update("005930", 48000.0, account_id="acc-test")

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
            account_id="acc-test",
        )

        result = manager.cancel(stop_id)
        assert result is True
        assert len(manager.active_orders) == 0

    async def test_cancel_nonexistent(self, manager: StopOrderManager) -> None:
        """존재하지 않는 주문 취소."""
        result = manager.cancel("stop-nonexistent")
        assert result is False


class TestExpiry:
    """세션 종료 만료 테스트."""

    async def test_stop_expires_all_on_stop(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """매니저 중지 시 모든 주문 만료."""
        manager.start()

        await manager.register(
            order_id="ord-001",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-test",
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
            account_id="acc-test",
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
            account_id="acc-test",
        )

        bot1_orders = manager.get_orders_for_bot("bot-001")
        assert len(bot1_orders) == 1
        assert bot1_orders[0].symbol == "005930"


class TestAccountOrders:
    """계좌별 주문 조회 테스트 (#2124, get_orders_for_bot 동형)."""

    def test_get_orders_for_account_exists(self) -> None:
        """#2124 재현 해소: get_orders_for_account 메서드 존재."""
        assert hasattr(StopOrderManager, "get_orders_for_account")

    async def test_get_orders_for_account_isolates_by_account(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """여러 계좌 등록 시 해당 계좌 활성 주문만 반환 (타 계좌 격리)."""
        await manager.register(
            order_id="ord-a1",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-a2",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-b1",
            bot_id="bot-003",
            strategy_id="stg-003",
            symbol="035720",
            side="buy",
            quantity=3.0,
            order_type="stop",
            stop_price=50000.0,
            account_id="acc-b",
        )

        acc_a_orders = manager.get_orders_for_account("acc-a")
        assert len(acc_a_orders) == 2
        assert all(o.account_id == "acc-a" for o in acc_a_orders)
        assert {o.symbol for o in acc_a_orders} == {"005930", "000660"}

        acc_b_orders = manager.get_orders_for_account("acc-b")
        assert len(acc_b_orders) == 1
        assert acc_b_orders[0].account_id == "acc-b"
        assert acc_b_orders[0].symbol == "035720"

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_get_orders_for_account_excludes_triggered_and_expired(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """triggered/expired 주문은 제외 (active_orders 기반)."""
        manager.start()

        # 트리거될 주문
        triggered_id = await manager.register(
            order_id="ord-trig",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        # 만료시킬 주문
        expired_id = await manager.register(
            order_id="ord-exp",
            bot_id="bot-002",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-a",
        )
        # 활성으로 유지될 주문
        await manager.register(
            order_id="ord-active",
            bot_id="bot-003",
            strategy_id="stg-003",
            symbol="035720",
            side="buy",
            quantity=3.0,
            order_type="stop",
            stop_price=200000.0,
            account_id="acc-a",
        )

        # triggered 주문 trigger 처리
        await manager.on_price_update("005930", 48500.0, account_id="acc-a")
        # expired 주문 만료 처리
        expired_order = manager.get_order(expired_id)
        assert expired_order is not None
        await manager._expire_order(expired_order, "session_ended")

        triggered_order = manager.get_order(triggered_id)
        assert triggered_order is not None
        assert triggered_order.triggered is True

        acc_a_orders = manager.get_orders_for_account("acc-a")
        assert len(acc_a_orders) == 1
        assert acc_a_orders[0].order_id == "ord-active"

    def test_get_orders_for_account_unknown_returns_empty(
        self, manager: StopOrderManager
    ) -> None:
        """미존재 account_id → 빈 리스트 (데이터 누출 없음)."""
        assert manager.get_orders_for_account("acc-unknown") == []

    async def test_get_orders_for_account_subset_of_active(
        self, manager: StopOrderManager, eventbus: MagicMock
    ) -> None:
        """get_orders_for_bot 과 교차 정합 — 같은 active set 의 부분집합."""
        await manager.register(
            order_id="ord-1",
            bot_id="bot-001",
            strategy_id="stg-001",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-a",
        )
        await manager.register(
            order_id="ord-2",
            bot_id="bot-001",
            strategy_id="stg-002",
            symbol="000660",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=100000.0,
            account_id="acc-b",
        )

        active = manager.active_orders
        acc_a_orders = manager.get_orders_for_account("acc-a")
        bot1_orders = manager.get_orders_for_bot("bot-001")

        # 두 조회 모두 active_orders 의 부분집합
        active_ids = {o.stop_order_id for o in active}
        assert {o.stop_order_id for o in acc_a_orders} <= active_ids
        assert {o.stop_order_id for o in bot1_orders} <= active_ids

        # acc-a 활성 주문 = bot-001 의 acc-a 주문 (ord-1) 한 건과 교차 정합
        acc_a_ids = {o.stop_order_id for o in acc_a_orders}
        bot1_ids = {o.stop_order_id for o in bot1_orders}
        assert acc_a_ids & bot1_ids == {
            o.stop_order_id
            for o in active
            if o.account_id == "acc-a" and o.bot_id == "bot-001"
        }


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


class TestCrossAccountIsolation:
    """SPLIT-3 (#1242): StopOrderManager는 같은 종목이라도 account_id 가
    다른 stop order 끼리 trigger를 격리한다.

    multi-account 환경에서는 account마다 별도의 KISStreamClient
    인스턴스가 ``account_id`` 명시 호출을 통해 ``on_price_update`` 를
    호출하므로, 시세가 들어온 account 의 stop order만 평가되어야 한다.
    """

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_register_requires_valid_account_id(
        self, _mock_session: MagicMock, manager: StopOrderManager
    ) -> None:
        """register 시 account_id 가 invalid 면 InvalidAccountIdError."""
        from ante.account.errors import InvalidAccountIdError

        with pytest.raises(InvalidAccountIdError):
            await manager.register(
                order_id="ord-bad",
                bot_id="bot-bad",
                strategy_id="stg-bad",
                symbol="005930",
                side="sell",
                quantity=10.0,
                order_type="stop",
                stop_price=49000.0,
                account_id="",
            )

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_on_price_update_requires_account_id(
        self, _mock_session: MagicMock, manager: StopOrderManager
    ) -> None:
        """on_price_update 호출 시 account_id 가 invalid 면 거부."""
        from ante.account.errors import InvalidAccountIdError

        manager.start()

        with pytest.raises(InvalidAccountIdError):
            await manager.on_price_update("005930", 50000.0, account_id="")

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_cross_account_isolation_only_triggers_matching_account(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """동일 symbol 이라도 account_id 가 다르면 trigger 되지 않는다."""
        manager.start()

        # acc-1 의 stop sell 주문 등록
        await manager.register(
            order_id="ord-acc1",
            bot_id="bot-acc1",
            strategy_id="stg-1",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-1",
        )
        # acc-2 의 stop sell 주문 등록 (same symbol, same trigger condition)
        await manager.register(
            order_id="ord-acc2",
            bot_id="bot-acc2",
            strategy_id="stg-2",
            symbol="005930",
            side="sell",
            quantity=10.0,
            order_type="stop",
            stop_price=49000.0,
            account_id="acc-2",
        )

        eventbus.publish.reset_mock()

        # acc-1 의 stream 에서 가격이 들어옴 → acc-1 주문만 trigger 되어야 한다
        await manager.on_price_update("005930", 48500.0, account_id="acc-1")

        # 1 trigger × 2 events (StopOrderTriggeredEvent + OrderRequestEvent)
        assert eventbus.publish.call_count == 2

        triggered_event = eventbus.publish.call_args_list[0][0][0]
        order_event = eventbus.publish.call_args_list[1][0][0]
        assert triggered_event.stop_order_id  # 첫 이벤트 stop order id 존재
        # OrderRequestEvent 는 acc-1 의 account_id 를 들고 발행되어야 한다.
        assert order_event.account_id == "acc-1"
        assert order_event.bot_id == "bot-acc1"

        # acc-2 의 주문은 여전히 active 로 남아 있다.
        active_for_acc2 = [o for o in manager.active_orders if o.account_id == "acc-2"]
        assert len(active_for_acc2) == 1

    @patch.object(StopOrderManager, "_is_in_session", return_value=True)
    async def test_cross_account_each_account_triggers_own_orders(
        self,
        _mock_session: MagicMock,
        manager: StopOrderManager,
        eventbus: MagicMock,
    ) -> None:
        """각 계좌 stream 에서 가격이 들어오면 각자의 주문만 trigger 된다."""
        manager.start()

        await manager.register(
            order_id="ord-acc1",
            bot_id="bot-acc1",
            strategy_id="stg-1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-1",
        )
        await manager.register(
            order_id="ord-acc2",
            bot_id="bot-acc2",
            strategy_id="stg-2",
            symbol="005930",
            side="buy",
            quantity=5.0,
            order_type="stop",
            stop_price=51000.0,
            account_id="acc-2",
        )

        # acc-1 stream 가격
        await manager.on_price_update("005930", 51500.0, account_id="acc-1")
        # acc-2 stream 가격
        await manager.on_price_update("005930", 51500.0, account_id="acc-2")

        # 두 trigger × 2 events 씩 = 4 events
        order_events = [
            call.args[0]
            for call in eventbus.publish.call_args_list
            if call.args and type(call.args[0]).__name__ == "OrderRequestEvent"
        ]
        assert len(order_events) == 2
        accounts = sorted(e.account_id for e in order_events)
        assert accounts == ["acc-1", "acc-2"]
