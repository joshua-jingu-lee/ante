# Ante SQLite 패턴 가이드

> SQLite를 사용하는 모듈(Config 동적 설정, Trade, Report 등)은 이 패턴을 따른다.

## 1. 라이브러리 선택: aiosqlite

```toml
# pyproject.toml
dependencies = [
    "aiosqlite>=0.20",
]
```

- `aiosqlite`: asyncio bridge for sqlite3. 내부적으로 단일 스레드에서 직렬 실행
- WAL 모드, foreign keys가 기본 활성화됨
- 대안: `asqlite` (Rapptz) — WAL + foreign keys + Row factory 기본 설정

## 2. 연결 관리 — 단일 라이터 + 단일 리더 패턴

Ante는 단일 asyncio 프로세스이므로 연결 풀 불필요. WAL 모드에서 읽기/쓰기 동시성을 위해 **라이터 1개 + 리더 1개**:

```python
import aiosqlite


class Database:
    """SQLite 연결 관리. 앱 전체에서 하나의 인스턴스."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: aiosqlite.Connection | None = None

    async def _init_conn(self) -> aiosqlite.Connection:
        """공통 PRAGMA 설정으로 연결 초기화."""
        conn = await aiosqlite.connect(self._db_path)
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA synchronous=NORMAL")
        await conn.execute("PRAGMA temp_store=MEMORY")
        await conn.execute("PRAGMA foreign_keys=ON")
        await conn.execute("PRAGMA busy_timeout=5000")
        await conn.execute("PRAGMA mmap_size=268435456")  # 256MB
        await conn.execute("PRAGMA cache_size=-32000")     # 32MB
        conn.row_factory = aiosqlite.Row
        return conn

    async def connect(self) -> None:
        self._writer = await self._init_conn()
        self._reader = await self._init_conn()  # WAL: reader는 writer를 블로킹하지 않음

    async def close(self) -> None:
        for conn in (self._writer, self._reader):
            if conn:
                await conn.close()
        self._writer = self._reader = None

    @property
    def writer(self) -> aiosqlite.Connection:
        """쓰기 전용. INSERT/UPDATE/DELETE는 반드시 이것으로."""
        if not self._writer:
            raise RuntimeError("DB 연결되지 않음. connect()를 먼저 호출하세요.")
        return self._writer

    @property
    def reader(self) -> aiosqlite.Connection:
        """읽기 전용. SELECT는 이것으로 (writer를 블로킹하지 않음)."""
        if not self._reader:
            raise RuntimeError("DB 연결되지 않음. connect()를 먼저 호출하세요.")
        return self._reader
```

**주의**:
- 연결 풀 불필요 (단일 프로세스, 단일 writer)
- `PRAGMA synchronous=NORMAL`은 WAL 모드에서 안전하면서 성능 향상
- `mmap_size`는 N100 VM 메모리에 맞게 조정 (256MB 권장, RAM 부족 시 줄이기)

## 3. 스키마 마이그레이션 — 간단한 버전 관리

```python
MIGRATIONS = [
    # v1: 초기 스키마
    """
    CREATE TABLE IF NOT EXISTS trades (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        side TEXT NOT NULL,
        quantity REAL NOT NULL,
        price REAL NOT NULL,
        executed_at TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_trades_bot ON trades(bot_id);
    """,
    # v2: 포지션 테이블 추가
    """
    CREATE TABLE IF NOT EXISTS positions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bot_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        quantity REAL NOT NULL DEFAULT 0.0,
        avg_price REAL NOT NULL DEFAULT 0.0,
        updated_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """,
]


async def migrate(db: Database) -> int:
    """순차적으로 마이그레이션 실행. PRAGMA user_version으로 추적."""
    conn = db.writer

    # 현재 버전 확인 (별도 메타 테이블 불필요)
    async with conn.execute("PRAGMA user_version") as cursor:
        row = await cursor.fetchone()
        current = row[0]

    if current >= len(MIGRATIONS):
        return current

    for version, sql in enumerate(MIGRATIONS[current:], start=current + 1):
        await conn.executescript(sql)
        await conn.execute(f"PRAGMA user_version = {version}")
        await conn.commit()

    return len(MIGRATIONS)
```

**규칙**:
- 마이그레이션은 추가만 (기존 마이그레이션 수정 금지)
- 각 마이그레이션은 멱등성 보장 (`IF NOT EXISTS`)
- ORM 사용하지 않음 — raw SQL + Row factory

## 4. 트랜잭션 패턴

```python
# 읽기 — reader 사용 (writer를 블로킹하지 않음)
async def get_trades(db: Database, bot_id: str) -> list[dict]:
    async with db.reader.execute(
        "SELECT * FROM trades WHERE bot_id = ? ORDER BY executed_at DESC",
        (bot_id,),
    ) as cursor:
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

# 쓰기 — writer 사용 (명시적 커밋)
async def record_trade(db: Database, trade: Trade) -> int:
    cursor = await db.writer.execute(
        """INSERT INTO trades (bot_id, symbol, side, quantity, price, executed_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (trade.bot_id, trade.symbol, trade.side,
         str(trade.quantity), str(trade.price), trade.executed_at.isoformat()),
    )
    await db.writer.commit()
    return cursor.lastrowid

# 복합 쓰기 — BEGIN IMMEDIATE로 즉시 쓰기 락 획득
async def execute_order(db: Database, trade: Trade, position_update: dict) -> None:
    try:
        await db.writer.execute("BEGIN IMMEDIATE")
        await db.writer.execute(
            "INSERT INTO trades (...) VALUES (...)", (...)
        )
        await db.writer.execute(
            "UPDATE positions SET ... WHERE ...", (...)
        )
        await db.writer.commit()
    except Exception:
        await db.writer.rollback()
        raise
```

**주의**:
- 금액은 `float` + DB `REAL` 타입 사용
- `datetime`은 ISO 8601 문자열로 저장
- 복합 쓰기는 반드시 BEGIN/COMMIT/ROLLBACK 사용

## 5. 금액 저장/복원

```python
# 저장: float → REAL
await conn.execute(
    "INSERT INTO trades (price, quantity) VALUES (?, ?)",
    (50000.50, 10.0),
)

# 복원: REAL → float
async with conn.execute("SELECT price, quantity FROM trades WHERE id = ?", (trade_id,)) as cursor:
    row = await cursor.fetchone()
    price = float(row["price"])
    quantity = float(row["quantity"])
```

- 금액은 `float` + DB `REAL` 타입 사용 (스펙 문서 기준)
- `datetime`은 ISO 8601 문자열로 저장

## 6. 온라인 백업

```python
import sqlite3

async def backup_database(db: Database, backup_path: str) -> None:
    """운영 중 DB 백업 (online backup API)."""
    source_conn = db.conn._conn  # aiosqlite 내부 sqlite3 연결
    dest_conn = sqlite3.connect(backup_path)
    try:
        source_conn.backup(dest_conn, pages=100)  # 100페이지씩 점진적 복사
    finally:
        dest_conn.close()
```

**주의**: aiosqlite의 내부 연결에 접근하므로, 가능하면 별도 동기 연결로 백업 수행

## 7. N100 환경 최적화 PRAGMA 요약

```sql
PRAGMA journal_mode = WAL;          -- 읽기/쓰기 동시성 향상
PRAGMA synchronous = NORMAL;        -- WAL 모드에서 안전하면서 빠름
PRAGMA temp_store = MEMORY;         -- 임시 테이블을 메모리에
PRAGMA mmap_size = 268435456;       -- 256MB 메모리 매핑
PRAGMA cache_size = -16000;         -- 16MB 페이지 캐시
PRAGMA foreign_keys = ON;           -- 외래키 제약 활성화
PRAGMA busy_timeout = 5000;         -- SQLITE_BUSY 시 5초 대기 후 재시도
```

## 8. 공통 주의사항

- **동기 sqlite3 호출 금지**: 반드시 `aiosqlite` 사용 (이벤트 루프 블로킹 방지)
- **파라미터 바인딩 필수**: `f"SELECT * FROM t WHERE id = {id}"` 금지 → `"... WHERE id = ?"` 사용 (SQL injection 방지)
- **TEXT 타입 활용**: SQLite는 동적 타입이지만, 스키마에 타입 명시하여 의도 전달
- **인덱스**: 자주 조회하는 컬럼(bot_id, symbol, executed_at)에 인덱스 생성
- **VACUUM**: 대량 삭제 후 실행 (디스크 공간 회수). 운영 중에는 자동 실행 주의
