from __future__ import annotations

import sqlite3
import time
from pathlib import Path

import pytest

from ante.db.backup import backup_db


@pytest.fixture()
def wal_db(tmp_path: Path) -> Path:
    """WAL 모드가 활성화된 테스트 DB를 생성한다."""
    db_path = tmp_path / "ante.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("INSERT INTO items (name) VALUES ('alpha')")
    conn.execute("INSERT INTO items (name) VALUES ('beta')")
    conn.commit()
    conn.close()
    return db_path


class TestBackupIntegrity:
    """TC-1: WAL 모드 DB 백업 정합성."""

    def test_wal_backup_data_matches(self, wal_db: Path) -> None:
        bak_path = backup_db(wal_db, "001")

        conn = sqlite3.connect(str(bak_path))
        rows = conn.execute("SELECT name FROM items ORDER BY id").fetchall()
        conn.close()

        assert rows == [("alpha",), ("beta",)]


class TestNoWalShm:
    """TC-2: 백업 경로에 -wal, -shm 파일이 없어야 한다."""

    def test_no_wal_shm_files(self, wal_db: Path) -> None:
        bak_path = backup_db(wal_db, "001")

        assert not Path(f"{bak_path}-wal").exists()
        assert not Path(f"{bak_path}-shm").exists()


class TestBackupFileName:
    """TC-3: 백업 파일명 형식 검증."""

    def test_filename_pattern(self, wal_db: Path) -> None:
        bak_path = backup_db(wal_db, "002")

        assert bak_path.name == "ante.db.bak.v002"


class TestOldBackupCleanup:
    """TC-4: 오래된 백업 자동 삭제 — 4개 백업 후 최근 3개만 유지."""

    def test_keeps_only_max_backups(self, wal_db: Path) -> None:
        for i in range(4):
            backup_db(wal_db, f"00{i + 1}")
            time.sleep(0.05)  # mtime 차이 보장

        pattern = f"{wal_db.name}.bak.v*"
        remaining = sorted(wal_db.parent.glob(pattern))

        assert len(remaining) == 3
        assert not (wal_db.parent / "ante.db.bak.v001").exists()


class TestMissingSourceDb:
    """TC-5: 원본 DB 미존재 시 오류."""

    def test_raises_on_missing_db(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.db"

        with pytest.raises(Exception):
            backup_db(missing, "001")
