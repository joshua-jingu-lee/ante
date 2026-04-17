# Account 모듈 세부 설계 - 데이터베이스 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# 데이터베이스 스키마

```sql
CREATE TABLE IF NOT EXISTS accounts (
    account_id   TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    -- 시장
    exchange     TEXT NOT NULL,
    currency     TEXT NOT NULL,
    timezone     TEXT NOT NULL DEFAULT 'Asia/Seoul',
    trading_hours_start TEXT NOT NULL DEFAULT '09:00',
    trading_hours_end   TEXT NOT NULL DEFAULT '15:30',
    -- 거래 모드
    trading_mode TEXT NOT NULL DEFAULT 'virtual'
        CHECK(trading_mode IN ('virtual', 'live')),
    -- 브로커
    broker_type  TEXT NOT NULL,
    credentials  TEXT NOT NULL DEFAULT '{}',   -- JSON, 암호화 저장
    broker_config TEXT NOT NULL DEFAULT '{}', -- JSON, 브로커 동작 설정
    -- 비용
    buy_commission_rate  REAL NOT NULL DEFAULT 0,
    sell_commission_rate REAL NOT NULL DEFAULT 0,
    -- 상태
    status       TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'suspended', 'deleted')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### credentials 암호화

credentials는 APP KEY, APP SECRET 등 민감 정보를 포함한다. DB에는 암호화된 JSON 문자열로 저장하며, 복호화는 런타임에만 수행한다. Fernet 대칭 암호화를 사용하고, 마스터 키는 `secrets.env`의 `ANTE_DB_ENCRYPTION_KEY`에서 로드한다.
