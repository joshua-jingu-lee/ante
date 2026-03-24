"""중앙 마이그레이션 러너.

schema_version 테이블을 관리하며, 등록된 마이그레이션을 순차 실행한다.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from ante.core.database import Database
from ante.db.versions import v001_baseline

MigrateFn = Callable[[Database], Coroutine[Any, Any, None]]

MIGRATIONS: list[tuple[int, str, MigrateFn]] = [
    (1, "0.7.0", v001_baseline.migrate),
]


async def ensure_schema_version_table(db: Database) -> None:
    """schema_version 테이블이 없으면 생성한다."""
    await db.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        "  seq INTEGER PRIMARY KEY,"
        "  version TEXT NOT NULL,"
        "  applied_at TEXT NOT NULL DEFAULT (datetime('now'))"
        ")"
    )


async def get_applied_seqs(db: Database) -> set[int]:
    """이미 적용된 마이그레이션 seq 목록을 반환한다."""
    rows = await db.fetch_all("SELECT seq FROM schema_version")
    return {r["seq"] for r in rows}


async def run_migrations(db: Database) -> list[str]:
    """미적용 마이그레이션을 순차 실행하고, 적용된 항목 라벨을 반환한다."""
    await ensure_schema_version_table(db)
    applied = await get_applied_seqs(db)
    newly_applied: list[str] = []
    for seq, version, migrate_fn in sorted(MIGRATIONS, key=lambda x: x[0]):
        if seq not in applied:
            async with db.transaction():
                await migrate_fn(db)
                await db.execute(
                    "INSERT INTO schema_version (seq, version) VALUES (?, ?)",
                    (seq, version),
                )
            newly_applied.append(f"{seq:03d}_{version}")
    return newly_applied
