"""포트폴리오 API — 자산 가치 + 추이."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ante.web.deps import get_bot_manager, get_trade_service, get_treasury
from ante.web.schemas import PortfolioHistoryResponse, PortfolioValueResponse

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/value", response_model=PortfolioValueResponse)
async def portfolio_value(
    treasury: Annotated[Any, Depends(get_treasury)],
) -> dict:
    """총 자산 가치 + 오늘 손익."""
    summary = treasury.get_summary()
    total_value = summary["total_evaluation"]
    daily_pnl = summary["total_profit_loss"]
    daily_pnl_pct = (daily_pnl / total_value * 100) if total_value else 0.0

    return {
        "total_value": total_value,
        "daily_pnl": daily_pnl,
        "daily_pnl_pct": round(daily_pnl_pct, 4),
        "updated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


# 기간 -> 일수 매핑
_PERIOD_DAYS = {
    "1d": 1,
    "1w": 7,
    "1m": 30,
    "3m": 90,
    "all": 0,
}


@router.get("/history", response_model=PortfolioHistoryResponse)
async def portfolio_history(
    trade_service: Annotated[Any, Depends(get_trade_service)],
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    period: str = Query(default="1m", pattern="^(1d|1w|1m|3m|all)$"),
) -> dict:
    """기간별 자산 추이."""
    # 모든 봇의 equity curve를 합산
    from ante.report.feedback import PerformanceFeedback

    feedback = PerformanceFeedback(trade_service, bot_manager)

    bots = bot_manager.list_bots() if hasattr(bot_manager, "list_bots") else []
    bot_ids = [b["bot_id"] if isinstance(b, dict) else b.bot_id for b in bots]

    # 봇이 없으면 빈 데이터
    if not bot_ids:
        return {"data": [], "period": period}

    # 전체 봇의 equity curve 합산
    merged: dict[str, float] = {}
    for bot_id in bot_ids:
        curve = await feedback.get_equity_curve(bot_id=bot_id)
        for point in curve:
            date = point["date"]
            merged[date] = merged.get(date, 0.0) + point["value"]

    # 기간 필터
    days = _PERIOD_DAYS.get(period, 30)
    if days > 0 and merged:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%d")
        merged = {d: v for d, v in merged.items() if d >= cutoff}

    data = [{"date": d, "value": round(v, 2)} for d, v in sorted(merged.items())]

    return {"data": data, "period": period}
