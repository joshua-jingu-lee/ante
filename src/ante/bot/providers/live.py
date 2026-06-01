"""Live 봇용 Provider 구현체.

실제 시스템 모듈(Treasury, Trade, Broker)을 경유하여
계좌 잔고·포지션·미체결 주문을 조회한다.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from ante.strategy.base import OrderView, PortfolioView, TradeHistoryView

if TYPE_CHECKING:
    from ante.trade.order_tracker import OrderTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder
    from ante.treasury.treasury import Treasury

logger = logging.getLogger(__name__)


class LivePortfolioView(PortfolioView):
    """Live 봇용 PortfolioView. Treasury(잔고) + Trade(포지션) 경유.

    ``account_id`` 는 봇별 컨텍스트 생성 시 ``StrategyContextFactory`` 가 closure
    로 binding 한다(``LiveOrderView`` #1948 패턴 미러). ``get_positions`` 는
    ``PositionHistory`` 인메모리 캐시를 ``(account_id, bot_id)`` 스코프로 조회해
    타 계좌 포지션이 전략 컨텍스트에 누출되지 않게 한다(#2139).
    """

    def __init__(
        self,
        treasury: Treasury,
        position_history: PositionHistory,
        account_id: str,
    ) -> None:
        self._treasury = treasury
        self._position_history = position_history
        self._account_id = account_id

    def get_positions(self, bot_id: str) -> dict[str, Any]:
        """현재 보유 포지션 조회 (인메모리 캐시, 봇 계좌 스코프)."""
        snapshots = self._position_history.get_positions_sync(
            bot_id, account_id=self._account_id
        )
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
    """Live 봇용 OrderView. OrderTracker(ante 제출 미체결 SSOT) 경유 (#1948).

    ``account_id`` 는 봇별 컨텍스트 생성 시 ``StrategyContextFactory`` 가 closure
    로 binding 한다(``LiveDataProvider`` 패턴 미러). ``get_open_orders`` 는
    OrderTracker 의 sync 인메모리 open 캐시(commit 된 DB 미러)를
    ``(account_id, bot_id)`` 스코프로 조회한다 — DB I/O 없이 이벤트 루프 위
    await 된 코루틴 내부에서 안전하게 sync 호출된다.

    **scope 경계**: OrderTracker 는 ante 가 제출한 주문만 추적한다. 수동/외부
    주문은 반영되지 않는다(전략 "미체결" 정의 = ante 제출 한정). cold-cache(warm
    완료 전) 시 빈 결과가 가능하다(best-effort, reconciler net) — known-limitation.
    """

    def __init__(self, order_tracker: OrderTracker, account_id: str) -> None:
        self._order_tracker = order_tracker
        self._account_id = account_id

    def get_open_orders(self, bot_id: str) -> list[dict[str, Any]]:
        """ante 제출 미체결 주문 목록 조회 (통일 OpenOrder dict 스키마)."""
        records = self._order_tracker.get_open_orders_for_bot_sync(
            self._account_id, bot_id
        )
        return [r.to_open_order_dict() for r in records]


class LiveTradeHistoryView(TradeHistoryView):
    """Live 봇용 TradeHistoryView. TradeRecorder에서 거래 이력 조회.

    ``account_id`` 는 봇별 컨텍스트 생성 시 ``StrategyContextFactory`` 가 closure
    로 binding 한다(``LiveOrderView`` #1948 패턴 미러). ``get_trade_history`` 는
    ``get_trades`` 호출을 ``(account_id, bot_id)`` 스코프로 좁혀 타 계좌 거래
    이력이 전략 컨텍스트에 누출되지 않게 한다(#2139).
    """

    def __init__(self, trade_recorder: TradeRecorder, account_id: str) -> None:
        self._recorder = trade_recorder
        self._account_id = account_id

    async def get_trade_history(
        self,
        bot_id: str,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """봇의 거래 이력 조회 (봇 계좌 스코프)."""
        records = await self._recorder.get_trades(
            account_id=self._account_id,
            bot_id=bot_id,
            symbol=symbol,
            limit=limit,
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
