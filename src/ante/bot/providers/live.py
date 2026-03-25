"""Live 봇용 Provider 구현체.

실제 시스템 모듈(Treasury, Trade, Broker)을 경유하여
계좌 잔고·포지션·미체결 주문을 조회한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.strategy.base import OrderView, PortfolioView, TradeHistoryView

if TYPE_CHECKING:
    from ante.broker.order_registry import OrderRegistry
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)


class LivePortfolioView(PortfolioView):
    """Live 봇용 PortfolioView. Treasury(잔고) + Trade(포지션) 경유."""

    def __init__(
        self,
        treasury: Treasury,
        position_history: PositionHistory,
    ) -> None:
        self._treasury = treasury
        self._position_history = position_history

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """현재 보유 포지션 조회 (인메모리 캐시)."""
        snapshots = self._position_history.get_positions_sync(bot_id)
        return {
            s.symbol: {
                "symbol": s.symbol,
                "quantity": s.quantity,
                "avg_entry_price": s.avg_entry_price,
                "realized_pnl": s.realized_pnl,
            }
            for s in snapshots
        }

    def get_balance(self, bot_id: str) -> dict[str, float]:
        """봇 할당 자금 현황 조회 (인메모리 캐시)."""
        budget = self._treasury.get_budget_sync(bot_id)
        if budget is None:
            return {"allocated": 0.0, "available": 0.0, "reserved": 0.0}
        return {
            "allocated": budget.allocated,
            "available": budget.available,
            "reserved": budget.reserved,
        }


class LiveOrderView(OrderView):
    """Live 봇용 OrderView. Broker OrderRegistry에서 미체결 주문 조회."""

    def __init__(self, order_registry: OrderRegistry) -> None:
        self._registry = order_registry

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """미체결 주문 목록 조회.

        OrderRegistry는 DB 기반이므로 동기 조회가 제한적이다.
        현재는 빈 목록을 반환하며, 실시간 주문 추적은 Phase 2에서 구현.
        """
        return []


class LiveTradeHistoryView(TradeHistoryView):
    """Live 봇용 TradeHistoryView. TradeRecorder에서 거래 이력 조회."""

    def __init__(self, trade_recorder: TradeRecorder) -> None:
        self._recorder = trade_recorder

    async def get_trade_history(
        self,
        bot_id: str,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """봇의 거래 이력 조회."""
        records = await self._recorder.get_trades(
            bot_id=bot_id, symbol=symbol, limit=limit
        )
        return [
            {
                "trade_id": r.trade_id,
                "symbol": r.symbol,
                "side": r.side,
                "quantity": r.quantity,
                "price": r.price,
                "status": r.status.value,
                "order_type": r.order_type,
                "reason": r.reason,
                "commission": r.commission,
                "timestamp": r.timestamp.isoformat()
                if r.timestamp is not None
                else None,
            }
            for r in records
        ]
