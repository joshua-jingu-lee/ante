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

-- 체결 이벤트 멱등 dedup (#1957)
-- OrderFilledEvent 의 outbox at-least-once 재전달에 대해 Treasury 정산을
-- 진짜 exactly-once-effect 로 만든다. fill_dedup_key(= #1949 결정적 키)를
-- PRIMARY KEY 로 두고, _on_order_filled 가 정산 트랜잭션 안에서 INSERT OR
-- IGNORE ... RETURNING 으로 신규 여부를 판정한다(행 반환=신규=정산 1회,
-- 충돌=이미 처리=정산 0회 추가). dedup-insert ⟺ 정산이 1:1 원자 결합된다.
CREATE TABLE treasury_fill_dedup (
    fill_dedup_key TEXT PRIMARY KEY,   -- order_id:canonical(confirmed_cumulative)
    bot_id         TEXT,
    account_id     TEXT,
    processed_at   TEXT DEFAULT (datetime('now'))
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

> **`purchasable_amount` 컬럼 의미 (#2384)**: 이 컬럼이 보관하는 매수가능액의 SSOT 출처는 KIS `inquire-psbl-order`의 `nrcvb_buy_amt`(미수 미사용 매수가능금액, 보수값)다. `inquire-balance`의 `psbl_sbst_amt`(대용가능금액)와는 다른 값이며, **컬럼 셋·DDL은 변경되지 않는다**(의미만 재지정). `substitute_amount`(대용가능금액)는 broker-balance dict 전용으로 Treasury가 영속화하지 않으므로 신규 컬럼을 추가하지 않는다. 따라서 `docs/architecture/generated/db-schema.md`는 재생성이 불필요하다(treasury_state 6컬럼 동일: `account_id`/`account_balance`/`purchasable_amount`/`total_evaluation`/`currency`/`last_synced_at`).

> **마이그레이션**: 1.0 이전 fresh schema 기준으로 Treasury DB는 fallback
> account 값을 생성하지 않는다. 기존 invalid dev DB 데이터의 자동 보존/변환은
> 이 계약의 범위가 아니다.

> **`treasury_fill_dedup` 보존 (#1957)**: fill 이벤트당 1행으로 누적되나 PK
> 인덱스만 증가하며 키 충돌이 없어 정합성 위험이 아니다. 개인 홈서버 fill
> 볼륨상 장기 비이슈이므로 retention/prune(terminal 주문 dedup row 정리 또는
> N일 경과 삭제)은 **별도 follow-up 후보**로 분리한다(#1957 bounded scope).

> **참고**: `positions` 테이블은 Trade 모듈이 소유한다. [trade.md](../trade/trade.md) 참조.
