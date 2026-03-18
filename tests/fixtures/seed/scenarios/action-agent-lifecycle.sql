-- 시나리오: action-agent-lifecycle
-- 에이전트 라이프사이클 액션 플로우 (등록 → 정지 → 폐기)

-- ── 기존 활성 에이전트 (정지/폐기 테스트용) ──────────
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, created_at, created_by, last_active_at)
VALUES ('lifecycle-agent-01', 'agent', 'default', 'strategy-lab', '라이프사이클 테스트 에이전트', '🦊', 'active',
        '["strategy:read","data:read"]',
        datetime('now', '-10 days'), 'owner', datetime('now', '-1 hours'));

-- ── 자금 (최소) ─────────────────────────────────────
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('account_balance', 50000000.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('allocated', 0.0);
INSERT OR IGNORE INTO treasury_state (key, value) VALUES ('unallocated', 50000000.0);
