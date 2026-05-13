# Member 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/member/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [approval.md](../approval/approval.md) 결재 연동, [cli.md](../cli/cli.md) CLI, [web-api.md](../web-api/web-api.md) 대시보드 인증

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[member.md](member.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [member.md](member.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [member.md](member.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-member-model.md](03-member-model.md) | Member 모델 |
| [04-database-schema.md](04-database-schema.md) | DB 스키마 |
| [05-member-service.md](05-member-service.md) | MemberService |
| [06-cli.md](06-cli.md) | CLI 커맨드 |
| [07-eventbus-integration.md](07-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [08-module-impact.md](08-module-impact.md) | 기존 모듈 영향 |
| [09-notification-events.md](09-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [10-invalid-role-cleanup.md](10-invalid-role-cleanup.md) | invalid-role row 식별/교정 운영 절차 (#1468) |
