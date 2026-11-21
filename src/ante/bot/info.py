"""Bot info enrichment helper — IPC 공유."""

from __future__ import annotations

from typing import Any


async def enrich_bot_info(
    bot: Any,
    *,
    strategy_registry: Any | None = None,
    treasury: Any | None = None,
    trade_service: Any | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """``bot.get_info()`` 결과에 strategy/budget/positions 정보를 보강한다.

    응답 shape/field/key 순서를 변경하지 않으며, 의존성 None 시 해당 섹션
    키 자체가 부재한다.
    """
    info: dict[str, Any] = bot.get_info()

    if strategy_registry is not None:
        record = await strategy_registry.get(info.get("strategy_id", ""))
        if record:
            info["strategy_name"] = record.name
            info["strategy_author_name"] = record.author_name
            info["strategy_author_id"] = record.author_id
            info["strategy"] = {
                "name": record.name,
                "version": record.version,
                "author_name": record.author_name,
                "author_id": record.author_id,
                "description": record.description,
            }

    if treasury is not None:
        budget = treasury.get_budget(bot.bot_id)
        if budget:
            info["budget"] = {
                "allocated": budget.allocated,
                "spent": budget.spent,
                "reserved": budget.reserved,
                "available": budget.available,
            }

    if trade_service is not None:
        if account_id is not None:
            positions = await trade_service.get_positions(
                bot_id=bot.bot_id, include_closed=True, account_id=account_id
            )
        else:
            positions = await trade_service.get_positions(
                bot_id=bot.bot_id, include_closed=True
            )
        info["positions"] = [
            {
                "symbol": p.symbol,
                "quantity": p.quantity,
                "avg_entry_price": p.avg_entry_price,
                "realized_pnl": p.realized_pnl,
            }
            for p in positions
        ]

    return info
