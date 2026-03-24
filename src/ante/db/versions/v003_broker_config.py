"""v003: Account 테이블에 broker_config 컬럼 추가."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """Account 테이블에 broker_config 컬럼 추가."""
    await db.execute(
        "ALTER TABLE accounts ADD COLUMN broker_config TEXT NOT NULL DEFAULT '{}'"
    )
