-- 시나리오: action-bot-lifecycle
-- 봇 생성 → 시작 → 중지 → 삭제 라이프사이클 액션 테스트

-- ── 전략 ────────────────────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('sma-cross', 'SMA 크로스', '1.0.0', 'strategies/sma_cross.py', 'active', datetime('now', '-14 days'),
        'SMA 5/20 크로스오버 전략', 'owner');

-- ── 자금: 충분한 미배정 예산 ─────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 100000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 100000000.0);
