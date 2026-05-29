"""포지션 정합성 검증 및 자동 보정."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.service import TradeService

logger = logging.getLogger(__name__)

# 분류 사유 — PositionMismatchEvent.reason / 보정 reason 에 실리는 SSOT 문자열.
REASON_EXTERNAL_LIQUIDATION = "외부 청산"
REASON_EXTERNAL_PARTIAL_SELL = "외부 일부 매도"
REASON_EXTERNAL_BUY = "외부 매수"
REASON_QTY_MISMATCH = "수량 불일치"
# self-submitted-unrecorded-fill (#1950): ante 가 제출했으나 아직 내부에 반영되지
# 않은 체결분. 외부 거래가 아니므로 자동 보정/매도를 유발하지 않고 info 알림만 낸다.
REASON_SELF_SUBMITTED = "ante 미반영 체결"


class PositionReconciler:
    """브로커 실제 포지션과 내부 포지션의 불일치를 감지하고 보정한다."""

    def __init__(
        self,
        trade_service: TradeService,
        eventbus: EventBus,
        order_tracker: OrderTracker | None = None,
    ) -> None:
        self._trade_service = trade_service
        self._eventbus = eventbus
        # #1950: broker_qty > internal_qty(외부 매수 후보) 분기에서 ante 미반영
        # 체결(self-submitted)을 외부 매수와 구분하기 위한 권위 저장소(OrderTracker).
        # 미주입(None)이면 self-check 를 생략하고 기존 "외부 매수" 분류로 동작한다
        # (하위 호환 — 다만 main.py 의 두 배선 경로는 항상 주입한다).
        self._order_tracker = order_tracker

    async def reconcile(
        self,
        bot_id: str,
        broker_positions: list[dict[str, Any]],
        *,
        account_id: str,
        skip_external_buy: bool = False,
    ) -> list[dict[str, Any]]:
        """봇의 내부 포지션과 브로커 포지션을 대조하여 보정.

        Args:
            bot_id: 대상 봇 ID.
            broker_positions: 브로커 실제 보유.
                [{"symbol": str, "quantity": float, "avg_price": float}, ...]
            account_id: 봇이 귀속된 account_id (포지션 보정 시 명시 필수).
            skip_external_buy: True 면 "외부 매수"(브로커>내부) 분류의 보정·이벤트
                발행을 **건너뛴다**(경고 로그만). 체결 복구(fill catch-up)가
                성공하지 못한 계좌에서, 미복구 ante 체결을 "외부 매수" 로
                오분류하는 것을 막기 위한 barrier 안전장치다(#1946 Finding 1).
                다른 분류(외부 청산·일부 매도)는 영향받지 않는다.

                **self-submitted 분류와는 직교한다(#1950 R1-1)**: self-check 는
                `skip_external_buy` 와 무관하게 항상 수행되며, 이 플래그는 분류
                결과 중 "외부 매수" 보정만 억제하는 별도 계층이다. 주기
                reconcile(`skip_external_buy=False`)에서도 self 는 보정되지 않는다.

        Returns:
            보정 내역 리스트. 불일치가 없으면 빈 리스트.
        """
        from ante.eventbus.events import (
            NotificationEvent,
            PositionMismatchEvent,
            ReconcileEvent,
        )

        internal = await self._trade_service.get_positions(
            bot_id, account_id=account_id
        )
        internal_map: dict[str, dict[str, float]] = {
            p.symbol: {
                "quantity": p.quantity,
                "avg_price": p.avg_entry_price,
            }
            for p in internal
            if p.quantity > 0
        }

        broker_map: dict[str, dict[str, float]] = {
            p["symbol"]: {
                "quantity": p["quantity"],
                "avg_price": p.get("avg_price", 0.0),
            }
            for p in broker_positions
            if p["quantity"] > 0
        }

        corrections: list[dict[str, Any]] = []

        # 내부에는 있지만 브로커에 없거나 수량 불일치
        all_symbols = set(internal_map.keys()) | set(broker_map.keys())

        for symbol in all_symbols:
            i_qty = internal_map.get(symbol, {}).get("quantity", 0.0)
            b_qty = broker_map.get(symbol, {}).get("quantity", 0.0)
            b_avg = broker_map.get(symbol, {}).get("avg_price", 0.0)

            if i_qty == b_qty:
                continue

            # 불일치 감지 — 분류
            is_external_buy = False
            if b_qty == 0 and i_qty > 0:
                reason = REASON_EXTERNAL_LIQUIDATION
            elif b_qty < i_qty:
                reason = REASON_EXTERNAL_PARTIAL_SELL
            elif b_qty > i_qty:
                # #1950: broker > internal — "외부 매수" 후보. ante 미반영
                # 체결(self-submitted)을 외부 매수와 구분하기 위해 **항상**
                # self-check 를 수행한다(skip_external_buy 와 무관, R1-1).
                if await self._is_self_submitted_fill(
                    bot_id=bot_id,
                    account_id=account_id,
                    symbol=symbol,
                    excess=b_qty - i_qty,
                ):
                    # self-submitted-unrecorded-fill: 외부 거래가 아니므로 자동
                    # 보정/매도를 유발하지 않는다. 실제 포지션 복구는
                    # FillApplier(#1946) 가 단일 권위자로 수행한다. reconciler 는
                    # info 알림만 내고 correct_position 을 호출하지 않는다.
                    logger.info(
                        "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s "
                        "(ante 미반영 체결 — 보정 skip, FillApplier 위임)",
                        bot_id,
                        symbol,
                        i_qty,
                        b_qty,
                        REASON_SELF_SUBMITTED,
                    )
                    await self._eventbus.publish(
                        PositionMismatchEvent(
                            bot_id=bot_id,
                            symbol=symbol,
                            internal_qty=i_qty,
                            broker_qty=b_qty,
                            reason=REASON_SELF_SUBMITTED,
                        )
                    )
                    await self._eventbus.publish(
                        NotificationEvent(
                            level="info",
                            title="포지션 동기화 지연",
                            message=(
                                f"봇: `{bot_id}` · 종목: `{symbol}`\n"
                                f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                                f"사유: {REASON_SELF_SUBMITTED} "
                                "(체결 반영 대기 — 자동 보정 없음)"
                            ),
                            category="broker",
                        )
                    )
                    continue
                reason = REASON_EXTERNAL_BUY
                is_external_buy = True
            else:
                reason = REASON_QTY_MISMATCH

            if is_external_buy and skip_external_buy:
                # fill 복구 미성공 계좌 — barrier 가 external-buy 분류를 연기한다.
                # 미복구 ante 체결을 "외부 매수" 로 오분류해 잘못 보정하지 않도록
                # 보정·이벤트를 건너뛰고 경고만 남긴다(#1946 Finding 1). 다음
                # 주기 대사(체결 복구 후)에서 정상 처리된다.
                logger.warning(
                    "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s "
                    "(fill 복구 미성공 — external-buy 분류 연기)",
                    bot_id,
                    symbol,
                    i_qty,
                    b_qty,
                    reason,
                )
                continue

            logger.warning(
                "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s",
                bot_id,
                symbol,
                i_qty,
                b_qty,
                reason,
            )

            await self._eventbus.publish(
                PositionMismatchEvent(
                    bot_id=bot_id,
                    symbol=symbol,
                    internal_qty=i_qty,
                    broker_qty=b_qty,
                    reason=reason,
                )
            )
            await self._eventbus.publish(
                NotificationEvent(
                    level="critical",
                    title="포지션 불일치",
                    message=(
                        f"봇: `{bot_id}` · 종목: `{symbol}`\n"
                        f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                        f"사유: {reason}"
                    ),
                    category="broker",
                )
            )

            correction = await self._trade_service.correct_position(
                bot_id=bot_id,
                symbol=symbol,
                quantity=b_qty,
                avg_price=b_avg if b_avg > 0 else None,
                reason=reason,
                account_id=account_id,
            )
            corrections.append(correction)

        if corrections:
            logger.info(
                "포지션 보정 완료 [%s]: %d건",
                bot_id,
                len(corrections),
            )
            await self._eventbus.publish(
                ReconcileEvent(
                    bot_id=bot_id,
                    discrepancy_count=len(corrections),
                    corrections=corrections,
                )
            )

        return corrections

    async def _is_self_submitted_fill(
        self,
        *,
        bot_id: str,
        account_id: str,
        symbol: str,
        excess: float,
    ) -> bool:
        """broker 초과분(``excess``)이 ante 미반영 체결로 설명되는지 판정 (#1950).

        OrderTracker 에서 ``(account_id, bot_id, symbol, side="buy")`` 의
        non-terminal(open/partially_filled) 주문을 조회하고, 그 미체결 잔량 합
        (capacity = Σ(ordered_qty − recorded_filled_qty)) 과 ``excess`` 를 비교한다.

        - ``excess <= capacity`` → True (self_submitted_unrecorded_fill).
          ante 가 제출했으나 FillApplier 가 아직 기록 못 한 체결로 설명 가능.
        - ``excess > capacity`` 또는 매칭 주문 없음 → False (외부 매수로 분류).
        - OrderTracker 미주입 → False (하위 호환 — 기존 "외부 매수" 동작).

        **bounded known-limitation (R2-1)**: broker 포지션은 총량만 주므로
        ante 미체결 capacity 안에 숨은 진짜 외부 매수는 즉시 보정되지 않는다.
        이는 #1945 auto-sell 캐스케이드 회피를 외부 검출 완전성보다 우선하는
        보수적 trade-off다. 매칭 ante 주문이 해소(완전 체결→open set 이탈, 또는
        EOD expire_stale→terminal)되면 다음 reconcile 에서 잔여 excess 가 external
        로 검출된다. 상세: ``docs/specs/trade/03-07-position-reconciler.md``.
        """
        if self._order_tracker is None:
            return False

        try:
            open_orders = await self._order_tracker.get_open_orders_for(
                account_id=account_id,
                bot_id=bot_id,
                symbol=symbol,
                side="buy",
            )
        except Exception:
            # OrderTracker 조회 실패 시 self-check 를 포기하고 보수적으로 외부
            # 매수로 분류한다(안전 보정 유지). 조회 자체가 reconcile 을 깨뜨리지
            # 않도록 방어한다.
            logger.exception(
                "self-check OrderTracker 조회 실패 [%s] %s — external 분류로 폴백",
                bot_id,
                symbol,
            )
            return False

        if not open_orders:
            return False

        capacity = sum(
            max(o.ordered_qty - o.recorded_filled_qty, 0.0) for o in open_orders
        )
        return excess <= capacity
