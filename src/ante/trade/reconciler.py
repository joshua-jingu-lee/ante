"""포지션 정합성 검증 및 자동 보정."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ante.eventbus.bus import EventBus
    from ante.trade.service import TradeService

logger = logging.getLogger(__name__)


class PositionReconciler:
    """브로커 실제 포지션과 내부 포지션의 불일치를 감지하고 보정한다."""

    def __init__(
        self,
        trade_service: TradeService,
        eventbus: EventBus,
    ) -> None:
        self._trade_service = trade_service
        self._eventbus = eventbus

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

            # 불일치 감지
            is_external_buy = False
            if b_qty == 0 and i_qty > 0:
                reason = "외부 청산"
            elif b_qty < i_qty:
                reason = "외부 일부 매도"
            elif b_qty > i_qty:
                reason = "외부 매수"
                is_external_buy = True
            else:
                reason = "수량 불일치"

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
