"""PerformanceFeedback — Agent 피드백용 실전 성과 조회."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.bot.manager import BotManager
    from ante.trade.service import TradeService


class PerformanceFeedback:
    """Agent 피드백용 실전 성과 조회 서비스."""

    def __init__(
        self,
        trade_service: TradeService,
        bot_manager: BotManager,
    ) -> None:
        self._trade = trade_service
        self._bots = bot_manager

    async def get_bot_performance(self, bot_id: str) -> dict:
        """봇의 실전 성과 조회."""
        metrics = await self._trade.get_performance(bot_id=bot_id)
        positions = await self._trade.get_positions(bot_id)
        return {
            "bot_id": bot_id,
            "metrics": {
                "total_trades": metrics.total_trades,
                "win_rate": metrics.win_rate,
                "net_pnl": metrics.net_pnl,
                "profit_factor": metrics.profit_factor,
                "max_drawdown": metrics.max_drawdown,
                "sharpe_ratio": metrics.sharpe_ratio,
            },
            "current_positions": [
                {
                    "symbol": p.symbol,
                    "quantity": p.quantity,
                    "avg_price": p.avg_entry_price,
                    "realized_pnl": p.realized_pnl,
                }
                for p in positions
            ],
        }

    async def get_strategy_performance(self, strategy_id: str) -> dict:
        """전략의 모든 봇 성과 집계."""
        bots = self._bots.list_bots()
        strategy_bots = [b for b in bots if b.get("strategy_id") == strategy_id]

        performances = []
        for bot in strategy_bots:
            perf = await self.get_bot_performance(bot["bot_id"])
            performances.append(perf)

        return {
            "strategy_id": strategy_id,
            "bot_count": len(performances),
            "bots": performances,
        }

    async def get_trade_history(
        self,
        bot_id: str,
        limit: int = 100,
    ) -> list[dict]:
        """봇의 거래 이력 조회."""
        trades = await self._trade.get_trades(bot_id=bot_id, limit=limit)
        return [
            {
                "timestamp": (t.timestamp.isoformat() if t.timestamp else None),
                "symbol": t.symbol,
                "side": t.side,
                "quantity": t.quantity,
                "price": t.price,
                "status": t.status.value,
            }
            for t in trades
        ]
