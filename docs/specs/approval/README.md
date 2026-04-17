# Approval 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/approval/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [notification.md](../notification/notification.md) 알림 연동, [report-store.md](../report-store/report-store.md) 리포트 참조

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [approval.md](approval.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [approval.md](approval.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
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
