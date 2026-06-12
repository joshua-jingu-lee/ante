"""Database 래퍼 단위 테스트."""

import asyncio
import sqlite3
from unittest.mock import patch

import aiosqlite
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


# --- read-only 연결 모드 (#1974 offline-factory.md §2 옵션 A) ---


async def _seed_rw_db(path: str) -> None:
    """write 가능한 ``Database`` 로 테이블 1개 + 행 1건을 생성 후 close 한다."""
    writer = Database(path)
    await writer.connect()
    try:
        await writer.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT);")
        await writer.execute("INSERT INTO t (id, v) VALUES (1, 'alpha')")
    finally:
        await writer.close()


async def test_read_only_reads_existing_db(tmp_path):
    """``read_only=True`` 로 기존 DB 를 schema/WAL 쓰기 없이 read 한다."""
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    ro = Database(db_path, read_only=True)
    await ro.connect()
    try:
        rows = await ro.fetch_all("SELECT id, v FROM t ORDER BY id")
        assert rows == [{"id": 1, "v": "alpha"}]
        one = await ro.fetch_one("SELECT v FROM t WHERE id = 1")
        assert one == {"v": "alpha"}
    finally:
        await ro.close()


async def test_read_only_opens_reader_only_no_writer(tmp_path):
    """``read_only=True`` 는 reader 단일 연결만 열고 writer 는 미개방."""
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    ro = Database(db_path, read_only=True)
    await ro.connect()
    try:
        assert ro._reader is not None
        assert ro._writer is None
    finally:
        await ro.close()


async def test_read_only_write_methods_raise_read_only_error(tmp_path):
    """ro 모드에서 write 경로 호출 시 ReadOnlyDatabaseError 로 명확히 실패한다.

    "DB 연결되지 않음" 이 아니라 read-only 전용 에러여야 한다(_writer 미개방).
    """
    from ante.core.database import ReadOnlyDatabaseError

    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    ro = Database(db_path, read_only=True)
    await ro.connect()
    try:
        with pytest.raises(ReadOnlyDatabaseError, match="read-only Database"):
            await ro.execute("INSERT INTO t (id, v) VALUES (2, 'beta')")
        with pytest.raises(ReadOnlyDatabaseError, match="read-only Database"):
            await ro.execute_script("CREATE TABLE t2 (id INTEGER)")
        with pytest.raises(ReadOnlyDatabaseError, match="read-only Database"):
            await ro.execute_fetch_one("UPDATE t SET v = 'x' RETURNING id")
        with pytest.raises(ReadOnlyDatabaseError, match="read-only Database"):
            await ro.execute_fetch_all("UPDATE t SET v = 'x' RETURNING id")
        with pytest.raises(ReadOnlyDatabaseError, match="read-only Database"):
            async with ro.transaction():
                pass  # pragma: no cover
    finally:
        await ro.close()


async def test_read_only_skips_write_pragmas(tmp_path):
    """ro 연결은 쓰기 PRAGMA(journal_mode=WAL/synchronous)를 발화하지 않는다.

    ``mode=ro`` 연결의 ``PRAGMA journal_mode`` 는 메인 DB 가 WAL 모드여도 ro
    연결에서 변경되지 않으며, ``synchronous`` 도 설정하지 않는다. 본 테스트는
    ``_open_ro_conn`` 이 실행하는 PRAGMA 시퀀스를 가로채 WAL/synchronous 쓰기
    PRAGMA 가 발화되지 않음을 단언한다.
    """
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    executed: list[str] = []
    real_execute = aiosqlite.Connection.execute

    def _spy_execute(self, sql, *a, **kw):  # noqa: ANN001, ANN002, ANN003, ANN202
        executed.append(sql)
        return real_execute(self, sql, *a, **kw)

    ro = Database(db_path, read_only=True)
    with patch.object(aiosqlite.Connection, "execute", _spy_execute):
        await ro.connect()
    try:
        normalized = [s.strip().lower() for s in executed]
        assert not any("journal_mode" in s for s in normalized), (
            f"ro 연결이 journal_mode PRAGMA 를 발화함: {executed}"
        )
        assert not any("synchronous" in s for s in normalized), (
            f"ro 연결이 synchronous PRAGMA 를 발화함: {executed}"
        )
        # read-only PRAGMA 는 적용되어야 한다.
        assert any("foreign_keys" in s for s in normalized)
        assert any("busy_timeout" in s for s in normalized)
        assert any("temp_store" in s for s in normalized)
    finally:
        await ro.close()


async def test_read_only_uri_uses_mode_ro_and_uri_flag(tmp_path):
    """ro 연결은 ``file:...?mode=ro`` URI 를 ``uri=True`` 로 연다."""
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    captured: dict = {}
    real_connect = aiosqlite.connect

    def _spy_connect(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        if not captured:
            captured["args"] = args
            captured["kwargs"] = dict(kwargs)
        return real_connect(*args, **kwargs)

    ro = Database(db_path, read_only=True)
    with patch("ante.core.database.aiosqlite.connect", side_effect=_spy_connect):
        await ro.connect()
    try:
        uri = captured["args"][0]
        assert uri.startswith("file:"), uri
        assert "mode=ro" in uri, uri
        assert "immutable" not in uri, uri  # 정상 DB → fallback 미발생
        assert captured["kwargs"].get("uri") is True, captured["kwargs"]
    finally:
        await ro.close()


async def test_read_only_immutable_fallback_on_wal_artifact(tmp_path):
    """mode=ro probe 가 WAL/권한 OperationalError 로 실패하면 immutable 재연결.

    첫 ``_open_ro_conn`` (mode=ro) 의 probe 가 ``unable to open database file`` 로
    실패하도록 강제하면, ``_init_ro_conn`` 이 ``immutable=1`` URI 로 재연결해
    read 에 성공해야 한다.
    """
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    real_probe = Database._probe_ro_conn
    calls = {"n": 0}

    async def _probe_first_fails(conn):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite3.OperationalError("unable to open database file")
        return await real_probe(conn)

    uris: list[str] = []
    real_connect = aiosqlite.connect

    def _spy_connect(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        uris.append(args[0])
        return real_connect(*args, **kwargs)

    ro = Database(db_path, read_only=True)
    with (
        patch.object(Database, "_probe_ro_conn", staticmethod(_probe_first_fails)),
        patch("ante.core.database.aiosqlite.connect", side_effect=_spy_connect),
    ):
        await ro.connect()
    try:
        # 첫 연결은 mode=ro, 재연결은 immutable=1.
        assert any("immutable=1" in u for u in uris), uris
        rows = await ro.fetch_all("SELECT id, v FROM t ORDER BY id")
        assert rows == [{"id": 1, "v": "alpha"}]
    finally:
        await ro.close()


async def test_read_only_no_such_table_not_fallback(tmp_path):
    """probe 가 ``no such table`` 로 실패하면 immutable fallback 하지 않고 재전파.

    ``no such table``/``malformed``/``not a database`` 는 WAL/권한 계열이 아니므로
    fallback 대상이 아니다. probe 단계에서 이런 메시지가 나오면 재연결 없이
    원본 예외를 재전파해야 한다(연결 leak 없이 정리).
    """
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    before = set(_live_worker_threads())
    connect_count = {"n": 0}
    real_connect = aiosqlite.connect

    def _count_connect(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        connect_count["n"] += 1
        return real_connect(*args, **kwargs)

    async def _probe_no_such_table(conn):  # noqa: ANN001, ANN202
        raise sqlite3.OperationalError("no such table: backtest_runs")

    ro = Database(db_path, read_only=True)
    with (
        patch.object(Database, "_probe_ro_conn", staticmethod(_probe_no_such_table)),
        patch("ante.core.database.aiosqlite.connect", side_effect=_count_connect),
    ):
        with pytest.raises(sqlite3.OperationalError, match="no such table"):
            await ro.connect()

    # fallback 재연결이 일어나지 않았어야 한다(연결 1회만).
    assert connect_count["n"] == 1, connect_count
    # 실패한 연결의 worker thread 가 leak 되지 않아야 한다(#1965 보존).
    leaked = set(_live_worker_threads()) - before
    assert not leaked, f"no-such-table 재전파 후 worker thread 누수: {leaked}"


async def test_read_only_malformed_not_fallback(tmp_path):
    """probe 가 ``database disk image is malformed`` 면 fallback 하지 않고 재전파."""
    db_path = str(tmp_path / "ro.db")
    await _seed_rw_db(db_path)

    connect_count = {"n": 0}
    real_connect = aiosqlite.connect

    def _count_connect(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        connect_count["n"] += 1
        return real_connect(*args, **kwargs)

    async def _probe_malformed(conn):  # noqa: ANN001, ANN202
        raise sqlite3.OperationalError("database disk image is malformed")

    ro = Database(db_path, read_only=True)
    with (
        patch.object(Database, "_probe_ro_conn", staticmethod(_probe_malformed)),
        patch("ante.core.database.aiosqlite.connect", side_effect=_count_connect),
    ):
        with pytest.raises(sqlite3.OperationalError, match="malformed"):
            await ro.connect()

    assert connect_count["n"] == 1, connect_count


async def test_read_only_connect_failure_drains_worker_thread(tmp_path):
    """ro 연결 자체가 실패해도 aiosqlite worker thread 가 누수되지 않는다(#1965)."""
    bad_path = str(tmp_path / "no-such-dir" / "ro.db")
    ro = Database(bad_path, read_only=True)

    before = set(_live_worker_threads())
    with pytest.raises(Exception, match="unable to open database file"):
        await ro.connect()

    leaked = set(_live_worker_threads()) - before
    assert not leaked, f"ro connect 실패 후 worker thread 누수: {leaked} (#1965)"


# --- writer 태스크 간 직렬화 + 트랜잭션 owner 추적 (#2365) ---
#
# 같은 writer 연결을 여러 asyncio 태스크가 공유할 때, ``execute*()`` 의
# implicit BEGIN(``conn.execute(sql)``)과 ``conn.commit()`` 사이 await 경계에서
# 태스크가 전환되면, 다른 태스크의 ``transaction()`` 이 이미 열린 SQLite
# 트랜잭션 위에서 ``BEGIN`` 을 실행해 ``cannot start a transaction within a
# transaction`` 으로 실패한다(race A). 역방향(race B)에서는 standalone
# ``execute()`` 가 진행 중인 트랜잭션에 합류해 무관한 쓰기가 rollback 으로
# 소실된다. 아래 테스트는 commit 지점을 ``asyncio.Event`` barrier 로 결정적으로
# 고정해 두 race 를 재현한다(stress 비사용).


def _install_commit_barrier(db):
    """writer 연결의 ``commit()`` 을 asyncio.Event barrier 로 가로챈다.

    반환된 ``released`` Event 를 set 하기 전까지 ``commit()`` 호출은
    ``reached`` Event 를 set 한 뒤 대기한다. 이로써 자동커밋 ``execute()`` 를
    "``execute`` 완료 후 ``commit`` 직전" 윈도우에 결정적으로 고정할 수 있다.
    원래 ``commit`` 은 ``released`` 후 정상 실행된다.
    """
    writer = db._get_writer()
    real_commit = writer.commit
    reached = asyncio.Event()
    released = asyncio.Event()

    async def gated_commit(*args, **kwargs):
        reached.set()
        await released.wait()
        return await real_commit(*args, **kwargs)

    patcher = patch.object(writer, "commit", side_effect=gated_commit)
    patcher.start()
    return reached, released, patcher


async def test_concurrent_autocommit_then_transaction_race_a(db):
    """race A: 태스크1 자동커밋 write 가 commit 직전 고정된 윈도우에서 태스크2가
    ``transaction()`` 을 진입해도 중첩 트랜잭션 오류 없이 성공하고, 태스크1의
    write 도 보존된다.

    수정 전(main): 태스크2 ``transaction()`` 의 ``BEGIN`` 이 태스크1이 연
    implicit 트랜잭션 위에서 실행돼 ``sqlite3.OperationalError: cannot start a
    transaction within a transaction`` (a 실패), 그리고 ``transaction()`` 의
    BaseException ROLLBACK 이 태스크1의 implicit write 를 되돌려 소실(b 실패) →
    둘 다 RED.
    """
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    reached, released, patcher = _install_commit_barrier(db)
    try:
        # 태스크1: 자동커밋 INSERT — execute 완료 후 commit 직전에서 고정된다.
        task1 = asyncio.create_task(
            db.execute("INSERT INTO t (id, val) VALUES (1, 'task1')")
        )
        # 태스크1 이 commit barrier 에 도달할 때까지 대기.
        await asyncio.wait_for(reached.wait(), timeout=5.0)

        # 윈도우 안에서 태스크2 가 transaction() 진입 (내부 write 포함).
        async def task2_body():
            async with db.transaction():
                await db.execute("INSERT INTO t (id, val) VALUES (2, 'task2')")

        task2 = asyncio.create_task(task2_body())

        # 태스크2 가 lock 대기(또는 실패)에 도달할 시간을 준 뒤 barrier 해제.
        await asyncio.sleep(0.05)
        released.set()

        # (a) 태스크2 트랜잭션이 예외 없이 성공해야 한다.
        await asyncio.wait_for(task2, timeout=5.0)
        await asyncio.wait_for(task1, timeout=5.0)
    finally:
        patcher.stop()

    # (a) 태스크2 행 커밋 + (b) 태스크1 write 보존.
    rows = await db.fetch_all("SELECT id, val FROM t ORDER BY id")
    assert [(r["id"], r["val"]) for r in rows] == [(1, "task1"), (2, "task2")]


async def test_concurrent_transaction_then_autocommit_race_b(db):
    """race B: 태스크1 ``transaction()`` 진행 중 태스크2 standalone ``execute()`` 가
    트랜잭션에 합류하지 않고 독립 커밋되며, 태스크1 rollback 시 태스크1 행만
    소실된다.

    수정 전(main): 태스크2 ``execute()`` 가 ``_in_transaction`` 플래그를 보고
    commit 을 skip → 태스크1 트랜잭션에 합류 → 태스크1 rollback 으로 태스크2
    행까지 소실(RED).
    """
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    task2_may_start = asyncio.Event()
    task2_inserted = asyncio.Event()

    async def task1_body():
        with pytest.raises(ValueError, match="의도적 예외"):
            async with db.transaction():
                await db.execute("INSERT INTO t (id, val) VALUES (1, 'task1')")
                # 태스크2 가 standalone execute 를 시도하도록 양보.
                task2_may_start.set()
                await asyncio.wait_for(task2_inserted.wait(), timeout=5.0)
                raise ValueError("의도적 예외")

    async def task2_body():
        await asyncio.wait_for(task2_may_start.wait(), timeout=5.0)
        # owner 태스크가 아니므로 transaction 합류 금지 → lock 대기 후 독립 커밋.
        # owner 트랜잭션이 lock 을 쥐고 있으므로 task1 이 commit/rollback 으로
        # lock 을 놓을 때까지 여기서 대기한다(교착 없음 — task1 은 task2 완료를
        # 직접 await 하지 않고 Event 로만 동기화).
        insert = asyncio.create_task(
            db.execute("INSERT INTO t (id, val) VALUES (2, 'task2')")
        )
        # task1 이 rollback 으로 진행하도록 신호.
        task2_inserted.set()
        await asyncio.wait_for(insert, timeout=5.0)

    await asyncio.gather(task1_body(), task2_body())

    # 태스크2 행만 커밋 유지, 태스크1 행은 rollback 으로 소실.
    rows = await db.fetch_all("SELECT id, val FROM t ORDER BY id")
    assert [(r["id"], r["val"]) for r in rows] == [(2, "task2")]


async def test_autocommit_cancel_leaves_no_open_transaction(db):
    """자동커밋 ``execute()`` 가 commit 대기 중 cancel 돼도 implicit 트랜잭션이
    잔존하지 않아 이후 ``transaction()`` 이 정상 동작한다(#2365)."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    reached, released, patcher = _install_commit_barrier(db)
    try:
        task1 = asyncio.create_task(
            db.execute("INSERT INTO t (id, val) VALUES (1, 'task1')")
        )
        await asyncio.wait_for(reached.wait(), timeout=5.0)
        # execute 완료 후 commit 대기 중에 cancel.
        task1.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task1
    finally:
        # barrier 를 풀어 cleanup ROLLBACK(또는 commit) 이 진행되도록 한다.
        released.set()
        patcher.stop()

    # implicit 트랜잭션 잔존이 없어야 — 새 transaction() 이 BEGIN 에서 실패하면 안 됨.
    async with db.transaction():
        await db.execute("INSERT INTO t (id, val) VALUES (2, 'after')")
    rows = await db.fetch_all("SELECT id, val FROM t ORDER BY id")
    assert [(r["id"], r["val"]) for r in rows] == [(2, "after")]


async def test_double_cancel_during_commit_and_rollback_releases_lock(db):
    """``transaction()`` COMMIT 대기 중 cancel → cleanup ROLLBACK 대기 중 재-cancel
    해도 lock 이 해제되고 다음 ``transaction()``/``execute()`` 가 정상 동작한다
    (enqueue-before-release invariant 검증, #2365 r2-②)."""
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    writer = db._get_writer()
    real_execute = writer.execute
    commit_reached = asyncio.Event()
    rollback_reached = asyncio.Event()
    release_commit = asyncio.Event()
    release_rollback = asyncio.Event()

    async def gated_execute(sql, *args, **kwargs):
        upper = sql.strip().upper()
        if upper.startswith("COMMIT"):
            # COMMIT 은 enqueue 전 barrier — 1차 cancel 이 COMMIT 결과 대기를
            # abandon 하게 한다(자동커밋 race 와 동형).
            commit_reached.set()
            await release_commit.wait()
            return await real_execute(sql, *args, **kwargs)
        if upper.startswith("ROLLBACK"):
            # enqueue-before-release invariant 충실 재현: cleanup ROLLBACK 은
            # real_execute 로 **먼저 실행(enqueue+settle)** 한 뒤 barrier 로
            # 추가 대기한다. 그래야 2차 cancel 이 "ROLLBACK 이 worker FIFO 에
            # 들어가 settle 된 후 결과 후처리 대기만 abandon" 하는 실제 코드의
            # invariant 와 동형이 된다(release 전에 cancel 해 enqueue 자체를
            # 막으면 프록시가 실제 조건을 왜곡 — 금지).
            result = await real_execute(sql, *args, **kwargs)
            rollback_reached.set()
            await release_rollback.wait()
            return result
        return await real_execute(sql, *args, **kwargs)

    async def txn_body():
        async with db.transaction():
            await db.execute("INSERT INTO t (id, val) VALUES (1, 'x')")

    with patch.object(writer, "execute", side_effect=gated_execute):
        task = asyncio.create_task(txn_body())
        # COMMIT 대기 진입까지 대기 후 1차 cancel.
        await asyncio.wait_for(commit_reached.wait(), timeout=5.0)
        task.cancel()
        # cancel 이 COMMIT await 에 전달돼 cleanup ROLLBACK 으로 진입할 시간을 준다.
        release_commit.set()
        # cleanup ROLLBACK 대기 진입까지 대기 후 2차 cancel.
        await asyncio.wait_for(rollback_reached.wait(), timeout=5.0)
        task.cancel()
        release_rollback.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    # lock 이 해제되어 다음 트랜잭션/자동커밋이 정상 동작해야 한다.
    async with db.transaction():
        await db.execute("INSERT INTO t (id, val) VALUES (2, 'next')")
    await db.execute("INSERT INTO t (id, val) VALUES (3, 'auto')")
    rows = await db.fetch_all("SELECT id FROM t ORDER BY id")
    assert [r["id"] for r in rows] == [2, 3]


async def test_child_task_execute_does_not_join_owner_transaction(db):
    """owner ``transaction()`` 블록 안에서 생성된 child task 의 ``execute()`` 는
    owner 트랜잭션에 합류하지 않고 lock 대기 → owner commit 후 독립 커밋된다.

    owner 는 child 완료를 블록 안에서 직접 await 하지 않는다(교착 경로는 문서
    invariant 로 금지). owner 가 commit 으로 lock 을 놓은 뒤 child 가 커밋된다.
    """
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT);")

    child: asyncio.Task | None = None

    async with db.transaction():
        await db.execute("INSERT INTO t (id, val) VALUES (1, 'owner')")
        # child task 는 별도 태스크 → owner 가 아니므로 lock 대기.
        child = asyncio.create_task(
            db.execute("INSERT INTO t (id, val) VALUES (2, 'child')")
        )
        # owner 는 child 완료를 직접 await 하지 않는다(교착 방지). child 가 lock
        # 대기 상태에 도달하도록 잠깐 양보만 한다.
        await asyncio.sleep(0.05)
        # child 는 아직 commit 되지 않았어야 한다(owner 가 lock 보유).
        assert not child.done()

    # owner commit 으로 lock 해제 → child 가 독립 커밋.
    await asyncio.wait_for(child, timeout=5.0)
    rows = await db.fetch_all("SELECT id, val FROM t ORDER BY id")
    assert [(r["id"], r["val"]) for r in rows] == [(1, "owner"), (2, "child")]


async def test_execute_script_inside_transaction_raises(db):
    """``transaction()`` owner 태스크가 ``execute_script()`` 를 호출하면 RuntimeError.

    Python ``executescript`` 의 암묵 COMMIT 이 열린 트랜잭션을 임의 커밋하는
    사고를 차단한다(schema/lifecycle 전용).
    """
    await db.execute_script("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    async with db.transaction():
        with pytest.raises(RuntimeError, match="트랜잭션 안에서는"):
            await db.execute_script("CREATE TABLE t2 (id INTEGER)")


async def test_execute_script_outside_transaction_still_works(db):
    """트랜잭션 밖에서는 ``execute_script()`` 가 기존대로 동작한다."""
    await db.execute_script("CREATE TABLE t3 (id INTEGER PRIMARY KEY, v TEXT);")
    await db.execute("INSERT INTO t3 (v) VALUES ('ok')")
    row = await db.fetch_one("SELECT v FROM t3")
    assert row is not None
    assert row["v"] == "ok"
