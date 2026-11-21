# Approval 모듈 세부 설계 - DB 스키마

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# DB 스키마

테이블 정의: [`approvals`](../../architecture/generated/db-schema.md#approvals) (코드의 DDL에서 생성된다).

- `approvals.params`: JSON
- `approvals.reviews`: JSON array
- `approvals.history`: JSON array (감사 이력)
