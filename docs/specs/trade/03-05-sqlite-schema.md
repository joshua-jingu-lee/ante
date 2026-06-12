# Trade 모듈 세부 설계 - 설계 결정 - SQLite 스키마

> 인덱스: [03-design-decisions.md](03-design-decisions.md) | 모듈 인덱스: [README.md](README.md)

# SQLite 스키마

```sql
-- 개별 거래 기록
CREATE TABLE trades (
    trade_id       TEXT PRIMARY KEY,
    account_id     TEXT NOT NULL,          -- fallback default 없음
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
```

`trades.account_id`는 fresh schema에서 필수값이며 `DEFAULT 'default'` 같은
fallback을 두지 않는다. `TradeRecorder`는 저장 직전과 명시 account 조회
필터에서 Account ID scoping helper로 `None`, 빈 문자열, `default`를 거부한다.

`trades.timestamp`는 **단일 포맷 invariant**를 가진다: UTC-aware ISO 8601
isoformat(`YYYY-MM-DDTHH:MM:SS[.ffffff]+00:00`, 예: `2026-06-12T04:43:53+00:00`)
으로만 저장한다. 모든 쓰기 경로(`save_trade`/`_save_trade`/`save_adjustment`)는
`datetime.now(UTC).isoformat()` 동일 포맷을 쓰며, SQLite `datetime('now')`의 공백
구분 포맷(`YYYY-MM-DD HH:MM:SS`)을 `timestamp` 값으로 저장하지 않는다. 이 invariant는
TEXT lexical 비교에서 공백(`0x20`) < `T`(`0x54`)로 인한 날짜/정렬 쿼리 누락
(`trade list --from` 당일 경계 등)을 차단한다. 과거 공백 포맷으로 저장된 행은
마이그레이션 v005(`v005_trades_timestamp_isoformat`)가 isoformat UTC로 정규화한다.
(`created_at` 등 다른 컬럼은 각자 계약이며 이 invariant는 `timestamp` 한정이다.)

봇별 종목 포지션 현재 상태:
```sql
CREATE TABLE positions (
    account_id       TEXT NOT NULL,
    bot_id           TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    quantity         REAL NOT NULL DEFAULT 0,
    avg_entry_price  REAL NOT NULL DEFAULT 0.0,
    realized_pnl     REAL NOT NULL DEFAULT 0.0,    -- 누적 실현 손익
    exchange         TEXT DEFAULT 'KRX',
    updated_at       TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (account_id, bot_id, symbol)
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
    account_id     TEXT NOT NULL,
    created_at     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX idx_position_history_bot ON position_history(bot_id, timestamp);
CREATE INDEX idx_position_history_account
    ON position_history(account_id, bot_id, timestamp);
```

`positions.account_id`와 `position_history.account_id`는 fresh schema에서
필수값이며 `DEFAULT 'default'` 같은 fallback을 두지 않는다. 현재 포지션의
유일 키는 account를 포함해 동일 `bot_id`/`symbol`이 다른 account에서
충돌하지 않아야 한다.

**근거**:
- `trades` 테이블: 모든 거래 시도를 기록 (체결/취소/거부/실패 모두)
- `positions` 테이블: 현재 포지션 상태 — 빠른 조회용 (이력은 별도 테이블)
- `position_history` 테이블: 포지션 변동 이력 — 진입/청산 경로 추적
- 인덱스: bot_id, strategy_id, symbol 기준 조회가 빈번하므로 복합 인덱스
