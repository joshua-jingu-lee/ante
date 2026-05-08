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
    -- 시장가 매수 reserve buffer 비율 (#1333). Account-level Treasury reserve
    -- policy. Decimal 정밀도는 Account dataclass / Treasury 내부에서만
    -- 유지되고, DB 컬럼은 REAL 로 저장한다.
    market_order_reserve_buffer_rate REAL NOT NULL DEFAULT 0.005,
    -- 상태
    status       TEXT NOT NULL DEFAULT 'active'
        CHECK(status IN ('active', 'suspended', 'deleted')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
```

### Migration: market_order_reserve_buffer_rate (#1333)

legacy DB(이 컬럼이 없는 단계) 가 켜질 때 `AccountService.initialize` 가 1 회성
ALTER 와 backfill 을 적용한다.

```sql
-- 1) 컬럼 추가 (default 0.005). 이미 있으면 OperationalError 로 무시.
ALTER TABLE accounts
    ADD COLUMN market_order_reserve_buffer_rate REAL NOT NULL DEFAULT 0.005;

-- 2) broker_type 별 backfill — ALTER 가 실제 성공한 1 회성 마이그레이션
--    경로에서만 실행한다. 2 회 이상 실행되면 운영자가 CLI 로 직접 지정한
--    ``test`` 계좌의 buffer 값을 0 으로 덮어쓰는 idempotency 위반이 된다.
UPDATE accounts SET market_order_reserve_buffer_rate = 0
    WHERE broker_type = 'test';
```

`broker_type='kis-domestic'` row 는 DDL default(0.005) 를 그대로 두며,
`broker_type='kis-overseas'` 같은 1.0 미지원 broker_type 의 legacy row 도
default 를 유지한다 — 1.1 에서 KISOverseasAdapter 와 함께 적합 값으로
backfill 한다. NULL/unknown broker_type 도 보수적으로 default 0.005 를
유지한다.

### credentials 암호화

credentials는 APP KEY, APP SECRET 등 민감 정보를 포함한다. DB에는 암호화된 JSON 문자열로 저장하며, 복호화는 런타임에만 수행한다. Fernet 대칭 암호화를 사용하고, 마스터 키는 `secrets.env`의 `ANTE_DB_ENCRYPTION_KEY`에서 로드한다.
