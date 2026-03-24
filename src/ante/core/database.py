"""SQLite WAL 모드 비동기 래퍼."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aiosqlite


class Database:
    """SQLite WAL 모드 비동기 래퍼. 모든 모듈이 공유."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None
        self._in_transaction: bool = False

    async def _init_conn(self) -> aiosqlite.Connection:
        """공통 PRAGMA 설정으로 연결 초기화."""
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        conn.row_factory = aiosqlite.Row
        return conn

    async def connect(self) -> None:
        """DB 연결 초기화. writer + reader 두 연결 생성."""
        self._writer = await self._init_conn()
        self._reader = await self._init_conn()

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
        """트랜잭션 컨텍스트 매니저. 실패 시 자동 ROLLBACK."""
        if self._in_transaction:
            raise RuntimeError("중첩 트랜잭션은 지원하지 않습니다")
        conn = self._get_writer()
        self._in_transaction = True
        try:
            await conn.execute("BEGIN")
            yield self
            await conn.execute("COMMIT")
        except Exception:
            await conn.execute("ROLLBACK")
            raise
        finally:
            self._in_transaction = False
