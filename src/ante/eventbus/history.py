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
        until: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """이벤트 로그 조회.

        Args:
            event_type: 이벤트 타입 이름(정확 일치).
            since: ``timestamp >= since`` (inclusive lower bound).
            until: ``timestamp <= until`` (inclusive upper bound).
            limit: SQL ``LIMIT`` — 반환 최대 건수.
            offset: SQL ``OFFSET`` — pagination skip 수.

        Note (#1437):
            ``until``과 ``offset`` 파라미터는 web bot logs endpoint의 정확한
            페이지네이션을 위해 추가되었다. payload 내부 필드(``bot_id`` 등)에
            대한 SQL filter는 지원하지 않으며, 그 종류의 필터는 호출자가
            in-memory에서 처리한다.
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
        until: datetime | None = None,
    ) -> int:
        """이벤트 로그 매칭 건수 (페이지네이션 전 total).

        ``query``와 동일한 SQL filter(``event_type``/``since``/``until``)
        만 지원한다. payload 내부 필드 매칭(예: ``bot_id``) total은 호출자가
        in-memory에서 계산한다 (#1437).

        Returns:
            매칭 row 수. 필터가 모두 ``None``이면 전체 ``event_log`` row 수.
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
