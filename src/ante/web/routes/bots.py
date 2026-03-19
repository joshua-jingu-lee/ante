"""봇 관리 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ante.web.deps import (
    get_bot_manager,
    get_strategy_registry,
    get_strategy_registry_optional,
    get_trade_service_optional,
    get_treasury_optional,
)
from ante.web.schemas import BotDetailResponse, BotListResponse

router = APIRouter()

_BOT_NOT_FOUND = "봇을 찾을 수 없습니다"


class BotCreateRequest(BaseModel):
    """봇 생성 요청."""

    bot_id: str
    strategy_id: str
    name: str = ""
    bot_type: str = "live"
    interval_seconds: int = Field(default=60, ge=10, le=3600)


@router.get("", response_model=BotListResponse)
async def list_bots(
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """봇 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    bots = bot_manager.list_bots()
    result = paginate(bots, cursor_field="bot_id", limit=limit, cursor=cursor)
    return {"bots": result["items"], "next_cursor": result["next_cursor"]}


@router.post("", status_code=201, response_model=BotDetailResponse)
async def create_bot(
    body: BotCreateRequest,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any, Depends(get_strategy_registry)],
) -> dict:
    """봇 생성."""
    from pathlib import Path

    from ante.bot.config import BotConfig
    from ante.bot.exceptions import BotError
    from ante.strategy.loader import StrategyLoader

    record = await registry.get(body.strategy_id)
    if not record:
        raise HTTPException(status_code=404, detail="전략을 찾을 수 없습니다")

    try:
        strategy_cls = StrategyLoader.load(Path(record.filepath))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"전략 로딩 실패: {e}") from e

    config = BotConfig(
        bot_id=body.bot_id,
        strategy_id=body.strategy_id,
        name=body.name or body.bot_id,
        bot_type=body.bot_type,
        interval_seconds=body.interval_seconds,
    )

    try:
        bot = await bot_manager.create_bot(
            config=config,
            strategy_cls=strategy_cls,
            source_path=Path(record.filepath),
        )
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {"bot": bot.get_info()}


@router.get("/{bot_id}", response_model=BotDetailResponse)
async def get_bot(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
    registry: Annotated[Any | None, Depends(get_strategy_registry_optional)],
    treasury: Annotated[Any | None, Depends(get_treasury_optional)],
    trade_service: Annotated[Any | None, Depends(get_trade_service_optional)],
) -> dict:
    """봇 상세 조회."""
    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    info = bot.get_info()

    # 전략 정보 추가
    if registry is not None:
        record = await registry.get(info.get("strategy_id", ""))
        if record:
            info["strategy"] = {
                "name": record.name,
                "version": record.version,
                "author": record.author,
                "description": record.description,
            }

    # 예산 정보 추가
    if treasury is not None:
        budget = treasury.get_budget(bot_id)
        if budget:
            info["budget"] = {
                "allocated": budget.allocated,
                "spent": budget.spent,
                "reserved": budget.reserved,
                "available": budget.available,
            }

    # 포지션 정보 추가
    if trade_service is not None:
        positions = await trade_service.get_positions(
            bot_id=bot_id, include_closed=True
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

    return {"bot": info}


@router.post("/{bot_id}/start", response_model=BotDetailResponse)
async def start_bot(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
) -> dict:
    """봇 시작."""
    from ante.bot.exceptions import BotError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    try:
        await bot_manager.start_bot(bot_id)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {"bot": bot.get_info()}


@router.post("/{bot_id}/stop", response_model=BotDetailResponse)
async def stop_bot(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
) -> dict:
    """봇 중지."""
    from ante.bot.exceptions import BotError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    try:
        await bot_manager.stop_bot(bot_id)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    return {"bot": bot.get_info()}


@router.delete("/{bot_id}", status_code=204)
async def delete_bot(
    bot_id: str,
    bot_manager: Annotated[Any, Depends(get_bot_manager)],
) -> None:
    """봇 삭제."""
    from ante.bot.exceptions import BotError

    bot = bot_manager.get_bot(bot_id)
    if bot is None:
        raise HTTPException(status_code=404, detail=_BOT_NOT_FOUND)

    try:
        await bot_manager.delete_bot(bot_id)
    except BotError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e
