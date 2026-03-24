"""schema_version 테이블 + 중앙 마이그레이션 러너 테스트."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ante.core.database import Database
from ante.db.migrations import (
    _accepts_data_path,
    ensure_schema_version_table,
    get_applied_seqs,
    run_migrations,
)
from ante.db.versions import v001_baseline, v002_parquet_migration


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


class TestParquetMigrationIntegration:
    """Parquet 마이그레이션의 중앙 러너 통합 테스트."""

    async def test_data_path_passed_to_parquet_migration(
        self, db: Database, tmp_path: Path
    ):
        """마이그레이션 러너에서 data_path 인자가 Parquet 마이그레이션에 전달된다."""
        data_path = tmp_path / "data"
        data_path.mkdir()

        with patch(
            "ante.data.store.migrate_parquet_paths",
            return_value=0,
        ) as mock_migrate:
            await run_migrations(db, data_path=data_path)

        mock_migrate.assert_called_once_with(data_path)

    async def test_parquet_migration_moves_paths(self, db: Database, tmp_path: Path):
        """Parquet 경로 변경이 실제로 적용된다 (구 경로 -> 신 경로)."""
        data_path = tmp_path / "data"
        old_path = data_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        (old_path / "2026-01.parquet").write_bytes(b"dummy-parquet-data")

        await run_migrations(db, data_path=data_path)

        # 구 경로 사라짐
        assert not old_path.exists()
        # 신 경로 생성됨
        new_path = data_path / "ohlcv" / "1d" / "KRX" / "005930"
        assert new_path.exists()
        assert (new_path / "2026-01.parquet").read_bytes() == b"dummy-parquet-data"

    async def test_parquet_data_preserved_after_migration(
        self, db: Database, tmp_path: Path
    ):
        """마이그레이션 전후 Parquet 내용이 일치한다."""
        data_path = tmp_path / "data"
        old_path = data_path / "ohlcv" / "1d" / "005930"
        old_path.mkdir(parents=True)
        original_content = b"parquet-binary-content-12345"
        (old_path / "2026-01.parquet").write_bytes(original_content)

        await run_migrations(db, data_path=data_path)

        new_file = data_path / "ohlcv" / "1d" / "KRX" / "005930" / "2026-01.parquet"
        assert new_file.read_bytes() == original_content

    async def test_v002_registered_in_migrations(self):
        """v002_parquet_migration이 MIGRATIONS 리스트에 등록되어 있다."""
        from ante.db.migrations import MIGRATIONS

        seqs = [seq for seq, _, _ in MIGRATIONS]
        fns = [fn for _, _, fn in MIGRATIONS]
        assert 2 in seqs
        assert v002_parquet_migration.migrate in fns

    async def test_run_migrations_without_data_path(self, db: Database):
        """data_path 없이 호출해도 정상 동작한다 (하위 호환)."""
        result = await run_migrations(db)
        assert "002_0.7.0" in result

        applied = await get_applied_seqs(db)
        assert 2 in applied

    async def test_no_data_path_skips_parquet_move(self, db: Database):
        """data_path=None이면 Parquet 마이그레이션이 파일 이동 없이 완료된다."""
        with patch(
            "ante.data.store.migrate_parquet_paths",
        ) as mock_migrate:
            await run_migrations(db)

        mock_migrate.assert_not_called()


class TestAcceptsDataPath:
    """_accepts_data_path 유틸리티 테스트."""

    def test_v001_does_not_accept_data_path(self):
        """v001_baseline은 data_path 파라미터가 없다."""
        assert not _accepts_data_path(v001_baseline.migrate)

    def test_v002_accepts_data_path(self):
        """v002_parquet_migration은 data_path 파라미터를 받는다."""
        assert _accepts_data_path(v002_parquet_migration.migrate)
