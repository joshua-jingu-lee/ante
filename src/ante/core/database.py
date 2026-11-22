"""SQLite WAL 모드 비동기 래퍼."""

import asyncio
import logging
import sqlite3
import urllib.request
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite

logger = logging.getLogger(__name__)

OperationalError = sqlite3.OperationalError
DatabaseError = sqlite3.DatabaseError

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
    없이 읽는 offline read 명령(현재 ``backtest history``, ``data list``
    의 종목명 보강, ``report list``/``report view``)에만
    적용된다.
    """

    def __init__(self, db_path: str, *, read_only: bool = False) -> None:
        self._db_path = db_path
        self._read_only = read_only
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()
        self._txn_owner: asyncio.Task[Any] | None = None

    @property
    def _in_transaction(self) -> bool:
        """현재 호출 태스크가 트랜잭션 owner 인지(같은 태스크 합류 판정)."""
        owner = self._txn_owner
        return owner is not None and owner is asyncio.current_task()

    @staticmethod
    async def _drain_failed_conn(conn: aiosqlite.Connection) -> None:
        """실패한 aiosqlite 연결의 background worker thread를 결정적으로 정리한다."""
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
        """공통 PRAGMA 설정으로 연결 초기화."""
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
        """read-only SQLite URI 를 생성한다."""
        url = urllib.request.pathname2url(self._db_path)
        query = "mode=ro&immutable=1" if immutable else "mode=ro"
        return f"file:{url}?{query}"

    async def _init_ro_conn(self) -> aiosqlite.Connection:
        """read-only(``mode=ro``) 연결을 초기화한다(쓰기 PRAGMA skip)."""
        conn = await self._open_ro_conn(immutable=False)
        try:
            await self._probe_ro_conn(conn)
        except sqlite3.OperationalError as exc:
            if not _is_ro_fallback_error(exc):
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

        어느 한쪽 연결이라도 실패하면 이미 열린 연결(writer)을 worker thread
        join 까지 포함해 **결정적으로 drain** 한 뒤 원본 예외를 재전파한다.
        ``connect()`` 가 부분적으로 성공한 상태(예: writer만 열림)에서 raise되면
        호출자가 받은 ``Database`` 핸들에 leak된 aiosqlite worker thread가 남아,
        ``asyncio.run`` 종료 시 닫힌 이벤트 루프를 건드려 stderr noise를
        유발하기 때문이다.
        """
        if self._read_only:
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

    @staticmethod
    async def _best_effort_rollback(conn: aiosqlite.Connection) -> None:
        """non-owner 자동커밋 경로의 cleanup ROLLBACK(best-effort)."""
        try:
            await conn.execute("ROLLBACK")
        except BaseException:
            pass

    async def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        """INSERT/UPDATE/DELETE 실행.

        현재 태스크가 트랜잭션 owner 면 lock 없이 인라인 실행 + commit skip
        (같은 태스크 트랜잭션 합류). 아니면 ``_write_lock`` 안에서 실행 후
        독립 commit 한다(태스크 간 직렬화).
        """
        conn = self._get_writer()
        if self._in_transaction:
            await conn.execute(sql, params)
            return
        async with self._write_lock:
            try:
                await conn.execute(sql, params)
                await conn.commit()
            except BaseException:
                await self._best_effort_rollback(conn)
                raise

    async def fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        """단일 행 조회. dict(컬럼명 → 값) 반환."""
        conn = self._get_reader()
        async with conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def execute_fetch_one(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> dict[str, Any] | None:
        """writer 연결에서 실행 후 단일 행을 반환 (RETURNING 등 atomic 패턴용).

        ``execute`` 와 동일하게 **writer 연결**에서 실행하므로, 진행 중인
        ``transaction()`` 의 미커밋 변경을 같은 트랜잭션 안에서 일관되게
        관측한다. reader 연결을 쓰는 ``fetch_one`` 은 WAL 격리로 인해 진행
        중인 writer 트랜잭션의 uncommitted row를 보지 못하므로, CAS 후
        ``RETURNING`` 으로 결과를 원자적으로 읽어야 하는 경로는 이 메서드를
        쓴다. ``_in_transaction`` 이 아니면 ``execute`` 와 동일하게 commit한다.
        """
        conn = self._get_writer()
        if self._in_transaction:
            async with conn.execute(sql, params) as cursor:
                row = await cursor.fetchone()
                return dict(row) if row else None
        async with self._write_lock:
            try:
                async with conn.execute(sql, params) as cursor:
                    row = await cursor.fetchone()
                    result = dict(row) if row else None
                await conn.commit()
            except BaseException:
                await self._best_effort_rollback(conn)
                raise
        return result

    async def execute_fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """writer 연결에서 실행 후 다중 행을 반환 (다건 RETURNING 등 atomic 패턴용).

        ``execute_fetch_one`` 의 다건 버전. ``execute`` 와 동일하게 **writer
        연결**에서 단일 호출로 실행하므로, 한 번의 UPDATE/DELETE ... RETURNING 으로
        실제 영향받은 행들을 원자적으로 받는다(읽기↔쓰기 분리 race 없음). reader
        연결을 쓰는 ``fetch_all`` 은 진행 중인 writer 트랜잭션의 uncommitted row 를
        보지 못하므로, 영향 행 집합을 RETURNING 으로 받아야 하는 경로는 이 메서드를
        쓴다. ``_in_transaction`` 이 아니면 ``execute`` 와 동일하게 commit한다.
        """
        conn = self._get_writer()
        if self._in_transaction:
            async with conn.execute(sql, params) as cursor:
                rows = await cursor.fetchall()
                return [dict(row) for row in rows]
        async with self._write_lock:
            try:
                async with conn.execute(sql, params) as cursor:
                    rows = await cursor.fetchall()
                    result = [dict(row) for row in rows]
                await conn.commit()
            except BaseException:
                await self._best_effort_rollback(conn)
                raise
        return result

    async def fetch_all(
        self, sql: str, params: tuple[Any, ...] = ()
    ) -> list[dict[str, Any]]:
        """다중 행 조회."""
        conn = self._get_reader()
        async with conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def execute_script(self, sql: str) -> None:
        """DDL 스크립트 실행 (schema/lifecycle 전용 — 테이블 생성 등).

        **트랜잭션 안에서 호출 금지**: Python ``executescript`` 는 실행 전에
        열린 트랜잭션을 암묵 COMMIT 하므로, ``transaction()`` owner 태스크가
        호출하면 진행 중인 트랜잭션을 의도치 않게 커밋해 원자성을 깨뜨린다.

        non-owner(트랜잭션 밖) 호출은 ``_write_lock`` 안에서 실행한다(태스크 간
        직렬화). ``executescript`` 자체가 암묵 COMMIT 으로 끝나므로 별도
        ``conn.commit()`` 는 하지 않는다(기존 시맨틱 유지).
        """
        if self._in_transaction:
            raise RuntimeError(
                "트랜잭션 안에서는 execute_script 를 호출할 수 없습니다 "
                "(executescript 의 암묵 COMMIT 이 열린 트랜잭션을 깨뜨립니다)"
            )
        conn = self._get_writer()
        async with self._write_lock:
            await conn.executescript(sql)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator["Database"]:
        """트랜잭션 컨텍스트 매니저.

        asyncio.CancelledError / KeyboardInterrupt / SystemExit 포함 모든
        BaseException 경로에서 ROLLBACK을 시도한 뒤 원본 예외를 재전파한다.
        ROLLBACK 자체 실패는 swallow하여 원본 예외(특히 CancelledError) 보존을
        우선한다.
        """
        if self._txn_owner is asyncio.current_task():
            raise RuntimeError("중첩 트랜잭션은 지원하지 않습니다")
        conn = self._get_writer()
        async with self._write_lock:
            self._txn_owner = asyncio.current_task()
            try:
                await conn.execute("BEGIN")
                yield self
                await conn.execute("COMMIT")
            except BaseException:
                try:
                    await conn.execute("ROLLBACK")
                except BaseException:
                    pass
                raise
            finally:
                self._txn_owner = None
