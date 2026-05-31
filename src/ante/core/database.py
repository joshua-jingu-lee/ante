"""SQLite WAL 모드 비동기 래퍼."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite

logger = logging.getLogger(__name__)


class Database:
    """SQLite WAL 모드 비동기 래퍼. 모든 모듈이 공유."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
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

    async def connect(self) -> None:
        """DB 연결 초기화. writer + reader 두 연결 생성.

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
