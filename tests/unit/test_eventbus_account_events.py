"""EventBus Account 이벤트 확장 테스트 (#562, #1139).

#1139에서 AccountDeletedEvent는 1.0 EventBus 계약에서 제거되었다.
잔존 Account 이벤트 2종(Suspended/Activated)과 기존 이벤트 account_id 필드
하위 호환을 검증한다.
"""

import pytest

from ante.eventbus import EventBus
from ante.eventbus.events import (
    AccountActivatedEvent,
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

    async def test_account_events_are_frozen(self):
        """Account 이벤트는 불변이다."""
        event = AccountSuspendedEvent(account_id="acc-001")
        with pytest.raises(AttributeError):
            event.account_id = "changed"  # type: ignore[misc]

    async def test_account_events_default_values(self):
        """Account 이벤트는 account_id를 보존하고 나머지 필드는 기본값 ''을 가진다."""
        suspended = AccountSuspendedEvent(account_id="acc-test")
        assert suspended.account_id == "acc-test"
        assert suspended.reason == ""
        assert suspended.suspended_by == ""

        activated = AccountActivatedEvent(account_id="acc-test")
        assert activated.account_id == "acc-test"
        assert activated.activated_by == ""


# ── 기존 이벤트 account_id 하위 호환 ─────────────────


class TestAccountIdBackwardCompat:
    """기존 이벤트에 추가된 account_id 필드가 명시 전달되어 보존된다."""

    async def test_order_events_default_account_id(self):
        """Order 이벤트 account_id는 생성 시 명시값으로 보존된다."""
        events = [
            OrderRequestEvent(
                symbol="005930", side="buy", quantity=10.0, account_id="acc-test"
            ),
            OrderCancelEvent(order_id="o1", account_id="acc-test"),
            OrderModifyEvent(order_id="o1", account_id="acc-test"),
            OrderModifyRejectedEvent(order_id="o1", account_id="acc-test"),
            OrderValidatedEvent(order_id="o1", account_id="acc-test"),
            OrderRejectedEvent(order_id="o1", account_id="acc-test"),
            OrderApprovedEvent(order_id="o1", account_id="acc-test"),
            OrderSubmittedEvent(order_id="o1", account_id="acc-test"),
            OrderFilledEvent(order_id="o1", account_id="acc-test"),
            OrderCancelledEvent(order_id="o1", account_id="acc-test"),
            OrderFailedEvent(order_id="o1", account_id="acc-test"),
        ]
        for event in events:
            assert event.account_id == "acc-test", (
                f"{type(event).__name__}.account_id 보존 실패"
            )

    async def test_bot_events_default_account_id(self):
        """Bot 이벤트 account_id는 생성 시 명시값으로 보존된다."""
        events = [
            BotStartedEvent(bot_id="bot1", account_id="acc-test"),
            BotStoppedEvent(bot_id="bot1", account_id="acc-test"),
            BotErrorEvent(bot_id="bot1", error_message="err", account_id="acc-test"),
        ]
        for event in events:
            assert event.account_id == "acc-test", (
                f"{type(event).__name__}.account_id 보존 실패"
            )

    async def test_balance_synced_default_account_id(self):
        """BalanceSyncedEvent account_id는 생성 시 명시값으로 보존된다."""
        event = BalanceSyncedEvent(account_balance=1000000.0, account_id="acc-test")
        assert event.account_id == "acc-test"

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
