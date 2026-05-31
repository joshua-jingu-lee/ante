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


# --- connect 실패 시 aiosqlite worker thread 정리 (#1965) ---


def _live_worker_threads() -> list[str]:
    """살아 있는 aiosqlite worker thread 이름 목록."""
    import threading

    return [
        t.name for t in threading.enumerate() if "_connection_worker_thread" in t.name
    ]


async def test_connect_failure_drains_worker_thread_open_error(tmp_path):
    """``connect()`` 가 'unable to open database file' 로 실패해도 aiosqlite
    worker thread 가 누수되지 않는다 (#1965).

    근본 원인: ``await aiosqlite.connect`` 는 worker thread 를 먼저 ``start()``
    한 뒤 ``sqlite3.connect`` 를 큐잉한다. 파일 오픈 실패 시 aiosqlite 가 내부
    ``stop()`` 의 future 를 폐기하므로, 호출자가 종료를 동기화하지 못한 채
    ``asyncio.run`` 이 루프를 닫으면 worker 가 닫힌 루프를 건드려 stderr 에
    ``RuntimeError: Event loop is closed`` traceback 이 남는다. 이는
    ``--format json`` stderr 청결 계약을 위반한다.

    수정 전: 이 테스트는 connect 실패 직후 worker thread 가 살아 있어 FAIL.
    """
    # 존재하지 않는 부모 디렉토리 → 첫(writer) 연결의 sqlite3.connect 가 실패.
    bad_path = str(tmp_path / "no-such-dir" / "ante.db")
    db = Database(bad_path)

    before = set(_live_worker_threads())
    with pytest.raises(Exception, match="unable to open database file"):
        await db.connect()

    # connect 실패 직후(루프 teardown 이전)에 새 worker thread 가 남아 있으면 안 된다.
    leaked = set(_live_worker_threads()) - before
    assert not leaked, (
        f"connect 실패 후 aiosqlite worker thread 가 누수됨: {leaked} "
        "(#1965 — _drain_failed_conn 가 join 으로 동기 정리해야 함)"
    )


async def test_connect_failure_drains_worker_thread_pragma_error(tmp_path):
    """``aiosqlite.connect`` 성공 후 PRAGMA 단계에서 실패해도 worker thread 가
    누수되지 않는다 (#1965).

    디렉토리를 DB 경로로 주면 ``sqlite3.connect`` 는 lazy 하게 성공하지만 첫
    PRAGMA 실행에서 'unable to open database file' 이 발생한다. 이 경우
    연결 객체는 열려 있으므로 ``conn.close()`` 로 worker 가 정리되어야 한다.
    """
    db = Database(str(tmp_path))  # tmp_path 는 디렉토리

    before = set(_live_worker_threads())
    with pytest.raises(Exception, match="unable to open database file"):
        await db.connect()

    leaked = set(_live_worker_threads()) - before
    assert not leaked, (
        f"PRAGMA 실패 후 aiosqlite worker thread 가 누수됨: {leaked} (#1965)"
    )


async def test_connect_partial_failure_closes_writer(tmp_path):
    """writer 는 열렸으나 reader(2번째 _init_conn) 가 실패하면 이미 열린 writer
    연결과 그 worker thread 가 ``connect()`` 의 cleanup 으로 정리된다 (#1965)."""
    db_path = str(tmp_path / "partial.db")
    db = Database(db_path)

    before = set(_live_worker_threads())

    real_init = Database._init_conn
    calls = {"n": 0}

    async def init_with_reader_failure(self):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 2:  # 2번째 호출(reader) 만 실패시킨다.
            raise RuntimeError("simulated reader init failure")
        return await real_init(self)

    with patch.object(Database, "_init_conn", init_with_reader_failure):
        with pytest.raises(RuntimeError, match="simulated reader init failure"):
            await db.connect()

    # connect 가 부분 성공(writer) 상태를 close 로 정리했어야 한다.
    assert db._writer is None
    assert db._reader is None
    leaked = set(_live_worker_threads()) - before
    assert not leaked, (
        f"reader 실패 후 writer worker thread 가 누수됨: {leaked} (#1965)"
    )


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
