# Rule Engine 모듈 세부 설계


> :warning: 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/rule/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 주문 처리 흐름, [AGENTS.md](../../../AGENTS.md) 거래 룰 (2중 구조), [notification.md](../notification/notification.md) 알림 발송

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [rule-engine.md](rule-engine.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [rule-engine.md](rule-engine.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-two-layer-evaluation.md](03-two-layer-evaluation.md) | 2계층 평가 흐름 |
| [04-rule-interface.md](04-rule-interface.md) | 룰 인터페이스 (Rule ABC) |
| [05-rule-context.md](05-rule-context.md) | RuleContext |
| [06-rule-catalog.md](06-rule-catalog.md) | 구체적 룰 목록 |
| [07-rule-engine-core.md](07-rule-engine-core.md) | RuleEngine 코어 |
| [08-notification-events.md](08-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [09-rule-management.md](09-rule-management.md) | 룰 정의 및 관리 |
| [10-rule-engine-manager.md](10-rule-engine-manager.md) | RuleEngineManager |
| [11-rest-api.md](11-rest-api.md) | REST API |
| [12-cli.md](12-cli.md) | CLI 인터페이스 |
| [13-open-issues.md](13-open-issues.md) | 미결 사항 |
| [14-cross-module-notes.md](14-cross-module-notes.md) | 타 모듈 설계 시 참고 |
