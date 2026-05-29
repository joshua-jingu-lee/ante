"""Database 래퍼 단위 테스트."""

import asyncio
from unittest.mock import patch

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


async def test_execute_fetch_all_returns_affected_rows(db):
    """UPDATE … RETURNING 으로 실제 영향받은 다건을 writer 단일 호출로 반환."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT);")
    await db.execute("INSERT INTO t (id, status) VALUES (1, 'open')")
    await db.execute("INSERT INTO t (id, status) VALUES (2, 'open')")
    await db.execute("INSERT INTO t (id, status) VALUES (3, 'filled')")

    rows = await db.execute_fetch_all(
        "UPDATE t SET status = 'expired' WHERE status = 'open' RETURNING id",
        (),
    )
    # status='open' 2건만 RETURNING — 'filled' 는 영향 없음.
    assert sorted(r["id"] for r in rows) == [1, 2]
    # 실제 DB 도 갱신됨(reader 에서도 commit 관측).
    after = await db.fetch_all("SELECT id, status FROM t ORDER BY id")
    assert [r["status"] for r in after] == ["expired", "expired", "filled"]


async def test_execute_fetch_all_empty_when_no_match(db):
    """매칭 행이 없으면 빈 리스트 반환."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, status TEXT);")
    await db.execute("INSERT INTO t (id, status) VALUES (1, 'filled')")
    rows = await db.execute_fetch_all(
        "UPDATE t SET status = 'expired' WHERE status = 'open' RETURNING id",
        (),
    )
    assert rows == []


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


# --- 트랜잭션 컨텍스트 매니저 테스트 ---


async def test_transaction_commit(db):
    """트랜잭션 내 INSERT 2건이 context 탈출 후 정상 커밋된다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    async with db.transaction():
        await db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
        await db.execute("INSERT INTO t (val) VALUES (?)", ("b",))

    rows = await db.fetch_all("SELECT * FROM t ORDER BY val")
    assert len(rows) == 2
    assert rows[0]["val"] == "a"
    assert rows[1]["val"] == "b"


async def test_transaction_rollback_on_exception(db):
    """트랜잭션 내 예외 발생 시 INSERT가 롤백된다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    with pytest.raises(ValueError, match="의도적 예외"):
        async with db.transaction():
            await db.execute("INSERT INTO t (val) VALUES (?)", ("a",))
            raise ValueError("의도적 예외")

    rows = await db.fetch_all("SELECT * FROM t")
    assert len(rows) == 0


async def test_transaction_nested_raises(db):
    """이미 트랜잭션 중 재진입 시 RuntimeError가 발생한다."""
    async with db.transaction():
        with pytest.raises(RuntimeError, match="중첩 트랜잭션은 지원하지 않습니다"):
            async with db.transaction():
                pass  # pragma: no cover


async def test_transaction_ddl(db):
    """ALTER TABLE 2건을 하나의 트랜잭션으로 묶어 실행한다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, col_a TEXT);")

    async with db.transaction():
        await db.execute("ALTER TABLE t ADD COLUMN col_b TEXT")
        await db.execute("ALTER TABLE t ADD COLUMN col_c TEXT")

    # 추가된 컬럼에 값을 삽입하여 DDL이 정상 적용되었는지 검증
    await db.execute(
        "INSERT INTO t (col_a, col_b, col_c) VALUES (?, ?, ?)",
        ("a", "b", "c"),
    )
    row = await db.fetch_one("SELECT * FROM t WHERE col_a = ?", ("a",))
    assert row is not None
    assert row["col_b"] == "b"
    assert row["col_c"] == "c"


# --- BaseException(CancelledError 등) 경로 ROLLBACK 회귀 (#1923) ---


async def test_transaction_rollback_on_cancelled_error(db):
    """asyncio.CancelledError 경로에서도 INSERT가 롤백되고 원본 예외가 재전파된다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    with pytest.raises(asyncio.CancelledError):
        async with db.transaction():
            await db.execute("INSERT INTO t (val) VALUES (?)", ("cancelled",))
            raise asyncio.CancelledError()

    rows = await db.fetch_all("SELECT * FROM t")
    assert rows == []


async def test_transaction_state_allows_new_transaction_after_cancelled_error(db):
    """CancelledError 후 _in_transaction이 해제되어 새 트랜잭션이 가능하다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    with pytest.raises(asyncio.CancelledError):
        async with db.transaction():
            await db.execute("INSERT INTO t (val) VALUES (?)", ("first",))
            raise asyncio.CancelledError()

    # 동일 Database 인스턴스에서 새 트랜잭션이 정상 시작/COMMIT 가능해야 한다.
    async with db.transaction():
        await db.execute("INSERT INTO t (val) VALUES (?)", ("second",))

    rows = await db.fetch_all("SELECT val FROM t")
    assert [row["val"] for row in rows] == ["second"]


async def test_transaction_rollback_failure_preserves_original_exception(db):
    """ROLLBACK 자체가 실패해도 원본 예외(CancelledError)가 호출자에게 전달된다."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    real_execute = db._get_writer().execute

    async def execute_with_rollback_failure(sql, *args, **kwargs):
        if sql.strip().upper().startswith("ROLLBACK"):
            raise RuntimeError("rollback boom")
        return await real_execute(sql, *args, **kwargs)

    with patch.object(
        db._get_writer(),
        "execute",
        side_effect=execute_with_rollback_failure,
    ):
        with pytest.raises(asyncio.CancelledError):
            async with db.transaction():
                await db.execute("INSERT INTO t (val) VALUES (?)", ("x",))
                raise asyncio.CancelledError()

    # _in_transaction 플래그도 finally에서 해제되어야 한다.
    assert db._in_transaction is False
