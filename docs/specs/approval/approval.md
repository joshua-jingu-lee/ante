# Approval 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/approval/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [notification.md](../notification/notification.md) 알림 연동, [report-store.md](../report-store/report-store.md) 리포트 참조

이 문서는 분할된 `approval` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-enums.md](03-enums.md) | Enum 정의 |
| [04-approval-request-model.md](04-approval-request-model.md) | ApprovalRequest 모델 |
| [05-approval-types.md](05-approval-types.md) | 결재 유형 |
| [06-status-flow.md](06-status-flow.md) | 결재 상태 흐름 |
| [07-database-schema.md](07-database-schema.md) | DB 스키마 |
| [08-approval-service.md](08-approval-service.md) | ApprovalService |
| [09-cli.md](09-cli.md) | CLI 커맨드 |
| [10-eventbus-integration.md](10-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [11-notification-events.md](11-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [12-cross-module-notes.md](12-cross-module-notes.md) | 타 모듈 설계 시 참고 |
| [13-open-issues.md](13-open-issues.md) | 미결 사항 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### Report와의 관계

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 만료 정책

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 외부 메신저를 통한 결재 처리

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 사전 검증과 참조자

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 결재 철회

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 감사 이력

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 전결 (자동 승인)

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### 사용자 직접 실행과의 구분

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## Enum 정의

상세 내용: [03-enums.md](03-enums.md)

### ApprovalStatus (StrEnum)

상세 내용: [03-enums.md](03-enums.md)

### ApprovalType (StrEnum)

상세 내용: [03-enums.md](03-enums.md)

## ApprovalRequest 모델

상세 내용: [04-approval-request-model.md](04-approval-request-model.md)

### reviews (사전 검증)

상세 내용: [04-approval-request-model.md](04-approval-request-model.md)

## 결재 유형

상세 내용: [05-approval-types.md](05-approval-types.md)

## 결재 상태 흐름

상세 내용: [06-status-flow.md](06-status-flow.md)

## DB 스키마

상세 내용: [07-database-schema.md](07-database-schema.md)

## ApprovalService

상세 내용: [08-approval-service.md](08-approval-service.md)

### 만료 스케줄러

상세 내용: [08-approval-service.md](08-approval-service.md)

### 자동 실행 (Executor)

상세 내용: [08-approval-service.md](08-approval-service.md)

### Executor 이중 검증

상세 내용: [08-approval-service.md](08-approval-service.md)

## CLI 커맨드

상세 내용: [09-cli.md](09-cli.md)

### `ante approval request`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval list`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval info <id>`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval review <id>`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval cancel <id>`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval reopen <id>`

상세 내용: [09-cli.md](09-cli.md)

### `ante approval approve <id>` / `ante approval reject <id>`

상세 내용: [09-cli.md](09-cli.md)

## 이벤트 버스 연동 (EventBus Integration)

상세 내용: [10-eventbus-integration.md](10-eventbus-integration.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [11-notification-events.md](11-notification-events.md)

### 1. 결재 요청 알림

상세 내용: [11-notification-events.md](11-notification-events.md)

### 2. 결재 처리 완료

상세 내용: [11-notification-events.md](11-notification-events.md)

## 타 모듈 설계 시 참고

상세 내용: [12-cross-module-notes.md](12-cross-module-notes.md)

## 미결 사항

상세 내용: [13-open-issues.md](13-open-issues.md)
