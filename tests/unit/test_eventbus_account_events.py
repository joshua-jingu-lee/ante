"""EventBus Account 이벤트 확장 테스트 (#562).

Account 이벤트 3종 추가 및 기존 이벤트 account_id 필드 하위 호환 검증.
"""

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
    AccountDeletedEvent,
    AccountSuspendedEvent,
    BalanceSyncedEvent,
    BotErrorEvent,
    BotStartedEvent,
    BotStoppedEvent,
    OrderApprovedEvent,
    OrderCancelEvent,
    OrderCancelledEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderModifyEvent,
    OrderModifyRejectedEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderSubmittedEvent,
    OrderValidatedEvent,
)


@pytest.fixture
def bus():
    return EventBus(history_size=50)


# ── Account 이벤트 3종 ─────────────────────────────


class TestAccountEvents:
    """Account 이벤트 3종이 올바르게 생성되고 발행된다."""

    async def test_account_suspended_event(self, bus: EventBus):
        """AccountSuspendedEvent 생성 및 발행."""
        received: list[AccountSuspendedEvent] = []

        async def handler(event: AccountSuspendedEvent) -> None:
            received.append(event)

        bus.subscribe(AccountSuspendedEvent, handler)
        event = AccountSuspendedEvent(
            account_id="acc-001",
            reason="위험 감지",
            suspended_by="system",
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].account_id == "acc-001"
        assert received[0].reason == "위험 감지"
        assert received[0].suspended_by == "system"

    async def test_account_activated_event(self, bus: EventBus):
        """AccountActivatedEvent 생성 및 발행."""
        received: list[AccountActivatedEvent] = []

        async def handler(event: AccountActivatedEvent) -> None:
            received.append(event)

        bus.subscribe(AccountActivatedEvent, handler)
        event = AccountActivatedEvent(
            account_id="acc-001",
            activated_by="admin",
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].account_id == "acc-001"
        assert received[0].activated_by == "admin"

    async def test_account_deleted_event(self, bus: EventBus):
        """AccountDeletedEvent 생성 및 발행."""
        received: list[AccountDeletedEvent] = []

        async def handler(event: AccountDeletedEvent) -> None:
            received.append(event)

        bus.subscribe(AccountDeletedEvent, handler)
        event = AccountDeletedEvent(
            account_id="acc-001",
            deleted_by="admin",
        )
        await bus.publish(event)

        assert len(received) == 1
        assert received[0].account_id == "acc-001"
        assert received[0].deleted_by == "admin"

    async def test_account_events_are_frozen(self):
        """Account 이벤트는 불변이다."""
        event = AccountSuspendedEvent(account_id="acc-001")
        with pytest.raises(AttributeError):
            event.account_id = "changed"  # type: ignore[misc]

    async def test_account_events_default_values(self):
        """Account 이벤트 기본값이 빈 문자열이다."""
        suspended = AccountSuspendedEvent()
        assert suspended.account_id == ""
        assert suspended.reason == ""
        assert suspended.suspended_by == ""

        activated = AccountActivatedEvent()
        assert activated.account_id == ""
        assert activated.activated_by == ""

        deleted = AccountDeletedEvent()
        assert deleted.account_id == ""
        assert deleted.deleted_by == ""


# ── 기존 이벤트 account_id 하위 호환 ─────────────────


class TestAccountIdBackwardCompat:
    """기존 이벤트에 추가된 account_id 필드가 기본값 ''으로 하위 호환된다."""

    async def test_order_events_default_account_id(self):
        """Order 이벤트 기본 account_id는 빈 문자열이다."""
        events = [
            OrderRequestEvent(symbol="005930", side="buy", quantity=10.0),
            OrderCancelEvent(order_id="o1"),
            OrderModifyEvent(order_id="o1"),
            OrderModifyRejectedEvent(order_id="o1"),
            OrderValidatedEvent(order_id="o1"),
            OrderRejectedEvent(order_id="o1"),
            OrderApprovedEvent(order_id="o1"),
            OrderSubmittedEvent(order_id="o1"),
            OrderFilledEvent(order_id="o1"),
            OrderCancelledEvent(order_id="o1"),
            OrderFailedEvent(order_id="o1"),
        ]
        for event in events:
            assert event.account_id == "", (
                f"{type(event).__name__}.account_id 기본값이 ''이 아님"
            )

    async def test_bot_events_default_account_id(self):
        """Bot 이벤트 기본 account_id는 빈 문자열이다."""
        events = [
            BotStartedEvent(bot_id="bot1"),
            BotStoppedEvent(bot_id="bot1"),
            BotErrorEvent(bot_id="bot1", error_message="err"),
        ]
        for event in events:
            assert event.account_id == "", (
                f"{type(event).__name__}.account_id 기본값이 ''이 아님"
            )

    async def test_balance_synced_default_account_id(self):
        """BalanceSyncedEvent 기본 account_id는 빈 문자열이다."""
        event = BalanceSyncedEvent(account_balance=1000000.0)
        assert event.account_id == ""

    async def test_order_event_with_account_id(self):
        """account_id를 명시적으로 전달할 수 있다."""
        event = OrderRequestEvent(
            account_id="acc-kr-stock",
            bot_id="bot1",
            symbol="005930",
            side="buy",
            quantity=10.0,
        )
        assert event.account_id == "acc-kr-stock"

    async def test_bot_event_with_account_id(self):
        """Bot 이벤트에 account_id를 전달할 수 있다."""
        event = BotStartedEvent(account_id="acc-001", bot_id="bot1")
        assert event.account_id == "acc-001"

    async def test_balance_synced_with_account_id(self):
        """BalanceSyncedEvent에 account_id를 전달할 수 있다."""
        event = BalanceSyncedEvent(
            account_id="acc-001",
            account_balance=5000000.0,
        )
        assert event.account_id == "acc-001"

    async def test_existing_fields_preserved(self):
        """account_id 추가 후에도 기존 필드가 정상 동작한다."""
        event = OrderRequestEvent(
            account_id="acc-001",
            bot_id="bot1",
            strategy_id="strat1",
            symbol="005930",
            side="buy",
            quantity=10.0,
            order_type="market",
            exchange="KRX",
        )
        assert event.bot_id == "bot1"
        assert event.strategy_id == "strat1"
        assert event.symbol == "005930"
        assert event.side == "buy"
        assert event.quantity == 10.0
        assert event.order_type == "market"
        assert event.exchange == "KRX"

    async def test_account_id_propagation_in_eventbus(self, bus: EventBus):
        """account_id가 EventBus를 통해 정상 전파된다."""
        received: list[OrderRequestEvent] = []

        async def handler(event: OrderRequestEvent) -> None:
            received.append(event)

        bus.subscribe(OrderRequestEvent, handler)
        await bus.publish(
            OrderRequestEvent(account_id="acc-001", symbol="005930"),
        )

        assert len(received) == 1
        assert received[0].account_id == "acc-001"
