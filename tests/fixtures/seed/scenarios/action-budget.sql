-- 시나리오: action-budget
-- 예산 할당/회수 액션 플로우 테스트용 시드
--
-- 설계:
--   - bot-alloc-01: 할당 대상 봇 (stopped, 예산 없음)
--   - bot-revoke-01: 회수 대상 봇 (stopped, 예산 있음)
--   - 미할당 자금 충분 (90,000,000 원)

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'active', datetime('now', '-14 days'),
        'SMA 5/20 크로스오버 전략', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v2', '모멘텀 돌파 전략 v2', '2.1.0', 'strategies/momentum_v2.py', 'active', datetime('now', '-30 days'),
        '20일 고점 돌파 시 매수', 'strategy-dev-01');

-- ── 봇: 할당 대상 (stopped, 예산 0) ─────────────────
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-alloc-01', '할당 테스트 봇', 'sma-cross', 'paper',
        '{"bot_id":"bot-alloc-01","strategy_id":"sma-cross","name":"할당 테스트 봇","bot_type":"paper","interval_seconds":60}',
        'stopped', datetime('now', '-5 days'));

-- ── 봇: 회수 대상 (stopped, 예산 10,000,000 보유) ───
INSERT INTO bots (bot_id, name, strategy_id, bot_type, config_json, status, created_at)
VALUES ('bot-revoke-01', '회수 테스트 봇', 'momentum-v2', 'live',
        '{"bot_id":"bot-revoke-01","strategy_id":"momentum-v2","name":"회수 테스트 봇","bot_type":"live","interval_seconds":60}',
        'stopped', datetime('now', '-10 days'));

-- ── 예산 ─────────────────────────────────────────────
-- 할당 대상 봇: 예산 0 (봇 목록에 표시되도록 레코드 존재)
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-alloc-01', 0.0, 0.0, 0.0, 0.0, 0.0);

-- 회수 대상 봇: 배정 10,000,000 / 가용 10,000,000
INSERT INTO bot_budgets (bot_id, allocated, available, reserved, spent, returned)
VALUES ('bot-revoke-01', 10000000.0, 10000000.0, 0.0, 0.0, 0.0);

-- ── Treasury 상태 ─────────────────────────────────────
-- 총 잔고 100,000,000 / 할당 10,000,000 / 미할당 90,000,000 (할당 여유 충분)
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 90000000.0);

-- ── 자금 변동 이력 (초기 할당 기록) ──────────────────
INSERT INTO treasury_transactions (bot_id, transaction_type, amount, description, created_at)
VALUES ('bot-revoke-01', 'allocate', 10000000.0, '초기 할당', datetime('now', '-10 days'));

-- ── 에이전트 멤버 ─────────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write"]', datetime('now', '-60 days'));
