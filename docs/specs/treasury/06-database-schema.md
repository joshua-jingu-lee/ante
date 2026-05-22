# Treasury 모듈 세부 설계 - 데이터베이스 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [treasury.md](treasury.md)

# 데이터베이스 스키마

```sql
-- 봇별 예산 상태
CREATE TABLE bot_budgets (
    bot_id       TEXT PRIMARY KEY,
    account_id   TEXT NOT NULL,                          -- 소속 계좌 ID, fallback default 없음
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
    account_id       TEXT NOT NULL,                       -- 소속 계좌 ID, fallback default 없음
    -- transaction_type vocabulary (5-value, SSOT):
    --   'allocate'             : 봇에 예산 할당
    --   'deallocate'           : 봇에서 예산 회수
    --   'release'              : 봇 삭제 시 할당 예산 전액 환수
    --   'fill'                 : 주문 체결로 인한 자금 이동
    --   'bot_stopped_release'  : 봇 중지 시 잔여 예약 자금 환수
    -- 코드 SSOT: src/ante/treasury/treasury.py::TRANSACTION_TYPE_VOCABULARY
    transaction_type TEXT NOT NULL,
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
CREATE INDEX idx_bot_budgets_account ON bot_budgets(account_id);
CREATE INDEX idx_treasury_transactions_account
    ON treasury_transactions(account_id);
```

> **마이그레이션**: 1.0 이전 fresh schema 기준으로 Treasury DB는 fallback
> account 값을 생성하지 않는다. 기존 invalid dev DB 데이터의 자동 보존/변환은
> 이 계약의 범위가 아니다.

> **참고**: `positions` 테이블은 Trade 모듈이 소유한다. [trade.md](../trade/trade.md) 참조.
