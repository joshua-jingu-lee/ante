# Member 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/member/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [approval.md](../approval/approval.md) 결재 연동, [cli.md](../cli/cli.md) CLI, [web-api.md](../web-api/web-api.md) 대시보드 인증

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [member.md](member.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [member.md](member.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
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
