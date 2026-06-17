"""Virtual 계좌 봇용 Provider 구현체 + VirtualExecutor.

인메모리 가상 자금/포지션으로 실제 계좌 영향 없이 전략을 검증한다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from ante.broker.models import CommissionInfo
from ante.strategy.base import OrderView, PortfolioView

if TYPE_CHECKING:
    from ante.account.readiness import RuntimeReadinessRegistry
    from ante.account.service import AccountService
    from ante.eventbus.bus import EventBus
    from ante.gateway.gateway import APIGateway

logger = logging.getLogger(__name__)


class VirtualPortfolioView(PortfolioView):
    """Virtual 계좌 봇용 PortfolioView. 인메모리 가상 잔고/포지션 관리."""

    def __init__(self, bot_id: str, initial_balance: float) -> None:
        self._bot_id = bot_id
        self._initial_balance = initial_balance
        self._balance = initial_balance
        self._reserved: float = 0.0
        self._positions: dict[str, dict[str, Any]] = {}
        self._pending_orders: dict[str, dict[str, Any]] = {}

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """현재 보유 포지션 조회."""
        return {
            symbol: dict(pos)
            for symbol, pos in self._positions.items()
            if pos["quantity"] > 0
        }

    def get_balance(self, bot_id: str) -> dict[str, float]:
        """가상 자금 현황 조회."""
        return {
            "allocated": self._initial_balance,
            "available": self._balance - self._reserved,
            "reserved": self._reserved,
        }

    def apply_fill(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        commission: float,
    ) -> None:
        """가상 체결 결과를 포지션/잔고에 반영."""
        pos = self._positions.get(
            symbol,
            {
                "symbol": symbol,
                "quantity": 0.0,
                "avg_entry_price": 0.0,
                "realized_pnl": 0.0,
            },
        )

        if side == "buy":
            total_cost = pos["avg_entry_price"] * pos["quantity"]
            new_cost = price * quantity
            new_qty = pos["quantity"] + quantity
            new_avg = (total_cost + new_cost) / new_qty if new_qty > 0 else 0.0

            pos["quantity"] = new_qty
            pos["avg_entry_price"] = new_avg
            self._balance -= price * quantity + commission

        elif side == "sell":
            pnl = (price - pos["avg_entry_price"]) * quantity - commission
            new_qty = pos["quantity"] - quantity

            pos["quantity"] = max(new_qty, 0.0)
            if new_qty <= 0:
                pos["avg_entry_price"] = 0.0
            pos["realized_pnl"] += pnl
            self._balance += price * quantity - commission

        self._positions[symbol] = pos

    def check_balance(self, amount: float) -> bool:
        """잔고 충분 여부 확인."""
        return (self._balance - self._reserved) >= amount

    def reserve(self, order_id: str, amount: float) -> None:
        """주문용 자금 예약."""
        self._reserved += amount
        self._pending_orders[order_id] = {"amount": amount}

    def release_reservation(self, order_id: str) -> None:
        """예약 해제."""
        order = self._pending_orders.pop(order_id, None)
        if order:
            self._reserved -= order["amount"]


class VirtualOrderView(OrderView):
    """Virtual 계좌 봇용 OrderView. VirtualPortfolioView의 미체결 주문 추적.

    #1948: VirtualExecutor 는 ``OrderApprovedEvent`` 를 즉시 가상 체결하고
    ``OrderSubmittedEvent`` 를 발행하지 않으므로(발행처는 live gateway 단독),
    virtual 주문은 OrderTracker 에 들어가지 않는다 → OrderTracker 백엔드 미사용.
    virtual 은 즉시 체결로 open window 가 사실상 없어
    ``_pending_orders`` (프로덕션 대개 빈)를 **통일 OpenOrder dict 스키마**로
    best-effort 매핑한다. amount(예약 금액)는 OrderView 스키마에서 제외한다.
    """

    def __init__(self, portfolio: VirtualPortfolioView) -> None:
        self._portfolio = portfolio

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회 (통일 OpenOrder dict 스키마)."""
        result: list[dict[str, Any]] = []
        for oid, info in self._portfolio._pending_orders.items():
            ordered_qty = float(info.get("ordered_qty", 0.0))
            recorded = float(info.get("recorded_filled_qty", 0.0))
            remaining = ordered_qty - recorded
            result.append(
                {
                    "order_id": oid,
                    "symbol": info.get("symbol", ""),
                    "side": info.get("side", ""),
                    "ordered_qty": ordered_qty,
                    "recorded_filled_qty": recorded,
                    "remaining_qty": remaining if remaining > 0 else 0.0,
                    "status": info.get("status", "open"),
                    "submitted_at": info.get("submitted_at"),
                }
            )
        return result


class VirtualExecutor:
    """Virtual 계좌 봇의 주문을 가상 체결하는 실행기.

    EventBus에서 OrderApprovedEvent를 구독하여 virtual 계좌 봇의 주문만 처리한다.
    RuleEngine → Treasury 파이프라인을 거친 승인된 주문만 체결한다.
    """

    def __init__(
        self,
        eventbus: EventBus,
        gateway: APIGateway | None = None,
        commission_rate: float = 0.00015,
        sell_tax_rate: float = 0.0023,
        slippage_rate: float = 0.0,
        runtime_readiness: RuntimeReadinessRegistry | None = None,
        account_service: AccountService | None = None,
    ) -> None:
        self._eventbus = eventbus
        self._gateway = gateway
        self._commission_info = CommissionInfo(
            buy_commission_rate=commission_rate,
            sell_commission_rate=commission_rate + sell_tax_rate,
        )
        self._slippage_rate = slippage_rate
        self._portfolios: dict[str, VirtualPortfolioView] = {}
        self._bot_configs: dict[str, Any] = {}
        # #2398 G9: virtual 경로 계층3-equivalent backstop. VirtualExecutor 와
        # APIGateway 는 둘 다 OrderApprovedEvent priority=50 구독이고 gateway 는
        # virtual 을 skip 하므로, not_ready virtual approval 이 (상류 우회/직접
        # 발행으로) 들어오면 gateway 차단을 우회해 VirtualExecutor 가 체결할 수
        # 있다. D-ACC-09 "단일 chokepoint 가정 금지" 원칙상 VirtualExecutor 가
        # virtual 경로를 독립 게이트한다. 미주입(None)이면 fail-closed(G2). 매
        # 이벤트 시점 registry 조회(상태 캐시 금지, G5).
        self._runtime_readiness = runtime_readiness
        self._account_service = account_service

    def register_bot(self, bot_id: str, portfolio: VirtualPortfolioView) -> None:
        """Virtual 계좌 봇의 PortfolioView 등록."""
        self._portfolios[bot_id] = portfolio
        logger.info("VirtualExecutor: 봇 등록 %s", bot_id)

    def unregister_bot(self, bot_id: str) -> None:
        """Virtual 계좌 봇 등록 해제."""
        self._portfolios.pop(bot_id, None)
        logger.info("VirtualExecutor: 봇 해제 %s", bot_id)

    # #2398 priority invariant: VirtualExecutor 의 OrderApprovedEvent 구독
    # priority 는 APIGateway(``_on_order_approved`` priority=50)보다 **반드시
    # 높아야** 한다. EventBus.publish 는 priority 내림차순(높은 priority 먼저)으로
    # 핸들러를 디스패치하므로(bus.py:46 reverse=True), 이 invariant 가 있으면
    # **구독(subscribe) 삽입 순서와 무관하게** VirtualExecutor 가 항상 gateway 보다
    # 먼저 실행돼 자신이 소유한 virtual 주문에 ``_virtual_handled`` 마커를 set 한다.
    # Fix A(gateway 메타 기반 non-LIVE silent skip)가 공통 케이스의 라우팅을 이미
    # 순서 무관으로 만들고, 이 priority 는 메타 실패 잔여 코너에서 gateway 가
    # 마커를 신뢰할 수 있게 하는 defense-in-depth 다(구독 순서 race 봉쇄).
    _ORDER_APPROVED_PRIORITY = 60

    def subscribe(self) -> None:
        """EventBus에 OrderApprovedEvent 구독.

        #2398: priority 는 ``_ORDER_APPROVED_PRIORITY``(=60)로 APIGateway(=50)보다
        높게 둔다 — 구독 삽입 순서와 무관하게 gateway 보다 먼저 실행돼
        ``_virtual_handled`` 마커를 set 한다(위 invariant 주석 참조).
        """
        from ante.eventbus.events import OrderApprovedEvent

        self._eventbus.subscribe(
            OrderApprovedEvent,
            self._on_order_approved,
            priority=self._ORDER_APPROVED_PRIORITY,
        )
        logger.info("VirtualExecutor 구독 완료")

    async def _gate_blocked_reason(self, account_id: str) -> str | None:
        """G9 + G7 backstop — virtual 경로 최종 차단 사유 토큰(fail-closed).

        #2398 attempt5: VirtualExecutor 는 virtual 경로의 **유일한 최종 backstop**
        이다(APIGateway 는 virtual 주문을 silent skip 하므로 gateway 계층3 의
        ``account_suspended`` 차단이 virtual 에는 적용되지 않는다). 따라서 계층1
        통과 후 Treasury/VirtualExecutor 처리 중 ``account suspend`` 가 끼어들거나
        ``OrderApprovedEvent`` 가 직접 유입되면, gateway 계층3 와 **대칭**으로
        VirtualExecutor 가 status(SUSPENDED)도 함께 재확인해야 한다(D-ACC-09 §8 —
        live=gateway 계층3, virtual=VirtualExecutor 최종 backstop).

        **단일 fetch 공유(중복 get 금지)**: account 를 **한 번** fetch 해
        status(SUSPENDED) + readiness(broker_type/trading_mode) 를 함께 평가한다.
        status 3-state 도출은 계층1/계층3 와 **동일 공유 헬퍼**
        (``derive_account_status``)를 써 중복 구현을 금지한다(SSOT).

        평가 축(둘 중 하나라도 막으면 차단 — D-ACC-09 §8 effect 일관성):

        - **status 축(G7 in-flight kill-switch backstop)**: verified SUSPENDED →
          ``account_suspended``; ``STATUS_UNAVAILABLE``(소스 present + 조회 예외/미상)
          → ``account_status_unavailable`` fail-closed; ``None``(소스 미구성)/verified
          non-SUSPENDED → status 축 통과.
        - **readiness 축(G9)**: registry/account_service 미주입·account 메타 취득
          실패 = 차단(G2). 면제 매트릭스 적용 후 not_ready → ``account_not_ready``.

        반환: 차단 사유 토큰(``account_suspended`` | ``account_status_unavailable`` |
        ``account_not_ready``) 또는 통과 시 ``None``. 매 이벤트 시점 fresh fetch +
        registry/status 조회(상태 캐시 금지, G5 liveness).
        """
        from ante.account.gate import (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
            ACCOUNT_SUSPENDED_REASON,
            STATUS_UNAVAILABLE,
            active_trading_blocked,
            derive_account_status,
        )
        from ante.account.models import AccountStatus

        # registry 미주입 = fail-closed(G2). account_service 미주입은 status 축
        # 비활성(derive_account_status → None)이지만 readiness 축이 차단한다.
        if self._runtime_readiness is None or self._account_service is None:
            return ACCOUNT_NOT_READY_REASON

        # ── 단일 fresh fetch(중복 get 금지) — status + readiness 공동 평가 ──────
        fetched: Any | None = None
        fetch_failed = False
        try:
            fetched = await self._account_service.get(account_id)
        except Exception:  # noqa: BLE001 — 조회 실패 = fail-closed(G2)·검증 불가.
            fetch_failed = True

        # status 축(G7) — gateway 계층3 와 동일 3-state 도출(공유 헬퍼 SSOT).
        # account_service 는 위에서 not-None 확인됨 → status 축 활성.
        status = derive_account_status(
            self._account_service, fetched, fetch_failed=fetch_failed
        )
        if status == AccountStatus.SUSPENDED:
            return ACCOUNT_SUSPENDED_REASON
        if status is STATUS_UNAVAILABLE:
            # 소스 present + 조회 예외/미상 = 검증 불가 → fail-closed(in-flight
            # suspend 를 stale 통과시키지 않는다). fetch 실패(fetched None)도 여기로
            # 귀결돼 readiness 축의 메타 미상 차단보다 우선한다(계층3 동형).
            return ACCOUNT_STATUS_UNAVAILABLE_REASON

        # readiness 축(G9) — status 축 통과 시에만 평가(둘 중 하나라도 막으면 차단).
        broker_type = getattr(fetched, "broker_type", None)
        trading_mode = getattr(fetched, "trading_mode", None)
        if not isinstance(broker_type, str) or trading_mode is None:
            return ACCOUNT_NOT_READY_REASON
        if active_trading_blocked(
            self._runtime_readiness,
            account_id,
            broker_type=broker_type,
            trading_mode=trading_mode,
        ):
            return ACCOUNT_NOT_READY_REASON
        return None

    async def _fail_order(self, event: Any, *, error_message: str) -> None:
        """virtual 주문을 OrderFailedEvent 로 종결한다(fill 금지).

        bot_id/order_id/account_id 를 보존해 Treasury ``_on_order_failed`` →
        ``release_reservation`` 정확 해제(시장가 매수 reserve 고착 방지, G3/G8).
        gate 차단 사유(``account_not_ready`` / ``account_suspended`` /
        ``account_status_unavailable``)면 G6 운영자 알림 1회를 함께 발행한다(G9 도
        G6 상속, BUY/SELL 무관, 청산 marker 면 "청산 차단" 문구). gateway 계층3 와
        대칭으로 status 차단(suspended/unavailable)도 동일 generic 알림 1회를 낸다.
        """
        from ante.account.gate import (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
            ACCOUNT_SUSPENDED_REASON,
            build_not_ready_notification,
            is_liquidation_reason,
        )
        from ante.eventbus.events import OrderFailedEvent

        # G6 발행 + error_code 부여 대상 gate 차단 사유(전 계층 통일 토큰 SSOT).
        gate_reasons = (
            ACCOUNT_NOT_READY_REASON,
            ACCOUNT_SUSPENDED_REASON,
            ACCOUNT_STATUS_UNAVAILABLE_REASON,
        )
        is_gate_block = error_message in gate_reasons
        await self._eventbus.publish(
            OrderFailedEvent(
                account_id=event.account_id,
                order_id=event.order_id,
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                symbol=event.symbol,
                side=event.side,
                quantity=event.quantity,
                # G8: 0원 체결 금지의 짝 — 실패 종결 OrderFailedEvent.price 는
                # 체결가가 아니라 known 명시가(없으면 0.0)일 뿐, fill 은 발생하지
                # 않는다.
                price=event.price or 0.0,
                order_type=event.order_type,
                error_message=error_message,
                # gate 차단(not_ready/suspended/status_unavailable)이면 해당 토큰을
                # error_code 로 보존한다(gateway 계층3 error_code 와 대칭).
                error_code=(error_message if is_gate_block else ""),
                exchange=event.exchange,
            )
        )
        if is_gate_block:
            await self._eventbus.publish(
                build_not_ready_notification(
                    account_id=event.account_id,
                    reason=error_message,
                    side=getattr(event, "side", ""),
                    # OrderApprovedEvent 는 reason 필드가 없어 청산 marker 를
                    # 운반하지 못하므로 generic 문구다(청산은 상류 계층1 차단).
                    is_liquidation=is_liquidation_reason(getattr(event, "reason", "")),
                )
            )

    async def _on_order_approved(self, event: object) -> None:
        """OrderApprovedEvent 처리. virtual 계좌 봇의 주문만 처리."""
        from ante.eventbus.events import (
            OrderApprovedEvent,
            OrderFilledEvent,
        )

        if not isinstance(event, OrderApprovedEvent):
            return

        # 등록 단계의 stop / stop_limit 주문은 가상 체결하지 않는다.
        # StopOrderManager가 trigger 시 변환된 OrderRequestEvent를 발행하면
        # 그 변환 주문이 일반 limit/market로 다시 RuleEngine → Treasury →
        # OrderApprovedEvent 경로를 타고 들어와 정상 체결된다.
        if event.order_type in ("stop", "stop_limit"):
            return

        portfolio = self._portfolios.get(event.bot_id)
        if portfolio is None:
            return  # live 봇의 주문 → 무시 (APIGateway가 처리)

        # ── #2398 deterministic virtual-routing 마커(메타 실패 코너 defense-in-depth) ─
        # VirtualExecutor 는 OrderApprovedEvent 를 ``_ORDER_APPROVED_PRIORITY``(=60)
        # 로 구독해 gateway(priority=50)보다 **구독 순서와 무관하게 항상 먼저**
        # 실행된다(EventBus priority 내림차순 디스패치, bus.py:46). 자신이
        # **소유**(portfolio 존재 = virtual 봇)한 주문에 마커를 set 하면 후속 gateway
        # 핸들러가 이를 신뢰할 수 있다(#1331 ``_consumed`` 선례 = frozen dataclass 에
        # ``object.__setattr__``). gateway 의 공통 라우팅은 account 메타 기반
        # non-LIVE silent skip 이지만(Fix A), gateway 의 메타 fetch 가 실패하는
        # 잔여 코너에서 gateway 는 이 마커를 보고 skip 하여 동일 order_id 에 대한
        # terminal 중복(strategy on_order_update / TradeRecorder 이중 처리)을 막는다.
        # account_service.get 일시 실패로 G9/G8 실패 종결이 나도 마커가 먼저 set
        # 되므로 gateway 메타 실패 fail-closed 경로와 겹쳐 중복 terminal 이 나지
        # 않는다. stop/stop_limit 은 위에서 marker 없이 early-return 하여 gateway
        # StopOrderManager 라우팅을 그대로 보존한다(virtual stop 경로 불변).
        object.__setattr__(event, "_virtual_handled", True)

        order_id = event.order_id
        account_id = event.account_id
        symbol = event.symbol
        side = event.side
        quantity = event.quantity
        order_type = event.order_type

        # ── #2398 G9 + G7: virtual 경로 계층3-equivalent 최종 backstop ─────────
        # 위치: stop/stop_limit·portfolio 필터·마커 set 직후. gateway 계층3 와
        # **대칭**으로 단일 fresh fetch 에서 status(SUSPENDED) + readiness 를 함께
        # 재확인한다(attempt5). 차단 사유(account_suspended/account_status_unavailable/
        # account_not_ready)면 OrderFailedEvent(bot_id/order_id/account_id 보존) 종결
        # + fill 금지(apply_fill/OrderFilledEvent 도달 차단) + G6 알림 1회. APIGateway
        # 가 virtual 을 silent skip 하므로 SUSPENDED in-flight 차단의 최종 backstop 은
        # 여기다(D-ACC-09 §8). fail-closed(G2): registry/account_service 미주입·조회
        # 예외 = 차단. 매 이벤트 시점 fetch/registry 조회(상태 캐시 금지, G5).
        blocked_reason = await self._gate_blocked_reason(account_id)
        if blocked_reason is not None:
            await self._fail_order(event, error_message=blocked_reason)
            return

        # 체결가 계산
        if order_type == "limit" and event.price is not None:
            fill_price = event.price
        else:
            # market 주문: 현재가 기반 + 슬리피지.
            # #2398 G8: broker 장애 중 가격 조회 실패가 0원 체결로 이어지지 않도록
            # ``event.price or 0.0`` 폴백을 제거한다. 가격 조회 실패 또는 gateway
            # 부재 + event.price 부재 시 OrderFailedEvent 로 종결한다(0원 체결 금지).
            # 이 지점은 OrderApprovedEvent 이후라 시장가 매수 reserve 가 잡혀 있을
            # 수 있고 Treasury 는 reserve 를 **OrderFailedEvent 로만** 해제하므로,
            # OrderRejectedEvent/예외로 끝내면 reserve 가 고착된다(계층3 정합 동일).
            current_price: float | None = None
            if self._gateway:
                try:
                    current_price = await self._gateway.get_current_price(
                        symbol, account_id=account_id
                    )
                except Exception:
                    logger.warning("현재가 조회 실패: %s — 주문 실패 종결", symbol)
                    current_price = None
            elif event.price is not None:
                # gateway 부재이지만 명시 가격이 있으면(예: limit 외 명시) 그대로 사용.
                current_price = event.price

            if current_price is None or current_price <= 0:
                logger.error(
                    "Virtual 시장가 체결가 미상 — 0원 체결 금지, 주문 실패 종결 "
                    "(order_id=%s, symbol=%s)",
                    order_id,
                    symbol,
                )
                await self._fail_order(
                    event, error_message="virtual_market_price_unavailable"
                )
                return

            if self._slippage_rate > 0:
                if side == "buy":
                    fill_price = current_price * (1 + self._slippage_rate)
                else:
                    fill_price = current_price * (1 - self._slippage_rate)
            else:
                fill_price = current_price

        # 수수료 계산
        trade_amount = fill_price * quantity
        commission = self._commission_info.calculate(side, trade_amount)

        # 가상 체결: 포지션/잔고 업데이트
        portfolio.apply_fill(symbol, side, quantity, fill_price, commission)

        # OrderFilledEvent 발행.
        #
        # #1949 fill_dedup_key 빈키 정책: VirtualProvider 는 가상 체결을 즉시 1회
        # 직접 발행하는 경로로, FillApplier/OrderTracker(CAS) 와 outbox 를 거치지
        # 않는다. 따라서 결정적 fill_dedup_key(= order_id:confirmed_cumulative)의
        # 산출 기반(CAS 확정 누적값)이 없다. at-least-once 재전달도 없으므로(outbox
        # 미경유, 단발 in-memory 발행) dedup 대상이 아니다 → fill_dedup_key 는
        # **빈키("")** 로 둔다. (default 이므로 명시 생략 가능하나, 정책을 코드로
        # 못박기 위해 명시한다.) 소비자(#1957)는 빈키를 "dedup 비대상" 으로 본다.
        await self._eventbus.publish(
            OrderFilledEvent(
                order_id=order_id,
                broker_order_id=f"virtual-{order_id[:8]}",
                bot_id=event.bot_id,
                strategy_id=event.strategy_id,
                account_id=account_id,
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=fill_price,
                commission=commission,
                order_type=order_type,
                timestamp=datetime.now(UTC),
                fill_dedup_key="",
            )
        )
        logger.info(
            "Virtual 체결: %s %s %s qty=%s price=%s commission=%s",
            event.bot_id,
            side,
            symbol,
            quantity,
            fill_price,
            commission,
        )
