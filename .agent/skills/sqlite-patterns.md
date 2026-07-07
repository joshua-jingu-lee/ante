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
        self._writer: aiosqlite.Connection | None = None
        self._reader: aiosqlite.Connection | None = None

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
- 위 PRAGMA 집합은 실제 코드와 일치한다 — SSOT는 `src/ante/core/database.py`
  (`_init_conn`). 실제 `Database`는 writer/reader 이중 연결, writer 직렬화 lock,
  read-only(`mode=ro`) 모드까지 포함하므로 새 연결 로직은 그 파일을 기준으로 한다.
- 메모리 매핑·페이지 캐시 관련 PRAGMA는 현재 **설정하지 않는다**(SQLite 기본값
  사용). N100 환경에서 추가 최적화가 필요하면 실측 후 별도 이슈로 도입한다.

## 3. 스키마 마이그레이션 — 중앙 러너 + 버전 모듈

Ante는 SQLite 내장 버전 카운터(PRAGMA)가 아니라 **`schema_version` 테이블**로 적용
이력을 추적하고, 각 마이그레이션을 `src/ante/db/versions/vNNN_*.py` 모듈의 async
`migrate(db)` 함수로 작성한다.

- 등록부: `src/ante/db/migrations.py`의
  `MIGRATIONS: list[tuple[int, str, MigrateFn]]` — `(seq, version, migrate_fn)`.
- 러너: `run_migrations(db)`가 미적용 seq만 골라 각 마이그레이션을
  `db.transaction()` 안에서 실행하고 `schema_version` INSERT와 원자 커밋한다.
- 실행 전 자동 백업: 미적용 항목이 있으면 `backup_db(...)`로 1회 백업한다.

**작성 규칙** (상세: `src/ante/db/migrations.py` 모듈 docstring, #2365):
- 마이그레이션은 추가만 한다 (기존 마이그레이션/버전 모듈 수정 금지).
- 각 마이그레이션은 멱등이어야 한다 (`IF NOT EXISTS`, `PRAGMA table_info` 가드 등).
  실제 예: `src/ante/db/versions/v006_order_tracker_order_price.py`.
- **트랜잭션 owner 태스크 안에서는 `execute_script` 금지** — Python `executescript`는
  열린 트랜잭션을 암묵 COMMIT하므로 원자성이 깨진다. DDL은 `db.execute(...)`로
  문장 단위 실행한다.
- ORM 사용하지 않음 — raw SQL + Row factory.

**red flag**: `MIGRATIONS = ["CREATE TABLE ..."]`(SQL 문자열 리스트) + SQLite 내장
버전 카운터(PRAGMA) 추적. 실제 구조는 `(seq, version, fn)` 튜플 + `schema_version`
테이블이며 내장 버전 카운터는 쓰지 않는다.

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

운영 중 DB 백업은 `sqlite3.Connection.backup()`으로 수행한다. aiosqlite 내부
연결의 private sqlite3 핸들에 직접 접근하지 않고 **별도 동기 `sqlite3.connect`**로
원본을 열어 백업한다.

- 실제 구현: `src/ante/db/backup.py`의 `backup_db(src_path, version)` — 원본/대상을
  각각 `sqlite3.connect`로 열고 `src_conn.backup(dst_conn)` 후 최근 `MAX_BACKUPS`개만
  유지한다.
- 호출 지점: `run_migrations`가 미적용 마이그레이션 실행 전에 1회 호출한다.

**red flag**: aiosqlite 객체의 내부 sqlite3 핸들(private 속성)에 직접 접근해
백업하는 것 — 실제 백업 경로는 별도 동기 연결을 연다.

## 7. N100 환경 PRAGMA 요약

실제 적용 집합 (SSOT: `src/ante/core/database.py` `_init_conn`):

```sql
PRAGMA journal_mode = WAL;          -- 읽기/쓰기 동시성 향상
PRAGMA synchronous = NORMAL;        -- WAL 모드에서 안전하면서 빠름
PRAGMA temp_store = MEMORY;         -- 임시 테이블을 메모리에
PRAGMA foreign_keys = ON;           -- 외래키 제약 활성화
PRAGMA busy_timeout = 5000;         -- SQLITE_BUSY 시 5초 대기 후 재시도
```

메모리 매핑·페이지 캐시 관련 PRAGMA는 현재 설정하지 않는다(SQLite 기본값). 추가
최적화가 필요하면 실측 후 별도 이슈로 도입한다.

## 8. 공통 주의사항

- **동기 sqlite3 호출 금지**: 반드시 `aiosqlite` 사용 (이벤트 루프 블로킹 방지)
- **파라미터 바인딩 필수**: `f"SELECT * FROM t WHERE id = {id}"` 금지 → `"... WHERE id = ?"` 사용 (SQL injection 방지)
- **TEXT 타입 활용**: SQLite는 동적 타입이지만, 스키마에 타입 명시하여 의도 전달
- **인덱스**: 자주 조회하는 컬럼(bot_id, symbol, executed_at)에 인덱스 생성
- **VACUUM**: 대량 삭제 후 실행 (디스크 공간 회수). 운영 중에는 자동 실행 주의
