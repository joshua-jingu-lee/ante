"""거래 기록 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ante.web.deps import get_trade_service
from ante.web.schemas import TradeListResponse

router = APIRouter()


@router.get(
    "",
    response_model=TradeListResponse,
    responses={503: {"description": "Trade service not available"}},
)
async def list_trades(
    trade_service: Annotated[Any, Depends(get_trade_service)],
    account_id: str | None = None,
    bot_id: str | None = None,
    symbol: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """거래 기록 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    trades = await trade_service.get_trades(
        account_id=account_id,
        bot_id=bot_id,
        symbol=symbol,
        limit=limit + 1,
    )
    items = [
        {
            "trade_id": str(t.trade_id),
            "bot_id": str(t.bot_id) if t.bot_id else "",
            "account_id": str(a)
            if isinstance(a := getattr(t, "account_id", ""), str)
            else "",
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "price": t.price,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "timestamp": str(t.timestamp) if t.timestamp else None,
        }
        for t in trades
    ]

    result = paginate(items, cursor_field="trade_id", limit=limit, cursor=cursor)
    return {"trades": result["items"], "next_cursor": result["next_cursor"]}
