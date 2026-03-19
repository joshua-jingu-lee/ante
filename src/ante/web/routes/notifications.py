"""알림 이력 API."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from ante.web.deps import get_notification_service
from ante.web.schemas import NotificationListResponse

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    notification_service: Annotated[Any, Depends(get_notification_service)],
    level: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> dict:
    """알림 이력 조회 (cursor 기반 페이지네이션)."""
    from ante.web.pagination import paginate

    rows = await notification_service.get_history(level=level, limit=limit + 1)
    items = [
        {
            "id": str(r["id"]),
            "level": r["level"],
            "title": r["title"],
            "message": r["message"],
            "success": bool(r["success"]),
            "created_at": r["created_at"],
        }
        for r in rows
    ]

    result = paginate(items, cursor_field="id", limit=limit, cursor=cursor)
    return {
        "notifications": result["items"],
        "next_cursor": result["next_cursor"],
    }
