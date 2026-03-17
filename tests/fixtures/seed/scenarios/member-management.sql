-- 시나리오: member-management
-- 멤버 관리 페이지 플로우

-- ── Human 멤버 추가 ─────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, password_hash, created_at, last_active_at)
VALUES ('admin-01', 'human', 'admin', 'operations', '운영 관리자', '🐻', 'active',
        '["bot:read","bot:write","data:read","approval:review"]',
        '6c033869e5f1b5b7e4ac8588e894fd2db644e477c82c227e4855aaf7c593b4a8:9433f5b7192eec78153a234e4f9776cde34c8e1fdd02088bf7cd4ac0fe63a200',
        datetime('now', '-60 days'), '2026-03-12 18:00:00');

-- ── Agent 멤버 6명 ──────────────────────────────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at)
VALUES ('strategy-dev-01', 'agent', 'default', 'strategy-lab', '전략 리서치 1호', '🦊', 'active',
        '["strategy:write","data:read","backtest:run","report:write"]',
        '2026-02-15 10:00:00', 'owner', '2026-03-13 09:30:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at)
VALUES ('strategy-dev-02', 'agent', 'default', 'strategy-lab', '전략 리서치 2호', '🐼', 'active',
        '["strategy:write","data:read","backtest:run"]',
        '2026-02-20 14:00:00', 'owner', '2026-03-13 08:45:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at)
VALUES ('risk-monitor', 'agent', 'default', 'risk', '리스크 감시', '🦉', 'active',
        '["bot:read","data:read","approval:review"]',
        '2026-02-18 09:00:00', 'owner', '2026-03-13 09:15:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at)
VALUES ('treasury-agent', 'agent', 'default', 'treasury', '자금 관리', '🐳', 'active',
        '["approval:create","data:read"]',
        '2026-02-22 11:00:00', 'owner', '2026-03-13 08:15:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at, suspended_at)
VALUES ('ops-agent-01', 'agent', 'default', 'operations', '봇 운영 1호', '🐧', 'suspended',
        '["bot:read","data:read"]',
        '2026-02-25 10:00:00', 'owner', '2026-03-10 16:00:00', '2026-03-10 16:00:00');

INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at, revoked_at)
VALUES ('old-agent-01', 'agent', 'default', 'default', '구 리서치 에이전트', '🐺', 'revoked',
        '[]',
        '2026-01-15 09:00:00', 'owner', '2026-02-15 12:00:00', '2026-02-15 12:00:00');

-- ── 시스템 상태 ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('total_cash', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 50000000.0);
