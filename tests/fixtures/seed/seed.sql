-- E2E 테스트용 시드 데이터
-- 모든 테이블 스키마는 각 모듈이 init 시 자동 생성하므로,
-- 이 파일은 데이터 INSERT만 포함한다.

-- ── 전략 등록 ────────────────────────────────────────
INSERT OR IGNORE INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES
    ('daily-buy-001', 'DailyFixedBuy', '0.1.0', 'strategies/daily_fixed_buy.py', 'active', datetime('now'), '매일 고정 금액 매수 전략 (E2E 테스트용)', 'seed'),
    ('momentum-001', 'SimpleMomentum', '0.1.0', 'strategies/simple_momentum.py', 'registered', datetime('now'), '단순 모멘텀 전략 (E2E 테스트용)', 'seed');

-- ── 봇 설정 ──────────────────────────────────────────
INSERT OR IGNORE INTO bots (bot_id, name, strategy_id, bot_type, config_json, auto_start, status)
VALUES
    ('seed-bot-live', 'Seed Live Bot', 'daily-buy-001', 'live',
     '{"bot_id":"seed-bot-live","strategy_id":"daily-buy-001","name":"Seed Live Bot","bot_type":"live","interval_seconds":60,"exchange":"KRX"}',
     0, 'created'),
    ('seed-bot-paper', 'Seed Paper Bot', 'daily-buy-001', 'paper',
     '{"bot_id":"seed-bot-paper","strategy_id":"daily-buy-001","name":"Seed Paper Bot","bot_type":"paper","interval_seconds":60,"paper_initial_balance":10000000.0,"exchange":"KRX"}',
     0, 'created');

-- ── 자금 배분 ────────────────────────────────────────
INSERT OR IGNORE INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES
    ('seed-bot-live', 5000000.0, 5000000.0, 0.0, 0.0, 0.0),
    ('seed-bot-paper', 10000000.0, 10000000.0, 0.0, 0.0, 0.0);

INSERT OR IGNORE INTO treasury_state (key, value)
VALUES
    ('total_cash', 100000000.0),
    ('allocated', 15000000.0),
    ('unallocated', 85000000.0);

-- ── 시스템 상태 ──────────────────────────────────────
INSERT OR IGNORE INTO system_state (key, value)
VALUES
    ('trading_state', 'active');

-- ── 멤버 (관리자) ────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, status, scopes, password_hash)
VALUES
    ('seed-admin', 'human', 'owner', 'default', 'Seed Admin', 'active', '["*"]', '');
