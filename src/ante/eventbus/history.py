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
    ) -> list[dict[str, Any]]:
        """이벤트 로그 조회."""
        sql = "SELECT * FROM event_log WHERE 1=1"
        params: list[str] = []

        if event_type:
            sql += " AND event_type = ?"
            params.append(event_type)
        if since:
            sql += " AND timestamp >= ?"
            params.append(since.isoformat())

        sql += " ORDER BY id DESC LIMIT ?"
        params.append(str(limit))

        rows = await self._db.fetch_all(sql, tuple(params))
        result = []
        for row in rows:
            entry = dict(row)
            entry["payload"] = json.loads(entry["payload"])
            result.append(entry)
        return result

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
