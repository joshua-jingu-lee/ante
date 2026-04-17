# Member 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/member/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [approval.md](../approval/approval.md) 결재 연동, [cli.md](../cli/cli.md) CLI, [web-api.md](../web-api/web-api.md) 대시보드 인증

이 문서는 분할된 `member` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-member-model.md](03-member-model.md) | Member 모델 |
| [04-database-schema.md](04-database-schema.md) | DB 스키마 |
| [05-member-service.md](05-member-service.md) | MemberService |
| [06-cli.md](06-cli.md) | CLI 커맨드 |
| [07-eventbus-integration.md](07-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [08-module-impact.md](08-module-impact.md) | 기존 모듈 영향 |
| [09-notification-events.md](09-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [10-open-issues.md](10-open-issues.md) | 미결 사항 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### Member 타입과 역할

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 조직 (org)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 인증 체계

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 비밀번호 복구 — Recovery Key

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 권한 범위 (Scope)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 시스템 초기화 흐름

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### bootstrap 시 토큰 동시 발급

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 이모지 시스템

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## Member 모델

상세 내용: [03-member-model.md](03-member-model.md)

### 토큰 만료 관리

상세 내용: [03-member-model.md](03-member-model.md)

### Member 상태 흐름

상세 내용: [03-member-model.md](03-member-model.md)

## DB 스키마

상세 내용: [04-database-schema.md](04-database-schema.md)

## MemberService

상세 내용: [05-member-service.md](05-member-service.md)

### 불변식 검증

상세 내용: [05-member-service.md](05-member-service.md)

## CLI 커맨드

상세 내용: [06-cli.md](06-cli.md)

### `ante member list`

상세 내용: [06-cli.md](06-cli.md)

### `ante member info <member_id>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member register`

상세 내용: [06-cli.md](06-cli.md)

### `ante member set-emoji <member_id> <emoji>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member suspend <member_id>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member reactivate <member_id>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member revoke <member_id>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member rotate-token <member_id>`

상세 내용: [06-cli.md](06-cli.md)

### `ante member reset-password`

상세 내용: [06-cli.md](06-cli.md)

### `ante member regenerate-recovery-key`

상세 내용: [06-cli.md](06-cli.md)

## 이벤트 버스 연동 (EventBus Integration)

상세 내용: [07-eventbus-integration.md](07-eventbus-integration.md)

## 기존 모듈 영향

상세 내용: [08-module-impact.md](08-module-impact.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [09-notification-events.md](09-notification-events.md)

### 1. 인증 실패

상세 내용: [09-notification-events.md](09-notification-events.md)

### 2. 패스워드 변경

상세 내용: [09-notification-events.md](09-notification-events.md)

### 3. 패스워드 리셋 (Recovery Key)

상세 내용: [09-notification-events.md](09-notification-events.md)

## 미결 사항

상세 내용: [10-open-issues.md](10-open-issues.md)

### bootstrap 시 토큰 동시 발급

상세 내용: [10-open-issues.md](10-open-issues.md)
