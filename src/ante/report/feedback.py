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
        bot = self._bots.get_bot(bot_id)
        account_id = bot.config.account_id if bot else "default"
        metrics = await self._trade.get_performance(
            account_id=account_id, bot_id=bot_id
        )
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

    async def get_equity_curve(
        self,
        bot_id: str,
        initial_balance: float = 0.0,
    ) -> list[dict]:
        """봇의 자산 곡선 데이터 생성.

        체결 거래의 누적 PnL로 일별 자산 곡선을 산출한다.

        Args:
            bot_id: 봇 ID.
            initial_balance: 초기 자산 (미지정 시 0, 상대 수익으로 표현).

        Returns:
            ``[{"date": "2025-01-01", "value": 10000000}, ...]`` 형식.
        """
        from ante.trade.recorder import TradeStatus

        trades = await self._trade.get_trades(
            bot_id=bot_id, status=TradeStatus.FILLED, limit=10000
        )
        if not trades:
            return []

        # 일별 PnL 집계
        daily_pnl: dict[str, float] = {}
        for t in trades:
            if not t.timestamp:
                continue
            date_str = t.timestamp.strftime("%Y-%m-%d")
            pnl = t.quantity * t.price * (1 if t.side == "sell" else -1)
            pnl -= t.commission
            daily_pnl[date_str] = daily_pnl.get(date_str, 0.0) + pnl

        # 누적 자산 곡선
        curve = []
        equity = initial_balance
        for date_str in sorted(daily_pnl.keys()):
            equity += daily_pnl[date_str]
            curve.append({"date": date_str, "value": round(equity, 2)})

        return curve
