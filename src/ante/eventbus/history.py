"""EventBus 이벤트 히스토리 — SQLite 영속화."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from ante.eventbus.events import Event

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

EVENT_LOG_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    TEXT NOT NULL,
    event_type  TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    payload     TEXT NOT NULL,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_event_log_type
    ON event_log(event_type);
CREATE INDEX IF NOT EXISTS idx_event_log_timestamp
    ON event_log(timestamp);
"""


def _event_to_dict(event: Event) -> dict[str, Any]:
    """이벤트를 직렬화 가능한 dict로 변환."""
    from dataclasses import fields

    result: dict[str, Any] = {}
    for f in fields(event):
        val = getattr(event, f.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        elif hasattr(val, "hex"):
            val = str(val)
        result[f.name] = val
    return result


class EventHistoryStore:
    """이벤트를 SQLite에 영속화하는 저장소.

    EventBus에 미들웨어로 연결하여 모든 발행 이벤트를 기록한다.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(EVENT_LOG_SCHEMA)

    async def record(self, event: Event) -> None:
        """이벤트를 event_log 테이블에 기록."""
        payload = _event_to_dict(event)
        await self._db.execute(
            """INSERT INTO event_log
               (event_id, event_type, timestamp, payload)
               VALUES (?, ?, ?, ?)""",
            (
                str(event.event_id),
                type(event).__name__,
                event.timestamp.isoformat(),
                json.dumps(payload, default=str),
            ),
        )

    async def query(
        self,
        event_type: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
        *,
        until: datetime | None = None,
        offset: int = 0,
        payload_filter: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        """이벤트 로그 조회.

        Args:
            event_type: 이벤트 타입 이름(정확 일치).
            since: ``timestamp >= since`` (inclusive lower bound).
            limit: SQL ``LIMIT`` — 반환 최대 건수.
            until: ``timestamp <= until`` (inclusive upper bound).
                Keyword-only (#1437 r2).
            offset: SQL ``OFFSET`` — pagination skip 수.
                Keyword-only (#1437 r2).
            payload_filter: payload JSON 내부 필드 일치 필터.
                ``{"bot_id": "X"}`` →
                ``WHERE json_extract(payload, '$.bot_id') = 'X'`` (#1437 r2).
                Keyword-only. SQLite 3.38+ JSON1 (현재 stack 3.53.0).

        Note (#1437 r2):
            r1은 ``until``과 ``offset``을 위치 인자 (``until`` 이 ``limit``
            앞)로 추가해 기존 caller가 ``query(event_type, since, 50)`` 처럼
            세 번째 위치 인자로 ``limit``을 넣던 호출 패턴이 ``50``을
            ``until``로 잘못 바인딩할 위험이 있었다. r2는 ``until``/``offset``
            을 keyword-only로 옮기고, ``limit``을 세 번째 위치 인자로 유지해
            기존 호출 패턴과 안전하게 호환된다. 또한 ``payload_filter``를
            추가해 web bot logs endpoint가 ``bot_id``를 SQL 단계에서
            필터링할 수 있게 한다 (in-memory fetch hard cap 제거).
        """
        sql = "SELECT * FROM event_log WHERE 1=1"
        params: list[str] = []

        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since:
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until:
            sql += " AND timestamp <= ?"
            params.append(until.isoformat())
        if payload_filter:
            for key, value in payload_filter.items():
                # SQLite JSON1 ``json_extract``를 사용한 payload JSON path 필터.
                # ``$.{key}``로 top-level 필드만 지원 (현재 use case로 충분).
                sql += " AND json_extract(payload, ?) = ?"
                params.append(f"$.{key}")
                params.append(value)

        sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
        params.append(str(limit))
        params.append(str(offset))

        rows = await self._db.fetch_all(sql, tuple(params))
        result = []
        for row in rows:
            entry = dict(row)
            entry["payload"] = json.loads(entry["payload"])
            result.append(entry)
        return result

    async def count(
        self,
        event_type: str | None = None,
        since: datetime | None = None,
        *,
        until: datetime | None = None,
        payload_filter: dict[str, str] | None = None,
    ) -> int:
        """이벤트 로그 매칭 건수 (페이지네이션 전 total).

        ``query``와 동일한 SQL filter(``event_type``/``since``/``until``/
        ``payload_filter``)를 지원한다.

        Args:
            event_type: 이벤트 타입 이름(정확 일치).
            since: ``timestamp >= since`` (inclusive lower bound).
            until: keyword-only. ``timestamp <= until`` inclusive upper bound.
            payload_filter: keyword-only. payload JSON path 필터
                (``json_extract(payload, '$.{key}') = value``) (#1437 r2).

        Returns:
            매칭 row 수. 필터가 모두 ``None``이면 전체 ``event_log`` row 수.

        Note (#1437 r2):
            ``until``과 ``payload_filter``를 keyword-only로 두어 위치 인자
            오바인딩을 차단한다.
        """
        sql = "SELECT COUNT(*) AS cnt FROM event_log WHERE 1=1"
        params: list[str] = []

        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since:
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())
        if until:
            sql += " AND timestamp <= ?"
            params.append(until.isoformat())
        if payload_filter:
            for key, value in payload_filter.items():
                sql += " AND json_extract(payload, ?) = ?"
                params.append(f"$.{key}")
                params.append(value)

        row = await self._db.fetch_one(sql, tuple(params))
        return int(row["cnt"]) if row else 0

    async def cleanup(self, retention_days: int = 30) -> int:
        """보존 기간 초과 이벤트 삭제."""
        result = await self._db.fetch_one(
            """SELECT COUNT(*) as cnt FROM event_log
               WHERE timestamp < datetime('now', ?)""",
            (f"-{retention_days} days",),
        )
        count = result["cnt"] if result else 0

        if count > 0:
            await self._db.execute(
                """DELETE FROM event_log
                   WHERE timestamp < datetime('now', ?)""",
                (f"-{retention_days} days",),
            )
            logger.info("이벤트 로그 정리: %d건 삭제", count)
        return count
