"""schema_version 테이블 + 중앙 마이그레이션 러너 테스트."""

import pytest

from ante.core.database import Database
from ante.db.migrations import (
    ensure_schema_version_table,
    get_applied_seqs,
    run_migrations,
)


@pytest.fixture
async def db(tmp_path):
    """임시 SQLite DB를 생성하고 반환한다."""
    db_path = str(tmp_path / "test.db")
    database = Database(db_path)
    await database.connect()
    yield database
    await database.close()


class TestEnsureSchemaVersionTable:
    """schema_version 테이블 자동 생성 테스트."""

    async def test_creates_table_when_not_exists(self, db: Database):
        """빈 DB에서 schema_version 테이블을 생성한다."""
        await ensure_schema_version_table(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None
        assert row["name"] == "schema_version"

    async def test_idempotent_creation(self, db: Database):
        """두 번 호출해도 에러 없이 동작한다."""
        await ensure_schema_version_table(db)
        await ensure_schema_version_table(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None


class TestRunMigrations:
    """마이그레이션 러너 테스트."""

    async def test_applies_all_on_empty_db(self, db: Database):
        """빈 DB에서 전체 마이그레이션 실행 시 schema_version에 모든 seq 기록."""
        result = await run_migrations(db)

        assert len(result) > 0
        assert "001_0.7.0" in result

        applied = await get_applied_seqs(db)
        assert 1 in applied

    async def test_skips_already_applied(self, db: Database):
        """이미 적용된 마이그레이션은 건너뛴다."""
        await run_migrations(db)

        # 수동으로 seq 확인
        applied_before = await get_applied_seqs(db)

        result = await run_migrations(db)

        assert result == []
        applied_after = await get_applied_seqs(db)
        assert applied_before == applied_after

    async def test_idempotent_double_call(self, db: Database):
        """2회 호출 시 두 번째는 빈 리스트를 반환한다 (멱등성)."""
        first = await run_migrations(db)
        second = await run_migrations(db)

        assert len(first) > 0
        assert second == []

    async def test_schema_version_table_auto_created(self, db: Database):
        """run_migrations가 schema_version 테이블을 자동 생성한다."""
        # 테이블이 없는 상태에서 바로 run_migrations 호출
        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is None

        await run_migrations(db)

        row = await db.fetch_one(
            "SELECT name FROM sqlite_master "
            "WHERE type='table' AND name='schema_version'"
        )
        assert row is not None
