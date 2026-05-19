"""Cursor 기반 페이지네이션 유틸리티."""

from __future__ import annotations

import base64
from typing import Any


def encode_cursor(value: str) -> str:
    """값을 opaque cursor 문자열로 인코딩."""
    return base64.urlsafe_b64encode(value.encode()).decode()


def decode_cursor(cursor: str) -> str:
    """Opaque cursor를 원래 값으로 디코딩.

    비어있지 않은 canonical cursor만 유효하다: ``encode_cursor(decode(c)) == c``.
    빈/비canonical/undecodable cursor는 형태/메커니즘과 무관하게 고정 메시지
    ``ValueError("invalid cursor")``로 정규화된다 (raw base64/codec 내부 detail이나
    입력 cursor를 메시지에 포함하지 않음 — by-construction no-reflection).
    ``ante.web.errors.value_error_handler``가 400으로 매핑한다 (#1356 sibling —
    ``paginate``의 ``limit < 1`` 가드와 동형).

    빈 문자열 cursor(``""``)는 유효한 opaque continuation token이 아니므로
    ``decode_cursor``가 직접 호출될 경우 ``invalid cursor``로 거부한다
    (self-consistency). 단 ``paginate``는 ``if cursor:``로 빈 cursor를
    'cursor 없음=첫 페이지'로 이미 처리하므로 빈 값은 ``decode_cursor``에
    도달하지 않는다. ``paginate``의 ``if cursor:`` 가드 및 빈 ``cursor_field``
    값에 대한 ``next_cursor`` emit 정합은 본 함수 범위 밖이다 (별 follow-up).

    Raises:
        ValueError: cursor가 비어있거나, strict URL-safe base64로 디코드되지
            않거나, canonical 라운드트립(``encode_cursor(decode(c)) == c``)을
            만족하지 않을 때. 메시지는 항상 고정 상수 ``"invalid cursor"``.
            ``ante.web.errors.value_error_handler``가 400으로 매핑.
    """
    if not cursor:
        raise ValueError("invalid cursor")
    try:
        decoded = base64.b64decode(
            cursor.encode(), altchars=b"-_", validate=True
        ).decode()
    except ValueError as e:
        raise ValueError("invalid cursor") from e
    if encode_cursor(decoded) != cursor:
        raise ValueError("invalid cursor")
    return decoded


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

    Raises:
        ValueError: ``limit < 1``일 때. 라우트 단의 ``Query(ge=1)``이 1차
            방어선이지만 helper 자체도 invariant를 보장한다 (#1356).
            ``ante.web.errors.value_error_handler``가 400으로 매핑.
    """
    if limit < 1:
        raise ValueError("limit must be >= 1")

    if cursor:
        decoded = decode_cursor(cursor)
        start_idx = 0
        for i, item in enumerate(items):
            if str(item[cursor_field]) == decoded:
                start_idx = i + 1
                break
        items = items[start_idx:]

    page = items[:limit]
    next_cursor = None
    if len(items) > limit:
        last = page[-1]
        next_cursor = encode_cursor(str(last[cursor_field]))

    return {"items": page, "next_cursor": next_cursor}
