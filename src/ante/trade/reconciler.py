"""포지션 정합성 검증 및 자동 보정."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.instrument.service import InstrumentService
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.service import TradeService

logger = logging.getLogger(__name__)

REASON_EXTERNAL_LIQUIDATION = "외부 청산"
REASON_EXTERNAL_PARTIAL_SELL = "외부 일부 매도"
REASON_EXTERNAL_BUY = "외부 매수"
REASON_QTY_MISMATCH = "수량 불일치"
REASON_SELF_SUBMITTED = "ante 미반영 체결"
REASON_UNATTRIBUTED_HOLDING = "미귀속 보유"


class PositionReconciler:
    """브로커 실제 포지션과 내부 포지션의 불일치를 감지하고 보정한다."""

    def __init__(
        self,
        trade_service: TradeService,
        eventbus: EventBus,
        order_tracker: OrderTracker | None = None,
        instrument_service: InstrumentService | None = None,
    ) -> None:
        self._trade_service = trade_service
        self._eventbus = eventbus
        self._order_tracker = order_tracker
        self._instrument_service = instrument_service

    def _symbol_label(self, symbol: str) -> str:
        """알림 메시지용 ``\\`{symbol}\\` (종목명)`` 병기 라벨(markdown).

        미주입/조회 불가 시 backtick symbol-only 로 폴백한다(format_label 폴백
        내장 — sync·무예외·무IO). reconciler payload 에 exchange 가 없어 KRX
        기본값으로 조회한다.
        """
        if self._instrument_service is not None:
            return self._instrument_service.format_label(symbol, markdown=True)
        return f"`{symbol}`"

    async def reconcile(
        self,
        bot_id: str,
        broker_positions: list[dict[str, Any]],
        *,
        account_id: str,
        skip_external_buy: bool = False,
        dry_run: bool = False,
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
                오분류하는 것을 막기 위한 barrier 안전장치다.
                다른 분류(외부 청산·일부 매도)는 영향받지 않는다.

                **self-submitted 분류와는 직교한다**: self-check 는
                `skip_external_buy` 와 무관하게 항상 수행되며, 이 플래그는 분류
                결과 중 "외부 매수" 보정만 억제하는 별도 계층이다. 주기
                reconcile(`skip_external_buy=False`)에서도 self 는 보정되지 않는다.
            dry_run: True 면 **detect-only** 모드 — 분류·로그·PositionMismatchEvent
                /NotificationEvent 발행은 그대로 수행하되 ``correct_position`` 을
                **호출하지 않는다**(보정 0건). 기존 external-buy/self-check 분류
                로직은 무변경이며, 발행되는 이벤트도 동일하다. 보정만 보류한다.
                (다중봇 귀속 ambiguity·user-initiated detect 경로용.)
                기본 False — 기존 호출자는 변경 없이 보정 동작 유지(무회귀).

        Returns:
            보정 내역 리스트. 불일치가 없거나 ``dry_run=True`` 면 빈 리스트.
        """
        from ante.account.scoping import require_account_id
        from ante.eventbus.events import (
            NotificationEvent,
            PositionMismatchEvent,
            ReconcileEvent,
        )

        account_id = require_account_id(account_id, context="reconciler.reconcile")

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

        all_symbols = set(internal_map.keys()) | set(broker_map.keys())

        for symbol in all_symbols:
            i_qty = internal_map.get(symbol, {}).get("quantity", 0.0)
            b_qty = broker_map.get(symbol, {}).get("quantity", 0.0)
            b_avg = broker_map.get(symbol, {}).get("avg_price", 0.0)

            if i_qty == b_qty:
                continue

            is_external_buy = False
            is_detect_only = False
            if b_qty < i_qty:
                if await self._is_self_submitted_fill(
                    bot_id=bot_id,
                    account_id=account_id,
                    symbol=symbol,
                    excess=i_qty - b_qty,
                    side="sell",
                ):
                    self._log_self_submitted(bot_id, symbol, i_qty, b_qty)
                    await self._publish_self_submitted(
                        account_id=account_id,
                        bot_id=bot_id,
                        symbol=symbol,
                        i_qty=i_qty,
                        b_qty=b_qty,
                    )
                    continue
                if b_qty == 0:
                    reason = REASON_EXTERNAL_LIQUIDATION
                else:
                    reason = REASON_EXTERNAL_PARTIAL_SELL
            elif b_qty > i_qty:
                if await self._is_self_submitted_fill(
                    bot_id=bot_id,
                    account_id=account_id,
                    symbol=symbol,
                    excess=b_qty - i_qty,
                    side="buy",
                ):
                    self._log_self_submitted(bot_id, symbol, i_qty, b_qty)
                    await self._publish_self_submitted(
                        account_id=account_id,
                        bot_id=bot_id,
                        symbol=symbol,
                        i_qty=i_qty,
                        b_qty=b_qty,
                    )
                    continue
                if i_qty == 0 and await self._is_unattributed_holding(
                    bot_id=bot_id,
                    account_id=account_id,
                    symbol=symbol,
                ):
                    reason = REASON_UNATTRIBUTED_HOLDING
                    is_detect_only = True
                else:
                    reason = REASON_EXTERNAL_BUY
                    is_external_buy = True
            else:
                reason = REASON_QTY_MISMATCH

            if is_external_buy and skip_external_buy:
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

            if is_detect_only:
                logger.warning(
                    "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s "
                    "(미귀속 보유 — 어느 봇도 추적하지 않은 보유, "
                    "force-write 보류·detect-only)",
                    bot_id,
                    symbol,
                    i_qty,
                    b_qty,
                    reason,
                )
            else:
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
                    account_id=account_id,
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
                        f"계좌: `{account_id}` · 봇: `{bot_id}` · "
                        f"종목: {self._symbol_label(symbol)}\n"
                        f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                        f"사유: {reason}"
                    ),
                    category="broker",
                )
            )

            if is_detect_only:
                continue

            if dry_run:
                logger.info(
                    "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s "
                    "(dry-run — 보정 보류)",
                    bot_id,
                    symbol,
                    i_qty,
                    b_qty,
                    reason,
                )
                continue

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
                    account_id=account_id,
                    bot_id=bot_id,
                    discrepancy_count=len(corrections),
                    corrections=corrections,
                )
            )

        return corrections

    async def compute_account_diff(
        self,
        broker_positions: list[dict[str, Any]],
        *,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """계좌 총합(broker) vs 전 봇 internal 합산 비교 — **순수(side-effect 無)**.

        broker 는 계좌 **총합**만 주므로 per-bot/per-symbol 귀속이 근본적으로
        ambiguous하다. 이 메서드는 이벤트/보정 없이 **읽기 전용으로**
        계좌 단위 심볼별 불일치만 계산한다(display/detect 공용).

        비교 기준:
            - broker: ``get_account_positions()`` 의 심볼별 총 수량.
            - internal: 해당 계좌의 **모든 봇(상태 무관) open 포지션을 심볼별로
              합산**(``TradeService.get_all_positions(account_id)``). per-bot
              비교가 같은 심볼을 보유한 다중봇을 false external-buy/청산으로
              오판하던 것을 제거한다.

        Returns:
            불일치 내역 리스트. 일치 시 빈 리스트.
            각 항목: {"symbol", "broker_qty", "internal_qty", "diff"}.
        """
        from ante.account.scoping import require_account_id

        account_id = require_account_id(
            account_id, context="reconciler.compute_account_diff"
        )

        internal = await self._trade_service.get_all_positions(account_id=account_id)
        internal_totals: dict[str, float] = {}
        for p in internal:
            if p.quantity > 0:
                internal_totals[p.symbol] = (
                    internal_totals.get(p.symbol, 0.0) + p.quantity
                )

        broker_totals: dict[str, float] = {}
        for bp in broker_positions:
            qty = float(bp.get("quantity", 0.0))
            if qty > 0:
                symbol = bp["symbol"]
                broker_totals[symbol] = broker_totals.get(symbol, 0.0) + qty

        mismatches: list[dict[str, Any]] = []
        all_symbols = set(internal_totals.keys()) | set(broker_totals.keys())
        for symbol in sorted(all_symbols):
            i_qty = internal_totals.get(symbol, 0.0)
            b_qty = broker_totals.get(symbol, 0.0)
            if i_qty == b_qty:
                continue
            mismatches.append(
                {
                    "symbol": symbol,
                    "broker_qty": b_qty,
                    "internal_qty": i_qty,
                    "diff": b_qty - i_qty,
                }
            )
        return mismatches

    async def detect_account_level(
        self,
        broker_positions: list[dict[str, Any]],
        *,
        account_id: str,
    ) -> list[dict[str, Any]]:
        """계좌 단위 불일치 **detect-only** — 탐지 + account-scoped 알림.

        다중봇(또는 0봇) 계좌에서 ``correct_position`` 을 **절대 호출하지 않고**,
        :meth:`compute_account_diff` 로 계산한 불일치를 account-scoped
        ``NotificationEvent`` 로 알린다. 신규 도메인 이벤트를
        신설하지 않고 ``NotificationEvent`` 만 사용한다 — bot-scoped 인
        ``PositionMismatchEvent``/``ReconcileEvent`` 는 다중봇 귀속이 ambiguous
        하므로 이 경로에서 발행하지 않는다.

        Args:
            broker_positions: 서버 BrokerAdapter 가 조회한 계좌 총합.
            account_id: 대상 계좌 ID (account-scoped 이벤트에 필수).

        Returns:
            불일치 내역 리스트(detect-only — 보정 없음). 일치 시 빈 리스트.
        """
        from ante.account.scoping import require_account_id
        from ante.eventbus.events import NotificationEvent

        account_id = require_account_id(
            account_id, context="reconciler.detect_account_level"
        )

        mismatches = await self.compute_account_diff(
            broker_positions, account_id=account_id
        )
        for m in mismatches:
            symbol = m["symbol"]
            i_qty = m["internal_qty"]
            b_qty = m["broker_qty"]
            logger.warning(
                "계좌 단위 포지션 불일치 [%s] %s: 내부합산=%.2f, 브로커=%.2f "
                "(detect-only — 다중봇 귀속 ambiguous, 보정 보류 #2270)",
                account_id,
                symbol,
                i_qty,
                b_qty,
            )
            await self._eventbus.publish(
                NotificationEvent(
                    level="critical",
                    title="계좌 단위 포지션 불일치",
                    message=(
                        f"계좌: `{account_id}` · 종목: {self._symbol_label(symbol)}\n"
                        f"내부 합산: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                        "사유: 계좌 단위 수량 불일치 (다중봇 귀속 ambiguous — "
                        "자동 보정 보류, 수동 확인 필요)"
                    ),
                    category="broker",
                )
            )

        if mismatches:
            logger.info(
                "계좌 단위 대사 완료 [%s]: 불일치 %d건 (detect-only)",
                account_id,
                len(mismatches),
            )
        return mismatches

    def _log_self_submitted(
        self, bot_id: str, symbol: str, i_qty: float, b_qty: float
    ) -> None:
        """self-submitted 미반영 체결 info 로그 (방향 중립 — buy / sell)."""
        logger.info(
            "포지션 불일치 [%s] %s: 내부=%.2f, 브로커=%.2f → %s "
            "(ante 미반영 체결 — 보정 skip, FillApplier 위임)",
            bot_id,
            symbol,
            i_qty,
            b_qty,
            REASON_SELF_SUBMITTED,
        )

    async def _publish_self_submitted(
        self,
        *,
        account_id: str,
        bot_id: str,
        symbol: str,
        i_qty: float,
        b_qty: float,
    ) -> None:
        """self-submitted 분기 공통 이벤트 발행 — `PositionMismatchEvent` +
        info `NotificationEvent`. buy-side·sell-side 동일 계층.

        reason 은 방향 중립 ``REASON_SELF_SUBMITTED`` 를 재사용한다. 방향은
        ``internal_qty``/``broker_qty`` 대소(buy=broker>internal, sell=
        internal>broker)로 판별된다.
        """
        from ante.eventbus.events import NotificationEvent, PositionMismatchEvent

        await self._eventbus.publish(
            PositionMismatchEvent(
                account_id=account_id,
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
                    f"계좌: `{account_id}` · 봇: `{bot_id}` · "
                    f"종목: {self._symbol_label(symbol)}\n"
                    f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                    f"사유: {REASON_SELF_SUBMITTED} "
                    "(체결 반영 대기 — 자동 보정 없음)"
                ),
                category="broker",
            )
        )

    async def _is_self_submitted_fill(
        self,
        *,
        bot_id: str,
        account_id: str,
        symbol: str,
        excess: float,
        side: str,
    ) -> bool:
        """broker-internal 불일치(``excess``)가 ante 미반영 체결로 설명되는지 판정.

        방향 대칭(buy / sell). OrderTracker 에서 ``(account_id, bot_id,
        symbol, side)`` 의 non-terminal(open/partially_filled) 주문을 조회하고, 그
        미체결 잔량 합(capacity = Σ(ordered_qty − recorded_filled_qty)) 과 ``excess``
        를 비교한다.

        - ``side="buy"``: ``excess = broker_qty - internal_qty`` — 외부 매수
          후보. 매칭되는 미반영 self 매수로 설명 가능한지 판정.
        - ``side="sell"``: ``excess = internal_qty - broker_qty``(deficit) —
          외부 청산/일부 매도 후보. 매칭되는 미반영 self 매도로 설명 가능한지 판정.
          KIS 모의 ccld 지연창(잔고는 매도 즉시 감소·ccld 당일 0건)에서 FillApplier 가
          아직 기록 못 한 self 매도가 정확히 non-terminal sell capacity 에 든다.

        - ``excess <= capacity`` → True (self_submitted_unrecorded_fill).
          ante 가 제출했으나 FillApplier 가 아직 기록 못 한 체결로 설명 가능.
        - ``excess > capacity`` 또는 매칭 주문 없음 → False (외부 거래로 분류).
        - OrderTracker 미주입 → False (하위 호환 — 기존 외부 분류 동작).

        **bounded known-limitation (R2-1, 방향 대칭)**: broker 포지션은 총량만
        주므로 capacity 안에 숨은 진짜 외부 거래(buy: 외부 매수 / sell: 외부 매도)는
        즉시 보정되지 않는다. 이는 auto-sell 캐스케이드 회피를 외부 검출
        완전성보다 우선하는 보수적 trade-off다. 매칭 ante 주문이 해소(완전 체결→open
        set 이탈, 또는 EOD expire_stale→terminal)되면 다음 reconcile 에서 잔여
        excess 가 external 로 검출된다. 상세:
        ``docs/specs/trade/03-07-position-reconciler.md``.
        """
        if self._order_tracker is None:
            return False

        try:
            open_orders = await self._order_tracker.get_open_orders_for(
                account_id=account_id,
                bot_id=bot_id,
                symbol=symbol,
                side=side,
            )
        except Exception:
            logger.exception(
                "self-check OrderTracker 조회 실패 [%s] %s side=%s — "
                "external 분류로 폴백",
                bot_id,
                symbol,
                side,
            )
            return False

        if not open_orders:
            return False

        capacity = sum(
            max(o.ordered_qty - o.recorded_filled_qty, 0.0) for o in open_orders
        )
        return excess <= capacity

    async def _is_unattributed_holding(
        self,
        *,
        bot_id: str,
        account_id: str,
        symbol: str,
    ) -> bool:
        """미귀속 보유(carryover) 시그니처인지 판정.

        ``b_qty > i_qty`` 분기에서 self-check(``_is_self_submitted_fill``)가
        미매칭(False)으로 떨어진 뒤, ``internal_qty == 0`` 인 보유가 그 봇이
        해당 종목에 대해 **추적 중인 non-terminal open buy 가 전무**(capacity == 0)
        인지 확인한다. 그렇다면 어느 봇도 거래(추적)한 적 없는 이월/외부 신규 매수
        보유이며, 단일봇 force-write 의 전제(봇 간 귀속 ambiguity 부재)가 성립하지
        않으므로 detect-only 로 둔다.

        - 매칭되는 non-terminal open buy 가 **하나도 없음** → True (미귀속 보유).
        - open buy 가 존재(capacity > 0) → False. 이 경우는 self-check 가 이미
          self_submitted(``excess <= capacity``) 또는 외부 매수(``excess >
          capacity``)로 처리하므로, 본 분기 대상이 아니다.
        - OrderTracker 미주입 → False (하위 호환 — 기존 "외부 매수" 동작).
        - OrderTracker 조회 실패 → False (보수적으로 기존 외부 매수 분류 유지).

        주의: ``_is_self_submitted_fill`` 은 "매칭 없음"과 "excess>capacity" 를
        **모두 False** 로 반환하므로 그것만으로는 둘을 구분할 수 없다. 여기서는
        capacity == 0(open buy 전무) 판정을 분리 구현해 미귀속 보유만 detect-only
        로 좁힌다. 상세: ``docs/specs/trade/03-07-position-reconciler.md``.
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
            logger.exception(
                "미귀속 판정 OrderTracker 조회 실패 [%s] %s — 외부 매수 분류 유지",
                bot_id,
                symbol,
            )
            return False

        return not open_orders
