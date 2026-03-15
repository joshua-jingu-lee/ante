"""세션 관리 — SQLite 기반 서버사이드 세션 저장소."""

from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

SESSION_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id    TEXT PRIMARY KEY,
    member_id     TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (datetime('now')),
    expires_at    TEXT NOT NULL,
    ip_address    TEXT DEFAULT '',
    user_agent    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_sessions_member_id ON sessions(member_id);
CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);
"""

SESSION_TOKEN_BYTES = 32
DEFAULT_SESSION_TTL_HOURS = 24


class SessionService:
    """서버사이드 세션 관리."""

    def __init__(
        self,
        db: Database,
        ttl_hours: int = DEFAULT_SESSION_TTL_HOURS,
    ) -> None:
        self._db = db
        self._ttl_hours = ttl_hours

    async def initialize(self) -> None:
        """세션 테이블 생성."""
        await self._db.execute_script(SESSION_SCHEMA)
        logger.info("SessionService 초기화 완료")

    async def create(
        self,
        member_id: str,
        ip_address: str = "",
        user_agent: str = "",
    ) -> str:
        """세션 생성. session_id 반환."""
        session_id = secrets.token_urlsafe(SESSION_TOKEN_BYTES)
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        expires_at = (datetime.now(UTC) + timedelta(hours=self._ttl_hours)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )

        await self._db.execute(
            """INSERT INTO sessions (session_id, member_id, created_at, expires_at,
               ip_address, user_agent)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (session_id, member_id, now, expires_at, ip_address, user_agent),
        )
        logger.info("세션 생성: member=%s", member_id)
        return session_id

    async def validate(self, session_id: str) -> dict | None:
        """세션 유효성 확인. 유효하면 세션 데이터 반환, 아니면 None."""
        row = await self._db.fetch_one(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if not row:
            return None

        expires = datetime.strptime(  # noqa: DTZ007
            row["expires_at"], "%Y-%m-%d %H:%M:%S"
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        if now > expires:
            await self.delete(session_id)
            return None

        return dict(row)

    async def delete(self, session_id: str) -> None:
        """세션 삭제."""
        await self._db.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )

    async def delete_by_member(self, member_id: str) -> None:
        """멤버의 모든 세션 삭제."""
        await self._db.execute(
            "DELETE FROM sessions WHERE member_id = ?",
            (member_id,),
        )

    async def cleanup_expired(self) -> int:
        """만료된 세션 일괄 삭제."""
        now = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")
        rows = await self._db.fetch_all(
            "SELECT session_id FROM sessions WHERE expires_at <= ?",
            (now,),
        )
        if rows:
            await self._db.execute(
                "DELETE FROM sessions WHERE expires_at <= ?",
                (now,),
            )
            logger.info("만료 세션 %d건 정리", len(rows))
        return len(rows)
