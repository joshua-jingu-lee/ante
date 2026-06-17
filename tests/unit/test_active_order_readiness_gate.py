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
        """G2: account 메타 미상 → 차단(account_metadata_unavailable).

        status 축은 verified(ACTIVE)로 통과시키고 broker_type/trading_mode 만
        미상으로 만들어 meta 축 fail-closed 를 격리 검증한다. (status 조회 예외는
        status 축이 먼저 account_status_unavailable 로 차단하므로 별도 테스트로
        분리.)
        """
        bus = EventBus()
        cap = _capture(bus)
        # status 는 verified ACTIVE 이되 broker_type/trading_mode 가 미상인 메타.
        meta_unavailable = MagicMock()
        meta_unavailable.status = AccountStatus.ACTIVE
        meta_unavailable.broker_type = None
        meta_unavailable.trading_mode = None
        svc = MagicMock()
        svc.get = AsyncMock(return_value=meta_unavailable)
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

    async def test_g7_live_status_failure_no_stale_snapshot_passthrough(self) -> None:
        """G7 P1(#2398 attempt3): live status 조회 예외 + stale ACTIVE 스냅샷 +
        (실제로는 suspended) → stale ACTIVE 로 통과하지 않고 fail-closed 거부.

        status 는 런타임 가변 kill-switch 이므로 live 조회 실패를 생성시점 스냅샷
        으로 fallback 하면 suspended 계좌 주문이 OrderValidatedEvent 까지 통과해
        kill-switch 가 우회된다(P1 회귀). live 실패 = account_status_unavailable
        fail-closed 거부 + G6 알림 1회, OrderValidatedEvent 미발행이어야 한다.
        """
        bus = EventBus()
        cap = _capture(bus)
        # 엔진 생성시점 스냅샷은 ACTIVE(실제로는 그 사이 suspend 됐다고 가정).
        stale_active = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        svc = MagicMock()
        # live status 조회가 DB 잠김/일시 오류로 실패.
        svc.get = AsyncMock(side_effect=RuntimeError("db locked"))
        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=svc,
            account=stale_active,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason == "account_status_unavailable"
        assert cap.validated == []  # OrderValidatedEvent 통과 금지(P1 lock).
        assert _notif_count(cap) == 1  # G6: 정확히 1회.

    async def test_g7_live_status_none_returns_fail_closed(self) -> None:
        """G7 P1: live status 가 None(status 미상)이어도 fail-closed 거부.

        account_service.get 은 성공하지만 status 속성이 미상이면 verified 가
        아니므로 스냅샷으로 fallback 하지 않고 account_status_unavailable 거부.
        """
        bus = EventBus()
        cap = _capture(bus)
        stale_active = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        live_status_unknown = MagicMock()
        live_status_unknown.status = None
        live_status_unknown.broker_type = "kis-domestic"
        live_status_unknown.trading_mode = TradingMode.LIVE
        svc = MagicMock()
        svc.get = AsyncMock(return_value=live_status_unknown)
        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=svc,
            account=stale_active,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await engine._on_order_request(_request(order_type="limit"))

        assert len(cap.rejected) == 1
        assert cap.rejected[0].reason == "account_status_unavailable"
        assert cap.validated == []

    async def test_status_axis_inactive_when_no_account_service(self) -> None:
        """비게이트 레거시(account_service is None): status 축이 주문을 차단하지
        않는다(과차단 회피). meta 는 self._account 스냅샷으로 verified, registry
        ready → 통과(OrderValidatedEvent 발행)."""
        bus = EventBus()
        cap = _capture(bus)
        account = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        engine = RuleEngine(
            eventbus=bus,
            account_id=ACCOUNT,
            account_service=None,  # status 소스 미구성 — status 축 비활성.
            account=account,
            runtime_readiness=ready_registry(ACCOUNT),
        )
        await engine._on_order_request(_request(order_type="limit"))

        # status 축이 차단하지 않으므로(None) account_status_unavailable/
        # account_suspended 거부가 없고, readiness ready 라 통과한다.
        assert cap.rejected == []
        assert len(cap.validated) == 1

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
        """G5: ready LIVE + verified ACTIVE → broker.place_order 1회 + G6 0회."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        gw = self._gateway(bus, registry=ready_registry(ACCOUNT), broker=broker)

        await gw._on_order_approved(_approved())

        broker.place_order.assert_called_once()
        assert len(cap.submitted) == 1
        assert cap.failed == []
        assert _notif_count(cap) == 0  # 정상 통과는 G6 알림 없음.

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
        """G2 + #2398 P2-B/attempt4-b: LIVE 주문 account_service.get 실패 →
        fail-closed.

        계층3 gate 가 ``place_order`` 직전 fresh fetch 로 메타/status 를 본다. get
        예외 = status 검증 불가(``STATUS_UNAVAILABLE``)이므로 status 축이 먼저
        ``account_status_unavailable`` fail-closed(attempt4-b SSOT — 계층1과 동일
        3-state) 로 G6 알림 + APIError → except 가 OrderFailedEvent 로 변환. 과거
        bare OrderFailedEvent(알림 누락) early-return 을 대체한다. OrderFailedEvent
        1회 + NotificationEvent(error/system) 1회(누락 없음). G3: error_code 무관
        하게 Treasury 가 bot_id/order_id 로 release."""
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
        # get 예외 = 검증 불가 → status 축 account_status_unavailable(계층1 동형).
        assert cap.failed[0].error_code == "account_status_unavailable"
        broker.place_order.assert_not_called()
        assert _notif_count(cap) == 1  # P2-B: 알림 누락 없음.


# ── attempt4 (P1×2 + 메타 감사): place_order 직전 단일 재확인 + in-flight backstop ─


class _CallbackRateLimiter:
    """``acquire()`` await 중 콜백을 실행하는 테스트용 rate limiter.

    Fix 1(attempt4-a) TOCTOU 모사 — gate 평가가 ``acquire()`` **뒤**(place_order
    직전)로 이동했으므로, ``acquire()`` 대기 중 readiness/status 가 전환되면 gate 가
    그 변화를 보고 차단해야 한다(이동 전이라면 stale 통과).
    """

    def __init__(self, on_acquire) -> None:
        self._on_acquire = on_acquire
        self.acquired = 0

    async def acquire(self) -> None:
        self.acquired += 1
        res = self._on_acquire()
        if res is not None and hasattr(res, "__await__"):
            await res


class TestLayer3GatePositionAndBackstop:
    """attempt4-a(P1): gate 가 ``rate_limiter.acquire()``+``_get_broker()`` **이후**,
    ``place_order`` **직전**에 단일 재확인하므로 await 대기 중 발생한 not_ready/
    suspend 를 잡는다. attempt4-b(adjudicated): 계층3 가 status(SUSPENDED)도 함께
    재확인하는 in-flight kill-switch backstop."""

    def _broker(self) -> MagicMock:
        b = MagicMock()
        b.place_order = AsyncMock(return_value="BRK-1")
        return b

    def _gateway(
        self,
        bus: EventBus,
        *,
        registry: RuntimeReadinessRegistry,
        svc: MagicMock,
        broker: MagicMock,
    ) -> APIGateway:
        svc.get_broker = AsyncMock(return_value=broker)
        return APIGateway(account_service=svc, eventbus=bus, runtime_readiness=registry)

    async def test_fix1_not_ready_during_acquire_blocks_before_place_order(
        self,
    ) -> None:
        """Fix 1(attempt4-a): ready 로 진입했으나 ``acquire()`` 대기 중
        ``mark_not_ready`` → place_order **미호출** + OrderFailedEvent
        (account_not_ready) + G6 1회. gate 가 acquire 앞에 있었다면 stale 통과해
        실주문이 나갔을 회귀를 lock 한다."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        registry = ready_registry(ACCOUNT)
        svc = _account_service(make_account(ACCOUNT, status=AccountStatus.ACTIVE))
        gw = self._gateway(bus, registry=registry, svc=svc, broker=broker)

        # acquire() 대기 중 readiness 가 not_ready 로 전환되도록 콜백 주입.
        def _flip() -> None:
            registry.mark_not_ready(
                ACCOUNT, ReadinessFlag.FILL_RECONCILE, "in-flight degrade"
            )

        gw._rate_limiters[ACCOUNT] = _CallbackRateLimiter(_flip)  # type: ignore[assignment]

        await gw._on_order_approved(_approved(order_type="limit"))

        broker.place_order.assert_not_called()  # acquire 후 재확인이 차단(P1 lock).
        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_not_ready"
        assert _notif_count(cap) == 1  # G6: 단일 재확인 지점 → 정확히 1회.

    async def test_fix2_suspended_during_acquire_blocked_by_layer3(self) -> None:
        """Fix 2(attempt4-b, in-flight kill-switch backstop): 계층1 통과 후
        ``acquire()`` 대기 중 account suspend → 계층3 가 place_order 직전 status
        재확인으로 차단(account_suspended) + G6 1회, place_order 미호출.

        fresh fetch 모사 — routing fetch 는 ACTIVE, gate fetch 는 SUSPENDED 를
        반환하도록 ``get`` 을 순차 응답으로 구성한다."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        registry = ready_registry(ACCOUNT)
        active = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        suspended = make_account(ACCOUNT, status=AccountStatus.SUSPENDED)
        svc = MagicMock()
        # 1st get(routing) → ACTIVE, 2nd get(gate, acquire 이후 fresh) → SUSPENDED.
        svc.get = AsyncMock(side_effect=[active, suspended])
        gw = self._gateway(bus, registry=registry, svc=svc, broker=broker)

        await gw._on_order_approved(_approved(order_type="limit"))

        broker.place_order.assert_not_called()
        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_suspended"
        assert _notif_count(cap) == 1  # G6 1회.

    async def test_fix2_status_unavailable_during_gate_fail_closed(self) -> None:
        """Fix 2: gate fresh fetch 시 ``get`` 예외(STATUS_UNAVAILABLE) →
        account_status_unavailable fail-closed + place_order 미호출 + G6 1회.

        routing fetch 는 ACTIVE 성공, gate fetch(2nd get)만 예외로 만들어 status
        검증 불가를 격리 검증한다."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        registry = ready_registry(ACCOUNT)
        active = make_account(ACCOUNT, status=AccountStatus.ACTIVE)
        svc = MagicMock()
        svc.get = AsyncMock(side_effect=[active, RuntimeError("db locked")])
        gw = self._gateway(bus, registry=registry, svc=svc, broker=broker)

        await gw._on_order_approved(_approved(order_type="limit"))

        broker.place_order.assert_not_called()
        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_status_unavailable"
        assert _notif_count(cap) == 1

    async def test_direct_submit_suspended_raises_account_suspended(self) -> None:
        """계층3 직접 submit_order: verified SUSPENDED → APIError(account_suspended)
        + broker 미호출 + G6 1회(단일 재확인 지점)."""
        from ante.broker.exceptions import APIError

        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        registry = ready_registry(ACCOUNT)
        svc = _account_service(make_account(ACCOUNT, status=AccountStatus.SUSPENDED))
        gw = self._gateway(bus, registry=registry, svc=svc, broker=broker)

        with pytest.raises(APIError) as exc:
            await gw.submit_order(
                bot_id=BOT,
                symbol=SYMBOL,
                side="buy",
                quantity=10.0,
                account_id=ACCOUNT,
            )
        assert exc.value.error_code == "account_suspended"
        broker.place_order.assert_not_called()
        assert _notif_count(cap) == 1

    async def test_g6_exactly_once_per_order_single_recheck(self) -> None:
        """G6: 단일 재확인 지점이므로 동일 order 에 대해 not_ready 알림이 정확히
        1회(중복 평가 없음)."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        svc = _account_service(make_account(ACCOUNT, status=AccountStatus.ACTIVE))
        gw = self._gateway(
            bus, registry=not_ready_registry(ACCOUNT), svc=svc, broker=broker
        )

        await gw._on_order_approved(_approved(order_type="limit"))

        assert _notif_count(cap) == 1
        broker.place_order.assert_not_called()


# ── attempt4 메타리뷰: SSOT 공유 헬퍼 resolve_account_status (3-state) ──────────


class TestResolveAccountStatusSSOT:
    """``ante.account.gate.resolve_account_status`` 3-state 단위 테스트 + 계층1/계층3
    가 동일 헬퍼를 쓰는지(중복 구현 금지) 검증한다."""

    async def test_none_when_no_account_service(self) -> None:
        """account_service None → None(status 축 비활성, 비게이트 레거시)."""
        from ante.account.gate import resolve_account_status

        assert await resolve_account_status(None, ACCOUNT) is None

    async def test_verified_status_passthrough(self) -> None:
        """소스 present + get 성공 + status present → verified status 그대로."""
        from ante.account.gate import resolve_account_status

        svc = _account_service(make_account(ACCOUNT, status=AccountStatus.SUSPENDED))
        assert await resolve_account_status(svc, ACCOUNT) == AccountStatus.SUSPENDED

        svc2 = _account_service(make_account(ACCOUNT, status=AccountStatus.ACTIVE))
        assert await resolve_account_status(svc2, ACCOUNT) == AccountStatus.ACTIVE

    async def test_status_unavailable_on_get_exception(self) -> None:
        """소스 present + get 예외 → STATUS_UNAVAILABLE(검증 불가, 스냅샷 fallback
        금지)."""
        from ante.account.gate import STATUS_UNAVAILABLE, resolve_account_status

        svc = MagicMock()
        svc.get = AsyncMock(side_effect=RuntimeError("db locked"))
        assert await resolve_account_status(svc, ACCOUNT) is STATUS_UNAVAILABLE

    async def test_status_unavailable_on_none_or_missing_status(self) -> None:
        """소스 present + get None/status 미상 → STATUS_UNAVAILABLE."""
        from ante.account.gate import STATUS_UNAVAILABLE, resolve_account_status

        svc_none = MagicMock()
        svc_none.get = AsyncMock(return_value=None)
        assert await resolve_account_status(svc_none, ACCOUNT) is STATUS_UNAVAILABLE

        no_status = MagicMock()
        no_status.status = None
        svc_no_status = MagicMock()
        svc_no_status.get = AsyncMock(return_value=no_status)
        assert (
            await resolve_account_status(svc_no_status, ACCOUNT) is STATUS_UNAVAILABLE
        )

    async def test_derive_account_status_3state(self) -> None:
        """derive_account_status(I/O 없는 순수 도출) 3-state."""
        from ante.account.gate import STATUS_UNAVAILABLE, derive_account_status

        # 소스 None → None.
        assert derive_account_status(None, None, fetch_failed=False) is None
        # 소스 present + fetch_failed → STATUS_UNAVAILABLE.
        svc = MagicMock()
        assert derive_account_status(svc, None, fetch_failed=True) is STATUS_UNAVAILABLE
        # 소스 present + fetched None → STATUS_UNAVAILABLE.
        assert (
            derive_account_status(svc, None, fetch_failed=False) is STATUS_UNAVAILABLE
        )
        # 소스 present + verified status → 그대로.
        acc = make_account(ACCOUNT, status=AccountStatus.SUSPENDED)
        assert (
            derive_account_status(svc, acc, fetch_failed=False)
            == AccountStatus.SUSPENDED
        )

    async def test_layer1_uses_shared_helper(self) -> None:
        """계층1(RuleEngine._resolve_account_status)이 공유 헬퍼에 위임한다
        (중복 구현 금지) — 헬퍼를 패치하면 계층1 결과가 바뀐다."""
        from unittest.mock import patch

        from ante.account.gate import STATUS_UNAVAILABLE

        engine = RuleEngine(
            eventbus=EventBus(),
            account_id=ACCOUNT,
            account_service=_account_service(make_account(ACCOUNT)),
            account=make_account(ACCOUNT),
            runtime_readiness=ready_registry(ACCOUNT),
        )
        with patch(
            "ante.account.gate.resolve_account_status",
            new=AsyncMock(return_value=STATUS_UNAVAILABLE),
        ) as helper:
            result = await engine._resolve_account_status()
        helper.assert_awaited_once()
        assert result is STATUS_UNAVAILABLE

    async def test_layer3_uses_shared_derive_helper(self) -> None:
        """계층3(APIGateway._readiness_gate)이 공유 derive_account_status 로 status
        축을 평가한다 — verified SUSPENDED 면 account_suspended 차단."""
        bus = EventBus()
        cap = _capture(bus)
        broker = MagicMock()
        broker.place_order = AsyncMock(return_value="BRK-1")
        svc = _account_service(make_account(ACCOUNT, status=AccountStatus.SUSPENDED))
        svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=svc, eventbus=bus, runtime_readiness=ready_registry(ACCOUNT)
        )
        await gw._on_order_approved(_approved(order_type="limit"))

        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_suspended"
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

    async def test_gateway_meta_non_live_silent_skip(self) -> None:
        """#2398 Fix A: gateway 는 account 메타(trading_mode != LIVE)로 virtual
        주문 broker 경로를 **결정적으로** silent skip — broker.place_order 미호출
        + terminal 발행 없음(구독 순서 비의존)."""
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
        ev = _approved()
        # 마커 미설정이어도(gateway 단독 호출) 메타 기반 non-LIVE silent skip.
        await gw._on_order_approved(ev)

        broker.place_order.assert_not_called()
        assert cap.failed == []  # silent skip 은 실패가 아님(terminal 없음).
        assert cap.submitted == []
        # 메타 기반 라우팅이므로 _get_account(=svc.get) 를 단일 호출한다.
        svc.get.assert_awaited_once()

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


# ── #2398 P2 attempt1: deterministic virtual-routing 마커(중복 terminal/알림 누락) ─


class TestVirtualRoutingMarkerP2:
    """VirtualExecutor + APIGateway 를 같은 EventBus 에 배선해, 동일
    OrderApprovedEvent 인스턴스에 대한 라우팅이 중복 terminal(finding 1)·LIVE 알림
    누락·non-LIVE broker 호출(안전장치)을 모두 막는지 검증한다.

    #2398 attempt2: gateway 는 account 메타 기반 non-LIVE silent skip(Fix A)으로
    공통 케이스를 구독 순서 무관으로 라우팅하고, VirtualExecutor 의 priority(=60 >
    gateway 50)가 메타 실패 잔여 코너의 마커 신뢰성을 보장한다(Fix C). 따라서
    **구독 순서를 뒤집어도**(gateway 먼저) VirtualExecutor 가 priority 정렬로 먼저
    실행돼 결과가 불변임을 함께 검증한다(finding 1 핵심 회귀).
    """

    def _broker(self) -> MagicMock:
        b = MagicMock()
        b.place_order = AsyncMock(return_value="BRK-1")
        return b

    def _wire(
        self,
        bus: EventBus,
        *,
        account: object,
        registry: RuntimeReadinessRegistry | None,
        broker: MagicMock,
        gateway_account_service: MagicMock | None = None,
        gateway_first: bool = False,
    ):
        """VirtualExecutor + gateway 를 같은 EventBus 에 배선한다.

        EventBus 는 priority 내림차순(높은 priority 먼저)으로 핸들러를 디스패치하고
        (bus.py:46 reverse=True), VirtualExecutor 의 OrderApprovedEvent 구독
        priority(=60)는 gateway(=50)보다 높다(Fix C). 따라서 **subscribe 삽입
        순서와 무관하게** VirtualExecutor 가 먼저 실행돼 마커를 set 한다.

        ``gateway_first=True`` 면 gateway 를 먼저 subscribe 해(프로덕션 배선의 역순)
        구독 순서 비의존성을 회귀 검증한다 — priority 정렬로 VirtualExecutor 가 여전히
        먼저 실행되어야 한다(finding 1 핵심 회귀).
        """
        from ante.bot.providers.virtual import (
            VirtualExecutor,
            VirtualPortfolioView,
        )

        vexec_svc = _account_service(account)
        executor = VirtualExecutor(
            eventbus=bus,
            gateway=None,
            runtime_readiness=registry,
            account_service=vexec_svc,
        )
        executor.register_bot(BOT, VirtualPortfolioView(BOT, 10_000_000.0))

        gw_svc = gateway_account_service or _account_service(account)
        gw_svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=gw_svc,
            eventbus=bus,
            runtime_readiness=registry,
        )

        if gateway_first:
            # 구독 순서를 뒤집는다(gateway 먼저). priority(60>50) 정렬로 여전히
            # VirtualExecutor 가 먼저 실행돼야 한다(finding 1 핵심 회귀).
            gw.start()
            executor.subscribe()
        else:
            # 프로덕션 배선(VirtualExecutor 먼저 — main.py).
            executor.subscribe()
            gw.start()
        # VirtualExecutor 가 시장가 체결가를 gateway.get_current_price 로 조회하므로
        # gateway 를 가격 소스로 연결한다(가상 체결 경로 완결).
        executor._gateway = gw
        return executor, gw, vexec_svc

    @pytest.mark.parametrize("gateway_first", [False, True])
    async def test_virtual_meta_failure_single_terminal(
        self, gateway_first: bool
    ) -> None:
        """finding 1 메타 실패 잔여 코너(구독 순서 비의존): virtual 봇 주문 +
        양쪽 account_service.get 일시 실패.

        VirtualExecutor(priority 60)가 구독 순서와 무관하게 먼저 실행돼 G9
        fail-closed OrderFailedEvent 를 발행하고 ``_virtual_handled`` 마커를 set
        한다. gateway 는 메타 fetch 가 실패(None)해도 마커를 보고 skip
        (defense-in-depth) → 동일 order_id 에 대해 OrderFailedEvent **정확히 1회**
        (gateway 중복 없음). ``gateway_first`` 양쪽 다 동일 결과여야 한다."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        # registry=None 이면 VirtualExecutor 가 fail-closed(account_service.get 도
        # 도달 전 차단)이므로, 메타 fetch 일시 실패를 정확히 모사하려면
        # registry 는 ready 로 두고 account_service.get 만 예외로 만든다.
        account = make_account(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        registry = ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        # VirtualExecutor 의 account_service.get 을 일시 실패시킨다(G9 fail-closed).
        executor, gw, vexec_svc = self._wire(
            bus,
            account=account,
            registry=registry,
            broker=broker,
            gateway_first=gateway_first,
        )
        vexec_svc.get = AsyncMock(side_effect=RuntimeError("meta boom"))
        # gateway 의 account_service.get 도 같은 일시 실패라고 가정 — gateway 는
        # 메타 None 을 받고 마커(VirtualExecutor 선행 set)를 보고 skip 해야 한다.
        gw._account_service.get = AsyncMock(side_effect=RuntimeError("meta boom"))  # type: ignore[attr-defined]

        await bus.publish(_approved())

        # OrderFailedEvent 정확히 1회 — gateway 중복 발행 없음(finding 1).
        assert len(cap.failed) == 1
        assert cap.failed[0].error_code == "account_not_ready"
        # gateway 는 메타 실패(None)+마커를 보고 skip → broker 미호출.
        broker.place_order.assert_not_called()
        assert cap.filled == []  # fill 금지(G9).
        assert _notif_count(cap) == 1  # G6 알림 1회(VirtualExecutor 발행).

    async def test_live_meta_failure_failed_and_alert(self) -> None:
        """P2-B/attempt4-b: LIVE 주문 + 메타 실패 → OrderFailedEvent + 알림 정확히
        1회.

        VirtualExecutor 는 portfolio 미소유(live 봇) early-return(마커 미설정) →
        gateway 가 submit_order → 계층3 gate 가 place_order 직전 fresh fetch. get
        예외 = status 검증 불가 → status 축 account_status_unavailable fail-closed →
        G6 알림 + APIError → except → OrderFailedEvent(누락 없음)."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        live_account = make_account(ACCOUNT, trading_mode=TradingMode.LIVE)
        registry = ready_registry(ACCOUNT)
        # live 봇은 VirtualExecutor 에 register 하지 않는다(portfolio 미소유).
        from ante.bot.providers.virtual import VirtualExecutor

        executor = VirtualExecutor(
            eventbus=bus,
            gateway=None,
            runtime_readiness=registry,
            account_service=_account_service(live_account),
        )
        executor.subscribe()
        gw_svc = MagicMock()
        gw_svc.get = AsyncMock(side_effect=RuntimeError("meta boom"))
        gw_svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=gw_svc, eventbus=bus, runtime_readiness=registry
        )
        gw.start()

        await bus.publish(_approved())

        assert len(cap.failed) == 1
        # get 예외 = 검증 불가 → status 축 account_status_unavailable(계층1 동형).
        assert cap.failed[0].error_code == "account_status_unavailable"
        assert _notif_count(cap) == 1  # P2-B: 알림 누락 없음.
        broker.place_order.assert_not_called()
        assert cap.filled == []

    async def test_live_normal_order_places_once(self) -> None:
        """LIVE 정상 주문 → place_order 1회(마커 미설정 → gateway 처리)."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        live_account = make_account(ACCOUNT, trading_mode=TradingMode.LIVE)
        registry = ready_registry(ACCOUNT)
        from ante.bot.providers.virtual import VirtualExecutor

        executor = VirtualExecutor(
            eventbus=bus,
            gateway=None,
            runtime_readiness=registry,
            account_service=_account_service(live_account),
        )
        executor.subscribe()
        gw_svc = _account_service(live_account)
        gw_svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=gw_svc, eventbus=bus, runtime_readiness=registry
        )
        gw.start()

        await bus.publish(_approved(order_type="limit"))

        broker.place_order.assert_called_once()
        assert len(cap.submitted) == 1
        assert cap.failed == []
        assert cap.filled == []  # live 는 가상 체결 없음.

    @pytest.mark.parametrize("gateway_first", [False, True])
    async def test_virtual_normal_order_fills_gateway_skips(
        self, gateway_first: bool
    ) -> None:
        """finding 1 핵심 회귀(구독 순서 비의존): virtual 정상 주문 →
        VirtualExecutor 체결 1회 + gateway place_order 미호출 + terminal 중복 없음.

        ``gateway_first=True`` 는 gateway 를 먼저 subscribe 한 배선(프로덕션 역순)
        에서도 priority 정렬(VirtualExecutor 60 > gateway 50)로 VirtualExecutor 가
        선행 실행돼 결과가 불변임을 검증한다 — gateway 가 먼저 실행돼 non-LIVE 를
        마커 미설정 상태로 broker 경로/non_live terminal 로 보내는 race 가 봉쇄됨."""
        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        virtual_account = make_account(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        registry = ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        executor, gw, _ = self._wire(
            bus,
            account=virtual_account,
            registry=registry,
            broker=broker,
            gateway_first=gateway_first,
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
        await bus.publish(ev)

        assert len(cap.filled) == 1  # VirtualExecutor 체결 정확히 1회.
        broker.place_order.assert_not_called()  # gateway 메타 non-LIVE silent skip.
        assert cap.failed == []  # non-LIVE terminal 중복 없음(finding 1).
        assert cap.submitted == []

    async def test_unmarked_non_live_silent_skip_and_direct_submit_blocked(
        self,
    ) -> None:
        """Fix A: 마커 미설정 virtual 주문을 gateway 핸들러에 직접 전달해도 메타
        기반 non-LIVE silent skip(terminal 없음). 단 ``submit_order`` 직접 호출은
        ``_readiness_gate`` non-LIVE fail-closed(APIError) 로 broker 호출을 막아,
        직접 호출 경로의 virtual 주문이 실 broker 로 새지 않는다."""
        from ante.broker.exceptions import APIError

        bus = EventBus()
        cap = _capture(bus)
        broker = self._broker()
        virtual_account = make_account(ACCOUNT, trading_mode=TradingMode.VIRTUAL)
        svc = _account_service(virtual_account)
        svc.get_broker = AsyncMock(return_value=broker)
        gw = APIGateway(
            account_service=svc,
            eventbus=bus,
            runtime_readiness=ready_registry(ACCOUNT, trading_mode=TradingMode.VIRTUAL),
        )
        # 마커 미설정 주문을 gateway 핸들러에 직접 전달(VirtualExecutor 미배선 edge).
        # 메타 기반 non-LIVE silent skip → broker 미호출 + terminal 없음.
        await gw._on_order_approved(_approved())

        broker.place_order.assert_not_called()  # silent skip.
        assert cap.failed == []  # silent skip 은 실패가 아님(terminal 없음).
        assert cap.submitted == []

        # submit_order 직접 호출(라우팅 우회)은 non-LIVE fail-closed(APIError) 보장.
        with pytest.raises(APIError) as exc:
            await gw.submit_order(
                bot_id=BOT,
                symbol=SYMBOL,
                side="buy",
                quantity=10.0,
                account_id=ACCOUNT,
            )
        assert exc.value.error_code == "account_not_ready"
        assert "non_live_broker_call_blocked" in str(exc.value)


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


# ── finding 2: reason 산출 fail-closed(registry 조회 예외) ─────────────────────


class _RaisingRegistry:
    """``is_ready``/``active_trading_ready`` 가 예외를 던지는 registry mock.

    finding 2 모사 — ``active_trading_blocked`` 는 예외=차단(fail-closed)으로
    변환하지만(G2), 이어지는 ``not_ready_reason`` 이 같은 예외를 밖으로 흘리면
    EventBus 가 핸들러 예외를 swallow 해 terminal(OrderRejectedEvent)·알림이
    미발행된다. reason 산출도 fail-closed(bare reason) 여야 한다.
    """

    def is_ready(self, account_id: str, flag: object) -> bool:
        raise RuntimeError("readiness backend down")

    def active_trading_ready(
        self, account_id: str, *, broker_type: str, trading_mode: object
    ) -> bool:
        raise RuntimeError("readiness backend down")


class TestReasonFailClosed:
    """finding 2: ``not_ready_reason`` 이 registry 조회 예외를 호출자로 전파하지
    않고 bare ``account_not_ready`` 안전값으로 끝나는지(직접) + 그 덕에 계층2
    (Treasury) 차단 경로가 예외 전파 없이 terminal·알림을 발행하는지 검증한다."""

    def test_not_ready_reason_swallows_registry_exception(self) -> None:
        """gate 단위: ``registry.is_ready`` 예외 → bare ``account_not_ready``
        반환(예외 미전파)."""
        from ante.account.gate import ACCOUNT_NOT_READY_REASON, not_ready_reason

        reason = not_ready_reason(
            _RaisingRegistry(),  # type: ignore[arg-type]
            ACCOUNT,
            broker_type="kis-domestic",
            trading_mode=TradingMode.LIVE,
        )
        # suffix 없이 bare reason(예외가 핸들러 밖으로 새지 않음).
        assert reason == ACCOUNT_NOT_READY_REASON

    @pytest.mark.parametrize("side", ["buy", "sell"])
    async def test_treasury_block_no_exception_propagation(self, side: str) -> None:
        """계층2(Treasury): registry 조회 예외에도 OrderRejectedEvent +
        NotificationEvent 가 발행되고(terminal 누락 없음) 예외가 핸들러 밖으로
        전파되지 않는다(EventBus swallow 로 terminal 소실 방지)."""
        bus = EventBus()
        cap = _capture(bus)
        treasury = Treasury(
            db=MagicMock(),
            eventbus=bus,
            account_id=ACCOUNT,
            runtime_readiness=_RaisingRegistry(),  # type: ignore[arg-type]
            broker_type="kis-domestic",
            trading_mode=TradingMode.LIVE,
        )
        treasury.reserve_for_order = AsyncMock(return_value=True)  # type: ignore[method-assign]

        # 핸들러를 직접 호출 — 예외가 전파되면 여기서 raise 된다(전파 금지 검증).
        await treasury._on_order_validated(_validated(side=side))

        assert len(cap.rejected) == 1  # terminal 발행(누락 없음).
        assert cap.rejected[0].reason == "account_not_ready"  # bare(suffix 없음).
        assert cap.approved == []
        treasury.reserve_for_order.assert_not_called()  # reserve 누수 없음(G3).
        assert _notif_count(cap) == 1  # G6 알림 1회(누락 없음).
