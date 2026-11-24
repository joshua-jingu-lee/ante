"""VirtualExecutor stop / stop_limit guard 회귀 테스트 (#1337).

정책 (사용자 승인, 2026-05-08):
- 등록 단계의 stop / stop_limit OrderApprovedEvent는 가상 체결되지 않는다.
- StopOrderManager가 trigger 시 발행하는 변환된 일반 주문(market/limit)은
  기존 OrderApprovedEvent 경로를 통해 정상 체결된다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.models import TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.bot.providers.virtual import VirtualExecutor
from ante.core.database import Database
from ante.eventbus import EventBus
from ante.eventbus.events import OrderApprovedEvent, OrderFilledEvent
from tests.unit._readiness_gate_helpers import make_account

ACCOUNT = "acct1"


def _gate_kwargs() -> dict:
    """#2398 G9 backstop 통과용 ready registry + account_service.

    (test, virtual) → treasury_sync 만 비면제이므로 ready mark.
    """
    reg = RuntimeReadinessRegistry()
    reg.mark_ready(ACCOUNT, ReadinessFlag.TREASURY_SYNC)
    svc = MagicMock()
    svc.get = AsyncMock(
        return_value=make_account(
            ACCOUNT, broker_type="test", trading_mode=TradingMode.VIRTUAL
        )
    )
    return {"runtime_readiness": reg, "account_service": svc}


@pytest.fixture
def eventbus():
    return EventBus()


class _Ledger:
    """가상 체결의 정본(포지션 표·봇 예산) — #2816 뒤 뷰가 읽는 곳."""

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        from ante.trade.fill_applier import FillApplier
        from ante.trade.fill_outbox import FillOutbox
        from ante.trade.order_tracker import OrderTracker
        from ante.trade.position import PositionHistory
        from ante.trade.recorder import TradeRecorder
        from ante.treasury.treasury import Treasury

        self.position_history = PositionHistory(db)
        self.recorder = TradeRecorder(db, self.position_history)
        self.tracker = OrderTracker(db)
        self.outbox = FillOutbox(db)
        self.applier = FillApplier(
            db=db,
            order_tracker=self.tracker,
            position_history=self.position_history,
            eventbus=eventbus,
            outbox=self.outbox,
        )
        self.treasury = Treasury(db, eventbus, account_id=ACCOUNT)

    async def start(self) -> None:
        await self.position_history.initialize()
        await self.recorder.initialize()
        await self.tracker.initialize()
        await self.outbox.initialize()
        await self.treasury.initialize()
        await self.treasury.set_account_balance(10_000_000.0)
        await self.treasury.allocate("virtual1", 10_000_000.0)

    def positions(self) -> dict[str, float]:
        return {
            p.symbol: p.quantity
            for p in self.position_history.get_positions_sync(
                "virtual1", account_id=ACCOUNT
            )
        }


@pytest.fixture
async def ledger(tmp_path, eventbus):
    db = Database(str(tmp_path / "stop_guard.db"))
    await db.connect()
    try:
        led = _Ledger(db, eventbus)
        await led.start()
        yield led
    finally:
        await db.close()


class TestVirtualProviderStopGuard:
    async def test_virtual_provider_skips_stop_orders(self, eventbus, ledger):
        """Virtual 계좌의 buy stop OrderApprovedEvent는 즉시 체결되지 않는다."""
        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
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
        assert ledger.positions() == {}
        budget = ledger.treasury.get_budget_sync("virtual1")
        assert budget is not None
        assert budget.reserved == 0.0

    async def test_virtual_provider_skips_stop_limit_orders(self, eventbus, ledger):
        """stop_limit도 동일하게 등록 단계에서 가상 체결되지 않는다."""
        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
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
        assert ledger.positions() == {}

    @pytest.mark.parametrize("order_type", ["stop", "stop_limit"])
    @pytest.mark.parametrize("price", [None, 1050.0])
    async def test_virtual_provider_leaves_stop_orders_untouched(
        self, eventbus, ledger, order_type, price
    ):
        """등록 단계 stop / stop_limit 은 체결도 실패 종결도 하지 않고 그대로 둔다."""
        from ante.eventbus.events import OrderFailedEvent

        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
        executor.subscribe()

        filled: list[OrderFilledEvent] = []
        failed: list[OrderFailedEvent] = []
        eventbus.subscribe(OrderFilledEvent, lambda e: filled.append(e))
        eventbus.subscribe(OrderFailedEvent, lambda e: failed.append(e))

        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-stop-untouched",
                account_id="acct1",
                bot_id="virtual1",
                strategy_id="A7",
                symbol="069500",
                side="buy",
                quantity=1.0,
                order_type=order_type,
                price=price,
                stop_price=1000.0,
                reserved_amount=0.0,
            )
        )

        assert filled == []
        assert failed == []
        assert ledger.positions() == {}
        budget = ledger.treasury.get_budget_sync("virtual1")
        assert budget is not None
        assert budget.available == 10_000_000.0

        # 같은 executor 가 일반 limit 주문은 체결한다(구독이 살아 있다는 대조군).
        await eventbus.publish(
            OrderApprovedEvent(
                order_id="ord-limit-control",
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
        assert [e.order_id for e in filled] == ["ord-limit-control"]

    async def test_virtual_provider_processes_trigger_converted_market(
        self, eventbus, ledger
    ):
        """StopOrderManager가 trigger 시 발행하는 변환 market 주문은 정상 체결된다."""
        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
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
        assert ledger.positions() == {"069500": 1.0}

    async def test_virtual_provider_processes_trigger_converted_limit(
        self, eventbus, ledger
    ):
        """stop_limit trigger 변환 limit 주문도 정상 체결된다."""
        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
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

    async def test_virtual_fill_has_empty_dedup_key(self, eventbus, ledger):
        executor = VirtualExecutor(
            eventbus=eventbus,
            commission_rate=0.00015,
            fill_applier=ledger.applier,
            **_gate_kwargs(),
        )
        executor.register_bot("virtual1")
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
