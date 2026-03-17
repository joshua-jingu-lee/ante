-- 공통 베이스 시드: 모든 시나리오에서 공유하는 최소 데이터
-- Reset API가 _base.sql → {scenario}.sql 순서로 실행한다.

-- ── 시스템 상태 ──────────────────────────────────────
INSERT OR IGNORE INTO system_state (key, value) VALUES ('trading_state', 'active');

-- ── 마스터 멤버 (owner) ─────────────────────────────
-- 패스워드: test1234 (PBKDF2-SHA256)
INSERT OR IGNORE INTO members (member_id, type, role, org, name, emoji, status, scopes, password_hash, created_at, last_active_at)
VALUES (
    'owner', 'human', 'master', 'default', 'Owner',
    '🦁', 'active', '["*"]',
    '6c033869e5f1b5b7e4ac8588e894fd2db644e477c82c227e4855aaf7c593b4a8:9433f5b7192eec78153a234e4f9776cde34c8e1fdd02088bf7cd4ac0fe63a200',
    datetime('now', '-30 days'),
    datetime('now', '-1 hours')
);
