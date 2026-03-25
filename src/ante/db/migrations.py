"""중앙 마이그레이션 러너.

schema_version 테이블을 관리하며, 등록된 마이그레이션을 순차 실행한다.
DB 마이그레이션과 Parquet 데이터 마이그레이션을 모두 지원한다.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from ante.core.database import Database
from ante.db.versions import v001_baseline, v002_parquet_migration, v003_broker_config

# 마이그레이션 함수 시그니처:
#   async def migrate(db: Database) -> None                          (DB 전용)
#   async def migrate(db: Database, *, data_path: Path | None) -> None  (DB + 데이터)
MigrateFn = Callable[..., Coroutine[Any, Any, None]]

MIGRATIONS: list[tuple[int, str, MigrateFn]] = [
    (1, "0.7.0", v001_baseline.migrate),
    (2, "0.7.0", v002_parquet_migration.migrate),
    (3, "0.8.0", v003_broker_config.migrate),
]


def _accepts_data_path(fn: MigrateFn) -> bool:
    """마이그레이션 함수가 data_path 키워드 인자를 받는지 검사한다."""
    sig = inspect.signature(fn)
    return "data_path" in sig.parameters


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


async def run_migrations(
    db: Database,
    *,
    data_path: Path | None = None,
) -> list[str]:
    """미적용 마이그레이션을 순차 실행하고, 적용된 항목 라벨을 반환한다.

    Args:
        db: Database 인스턴스.
        data_path: 데이터 저장소 루트 경로. Parquet 마이그레이션에 전달된다.
    """
    await ensure_schema_version_table(db)
    applied = await get_applied_seqs(db)
    newly_applied: list[str] = []
    for seq, version, migrate_fn in sorted(MIGRATIONS, key=lambda x: x[0]):
        if seq not in applied:
            kwargs: dict[str, Any] = {}
            if _accepts_data_path(migrate_fn):
                kwargs["data_path"] = data_path
            async with db.transaction():
                await migrate_fn(db, **kwargs)
                await db.execute(
                    "INSERT INTO schema_version (seq, version) VALUES (?, ?)",
                    (seq, version),
                )
            newly_applied.append(f"{seq:03d}_{version}")
    return newly_applied


if __name__ == "__main__":
    import asyncio

    async def main() -> None:
        db = Database("db/ante.db")
        await db.connect()
        applied = await run_migrations(db, data_path=Path("data/"))
        if applied:
            print(f"마이그레이션 적용: {', '.join(applied)}")
        else:
            print("적용할 마이그레이션이 없습니다")
        await db.close()

    asyncio.run(main())
