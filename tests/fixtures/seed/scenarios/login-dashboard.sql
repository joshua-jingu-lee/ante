-- 시나리오: login-dashboard
-- 로그인 → 대시보드 플로우에 필요한 시드 데이터

-- ── 포트폴리오 (treasury) ───────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('total_cash', 100000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 100000000.0);

-- ── 승인 대기 2건 ───────────────────────────────────
INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES (
    'approval-login-01', 'strategy_adopt', 'pending', 'strategy-dev-01',
    '모멘텀 돌파 전략 v2 채택 요청',
    '백테스트 결과 양호하여 채택 요청합니다.',
    '{"strategy_id": "momentum-v2"}',
    datetime('now', '-1 hours'),
    datetime('now', '+3 days')
);

INSERT INTO approvals (id, type, status, requester, title, body, params, created_at, expires_at)
VALUES (
    'approval-login-02', 'budget_change', 'pending', 'treasury-agent',
    'bot-momentum-01 예산 증액 요청',
    '운용 성과 양호하여 예산 증액 요청합니다.',
    '{"bot_id": "bot-momentum-01", "amount": 25000000}',
    datetime('now', '-2 hours'),
    datetime('now', '+3 days')
);

-- ── 에이전트 멤버 (승인 요청자) ─────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active', '["strategy:write","data:read"]', datetime('now', '-30 days'));

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at)
VALUES ('treasury-agent', 'agent', 'default', 'treasury', '자금 관리', '🐳', 'active', '["approval:create","data:read"]', datetime('now', '-30 days'));
