# Bot 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/bot/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 봇 모듈, [strategy.md](../strategy/strategy.md) 전략 인터페이스, D-003

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [bot.md](bot.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [bot.md](bot.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-eventbus-integration.md](04-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [05-notification-events.md](05-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [06-cli-usage.md](06-cli-usage.md) | CLI 사용법 |
| [07-testing.md](07-testing.md) | 테스트 고려사항 |
| [08-cross-module-notes.md](08-cross-module-notes.md) | 타 모듈 설계 시 참고 |
| [09-open-issues.md](09-open-issues.md) | 미결 사항 |
