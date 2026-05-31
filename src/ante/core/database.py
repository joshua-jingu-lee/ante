"""SQLite WAL 모드 비동기 래퍼."""

import asyncio
import logging
import sqlite3
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)

# read-only(``mode=ro``) probe(``PRAGMA schema_version``) 가 아래 메시지 계열
# ``sqlite3.OperationalError`` 로 실패하면 ``immutable=1`` 로 재연결 fallback 한다
# (offline-factory.md §2 옵션 A). WAL DB 를 실제 read-only 파일시스템에서 ro 로
# 열면 SQLite 가 ``-wal``/``-shm`` 을 생성/쓰기 시도하다 실패하는데, 그 표면
# 메시지는 환경(권한·잔여 WAL artifact)에 따라 아래 중 하나로 나타난다.
#
# 반대로 ``no such table`` (테이블 부재 — query 시점에 발생, connect probe 단계
# 아님), ``database disk image is malformed``, ``file is not a database`` 는
# 데이터 무결성/스키마 문제이지 WAL/권한 문제가 아니므로 fallback 하지 않고
# 재전파한다(blanket OperationalError fallback 금지 — 메시지 allowlist 로만 좁힘).
_RO_IMMUTABLE_FALLBACK_SIGNATURES: tuple[str, ...] = (
    "attempt to write a readonly database",
    "unable to open database file",
    "disk i/o error",
    "-wal",
    "-shm",
)


def _is_ro_fallback_error(exc: sqlite3.OperationalError) -> bool:
    """probe 실패가 ``immutable=1`` fallback 대상(WAL/권한 계열)인지 판별한다."""
    message = str(exc).lower()
    return any(sig in message for sig in _RO_IMMUTABLE_FALLBACK_SIGNATURES)


class ReadOnlyDatabaseError(RuntimeError):
    """read-only ``Database`` 에서 write 연산을 시도했을 때 발생한다.

    ``read_only=True`` 로 생성된 ``Database`` 는 writer 연결을 열지 않으므로
    ``execute``/``execute_script``/``execute_fetch_*``/``transaction`` 등 writer
    경로를 호출하면 "연결되지 않음"이 아니라 본 예외로 명확히 실패한다
    (offline-factory.md §2 옵션 A).
    """


class Database:
    """SQLite WAL 모드 비동기 래퍼. 모든 모듈이 공유.

    기본(``read_only=False``)은 writer + reader 두 연결을 열고 WAL 모드를
    설정한다(기존 baseline). ``read_only=True``는 reader 단일 연결만 SQLite
    ``file:...?mode=ro`` URI 로 열어 schema/WAL 쓰기 없이 기존 DB 를 읽는다
    (offline-factory.md §2 옵션 A). read-only 모드는 기존 스키마를 부트스트랩
    없이 읽는 offline read 명령(현재 ``backtest history``)에만 적용된다.
    """

    def __init__(self, db_path: str, *, read_only: bool = False) -> None:
        self._db_path = db_path
        self._read_only = read_only
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._in_transaction: bool = False

    @staticmethod
    async def _drain_failed_conn(conn: aiosqlite.Connection) -> None:
        """실패한 aiosqlite 연결의 background worker thread를 결정적으로 정리한다.

        근본 배경(#1965): ``await aiosqlite.connect(...)`` 의 ``__await__`` 는
        먼저 worker thread를 ``start()`` 한 뒤 실제 ``sqlite3.connect`` 를 큐에
        넣는다. 파일을 열 수 없으면(예: ``unable to open database file``)
        aiosqlite 의 ``_connect`` 가 내부적으로 ``stop()`` 을 호출해 종료
        sentinel을 큐에 넣지만, 그 **future를 폐기**하고 예외를 재전파한다.
        따라서 worker thread는 (스스로 곧 종료하긴 하나) 호출자 쪽에서 종료를
        **동기화할 수단이 없다**. 이 상태로 ``asyncio.run`` 이 이벤트 루프를
        먼저 닫으면, worker thread가 닫힌 루프에 ``call_soon_threadsafe`` 를
        시도해 stderr에 ``RuntimeError: Event loop is closed`` traceback이
        남는다(``--format json`` stderr 청결 계약 위반).

        정리 전략:

        1. ``conn.close()`` — 연결이 실제로 열렸던 경우(PRAGMA 단계 실패 등)
           내부 종료 future를 await 해 worker를 비운다. 연결이 안 열렸으면
           (``_connection is None``) no-op으로 빠르게 반환한다.
        2. 그래도 thread가 살아 있으면(=connect 자체 실패로 future가 폐기된
           경우), 그 thread를 이벤트 루프 밖(executor)에서 ``join`` 해 루프
           teardown **이전**에 worker가 확실히 종료하도록 동기화한다.

        ``_thread`` 접근은 aiosqlite 내부 구현에 의존하지만, 모두 ``getattr``
        방어로 감싸 향후 구현이 바뀌어도 graceful degrade(예외 없이 best-effort)
        하도록 한다. 어떤 단계의 예외든 swallow하여 호출자에게는 원본 connect
        예외만 surface한다.
        """
        try:
            await conn.close()
        except Exception:
            logger.debug("aiosqlite close() on failed connect raised", exc_info=True)

        thread = getattr(conn, "_thread", None)
        if thread is None:
            return
        try:
            if thread.is_alive():
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, thread.join, 5.0)
        except Exception:
            logger.debug("joining aiosqlite worker thread raised", exc_info=True)

    async def _init_conn(self) -> aiosqlite.Connection:
        """공통 PRAGMA 설정으로 연결 초기화.

        ``aiosqlite.connect`` 의 ``await`` 또는 이후 PRAGMA 단계가 실패하면,
        이미 ``start()`` 된 worker thread가 leak된다(``connect()`` 가
        ``self._writer``/``self._reader`` 에 할당하기 **전**에 raise되므로
        ``Database.close()`` 로도 회수할 수 없다). 이 경우 :meth:`_drain_failed_conn`
        으로 worker thread를 결정적으로 정리한 뒤 원본 예외를 재전파한다(#1965).

        ``aiosqlite.connect(...)`` 는 ``await`` 전에 ``Connection`` 객체를
        반환하므로, ``await`` 자체가 실패하더라도 그 객체 핸들을 잡아 thread를
        정리할 수 있도록 ``await`` 를 객체 생성과 분리한다.
        """
        conn = aiosqlite.connect(self._db_path)
        try:
            await conn
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute("PRAGMA synchronous=NORMAL")
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = aiosqlite.Row
        except BaseException:
            await self._drain_failed_conn(conn)
            raise
        return conn

    def _ro_uri(self, *, immutable: bool) -> str:
        """read-only SQLite URI 를 생성한다.

        절대경로를 ``urllib.request.pathname2url`` 로 escape 해 공백/특수문자/
        Windows drive 문자를 안전하게 처리한다(f-string 직접 보간 금지). 본
        URI 는 ``aiosqlite.connect(..., uri=True)`` 로만 열어야 한다 — ``uri``
        플래그가 없으면 ``mode=ro``/``immutable=1`` 쿼리스트링이 리터럴 파일명의
        일부로 취급된다.

        ``immutable=1`` 은 read-only artifact 전용이다(live 동시쓰기 DB 비대상).
        WAL DB 를 실제 read-only 파일시스템에서 ``mode=ro`` 만으로 열면 SQLite 가
        ``-wal``/``-shm`` 를 생성/쓰기하려다 실패하므로, immutable fallback 으로
        DB 파일을 변경 불가 스냅샷으로 간주해 sidecar 없이 read 한다.
        """
        url = urllib.request.pathname2url(self._db_path)
        query = "mode=ro&immutable=1" if immutable else "mode=ro"
        return f"file:{url}?{query}"

    async def _init_ro_conn(self) -> aiosqlite.Connection:
        """read-only(``mode=ro``) 연결을 초기화한다(쓰기 PRAGMA skip).

        ``mode=ro`` 로 연결한 직후 ``PRAGMA schema_version`` probe read 를
        수행한다. WAL artifact/권한 계열 ``sqlite3.OperationalError`` 로 probe 가
        실패하면(:func:`_is_ro_fallback_error`) ``immutable=1`` 로 재연결한다.
        그 외(예: ``no such table`` — query 시점 발생, ``malformed`` 등)는
        재전파한다.

        쓰기 PRAGMA(``journal_mode=WAL``/``synchronous=NORMAL``)는 read-only 파일
        시스템에서 실패하므로 발화하지 않고, ``foreign_keys``/``busy_timeout``/
        ``temp_store``/``row_factory`` 만 적용한다.

        연결 실패 시 :meth:`_init_conn` 과 동일하게 :meth:`_drain_failed_conn`
        으로 worker thread 를 결정적으로 정리한다(#1965/#1970).
        """
        conn = await self._open_ro_conn(immutable=False)
        try:
            await self._probe_ro_conn(conn)
        except sqlite3.OperationalError as exc:
            if not _is_ro_fallback_error(exc):
                # no such table / malformed / not a database 등은 fallback 대상이
                # 아니다 — 연결을 정리하고 원본 예외를 재전파한다.
                await self._drain_failed_conn(conn)
                raise
            logger.debug(
                "read-only mode=ro probe 실패 — immutable=1 fallback 재연결: %s",
                exc,
            )
            await self._drain_failed_conn(conn)
            conn = await self._open_ro_conn(immutable=True)
            try:
                await self._probe_ro_conn(conn)
            except BaseException:
                await self._drain_failed_conn(conn)
                raise
        except BaseException:
            await self._drain_failed_conn(conn)
            raise
        return conn

    async def _open_ro_conn(self, *, immutable: bool) -> aiosqlite.Connection:
        """``mode=ro``(또는 ``immutable=1``) URI 로 연결하고 read-only PRAGMA 적용."""
        uri = self._ro_uri(immutable=immutable)
        conn = aiosqlite.connect(uri, uri=True)
        try:
            await conn
            await conn.execute("PRAGMA temp_store=MEMORY")
            await conn.execute("PRAGMA foreign_keys=ON")
            await conn.execute("PRAGMA busy_timeout=5000")
            conn.row_factory = aiosqlite.Row
        except BaseException:
            await self._drain_failed_conn(conn)
            raise
        return conn

    @staticmethod
    async def _probe_ro_conn(conn: aiosqlite.Connection) -> None:
        """최소 probe read(``PRAGMA schema_version``)로 ro 연결 가독성을 확인."""
        async with conn.execute("PRAGMA schema_version") as cursor:
            await cursor.fetchone()

    async def connect(self) -> None:
        """DB 연결 초기화.

        ``read_only=True`` 면 reader 단일 ``mode=ro`` 연결만 열고 ``_writer`` 는
        미개방한다(write 경로는 :class:`ReadOnlyDatabaseError`). probe/fallback
        실패 시에도 :meth:`_init_ro_conn` 이 worker thread 를 drain 하므로 leak
        없이 정리된다(#1965/#1970).

        ``read_only=False`` 면 기존 baseline 그대로 writer + reader 두 연결을
        생성한다(아래 docstring 의 partial-failure drain 보존).

        어느 한쪽 연결이라도 실패하면 이미 열린 연결(writer)을 worker thread
        join 까지 포함해 **결정적으로 drain** 한 뒤 원본 예외를 재전파한다.
        ``connect()`` 가 부분적으로 성공한 상태(예: writer만 열림)에서 raise되면
        호출자가 받은 ``Database`` 핸들에 leak된 aiosqlite worker thread가 남아,
        ``asyncio.run`` 종료 시 닫힌 이벤트 루프를 건드려 stderr noise를
        유발하기 때문이다(#1965).

        주의(#1970): 일반 ``close()`` 는 ``await conn.close()`` 만 호출하는데
        aiosqlite ``Connection.close()`` 는 worker thread 루프에 종료
        신호(``_running=False``)만 보내고 **``thread.join`` 을 하지 않는다**.
        따라서 ``close()`` 반환 직후에도 worker ``_connection_worker_thread`` 가
        아직 종료 중일 수 있다. partial-failure 정리에서 ``close()`` 만 쓰면
        thread teardown 이 느린 환경(Linux CI)에서 "정리 직후 leak 없음" 단언이
        타이밍 의존으로 간헐 실패한다. 이를 막기 위해 여기서는 이미 할당된
        연결을 :meth:`_drain_failed_conn` (close + ``thread.join``)으로 정리해
        반환 시점에 worker thread leak 이 없음을 결정적으로 보장한다.

        ``_init_conn`` 이 raise하는 경우(예: 첫 writer 연결 실패) 해당 연결의
        worker thread는 ``_init_conn`` 내부에서 이미 drain되며, 여기서는 이미
        할당된 ``self._writer`` (reader 실패 시) 만 drain한다. join 은
        bounded(5s) + 예외 swallow 이므로 원본 connect 예외를 가리거나 hang
        하지 않는다.
        """
        if self._read_only:
            # reader 단일 mode=ro 연결만. probe/fallback 실패 시 _init_ro_conn 이
            # 이미 worker thread 를 drain 하므로 여기서 추가 정리는 불필요하다.
            self._reader = await self._init_ro_conn()
            return
        try:
            self._writer = await self._init_conn()
            self._reader = await self._init_conn()
        except BaseException:
            for conn in (self._writer, self._reader):
                if conn is not None:
                    await self._drain_failed_conn(conn)
            self._writer = self._reader = None
            raise

    async def close(self) -> None:
        """연결 종료."""
        for conn in (self._writer, self._reader):
            if conn:
                await conn.close()
        self._writer = self._reader = None

    def _get_writer(self) -> aiosqlite.Connection:
        if self._read_only:
            raise ReadOnlyDatabaseError(
                "read-only Database: write operation not permitted "
                "(read_only=True 로 생성된 연결은 writer 가 없습니다)"
            )
        if not self._writer:
            raise RuntimeError("DB 연결되지 않음. connect()를 먼저 호출하세요.")
        return self._writer

    def _get_reader(self) -> aiosqlite.Connection:
        if not self._reader:
            raise RuntimeError("DB 연결되지 않음. connect()를 먼저 호출하세요.")
        return self._reader

    async def execute(self, sql: str, params: tuple = ()) -> None:
        """INSERT/UPDATE/DELETE 실행."""
        conn = self._get_writer()
        await conn.execute(sql, params)
        if not self._in_transaction:
            await conn.commit()

    async def fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """단일 행 조회. dict(컬럼명 → 값) 반환."""
        conn = self._get_reader()
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def execute_fetch_one(self, sql: str, params: tuple = ()) -> dict | None:
        """writer 연결에서 실행 후 단일 행을 반환 (RETURNING 등 atomic 패턴용).

        ``execute`` 와 동일하게 **writer 연결**에서 실행하므로, 진행 중인
        ``transaction()`` 의 미커밋 변경을 같은 트랜잭션 안에서 일관되게
        관측한다. reader 연결을 쓰는 ``fetch_one`` 은 WAL 격리로 인해 진행
        중인 writer 트랜잭션의 uncommitted row를 보지 못하므로, CAS 후
        ``RETURNING`` 으로 결과를 원자적으로 읽어야 하는 경로는 이 메서드를
        쓴다. ``_in_transaction`` 이 아니면 ``execute`` 와 동일하게 commit한다.
        """
        conn = self._get_writer()
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            result = dict(row) if row else None
        if not self._in_transaction:
            await conn.commit()
        return result

    async def execute_fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """writer 연결에서 실행 후 다중 행을 반환 (다건 RETURNING 등 atomic 패턴용).

        ``execute_fetch_one`` 의 다건 버전. ``execute`` 와 동일하게 **writer
        연결**에서 단일 호출로 실행하므로, 한 번의 UPDATE/DELETE ... RETURNING 으로
        실제 영향받은 행들을 원자적으로 받는다(읽기↔쓰기 분리 race 없음). reader
        연결을 쓰는 ``fetch_all`` 은 진행 중인 writer 트랜잭션의 uncommitted row 를
        보지 못하므로, 영향 행 집합을 RETURNING 으로 받아야 하는 경로는 이 메서드를
        쓴다. ``_in_transaction`` 이 아니면 ``execute`` 와 동일하게 commit한다.
        """
        conn = self._get_writer()
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            result = [dict(row) for row in rows]
        if not self._in_transaction:
            await conn.commit()
        return result

    async def fetch_all(self, sql: str, params: tuple = ()) -> list[dict]:
        """다중 행 조회."""
        conn = self._get_reader()
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def execute_script(self, sql: str) -> None:
        """DDL 스크립트 실행 (테이블 생성 등)."""
        conn = self._get_writer()
        await conn.executescript(sql)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Database"]:
        """트랜잭션 컨텍스트 매니저.

        asyncio.CancelledError / KeyboardInterrupt / SystemExit 포함 모든
        BaseException 경로에서 ROLLBACK을 시도한 뒤 원본 예외를 재전파한다.
        ROLLBACK 자체 실패는 swallow하여 원본 예외(특히 CancelledError) 보존을
        우선한다.

        nested transaction은 지원하지 않는다. savepoint는 본 구현 범위 외.
        """
        if self._in_transaction:
            raise RuntimeError("중첩 트랜잭션은 지원하지 않습니다")
        conn = self._get_writer()
        self._in_transaction = True
        try:
            await conn.execute("BEGIN")
            yield self
            await conn.execute("COMMIT")
        except BaseException:
            try:
                await conn.execute("ROLLBACK")
            except BaseException:
                # rollback 실패도 swallow — 원본 예외 보존이 우선
                pass
            raise
        finally:
            self._in_transaction = False
