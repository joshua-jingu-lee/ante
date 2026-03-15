"""감사 로그 서비스."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from ante.core.database import Database

logger = logging.getLogger(__name__)

AUDIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    member_id   TEXT NOT NULL,
    action      TEXT NOT NULL,
    resource    TEXT NOT NULL DEFAULT '',
    detail      TEXT DEFAULT '',
    ip          TEXT DEFAULT '',
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_member ON audit_log(member_id);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action);
CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at);
"""


class AuditLogger:
    """멤버 액션 감사 로그 기록 및 조회."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """audit_log 테이블 생성."""
        await self._db.execute_script(AUDIT_SCHEMA)
        logger.info("AuditLogger 초기화 완료")

    async def log(
        self,
        *,
        member_id: str,
        action: str,
        resource: str = "",
        detail: str = "",
        ip: str = "",
    ) -> None:
        """감사 로그 기록."""
        now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S")
        await self._db.execute(
            """INSERT INTO audit_log
               (member_id, action, resource, detail, ip, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (member_id, action, resource, detail, ip, now),
        )
        logger.debug("감사 로그: %s %s %s", member_id, action, resource)

    async def query(
        self,
        *,
        member_id: str | None = None,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """감사 로그 조회. 최신순."""
        conditions: list[str] = []
        params: list[str | int] = []

        if member_id:
            conditions.append("member_id = ?")
            params.append(member_id)
        if action:
            conditions.append("action LIKE ?")
            params.append(f"{action}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"""SELECT id, member_id, action, resource, detail, ip, created_at
                  FROM audit_log {where}
                  ORDER BY id DESC LIMIT ? OFFSET ?"""
        params.extend([limit, offset])
        return await self._db.fetch_all(sql, tuple(params))

    async def count(
        self,
        *,
        member_id: str | None = None,
        action: str | None = None,
    ) -> int:
        """감사 로그 건수 조회."""
        conditions: list[str] = []
        params: list[str] = []

        if member_id:
            conditions.append("member_id = ?")
            params.append(member_id)
        if action:
            conditions.append("action LIKE ?")
            params.append(f"{action}%")

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT COUNT(*) as cnt FROM audit_log {where}"
        row = await self._db.fetch_one(sql, tuple(params))
        return row["cnt"] if row else 0
