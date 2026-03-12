"""Database 래퍼 단위 테스트."""

import pytest

from ante.core import Database


@pytest.fixture
async def db(tmp_path):
    """임시 DB 인스턴스."""
    database = Database(str(tmp_path / "test.db"))
    await database.connect()
    yield database
    await database.close()


async def test_execute_and_fetch(db):
    """INSERT 후 SELECT로 조회한다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT);")
    await db.execute("INSERT INTO t (name) VALUES (?)", ("hello",))

    row = await db.fetch_one("SELECT * FROM t WHERE name = ?", ("hello",))
    assert row is not None
    assert row["name"] == "hello"


async def test_fetch_all(db):
    """다중 행 조회."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")
    await db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
    await db.execute("INSERT INTO t (val) VALUES (?)", ("b",))

    rows = await db.fetch_all("SELECT * FROM t ORDER BY val")
    assert len(rows) == 2
    assert rows[0]["val"] == "a"
    assert rows[1]["val"] == "b"


async def test_fetch_one_returns_none(db):
    """존재하지 않는 행은 None 반환."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    assert await db.fetch_one("SELECT * FROM t WHERE id = 999") is None


async def test_wal_mode(db):
    """WAL 모드가 활성화되어 있다."""
    row = await db.fetch_one("PRAGMA journal_mode")
    assert row is not None
    # dict key는 PRAGMA에 따라 "journal_mode"
    journal_mode = list(row.values())[0]
    assert journal_mode == "wal"


async def test_not_connected_raises():
    """connect() 전에 실행하면 RuntimeError."""
    db = Database(":memory:")
    with pytest.raises(RuntimeError, match="DB 연결되지 않음"):
        await db.execute("SELECT 1")
