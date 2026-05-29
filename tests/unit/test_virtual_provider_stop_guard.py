"""VirtualExecutor stop / stop_limit guard 회귀 테스트 (#1337).

정책 (사용자 승인, 2026-05-08):
- 등록 단계의 stop / stop_limit OrderApprovedEvent는 가상 체결되지 않는다.
- StopOrderManager가 trigger 시 발행하는 변환된 일반 주문(market/limit)은
  기존 OrderApprovedEvent 경로를 통해 정상 체결된다.
"""

from __future__ import annotations

import pytest

from ante.bot.providers.virtual import VirtualExecutor, VirtualPortfolioView
from ante.eventbus import EventBus
from ante.eventbus.events import OrderApprovedEvent, OrderFilledEvent


@pytest.fixture
def eventbus():
    return EventBus()


class TestVirtualProviderStopGuard:
    async def test_virtual_provider_skips_stop_orders(self, eventbus):
        """Virtual 계좌의 buy stop OrderApprovedEvent는 즉시 체결되지 않는다."""
        executor = VirtualExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = VirtualPortfolioView(
            bot_id="virtual1", initial_balance=10_000_000.0
        )
        executor.register_bot("virtual1", portfolio)
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-stop-1",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type="stop",
                price=None,
                stop_price=1000.0,
                reserved_amount=0.0,
            )
        )

        assert len(filled) == 0, (
            "등록 단계의 stop은 trigger 전이므로 가상 체결되어선 안 된다 (#1337)."
        )
        # 포지션·잔고에도 영향 없음
        assert portfolio.get_positions("virtual1") == {}
        balance = portfolio.get_balance("virtual1")
        assert balance["reserved"] == 0.0

    async def test_virtual_provider_skips_stop_limit_orders(self, eventbus):
        """stop_limit도 동일하게 등록 단계에서 가상 체결되지 않는다."""
        executor = VirtualExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = VirtualPortfolioView(
            bot_id="virtual1", initial_balance=10_000_000.0
        )
        executor.register_bot("virtual1", portfolio)
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-stoplim-1",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type="stop_limit",
                price=1050.0,
                stop_price=1000.0,
                reserved_amount=0.0,
            )
        )

        assert len(filled) == 0
        assert portfolio.get_positions("virtual1") == {}

    async def test_virtual_provider_processes_trigger_converted_market(self, eventbus):
        """StopOrderManager가 trigger 시 발행하는 변환 market 주문은 정상 체결된다."""
        executor = VirtualExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = VirtualPortfolioView(
            bot_id="virtual1", initial_balance=10_000_000.0
        )
        executor.register_bot("virtual1", portfolio)
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        # trigger 변환 후의 일반 market 주문 (일반 reserve 절차 통과 가정).
        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-trig-mkt-1",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type="market",
                price=1000.0,
                reserved_amount=1000.0 * 1.00015,
            )
        )

        assert len(filled) == 1
        evt = filled[0]
        assert evt.order_type == "market"
        assert evt.symbol == "069500"
        assert evt.quantity == 1.0
        assert evt.price == 1000.0
        positions = portfolio.get_positions("virtual1")
        assert positions["069500"]["quantity"] == 1.0

    async def test_virtual_provider_processes_trigger_converted_limit(self, eventbus):
        """stop_limit trigger 변환 limit 주문도 정상 체결된다."""
        executor = VirtualExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = VirtualPortfolioView(
            bot_id="virtual1", initial_balance=10_000_000.0
        )
        executor.register_bot("virtual1", portfolio)
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-trig-lim-1",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type="limit",
                price=1050.0,
                reserved_amount=1050.0 * 1.00015,
            )
        )

        assert len(filled) == 1
        evt = filled[0]
        assert evt.order_type == "limit"
        assert evt.price == 1050.0


class TestVirtualProviderFillDedupKeyPolicy:
    """#1949: VirtualProvider 직접 발행 경로의 fill_dedup_key 빈키 정책.

    VirtualExecutor 는 가상 체결을 즉시 1회 직접 발행하며 FillApplier/OrderTracker
    (CAS) 와 outbox 를 거치지 않는다. 결정적 키(order_id:confirmed_cumulative)의
    산출 기반(CAS 확정 누적값)이 없고 at-least-once 재전달도 없으므로, dedup 비대상
    이며 fill_dedup_key 는 빈키("")로 발행한다.
    """

    async def test_virtual_fill_has_empty_dedup_key(self, eventbus):
        executor = VirtualExecutor(eventbus=eventbus, commission_rate=0.00015)
        portfolio = VirtualPortfolioView(
            bot_id="virtual1", initial_balance=10_000_000.0
        )
        executor.register_bot("virtual1", portfolio)
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-virt-1",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type="market",
                price=1000.0,
                reserved_amount=1000.0 * 1.00015,
            )
        )

        assert len(filled) == 1
        # 빈키 정책: VirtualProvider 직접 발행은 dedup 비대상.
        assert filled[0].fill_dedup_key == ""
