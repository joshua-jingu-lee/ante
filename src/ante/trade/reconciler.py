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
# 미귀속 보유 (#2352): broker > internal 이고 internal_qty == 0 이며 그 봇이 해당
# 종목에 대해 추적 중인 non-terminal open buy 가 전무(capacity == 0)인 보유.
# 어느 봇도 거래(추적)하지 않은 이월(carryover)·외부 신규 매수를 포함하는 보수적
# 분류명이며, 단일봇이라는 이유만으로 그 봇 소유로 단정하지 않는다. force-write
# (correct_position) 하지 않고 영구 detect-only(이벤트/알림만)로 둔다 — 전략이
# 미보유 종목을 자기 포지션으로 인식해 실거래 오매도하는 것을 막는다(#2317 canary).
REASON_UNATTRIBUTED_HOLDING = "미귀속 보유"


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
                오분류하는 것을 막기 위한 barrier 안전장치다(#1946 Finding 1).
                다른 분류(외부 청산·일부 매도)는 영향받지 않는다.

                **self-submitted 분류와는 직교한다(#1950 R1-1)**: self-check 는
                `skip_external_buy` 와 무관하게 항상 수행되며, 이 플래그는 분류
                결과 중 "외부 매수" 보정만 억제하는 별도 계층이다. 주기
                reconcile(`skip_external_buy=False`)에서도 self 는 보정되지 않는다.
            dry_run: True 면 **detect-only** 모드 — 분류·로그·PositionMismatchEvent
                /NotificationEvent 발행은 그대로 수행하되 ``correct_position`` 을
                **호출하지 않는다**(보정 0건). 기존 external-buy/self-check 분류
                로직은 무변경이며, 발행되는 이벤트도 동일하다. 보정만 보류한다.
                (#2119/#2122: 다중봇 귀속 ambiguity·user-initiated detect 경로용.)
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

        # #2058: PositionMismatchEvent/ReconcileEvent 는 account-scoped 이벤트로
        # 승격되어 valid account_id 를 요구한다. marker(_requires_account_id) 는
        # "존재"가 아니라 "valid"를 요구하므로, source 인 reconcile() 진입부에서
        # invalid("" / None / "default" / 형식 위반) 를 fail-fast 로 차단한다.
        # 여기서 raise되면 이후 모든 emit/notification/correct_position 경로가
        # 실행되지 않는다.
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
            # #2352: detect-only(보정 skip)로 분류되었으나 critical 관측은 유지하는
            # 미귀속 보유. is_external_buy 와 직교 — correct_position 만 건너뛴다.
            is_detect_only = False
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
                                f"종목: `{symbol}`\n"
                                f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                                f"사유: {REASON_SELF_SUBMITTED} "
                                "(체결 반영 대기 — 자동 보정 없음)"
                            ),
                            category="broker",
                        )
                    )
                    continue
                # #2352: self-check 미매칭 이후 — 미귀속 보유(carryover) 판정.
                # internal_qty == 0 이고 그 봇이 해당 종목에 대해 추적 중인
                # non-terminal open buy 가 전무(capacity == 0)이면, 어느 봇도
                # 거래한 적 없는 보유다. 단일봇이라는 이유만으로 그 봇 소유로
                # force-write 하면 전략이 미보유 종목을 자기 포지션으로 인식해
                # 실거래 오매도한다(#2317 canary). detect-only 로 보정만 skip 하고
                # 이벤트/알림은 critical 로 유지한다.
                #
                # #1950 경계 보존: capacity > 0(추적 open buy 존재) 케이스는 위
                # self-check 가 이미 self_submitted(excess<=capacity, continue) 또는
                # 외부 매수(excess>capacity, 아래 fall-through)로 처리한다 — 본
                # 분기는 capacity == 0 && internal_qty == 0 부분집합만 다룬다.
                # order_tracker 미주입(capacity 판정 불가)이면 적용하지 않는다
                # (하위 호환 — 기존 외부 매수 동작).
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

            if is_detect_only:
                # #2352: 미귀속 보유 — 보정(correct_position)은 skip 하나 critical
                # 관측(이벤트/알림)은 유지한다. 어느 봇에도 귀속할 수 없는 보유를
                # 단일봇이라는 이유만으로 force-write 하지 않는다.
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
                        f"종목: `{symbol}`\n"
                        f"내부: {i_qty:.0f}주 · 브로커: {b_qty:.0f}주\n"
                        f"사유: {reason}"
                    ),
                    category="broker",
                )
            )

            if is_detect_only:
                # #2352: 미귀속 보유는 영구 detect-only — correct_position 미호출.
                # dry_run 과 달리 보정 정책 자체가 "귀속 불가 보유는 보정하지
                # 않는다"이므로 dry_run=False(보정 모드)에서도 skip 한다.
                continue

            if dry_run:
                # detect-only: 분류·이벤트는 위에서 발행했으나 실제 보정
                # (correct_position)은 호출하지 않는다(#2119/#2122). 다중봇
                # 귀속이 ambiguous하거나 user-initiated 탐지 요청인 경로에서
                # 잘못된 보정으로 실거래 포지션을 손상시키지 않기 위함이다.
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
        ambiguous하다(#2270). 이 메서드는 이벤트/보정 없이 **읽기 전용으로**
        계좌 단위 심볼별 불일치만 계산한다(display/detect 공용).

        비교 기준:
            - broker: ``get_account_positions()`` 의 심볼별 총 수량.
            - internal: 해당 계좌의 **모든 봇(상태 무관) open 포지션을 심볼별로
              합산**(``TradeService.get_all_positions(account_id)``). per-bot
              비교가 같은 심볼을 보유한 다중봇을 false external-buy/청산으로
              오판하던 것을 제거한다(#2120).

        Returns:
            불일치 내역 리스트. 일치 시 빈 리스트.
            각 항목: {"symbol", "broker_qty", "internal_qty", "diff"}.
        """
        from ante.account.scoping import require_account_id

        account_id = require_account_id(
            account_id, context="reconciler.compute_account_diff"
        )

        # 전 봇(상태 무관) open 포지션을 심볼별 합산 — #2120 다중봇 합산.
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
        ``NotificationEvent`` 로 알린다(#2118/#2120). 신규 도메인 이벤트를
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
                        f"계좌: `{account_id}` · 종목: `{symbol}`\n"
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

    async def _is_unattributed_holding(
        self,
        *,
        bot_id: str,
        account_id: str,
        symbol: str,
    ) -> bool:
        """미귀속 보유(carryover) 시그니처인지 판정 (#2352).

        ``b_qty > i_qty`` 분기에서 self-check(``_is_self_submitted_fill``)가
        미매칭(False)으로 떨어진 뒤, ``internal_qty == 0`` 인 보유가 그 봇이
        해당 종목에 대해 **추적 중인 non-terminal open buy 가 전무**(capacity == 0)
        인지 확인한다. 그렇다면 어느 봇도 거래(추적)한 적 없는 이월/외부 신규 매수
        보유이며, 단일봇 force-write 의 전제(봇 간 귀속 ambiguity 부재)가 성립하지
        않으므로 detect-only 로 둔다.

        - 매칭되는 non-terminal open buy 가 **하나도 없음** → True (미귀속 보유).
        - open buy 가 존재(capacity > 0) → False. 이 경우는 self-check 가 이미
          self_submitted(``excess <= capacity``) 또는 외부 매수(``excess >
          capacity``)로 처리하므로(#1950 무변경), 본 분기 대상이 아니다.
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
            # 조회 실패 시 미귀속 판정을 포기하고 기존 외부 매수 분류를 유지한다
            # (보수적 — 신규 detect-only 분기가 reconcile 을 깨뜨리지 않도록 방어).
            logger.exception(
                "미귀속 판정 OrderTracker 조회 실패 [%s] %s — 외부 매수 분류 유지",
                bot_id,
                symbol,
            )
            return False

        # 추적 중인 non-terminal open buy 가 하나도 없음 = capacity 0 = 미귀속 보유.
        return not open_orders
