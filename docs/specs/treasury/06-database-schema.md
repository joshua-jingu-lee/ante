# Treasury 모듈 세부 설계 - 데이터베이스 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 데이터베이스 스키마

```sql
-- 봇별 예산 상태
CREATE TABLE bot_budgets (
    bot_id       TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL,                          -- 소속 계좌 ID
    allocated    REAL NOT NULL DEFAULT 0.0,
    available    REAL NOT NULL DEFAULT 0.0,
    reserved     REAL NOT NULL DEFAULT 0.0,
    spent        REAL NOT NULL DEFAULT 0.0,
    returned     REAL NOT NULL DEFAULT 0.0,
    last_updated TEXT DEFAULT (datetime('now'))
);

-- 자금 거래 이력 (감사용)
CREATE TABLE treasury_transactions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id           TEXT,
    account_id       TEXT DEFAULT 'default',              -- 소속 계좌 ID
    transaction_type TEXT NOT NULL,  -- 'allocate', 'deallocate', 'reserve', 'release', 'fill'
    amount           REAL NOT NULL,
    description      TEXT DEFAULT '',
    created_at       TEXT DEFAULT (datetime('now'))
);

-- 계좌별 상태 저장
CREATE TABLE treasury_state (
    account_id         TEXT PRIMARY KEY,                   -- 계좌별 분리 (기존: key TEXT PK)
    account_balance    REAL NOT NULL DEFAULT 0,
    purchasable_amount REAL NOT NULL DEFAULT 0,
    total_evaluation   REAL NOT NULL DEFAULT 0,
    currency           TEXT NOT NULL DEFAULT 'KRW',
    last_synced_at     TEXT
);
```

> **마이그레이션**: 기존 `treasury_state`는 key-value 구조에서 계좌별 행 구조로 변경되므로, 테이블 재생성이 필요하다. 기존 데이터는 `account_id = "default"` 행으로 변환한다.

> **참고**: `positions` 테이블은 Trade 모듈이 소유한다. [trade.md](../trade/trade.md) 참조.
