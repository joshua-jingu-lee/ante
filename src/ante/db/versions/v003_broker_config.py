"""v003: Account 테이블에 broker_config 컬럼 추가."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ante.core.database import Database


async def migrate(db: Database) -> None:
    """Account 테이블에 broker_config 컬럼 추가."""
    row = await db.fetch_one(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='accounts'"
    )
    if row is None:
        return  # accounts 테이블이 없으면 스킵 (신규 설치 시 DDL에 이미 포함)

    # 컬럼 존재 여부 확인
    cols = await db.fetch_all("PRAGMA table_info(accounts)")
    col_names = {c["name"] for c in cols}
    if "broker_config" not in col_names:
        await db.execute(
            "ALTER TABLE accounts ADD COLUMN broker_config TEXT NOT NULL DEFAULT '{}'"
        )
