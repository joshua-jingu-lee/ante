"""SignalKeyManager — 봇별 시그널 키 발급/관리."""

from __future__ import annotations

import logging
import secrets
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

SIGNAL_KEY_SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_keys (
    key_id       TEXT PRIMARY KEY,
    bot_id       TEXT NOT NULL UNIQUE,
    created_at   TEXT DEFAULT (datetime('now'))
);
"""

# 키 형식: sk_ + 32자 hex (128-bit entropy)
_KEY_PREFIX = "sk_"
_KEY_BYTES = 16


class SignalKeyManager:
    """봇별 시그널 키 발급/조회/재발급/폐기."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """signal_keys 테이블 생성."""
        await self._db.execute_script(SIGNAL_KEY_SCHEMA)

    async def generate(self, bot_id: str) -> str:
        """시그널 키 발급. 이미 존재하면 기존 키 반환."""
        existing = await self.get_key(bot_id)
        if existing:
            return existing

        key = _KEY_PREFIX + secrets.token_hex(_KEY_BYTES)
        await self._db.execute(
            "INSERT INTO signal_keys (key_id, bot_id) VALUES (?, ?)",
            (key, bot_id),
        )
        logger.info("시그널 키 발급: bot=%s", bot_id)
        return key

    async def get_key(self, bot_id: str) -> str | None:
        """봇의 시그널 키 조회."""
        row = await self._db.fetch_one(
            "SELECT key_id FROM signal_keys WHERE bot_id = ?",
            (bot_id,),
        )
        return row["key_id"] if row else None

    async def rotate(self, bot_id: str) -> str:
        """기존 키 폐기 + 새 키 발급."""
        await self.revoke(bot_id)
        new_key = _KEY_PREFIX + secrets.token_hex(_KEY_BYTES)
        await self._db.execute(
            "INSERT INTO signal_keys (key_id, bot_id) VALUES (?, ?)",
            (new_key, bot_id),
        )
        logger.info("시그널 키 재발급: bot=%s", bot_id)
        return new_key

    async def revoke(self, bot_id: str) -> bool:
        """시그널 키 폐기."""
        existing = await self.get_key(bot_id)
        if not existing:
            return False
        await self._db.execute(
            "DELETE FROM signal_keys WHERE bot_id = ?",
            (bot_id,),
        )
        logger.info("시그널 키 폐기: bot=%s", bot_id)
        return True

    async def validate_key(self, key: str) -> str | None:
        """키 유효성 검증. 유효하면 bot_id 반환."""
        row = await self._db.fetch_one(
            "SELECT bot_id FROM signal_keys WHERE key_id = ?",
            (key,),
        )
        return row["bot_id"] if row else None
