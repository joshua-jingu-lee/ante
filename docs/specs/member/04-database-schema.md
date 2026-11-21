# Member 모듈 세부 설계 - DB 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# DB 스키마

테이블 정의: [`members`](../../architecture/generated/db-schema.md#members) (코드의 DDL에서 생성된다).

- `members.type`: 'human' | 'agent'
- `members.role`: 'master' | 'admin' | 'default'
- `members.emoji`: 아바타 이모지 (단일 이모지)
- `members.status`: 'active' | 'suspended' | 'revoked'
- `members.scopes`: JSON 배열
- `members.token_hash`: SHA-256 해시
- `members.password_hash`: PBKDF2-SHA256 해시 (human만)
- `members.recovery_key_hash`: PBKDF2-SHA256 해시 (human만)
- `members.created_by`: 생성자 member_id
- `members.token_expires_at`: 토큰 만료 시각 (마이그레이션 추가, 기본 90일)
