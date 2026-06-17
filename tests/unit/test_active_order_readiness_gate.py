"""#2398 active-order readiness gate — 3계층 defense-in-depth(+G9) 단위 테스트.

invariant G1–G9 (이슈 #2398 Implementation Plan rev5 / D-ACC-09 축 ii):

- G1 block / G2 fail-closed / G3 no-reserve-leak(계층3 OrderFailedEvent→release)
- G5 liveness(ready 통과) / G6 operator alert(전 계층 1회) / G7 SUSPENDED kill-switch
- G8 virtual 0원 체결 금지 / G9 virtual 경로 backstop

SSOT: docs/specs/account/02-design-decisions.md(D-ACC-09),
rule-engine/07-rule-engine-core.md:80-106, treasury/05-treasury-manager.md:62-76,
broker-adapter/11-order-flow.md:61-82, api-gateway/api-gateway.md:155-164.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock

import pytest

from ante.account.models import AccountStatus, TradingMode
from ante.account.readiness import ReadinessFlag, RuntimeReadinessRegistry
from ante.eventbus import EventBus
from ante.eventbus.events import (
    NotificationEvent,
    OrderApprovedEvent,
    OrderFailedEvent,
    OrderFilledEvent,
    OrderRejectedEvent,
    OrderRequestEvent,
    OrderSubmittedEvent,
    OrderValidatedEvent,
)
from ante.gateway.gateway import APIGateway
from ante.rule import RuleEngine
from ante.treasury.treasury import Treasury
from tests.unit._readiness_gate_helpers import (
    make_account,
    not_ready_registry,
    ready_registry,
)

ACCOUNT = "acc-001"
BOT = "bot1"
SYMBOL = "005930"
LIQUIDATION_PREFIX = "liquidation:"


@dataclass
class _Captured:
    rejected: list[OrderRejectedEvent] = field(default_factory=list)
    validated: list[OrderValidatedEvent] = field(default_factory=list)
    approved: list[OrderApprovedEvent] = field(default_factory=list)
    failed: list[OrderFailedEvent] = field(default_factory=list)
    submitted: list[OrderSubmittedEvent] = field(default_factory=list)
    filled: list[OrderFilledEvent] = field(default_factory=list)
    notifications: list[NotificationEvent] = field(default_factory=list)


def _capture(eventbus: EventBus) -> _Captured:
    cap = _Captured()
    eventbus.subscribe(OrderRejectedEvent, lambda e: cap.rejected.append(e))
    eventbus.subscribe(OrderValidatedEvent, lambda e: cap.validated.append(e))
    eventbus.subscribe(OrderApprovedEvent, lambda e: cap.approved.append(e))
    eventbus.subscribe(OrderFailedEvent, lambda e: cap.failed.append(e))
    eventbus.subscribe(OrderSubmittedEvent, lambda e: cap.submitted.append(e))
    eventbus.subscribe(OrderFilledEvent, lambda e: cap.filled.append(e))
    eventbus.subscribe(NotificationEvent, lambda e: cap.notifications.append(e))
    return cap


def _account_service(account: object) -> MagicMock:
    svc = MagicMock()
    svc.get = AsyncMock(return_value=account)
    return svc


def _request(
    *,
    side: str = "buy",
    order_type: str = "market",
    price: float | None = 50000.0,
    reason: str = "",
) -> OrderRequestEvent:
    return OrderRequestEvent(
        account_id=ACCOUNT,
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side=side,
        quantity=10.0,
        order_type=order_type,
        price=price,
        reason=reason,
    )


def _validated(*, side: str = "buy", reason: str = "") -> OrderValidatedEvent:
    return OrderValidatedEvent(
        account_id=ACCOUNT,
        order_id="ord-1",
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side=side,
        quantity=10.0,
        price=None,
        order_type="market",
        reason=reason,
    )


def _approved(*, side: str = "buy", order_type: str = "market") -> OrderApprovedEvent:
    return OrderApprovedEvent(
        account_id=ACCOUNT,
        order_id="ord-1",
        bot_id=BOT,
        strategy_id="s1",
        symbol=SYMBOL,
        side=side,
        quantity=10.0,
        price=None,
        order_type=order_type,
        reserved_amount=500000.0,
    )


def _notif_count(cap: _Captured) -> int:
    return sum(
        1 for n in cap.notifications if n.level == "error" and n.category == "system"
    )


# ── 계층1 (RuleEngine._on_order_request) ────────────────────────────────────


class TestLayer1RuleEngine:
    def _engine(
        self,
        eventbus: EventBus,
        *,
        registry: RuntimeReadinessRegistry | None,
        account: object | None = None,
    ) -> RuleEngine:
        if account is None:
            account = make_account(ACCOUNT)
        return RuleEngine(
            eventbus=eventbus,
            account_id=ACCOUNT,
            account_service=_account_service(account),
            account=account,
            runtime_readiness=registry,
        )

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_not_ready_rejects_with_alert(self, side: str) -> None:
        """G1/G6: not_ready BUY/SELL → OrderRejectedEvent + NotificationEvent 1회."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=not_ready_registry(ACCOUNT))
        await engine._on_order_request(_request(side=side, order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason.startswith("account_not_ready")
        assert cap.validated == []
        assert _notif_count(cap) == 1  # G6: 정확히 1회.

    async def test_ready_passes(self) -> None:
        """G5: ready 면 gate 통과 → OrderValidatedEvent(거부 없음)."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=ready_registry(ACCOUNT))
        await engine._on_order_request(_request(order_type="limit"))

        assert cap.rejected == []
        assert len(cap.validated) == 1
        assert _notif_count(cap) == 0

    async def test_fail_closed_registry_none(self) -> None:
        """G2: registry 미주입(None) → fail-closed 차단."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=None)
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason.startswith("account_not_ready")
        assert cap.validated == []

    async def test_fail_closed_meta_unavailable(self) -> None:
        """G2: account 메타 취득 실패(snapshot 없음 + service.get 예외) → 차단."""
        bus = EventBus()
        cap = _capture(bus)
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=RuntimeError("boom"))
        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=svc,
            account=None,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert "account_metadata_unavailable" in cap.rejected[0].reason
        assert cap.validated == []

    async def test_g7_suspended_blocked_even_if_ready(self) -> None:
        """G7: readiness ready 여도 AccountStatus.SUSPENDED → account_suspended 차단."""
        bus = EventBus()
        cap = _capture(bus)
        suspended = make_account(ACCOUNT, status=AccountStatus.SUSPENDED)
        engine = self._engine(bus, registry=ready_registry(ACCOUNT), account=suspended)
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason == "account_suspended"
        assert cap.validated == []
        assert _notif_count(cap) == 1

    async def test_g7_suspended_uses_live_status_over_stale_snapshot(self) -> None:
        """G7: 스냅샷 ACTIVE 여도 live status SUSPENDED 면 차단(kill-switch race)."""
        bus = EventBus()
        cap = _capture(bus)
        stale_active = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        live_suspended = make_account(ACCOUNT, status=AccountStatus.SUSPENDED)
        svc = MagicMock()
        svc.get = AsyncMock(return_value=live_suspended)
        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=svc,
            account=stale_active,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason == "account_suspended"

    async def test_liquidation_marker_uses_dedicated_phrasing(self) -> None:
        """G6 청산: not_ready 청산 SELL marker → "청산 차단" 전용 문구."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=not_ready_registry(ACCOUNT))
        await engine._on_order_request(
            _request(side="sell", reason=f"{LIQUIDATION_PREFIX} 봇 삭제 청산")
        )

        assert len(cap.rejected) == 1
        assert _notif_count(cap) == 1
        assert "청산 차단" in cap.notifications[-1].title

    async def test_non_liquidation_uses_generic_phrasing(self) -> None:
        """G6: 일반(비청산) 거부는 generic 문구(잘못된 "청산" 문구 없음)."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=not_ready_registry(ACCOUNT))
        await engine._on_order_request(_request(side="sell", order_type="limit"))

        assert _notif_count(cap) == 1
        assert "청산" not in cap.notifications[-1].title

    async def test_layer1_blocks_before_side_validation(self) -> None:
        """gate 가 side 검증 前 실행 — invalid side 라도 account_not_ready 우선."""
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=not_ready_registry(ACCOUNT))
        bad = _request(order_type="limit")
        object.__setattr__(bad, "side", "INVALID")
        await engine._on_order_request(bad)

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason.startswith("account_not_ready")

    async def test_stop_trigger_reentry_regated(self) -> None:
        """stop order 재진입 재게이트: 트리거 변환 OrderRequestEvent(일반
        order_type)도 계층1 gate 를 통과(ready)/차단(not_ready)한다(트리거 시점
        readiness 재평가)."""
        # not_ready → 변환 주문 차단.
        bus = EventBus()
        cap = _capture(bus)
        engine = self._engine(bus, registry=not_ready_registry(ACCOUNT))
        # StopOrderManager 트리거가 발행하는 변환 일반 주문(market) 모사.
        await engine._on_order_request(_request(side="buy", order_type="market"))
        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason.startswith("account_not_ready")

        # ready → 통과.
        bus2 = EventBus()
        cap2 = _capture(bus2)
        engine2 = self._engine(bus2, registry=ready_registry(ACCOUNT))
        await engine2._on_order_request(_request(side="buy", order_type="limit"))
        assert cap2.rejected == []
        assert len(cap2.validated) == 1


# ── 계층2 (Treasury._on_order_validated) ────────────────────────────────────


class TestLayer2Treasury:
    def _treasury(
        self,
        eventbus: EventBus,
        *,
        registry: RuntimeReadinessRegistry | None,
        broker_type: str = "kis-domestic",
        trading_mode: TradingMode = TradingMode.LIVE,
    ) -> Treasury:
        return Treasury(
            db=MagicMock(),
            eventbus=eventbus,
            account_id=ACCOUNT,
            runtime_readiness=registry,
            broker_type=broker_type,
            trading_mode=trading_mode,
        )

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_not_ready_rejects_no_reserve(self, side: str) -> None:
        """G1/G3/G6: not_ready → OrderRejectedEvent + reserve 미실행 + 알림 1회."""
        bus = EventBus()
        cap = _capture(bus)
        treasury = self._treasury(bus, registry=not_ready_registry(ACCOUNT))
        treasury.reserve_for_order = AsyncMock(return_value=True)  # type: ignore[method-assign]
        await treasury._on_order_validated(_validated(side=side))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason.startswith("account_not_ready")
        assert cap.approved == []
        treasury.reserve_for_order.assert_not_called()  # reserve 누수 없음.
        assert _notif_count(cap) == 1

    async def test_fail_closed_registry_none(self) -> None:
        """G2: registry None → 차단(reserve 미실행)."""
        bus = EventBus()
        cap = _capture(bus)
        treasury = self._treasury(bus, registry=None)
        treasury.reserve_for_order = AsyncMock(return_value=True)  # type: ignore[method-assign]
        await treasury._on_order_validated(_validated())

        assert len(cap.rejected) == 1
        treasury.reserve_for_order.assert_not_called()

    async def test_liquidation_marker_phrasing(self) -> None:
        """G6 청산: OrderValidatedEvent.reason marker → "청산 차단" 문구."""
        bus = EventBus()
        cap = _capture(bus)
        treasury = self._treasury(bus, registry=not_ready_registry(ACCOUNT))
        await treasury._on_order_validated(
            _validated(side="sell", reason=f"{LIQUIDATION_PREFIX} 청산")
        )

        assert _notif_count(cap) == 1
        assert "청산 차단" in cap.notifications[-1].title


# ── 계층3 (APIGateway.submit_order / _on_order_approved) ─────────────────────


class TestLayer3Gateway:
    def _gateway(
        self,
        eventbus: EventBus,
        *,
        registry: RuntimeReadinessRegistry | None,
        broker: MagicMock,
        account: object | None = None,
    ) -> APIGateway:
        if account is None:
            account = make_account(ACCOUNT)
        svc = _account_service(account)
        svc.get_broker = AsyncMock(return_value=broker)
        return APIGateway(
            account_service=svc,
            eventbus=eventbus,
            runtime_readiness=registry,
        )

    def _broker(self) -> MagicMock:
        b = MagicMock()
        b.place_order = AsyncMock(return_value="BRK-1")
        return b

    async def test_not_ready_raises_api_error_no_broker(self) -> None:
        """계층3: not_ready submit_order → APIError, broker 미호출."""
        from ante.broker.exceptions import APIError

        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        gw = self._gateway(bus, registry=not_ready_registry(ACCOUNT), broker=broker)

        with pytest.raises(APIError) as exc:
            await gw.submit_order(
                bot_id=BOT,
                symbol=SYMBOL,
                side="buy",
                quantity=10.0,
                account_id=ACCOUNT,
            )
        assert exc.value.error_code == "account_not_ready"
        broker.place_order.assert_not_called()
        assert _notif_count(cap) == 1  # G6 계층3 알림 1회.

    async def test_on_order_approved_not_ready_failed_not_swallowed(self) -> None:
        """G3 핵심: not_ready OrderApprovedEvent → except 가 OrderFailedEvent 변환
        (EventBus swallow 아님) + bot/order/account 보존."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        gw = self._gateway(bus, registry=not_ready_registry(ACCOUNT), broker=broker)

        await gw._on_order_approved(_approved())

        assert len(cap.failed) == 1
        failed = cap.failed[0]
        assert failed.error_code == "account_not_ready"
        assert failed.bot_id == BOT
        assert failed.order_id == "ord-1"
        assert failed.account_id == ACCOUNT
        broker.place_order.assert_not_called()

    async def test_g3_release_reservation_called_on_failed(self) -> None:
        """G3: 계층3 거부 OrderFailedEvent 를 Treasury 가 구독 → release_reservation
        실제 호출(reserve 해제). EventBus swallow 였다면 호출되지 않는다."""
        bus = EventBus()
        broker = self._broker()
        gw = self._gateway(bus, registry=not_ready_registry(ACCOUNT), broker=broker)
        # Treasury 는 ready 로 둬 gate 가 release 경로만 검증(계층2 무관).
        treasury = Treasury(
            db=MagicMock(),
            eventbus=bus,
            account_id=ACCOUNT,
            runtime_readiness=ready_registry(ACCOUNT),
            broker_type="kis-domestic",
            trading_mode=TradingMode.LIVE,
        )
        treasury.release_reservation = AsyncMock()  # type: ignore[method-assign]
        bus.subscribe(OrderFailedEvent, treasury._on_order_failed, priority=50)

        await gw._on_order_approved(_approved())

        treasury.release_reservation.assert_awaited_once()
        call = treasury.release_reservation.await_args
        assert call.args[0] == BOT and call.args[1] == "ord-1"

    async def test_ready_passes_to_broker(self) -> None:
        """G5: ready LIVE → broker.place_order + OrderSubmittedEvent."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        gw = self._gateway(bus, registry=ready_registry(ACCOUNT), broker=broker)

        await gw._on_order_approved(_approved())

        broker.place_order.assert_called_once()
        assert len(cap.submitted) == 1
        assert cap.failed == []

    async def test_approved_payload_preserved_on_block(self) -> None:
        """계층3 OrderApprovedEvent payload bot/order/account 보존(OrderFailedEvent)."""
        bus = EventBus()
        cap = _capture(bus)
        gw = self._gateway(
            bus, registry=not_ready_registry(ACCOUNT), broker=self._broker()
        )
        await gw._on_order_approved(_approved(side="sell"))

        assert len(cap.failed) == 1
        assert cap.failed[0].side == "sell"
        assert cap.failed[0].symbol == SYMBOL

    async def test_fail_closed_meta_unavailable(self) -> None:
        """G2: account_service.get 실패 → fail-closed OrderFailedEvent(virtual
        fall-open 금지)."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=RuntimeError("boom"))
        svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=svc,
            eventbus=bus,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await gw._on_order_approved(_approved())

        assert len(cap.failed) == 1
        broker.place_order.assert_not_called()


# ── Virtual 라우팅 + G8 + G9 (VirtualExecutor / gateway skip) ────────────────


class TestVirtualRouting:
    def _make_virtual_executor(
        self,
        eventbus: EventBus,
        *,
        registry: RuntimeReadinessRegistry | None,
        gateway: object | None = None,
        account: object | None = None,
    ):
        from ante.bot.providers.virtual import (
            VirtualExecutor,
            VirtualPortfolioView,
        )

        if account is None:
            account = make_account(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        executor = VirtualExecutor(
            eventbus=eventbus,
            gateway=gateway,
            runtime_readiness=registry,
            account_service=_account_service(account),
        )
        executor.register_bot(BOT, VirtualPortfolioView(BOT, 10_000_000.0))
        return executor

    async def test_gateway_skips_place_order_for_virtual(self) -> None:
        """G3 라우팅: kis-domestic + virtual 주문은 broker.place_order 미호출."""
        bus = EventBus()
        cap = _capture(bus)
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value="BRK-1")
        virtual_acc = make_account(
            ACCOUNT, broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL
        )
        svc = _account_service(virtual_acc)
        svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=svc,
            eventbus=bus,
            runtime_readiness=ready_registry(
                ACCOUNT, broker_type="kis-domestic", trading_mode=TradingMode.VIRTUAL
            ),
        )
        await gw._on_order_approved(_approved())

        broker.place_order.assert_not_called()
        assert cap.failed == []  # skip 은 실패가 아님.
        assert cap.submitted == []

    async def test_virtual_stop_preserves_stop_manager(self) -> None:
        """virtual + stop → StopOrderManager 등록 보존(skip 통째 금지)."""
        bus = EventBus()
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value="BRK-1")
        stop_mgr = MagicMock()
        stop_mgr.register = AsyncMock(return_value="stop-1")
        virtual_acc = make_account(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        svc = _account_service(virtual_acc)
        svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=svc,
            eventbus=bus,
            stop_order_manager=stop_mgr,
            runtime_readiness=ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL),
        )
        await gw._on_order_approved(_approved(order_type="stop"))

        stop_mgr.register.assert_called_once()
        broker.place_order.assert_not_called()

    async def test_g8_virtual_market_price_failure_no_zero_fill(self) -> None:
        """G8: virtual 시장가 가격 조회 실패 → 0원 OrderFilledEvent 없음 +
        OrderFailedEvent."""
        bus = EventBus()
        cap = _capture(bus)
        gateway = MagicMock()
        gateway.get_current_price = AsyncMock(side_effect=RuntimeError("no price"))
        executor = self._make_virtual_executor(
            bus,
            registry=ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL),
            gateway=gateway,
        )
        await executor._on_order_approved(_approved())

        assert cap.filled == []  # 0원 체결 금지.
        assert len(cap.failed) == 1
        assert cap.failed[0].error_message == "virtual_market_price_unavailable"

    async def test_g8_no_gateway_market_no_price_fails(self) -> None:
        """G8: gateway None + event.price None 시장가 → 0원 체결 없음 + 실패."""
        bus = EventBus()
        cap = _capture(bus)
        executor = self._make_virtual_executor(
            bus,
            registry=ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL),
            gateway=None,
        )
        await executor._on_order_approved(_approved())

        assert cap.filled == []
        assert len(cap.failed) == 1

    async def test_g8_virtual_limit_fills_normally(self) -> None:
        """G8 회귀: ready virtual limit(명시 가격)은 정상 체결(가격 안전과 양립)."""
        bus = EventBus()
        cap = _capture(bus)
        executor = self._make_virtual_executor(
            bus,
            registry=ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL),
        )
        ev = OrderApprovedEvent(
            account_id=ACCOUNT,
            order_id="ord-1",
            bot_id=BOT,
            strategy_id="s1",
            symbol=SYMBOL,
            side="buy",
            quantity=10.0,
            price=50000.0,
            order_type="limit",
            reserved_amount=500000.0,
        )
        await executor._on_order_approved(ev)

        assert len(cap.filled) == 1
        assert cap.filled[0].price == 50000.0
        assert cap.failed == []

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_g9_not_ready_virtual_backstop(self, side: str) -> None:
        """G9: not_ready virtual OrderApprovedEvent(상류 우회 시뮬) → fill 0건 +
        OrderFailedEvent + NotificationEvent(error) 1회(G6 상속, BUY/SELL 무관)."""
        bus = EventBus()
        cap = _capture(bus)
        gateway = MagicMock()
        gateway.get_current_price = AsyncMock(return_value=50000.0)
        executor = self._make_virtual_executor(
            bus,
            registry=not_ready_registry(
                ACCOUNT,
                trading_mode=TradingMode.VIRTUAL,
                flag=ReadinessFlag.TREASURY_SYNC,
            ),
            gateway=gateway,
        )
        await executor._on_order_approved(_approved(side=side))

        assert cap.filled == []  # fill 금지.
        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_not_ready"
        assert _notif_count(cap) == 1

    async def test_g9_fail_closed_registry_none(self) -> None:
        """G2/G9: VirtualExecutor registry None → fail-closed(fill 금지 + 실패)."""
        bus = EventBus()
        cap = _capture(bus)
        gateway = MagicMock()
        gateway.get_current_price = AsyncMock(return_value=50000.0)
        executor = self._make_virtual_executor(bus, registry=None, gateway=gateway)
        await executor._on_order_approved(_approved())

        assert cap.filled == []
        assert len(cap.failed) == 1


# ── 통합: #2395 회귀 락 + G5 liveness (full layer1→2→3 파이프라인) ─────────────


class TestPipelineIntegration:
    """RuleEngine(계층1) + Treasury(계층2) + APIGateway(계층3) 를 같은 EventBus 에
    배선해 end-to-end 차단/통과를 검증한다(#2395 회귀 락 + G5 liveness)."""

    async def _wire(self, registry: RuntimeReadinessRegistry, db_path: str):
        from ante.core import Database

        bus = EventBus()
        account = make_account(ACCOUNT)
        svc = _account_service(account)
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value="BRK-1")
        svc.get_broker = AsyncMock(return_value=broker)

        db = Database(db_path)
        await db.connect()
        treasury = Treasury(
            db=db,
            eventbus=bus,
            account_id=ACCOUNT,
            buy_commission_rate=0.0,
            sell_commission_rate=0.0,
            runtime_readiness=registry,
            broker_type="kis-domestic",
            trading_mode=TradingMode.LIVE,
        )
        await treasury.initialize()  # OrderValidated/Failed 구독 등록.
        await treasury.set_account_balance(100_000_000.0)
        await treasury.allocate(BOT, 10_000_000.0)

        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=svc,
            account=account,
            treasury=treasury,
            runtime_readiness=registry,
        )
        engine.start()

        gw = APIGateway(account_service=svc, eventbus=bus, runtime_readiness=registry)
        gw.start()
        return bus, broker, db

    async def test_2395_unregistered_fill_scheduler_blocks_active_buy(
        self, tmp_path
    ) -> None:
        """#2395 회귀: fill_reconcile_ready False LIVE 계좌의 active BUY 는
        broker.place_order 에 도달하지 않는다(계층1 에서 차단)."""
        registry = not_ready_registry(ACCOUNT, flag=ReadinessFlag.FILL_RECONCILE)
        bus, broker, db = await self._wire(registry, str(tmp_path / "t1.db"))
        try:
            cap = _capture(bus)
            await bus.publish(
                OrderRequestEvent(
                    account_id=ACCOUNT,
                    bot_id=BOT,
                    strategy_id="s1",
                    symbol=SYMBOL,
                    side="buy",
                    quantity=10.0,
                    order_type="limit",
                    price=50000.0,
                )
            )
            broker.place_order.assert_not_called()
            assert len(cap.rejected) == 1
            assert cap.rejected[0].reason.startswith("account_not_ready")
            assert cap.validated == []  # 계층1 에서 종결.
        finally:
            await db.close()

    async def test_g5_liveness_unblocks_after_ready_transition(self, tmp_path) -> None:
        """G5 liveness: not_ready→ready 전이(self-healing 모사) 후 같은 주문이
        broker.place_order 까지 통과한다(transient 실패가 영구 차단되지 않음)."""
        registry = not_ready_registry(ACCOUNT, flag=ReadinessFlag.FILL_RECONCILE)
        bus, broker, db = await self._wire(registry, str(tmp_path / "t2.db"))
        try:
            # 1) not_ready → 차단.
            await bus.publish(
                OrderRequestEvent(
                    account_id=ACCOUNT,
                    bot_id=BOT,
                    strategy_id="s1",
                    symbol=SYMBOL,
                    side="buy",
                    quantity=10.0,
                    order_type="limit",
                    price=50000.0,
                )
            )
            broker.place_order.assert_not_called()

            # 2) self-healing ready 전이(매 이벤트 시점 조회 → 상태 캐시 없음, G5).
            registry.mark_ready(ACCOUNT, ReadinessFlag.FILL_RECONCILE)
            cap = _capture(bus)
            await bus.publish(
                OrderRequestEvent(
                    account_id=ACCOUNT,
                    bot_id=BOT,
                    strategy_id="s1",
                    symbol=SYMBOL,
                    side="buy",
                    quantity=10.0,
                    order_type="limit",
                    price=50000.0,
                )
            )
            # 계층1→2→3 통과 → broker.place_order 도달.
            broker.place_order.assert_called_once()
            assert cap.rejected == []
            assert len(cap.submitted) == 1
        finally:
            await db.close()
