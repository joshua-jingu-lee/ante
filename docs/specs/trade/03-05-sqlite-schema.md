# Trade 모듈 세부 설계 - 설계 결정 - SQLite 스키마

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# SQLite 스키마

```sql
-- 개별 거래 기록
CREATE TABLE trades (
    trade_id       TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL,
    bot_id         TEXT NOT NULL,
    strategy_id    TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    symbol_name    TEXT DEFAULT '',
    side           TEXT NOT NULL,           -- 'buy' | 'sell'
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    status         TEXT NOT NULL,           -- 'filled' | 'cancelled' | 'rejected' | 'failed' | 'adjusted'
    order_type     TEXT DEFAULT '',
    reason         TEXT DEFAULT '',
    commission     REAL DEFAULT 0.0,
    currency       TEXT DEFAULT 'KRW',
    timestamp      TEXT,
    order_id       TEXT,                    -- 증권사 주문 ID
    exchange       TEXT DEFAULT 'KRX',
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_trades_account ON trades(account_id, timestamp);
CREATE INDEX idx_trades_bot ON trades(bot_id, timestamp);
CREATE INDEX idx_trades_strategy ON trades(strategy_id, timestamp);
CREATE INDEX idx_trades_symbol ON trades(symbol, timestamp);
CREATE INDEX idx_trades_status ON trades(status);

-- 봇별 종목 포지션 현재 상태
CREATE TABLE positions (
    account_id       TEXT NOT NULL,
    bot_id           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    quantity         REAL NOT NULL DEFAULT 0,
    avg_entry_price  REAL NOT NULL DEFAULT 0.0,
    realized_pnl     REAL NOT NULL DEFAULT 0.0,    -- 누적 실현 손익
    exchange         TEXT DEFAULT 'KRX',
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (bot_id, symbol)
);

-- 포지션 변동 이력
CREATE TABLE position_history (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_id         TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    action         TEXT NOT NULL,           -- 'buy' | 'sell'
    quantity       REAL NOT NULL,
    price          REAL NOT NULL,
    pnl            REAL DEFAULT 0.0,        -- 이 거래의 실현 손익 (sell 시)
    timestamp      TEXT,
    exchange       TEXT DEFAULT 'KRX',      -- v0.2 마이그레이션으로 추가
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_position_history_bot ON position_history(bot_id, timestamp);
```

**근거**:
- `trades` 테이블: 모든 거래 시도를 기록 (체결/취소/거부/실패 모두)
- `positions` 테이블: 현재 포지션 상태 — 빠른 조회용 (이력은 별도 테이블)
- `position_history` 테이블: 포지션 변동 이력 — 진입/청산 경로 추적
- 인덱스: bot_id, strategy_id, symbol 기준 조회가 빈번하므로 복합 인덱스
