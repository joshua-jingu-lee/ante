# Member 모듈 세부 설계 - 기존 모듈 영향

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 기존 모듈 영향

Member 모듈 도입 시 기존 모듈에서 `"agent"` 하드코딩을 member_id로 교체해야 한다.

| 모듈 | 현재 | 변경 후 |
|------|------|---------|
| Strategy `author` | `"agent"` 하드코딩 | 인증된 member_id 사용 |
| Report `submitted_by` | `"agent"` 하드코딩 | 인증된 member_id 사용 |
| Approval `requester` | CLI `--requester` 옵션 (기본 `"agent"`) | 토큰에서 member_id 자동 추출 |
| Approval `resolved_by` | `"user"` 하드코딩 | 인증된 member_id 사용 |
| Approval `history.actor` | 자유 문자열 | member_id 사용 |
| CLI 전체 | 인증 없음 | 토큰 기반 인증 미들웨어 추가 |
| Web API | 인증 없음 | 세션/토큰 기반 인증 미들웨어 추가 |

**하위 호환성**: 기존 DB 레코드의 `"agent"`, `"user"` 문자열은 그대로 보존한다. Member 모듈 도입 후 생성되는 레코드부터 member_id를 사용한다.

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
