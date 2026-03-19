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
    bot_id: str | None = None,
    symbol: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """거래 기록 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    trades = await trade_service.get_trades(
        bot_id=bot_id,
        symbol=symbol,
        limit=limit + 1,
    )
    items = [
        {
            "trade_id": t.trade_id,
            "bot_id": t.bot_id,
            "symbol": t.symbol,
            "side": t.side,
            "quantity": t.quantity,
            "price": t.price,
            "status": t.status.value if hasattr(t.status, "value") else str(t.status),
            "created_at": str(t.created_at),
        }
        for t in trades
    ]

    result = paginate(items, cursor_field="trade_id", limit=limit, cursor=cursor)
    return {"trades": result["items"], "next_cursor": result["next_cursor"]}
