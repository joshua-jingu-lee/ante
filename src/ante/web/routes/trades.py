"""거래 기록 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from ante.web.deps import get_trade_service, require_trade_read
from ante.web.schemas import TradeListResponse
from ante.web.utils.account_params import reject_invalid_account_id

router = APIRouter()


@router.get(
    "",
    response_model=TradeListResponse,
    responses={
        422: {
            "description": (
                "Invalid ``account_id`` query. 제공된 runtime-invalid 값"
                ' (``""``/``"default"``/``^[a-zA-Z0-9\\-]{3,30}$`` 불일치)은'
                " service 위임 이전에 422로 거부된다 — downstream"
                " ``InvalidAccountIdError``가 generic 500으로 escape하던 경로를"
                " 차단한다. ``account_id`` 미지정은 전체 필터로 통과한다"
                " (#1218 보존, #1624)."
            ),
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
        503: {
            "description": "Trade service not available",
            "content": {
                "application/problem+json": {
                    "schema": {"$ref": "#/components/schemas/ErrorResponse"},
                },
            },
        },
    },
)
async def list_trades(
    _caller_id: Annotated[str, Depends(require_trade_read)],
    trade_service: Annotated[Any, Depends(get_trade_service)],
    account_id: str | None = None,
    bot_id: str | None = None,
    symbol: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = None,
) -> dict:
    """거래 기록 목록 조회 (cursor 기반 페이지네이션). 인증된 master/human 또는
    ``trade:read`` scope 를 보유한 agent 만 호출 가능 (#1407).

    제공된 runtime-invalid ``account_id`` (``""``/``"default"``/패턴 위반)는
    service 위임 **이전**에 422로 거부한다 (#1624). 가드가 없으면
    ``TradeService.get_trades`` downstream의 ``require_account_id``가
    ``InvalidAccountIdError``를 raise하고, Web generic exception handler가
    이를 500 `An unexpected error occurred.`로 흘려 invalid-input ↔
    server-failure 구분이 깨진다. ``account_id`` 미지정(``None``)은
    전체 필터로 통과한다 (#1218 보존)."""
    from ante.web.pagination import paginate

    reject_invalid_account_id(account_id)

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
            "account_id": t.account_id,
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
