-- 시나리오: action-approval-review
-- 결재 승인/거부 액션 플로우

-- ── 에이전트 멤버 (요청자) ──────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active',
        '["strategy:write","data:read","backtest:run","report:write"]',
        datetime('now', '-60 days'), '2026-03-13 09:30:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, last_active_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active',
        '["strategy:write","data:read","backtest:run"]',
        datetime('now', '-45 days'), '2026-03-12 17:45:00');

-- ── 전략 (결재 참조용) ───────────────────────────────
INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('momentum-v3', '모멘텀 돌파 전략 v3', '3.0.0', 'strategies/momentum_v3.py', 'registered',
        datetime('now', '-10 days'), '20일 고점 돌파 + 거래량 필터', 'strategy-dev-01');

INSERT INTO strategies (strategy_id, name, version, filepath, status, registered_at, description, author)
VALUES ('macd-v2', 'MACD 크로스 v2', '2.0.0', 'strategies/macd_v2.py', 'registered',
        datetime('now', '-8 days'), 'MACD 다중 타임프레임 크로스 전략', 'strategy-dev-02');

-- ── 결재 요청 2건 (모두 pending) ────────────────────
-- [대기] 전략 채택 — 승인 테스트용 (appr-r01)
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES ('appr-r01', 'strategy_adopt', 'pending', 'strategy-dev-01',
        '모멘텀 돌파 전략 v3 채택 요청',
        '백테스트 3년 수익률 42.1%, 샤프비율 1.62로 양호합니다. 실전 투입을 요청합니다.',
        '{"strategy_id":"momentum-v3","version":"3.0.0"}',
        '2026-03-16 10:00:00', '2026-03-19 10:00:00');

-- [대기] 전략 채택 — 거부 테스트용 (appr-r02)
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES ('appr-r02', 'strategy_adopt', 'pending', 'strategy-dev-02',
        'MACD 크로스 v2 채택 요청',
        'MACD 다중 타임프레임 전략 백테스트 완료. 실전 투입을 요청합니다.',
        '{"strategy_id":"macd-v2","version":"2.0.0"}',
        '2026-03-16 11:00:00', '2026-03-19 11:00:00');

-- ── 자금 (최소) ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('total_cash', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 50000000.0);
