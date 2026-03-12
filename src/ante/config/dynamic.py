"""DynamicConfigService — 동적 설정 CRUD + 변경 알림."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

from ante.config.exceptions import ConfigError

if TYPE_CHECKING:
    from ante.core.database import Database
    from ante.eventbus.bus import EventBus

logger = logging.getLogger(__name__)

DYNAMIC_CONFIG_SCHEMA = """
CREATE TABLE IF NOT EXISTS dynamic_config (
    key       TEXT PRIMARY KEY,
    value     TEXT NOT NULL,
    category  TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
"""


class DynamicConfigService:
    """동적 설정 CRUD + 변경 알림.

    런타임 변경이 필요한 설정을 SQLite에 저장하고,
    변경 시 EventBus를 통해 ConfigChangedEvent를 발행한다.
    """

    def __init__(self, db: Database, eventbus: EventBus) -> None:
        self._db = db
        self._eventbus = eventbus

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(DYNAMIC_CONFIG_SCHEMA)

    async def get(self, key: str, default: Any = None) -> Any:
        """동적 설정 값 조회. JSON 역직렬화하여 반환."""
        row = await self._db.fetch_one(
            "SELECT value FROM dynamic_config WHERE key = ?", (key,)
        )
        if row is None:
            if default is not None:
                return default
            raise ConfigError(f"Dynamic config not found: {key}")
        return json.loads(row["value"])

    async def set(self, key: str, value: Any, category: str) -> None:
        """동적 설정 값 변경 + EventBus 알림."""
        from ante.eventbus.events import ConfigChangedEvent

        old_value = None
        if await self.exists(key):
            old_value = await self.get(key)

        json_value = json.dumps(value)
        await self._db.execute(
            """INSERT INTO dynamic_config (key, value, category, updated_at)
               VALUES (?, ?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 updated_at = excluded.updated_at""",
            (key, json_value, category),
        )
        await self._eventbus.publish(
            ConfigChangedEvent(
                category=category,
                key=key,
                old_value=json.dumps(old_value) if old_value is not None else "",
                new_value=json_value,
            )
        )
        logger.info("동적 설정 변경: %s = %s (category=%s)", key, value, category)

    async def delete(self, key: str) -> bool:
        """동적 설정 삭제. 삭제 성공 시 True 반환."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM dynamic_config WHERE key = ?", (key,)
        )
        if row is None:
            return False
        await self._db.execute("DELETE FROM dynamic_config WHERE key = ?", (key,))
        return True

    async def get_by_category(self, category: str) -> dict[str, Any]:
        """카테고리별 모든 설정 조회."""
        rows = await self._db.fetch_all(
            "SELECT key, value FROM dynamic_config WHERE category = ?",
            (category,),
        )
        return {row["key"]: json.loads(row["value"]) for row in rows}

    async def exists(self, key: str) -> bool:
        """설정 존재 여부 확인."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM dynamic_config WHERE key = ?", (key,)
        )
        return row is not None
