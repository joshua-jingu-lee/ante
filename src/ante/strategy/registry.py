"""StrategyRegistry — 검증 완료된 전략 목록 관리."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from ante.strategy.base import StrategyMeta
from ante.strategy.exceptions import StrategyError

if TYPE_CHECKING:
    from ante.core.database import Database

logger = logging.getLogger(__name__)

STRATEGY_REGISTRY_SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id          TEXT PRIMARY KEY,
    name                 TEXT NOT NULL,
    version              TEXT NOT NULL,
    filepath             TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'registered',
    registered_at        TEXT NOT NULL,
    description          TEXT DEFAULT '',
    author               TEXT DEFAULT 'agent',
    validation_warnings  TEXT DEFAULT '[]',
    rationale            TEXT DEFAULT '',
    risks                TEXT DEFAULT '[]'
);
"""


class StrategyStatus(StrEnum):
    """전략 상태."""

    REGISTERED = "registered"
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


@dataclass
class StrategyRecord:
    """Registry에 저장되는 전략 레코드."""

    strategy_id: str
    name: str
    version: str
    filepath: str
    status: StrategyStatus
    registered_at: datetime
    description: str = ""
    author: str = "agent"
    validation_warnings: list[str] = field(default_factory=list)
    rationale: str = ""
    risks: list[str] = field(default_factory=list)


class StrategyRegistry:
    """검증 완료된 전략 목록 관리. SQLite에 영속화."""

    def __init__(self, db: Database) -> None:
        self._db = db

    async def initialize(self) -> None:
        """스키마 생성."""
        await self._db.execute_script(STRATEGY_REGISTRY_SCHEMA)

    async def register(
        self,
        filepath: Path,
        meta: StrategyMeta,
        warnings: list[str] | None = None,
        *,
        rationale: str = "",
        risks: list[str] | None = None,
    ) -> StrategyRecord:
        """전략 등록."""
        strategy_id = f"{meta.name}_v{meta.version}"

        if await self.exists(strategy_id):
            raise StrategyError(f"Strategy already registered: {strategy_id}")

        now = datetime.now(UTC)
        record = StrategyRecord(
            strategy_id=strategy_id,
            name=meta.name,
            version=meta.version,
            filepath=str(filepath),
            status=StrategyStatus.REGISTERED,
            registered_at=now,
            description=meta.description,
            author=meta.author,
            validation_warnings=warnings or [],
            rationale=rationale,
            risks=risks or [],
        )

        await self._db.execute(
            """INSERT INTO strategies
               (strategy_id, name, version, filepath, status,
                registered_at, description, author,
                validation_warnings, rationale, risks)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                record.strategy_id,
                record.name,
                record.version,
                record.filepath,
                record.status.value,
                record.registered_at.isoformat(),
                record.description,
                record.author,
                json.dumps(record.validation_warnings),
                record.rationale,
                json.dumps(record.risks),
            ),
        )
        logger.info("전략 등록: %s", strategy_id)
        return record

    async def get(self, strategy_id: str) -> StrategyRecord | None:
        """전략 레코드 조회."""
        row = await self._db.fetch_one(
            "SELECT * FROM strategies WHERE strategy_id = ?",
            (strategy_id,),
        )
        if row is None:
            return None
        return self._row_to_record(row)

    async def list_strategies(
        self,
        status: StrategyStatus | None = None,
    ) -> list[StrategyRecord]:
        """전략 목록 조회."""
        if status:
            rows = await self._db.fetch_all(
                "SELECT * FROM strategies WHERE status = ? ORDER BY registered_at DESC",
                (status.value,),
            )
        else:
            rows = await self._db.fetch_all(
                "SELECT * FROM strategies ORDER BY registered_at DESC"
            )
        return [self._row_to_record(row) for row in rows]

    async def update_status(
        self,
        strategy_id: str,
        status: StrategyStatus,
    ) -> None:
        """전략 상태 변경."""
        await self._db.execute(
            "UPDATE strategies SET status = ? WHERE strategy_id = ?",
            (status.value, strategy_id),
        )

    async def get_by_name(self, name: str) -> list[StrategyRecord]:
        """이름으로 전략 레코드 조회 (동일 이름 여러 버전 가능)."""
        rows = await self._db.fetch_all(
            "SELECT * FROM strategies WHERE name = ? ORDER BY registered_at DESC",
            (name,),
        )
        return [self._row_to_record(row) for row in rows]

    async def exists(self, strategy_id: str) -> bool:
        """전략 존재 여부 확인."""
        row = await self._db.fetch_one(
            "SELECT 1 FROM strategies WHERE strategy_id = ?",
            (strategy_id,),
        )
        return row is not None

    @staticmethod
    def _row_to_record(row: dict) -> StrategyRecord:
        return StrategyRecord(
            strategy_id=row["strategy_id"],
            name=row["name"],
            version=row["version"],
            filepath=row["filepath"],
            status=StrategyStatus(row["status"]),
            registered_at=datetime.fromisoformat(row["registered_at"]),
            description=row["description"],
            author=row["author"],
            validation_warnings=json.loads(row["validation_warnings"]),
            rationale=row.get("rationale", ""),
            risks=json.loads(row["risks"]) if row.get("risks") else [],
        )
