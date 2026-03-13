"""Cursor 기반 페이지네이션 유틸리티."""

from __future__ import annotations

import base64
from typing import Any


def encode_cursor(value: str) -> str:
    """값을 opaque cursor 문자열로 인코딩."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Opaque cursor를 원래 값으로 디코딩."""
    return base64.urlsafe_b64decode(cursor.encode()).decode()


def paginate(
    items: list[dict[str, Any]],
    *,
    cursor_field: str,
    limit: int,
    cursor: str | None = None,
) -> dict[str, Any]:
    """리스트에 cursor 기반 페이지네이션 적용.

    Args:
        items: 전체 항목 (cursor_field 기준 정렬 필요).
        cursor_field: cursor로 사용할 필드 이름.
        limit: 반환할 최대 항목 수.
        cursor: 이전 페이지의 next_cursor 값.

    Returns:
        {"items": [...], "next_cursor": "..." | None}
    """
    if cursor:
        decoded = decode_cursor(cursor)
        filtered = []
        found = False
        for item in items:
            if found:
                filtered.append(item)
            elif str(item[cursor_field]) == decoded:
                found = True
        items = filtered

    page = items[:limit]
    next_cursor = None
    if len(items) > limit:
        last = page[-1]
        next_cursor = encode_cursor(str(last[cursor_field]))

    return {"items": page, "next_cursor": next_cursor}
