"""TradeService — Trade 모듈 통합 인터페이스 (파사드)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import uuid4

from ante.trade.models import (
    PerformanceMetrics,
    PositionSnapshot,
    TradeRecord,
    TradeStatus,
)

if TYPE_CHECKING:
    from ante.trade.performance import PerformanceTracker
    from ante.trade.position import PositionHistory
    from ante.trade.recorder import TradeRecorder


class TradeService:
    """Trade 모듈의 통합 인터페이스.

    CLI, IPC, 내부 모듈은 이 클래스를 통해 접근.
    """

    def __init__(
        self,
        recorder: TradeRecorder,
        position_history: PositionHistory,
        performance: PerformanceTracker,
    ) -> None:
        self._recorder = recorder
        self._position_history = position_history
        self._performance = performance

    # ── 거래 기록 조회 ────────────────────────────────

    async def get_trades(
        self,
        account_id: str | None = None,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        symbol: str | None = None,
        status: TradeStatus | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[TradeRecord]:
        """거래 기록 조회."""
        return await self._recorder.get_trades(
            account_id=account_id,
            bot_id=bot_id,
            strategy_id=strategy_id,
            symbol=symbol,
            status=status,
            from_date=from_date,
            to_date=to_date,
            limit=limit,
            offset=offset,
        )

    # ── 포지션 조회 ──────────────────────────────────

    async def get_positions(
        self,
        bot_id: str,
        include_closed: bool = False,
        *,
        account_id: str | None = None,
    ) -> list[PositionSnapshot]:
        """봇의 현재 포지션 조회."""
        return await self._position_history.get_positions(
            bot_id=bot_id,
            include_closed=include_closed,
            account_id=account_id,
        )

    async def get_all_positions(
        self, *, account_id: str | None = None
    ) -> list[PositionSnapshot]:
        """전체 봇의 모든 포지션 조회 (대사 계좌 합산 검증용)."""
        return await self._position_history.get_all_positions(account_id=account_id)

    async def get_position_history(
        self,
        bot_id: str,
        symbol: str | None = None,
        *,
        account_id: str | None = None,
    ) -> list[dict]:
        """포지션 변동 이력 조회."""
        return await self._position_history.get_history(
            bot_id=bot_id,
            symbol=symbol,
            account_id=account_id,
        )

    # ── 성과 지표 ────────────────────────────────────

    async def get_performance(
        self,
        account_id: str,
        bot_id: str | None = None,
        strategy_id: str | None = None,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
    ) -> PerformanceMetrics:
        """성과 지표 조회."""
        return await self._performance.calculate(
            account_id=account_id,
            bot_id=bot_id,
            strategy_id=strategy_id,
            from_date=from_date,
            to_date=to_date,
        )

    # ── 요약 ──────────────────────────────────────

    async def get_summary(self, bot_id: str, account_id: str) -> dict:
        """봇 요약 정보."""
        positions = await self.get_positions(bot_id, account_id=account_id)
        performance = await self.get_performance(account_id=account_id, bot_id=bot_id)
        recent_trades = await self.get_trades(
            account_id=account_id, bot_id=bot_id, limit=10
        )

        return {
            "positions": positions,
            "performance": performance,
            "recent_trades": recent_trades,
        }

    # ── 대사(Reconciliation) 보정 ────────────────────

    async def correct_position(
        self,
        bot_id: str,
        symbol: str,
        quantity: float,
        *,
        account_id: str,
        avg_price: float | None = None,
        reason: str = "",
    ) -> dict:
        """포지션을 브로커 기준으로 강제 보정. Reconciler가 호출.

        ``account_id`` 는 메서드 진입 시 ``require_account_id`` 로 검증한다.
        force_update는 즉시 DB commit하므로, invalid 값이 일시적으로라도
        positions 테이블에 들어가지 않도록 사전 차단해야 한다.
        """
        from ante.account.scoping import require_account_id

        account_id = require_account_id(account_id, context="correct_position")

        old = await self._position_history.get_current(
            bot_id=bot_id, symbol=symbol, account_id=account_id
        )
        old_qty = old.get("quantity", 0)
        old_avg = old.get("avg_entry_price", 0.0)

        await self._position_history.force_update(
            bot_id=bot_id,
            symbol=symbol,
            quantity=quantity,
            avg_entry_price=avg_price if avg_price else old_avg,
            account_id=account_id,
        )

        await self._recorder.save_adjustment(
            bot_id=bot_id,
            symbol=symbol,
            old_quantity=old_qty,
            new_quantity=quantity,
            reason=reason,
            account_id=account_id,
        )

        return {
            "symbol": symbol,
            "old_quantity": old_qty,
            "new_quantity": quantity,
            "old_avg_price": old_avg,
            "new_avg_price": avg_price if avg_price else old_avg,
            "reason": reason,
        }

    async def insert_adjustment(
        self,
        bot_id: str,
        strategy_id: str,
        fill: dict,
        *,
        account_id: str,
        reason: str = "reconciliation",
    ) -> None:
        """누락된 체결 기록을 보정 추가. Reconciler가 호출."""
        record = TradeRecord(
            trade_id=uuid4(),
            bot_id=bot_id,
            strategy_id=strategy_id,
            symbol=fill["symbol"],
            side=fill["side"],
            quantity=fill["quantity"],
            price=fill["price"],
            status=TradeStatus.ADJUSTED,
            order_type=fill.get("order_type", ""),
            reason=reason,
            commission=fill.get("commission", 0.0),
            timestamp=fill.get("timestamp"),
            order_id=fill.get("order_id"),
            account_id=account_id,
        )
        await self._recorder.save(record)
