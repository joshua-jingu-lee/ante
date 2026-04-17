# Member 모듈 세부 설계 - DB 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# DB 스키마

```sql
CREATE TABLE IF NOT EXISTS members (
    member_id          TEXT PRIMARY KEY,
    type               TEXT NOT NULL,                    -- 'human' | 'agent'
    role               TEXT NOT NULL DEFAULT 'default',  -- 'master' | 'admin' | 'default'
    org                TEXT NOT NULL DEFAULT 'default',
    name               TEXT NOT NULL DEFAULT '',
    emoji              TEXT NOT NULL DEFAULT '',          -- 아바타 이모지 (단일 이모지)
    status             TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'suspended' | 'revoked'
    scopes             TEXT NOT NULL DEFAULT '[]',       -- JSON 배열
    token_hash         TEXT DEFAULT '',                  -- SHA-256 해시
    password_hash      TEXT DEFAULT '',                  -- PBKDF2-SHA256 해시 (human만)
    recovery_key_hash  TEXT DEFAULT '',                  -- PBKDF2-SHA256 해시 (human만)
    created_at         TEXT DEFAULT (datetime('now')),
    created_by         TEXT DEFAULT '',                  -- 생성자 member_id
    last_active_at     TEXT DEFAULT '',
    suspended_at       TEXT DEFAULT '',
    revoked_at         TEXT DEFAULT '',
    token_expires_at   TEXT DEFAULT ''                 -- 토큰 만료 시각 (마이그레이션 추가, 기본 90일)
);
CREATE INDEX IF NOT EXISTS idx_members_type ON members(type);
CREATE INDEX IF NOT EXISTS idx_members_status ON members(status);
CREATE INDEX IF NOT EXISTS idx_members_org ON members(org);
```
