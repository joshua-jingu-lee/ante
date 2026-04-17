# Approval 모듈 세부 설계 - DB 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# DB 스키마

```sql
CREATE TABLE IF NOT EXISTS approvals (
    id              TEXT PRIMARY KEY,
    type            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending',
    requester       TEXT NOT NULL,
    title           TEXT NOT NULL,
    body            TEXT NOT NULL DEFAULT '',
    params          TEXT NOT NULL DEFAULT '{}',   -- JSON
    reviews         TEXT NOT NULL DEFAULT '[]',   -- JSON array
    history         TEXT NOT NULL DEFAULT '[]',   -- JSON array (감사 이력)
    reference_id    TEXT DEFAULT '',
    expires_at      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    resolved_at     TEXT DEFAULT '',
    resolved_by     TEXT DEFAULT '',
    reject_reason   TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_approvals_type ON approvals(type);
```
