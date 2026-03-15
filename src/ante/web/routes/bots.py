"""봇 관리 API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter()


class BotCreateRequest(BaseModel):
    """봇 생성 요청."""

    strategy_id: str
    bot_type: str = "live"
    interval_seconds: int = Field(default=60, ge=10, le=3600)


class BotUpdateRequest(BaseModel):
    """봇 설정 수정 요청."""

    interval_seconds: int | None = Field(default=None, ge=10, le=3600)


@router.get("")
async def list_bots(
    request: Request,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """봇 목록 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    bot_manager = getattr(request.app.state, "bot_manager", None)
    if bot_manager is None:
        raise HTTPException(status_code=503, detail="Bot manager not available")

    bots = bot_manager.list_bots()
    result = paginate(bots, cursor_field="bot_id", limit=limit, cursor=cursor)
    return {"bots": result["items"], "next_cursor": result["next_cursor"]}
