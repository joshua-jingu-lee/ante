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
    ) -> list[dict[str, Any]]:
        """봇의 내부 포지션과 브로커 포지션을 대조하여 보정.

        Args:
            bot_id: 대상 봇 ID.
            broker_positions: 브로커 실제 보유.
                [{"symbol": str, "quantity": float, "avg_price": float}, ...]

        Returns:
            보정 내역 리스트. 불일치가 없으면 빈 리스트.
        """
        from ante.eventbus.events import (
            PositionMismatchEvent,
            ReconcileEvent,
        )

        internal = await self._trade_service.get_positions(bot_id)
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
            if b_qty == 0 and i_qty > 0:
                reason = "외부 청산"
            elif b_qty < i_qty:
                reason = "외부 일부 매도"
            elif b_qty > i_qty:
                reason = "외부 매수"
            else:
                reason = "수량 불일치"

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

            correction = await self._trade_service.correct_position(
                bot_id=bot_id,
                symbol=symbol,
                quantity=b_qty,
                avg_price=b_avg if b_avg > 0 else None,
                reason=reason,
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
