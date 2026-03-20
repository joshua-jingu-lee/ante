-- E2E 테스트용 시드 데이터
-- 모든 테이블 스키마는 각 모듈이 init 시 자동 생성하므로,
-- 이 파일은 데이터 INSERT만 포함한다.

-- ── 테스트 계좌 ────────────────────────────────────────
INSERT OR IGNORE INTO accounts (account_id, name, exchange, currency, timezone, trading_hours_start, trading_hours_end, trading_mode, broker_type, status, credentials, created_at)
VALUES
    ('test', 'Test Account', 'TEST', 'KRW', 'Asia/Seoul', '09:00', '15:30', 'virtual', 'test', 'active', '{}', datetime('now'));

-- ── 전략 등록 ────────────────────────────────────────
INSERT OR IGNORE INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES
    ('daily-buy-001', 'DailyFixedBuy', '0.1.0', 'strategies/daily_fixed_buy.py', 'active', datetime('now'), '매일 고정 금액 매수 전략 (E2E 테스트용)', 'seed'),
    ('momentum-001', 'SimpleMomentum', '0.1.0', 'strategies/simple_momentum.py', 'registered', datetime('now'), '단순 모멘텀 전략 (E2E 테스트용)', 'seed');

-- ── 봇 설정 ──────────────────────────────────────────
INSERT OR IGNORE INTO bots (bot_id, name, strategy_id, account_id, config_json, auto_start, status)
VALUES
    ('seed-bot-live', 'Seed Live Bot', 'daily-buy-001', 'test',
     '{"bot_id":"seed-bot-live","strategy_id":"daily-buy-001","name":"Seed Live Bot","account_id":"test","interval_seconds":60}',
     0, 'created'),
    ('seed-bot-paper', 'Seed Paper Bot', 'daily-buy-001', 'test',
     '{"bot_id":"seed-bot-paper","strategy_id":"daily-buy-001","name":"Seed Paper Bot","account_id":"test","interval_seconds":60,"paper_initial_balance":10000000.0}',
     0, 'created');

-- ── 자금 배분 ────────────────────────────────────────
INSERT OR IGNORE INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES
    ('seed-bot-live', 5000000.0, 5000000.0, 0.0, 0.0, 0.0),
    ('seed-bot-paper', 10000000.0, 10000000.0, 0.0, 0.0, 0.0);

INSERT OR IGNORE INTO treasury_state (account_id, account_balance, purchasable_amount, total_evaluation, currency)
VALUES
    ('test', 100000000.0, 85000000.0, 15000000.0, 'KRW');

-- ── 멤버 (관리자) ────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, status, scopes, password_hash)
VALUES
    ('seed-admin', 'human', 'owner', 'default', 'Seed Admin', 'active', '["*"]', '');
