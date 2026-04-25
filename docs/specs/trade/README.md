# Trade 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/trade/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [bot.md](../bot/bot.md) Bot 실행 흐름, [strategy.md](../strategy/strategy.md) Signal/OrderAction

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
계약 SSOT는 이 README의 문서 목록과 주제별 하위 문서다.
[trade.md](trade.md)는 기존 링크와 섹션 앵커 호환을 위한 인덱스이며 계약 본문이 아니다.
새 계약, 결정, 미결 사항은 [trade.md](trade.md)에 추가하지 않고 해당 하위 문서에 반영한다.

| 문서 | 내용 |
|---|---|
| [trade.md](trade.md) | 호환용 인덱스 및 기존 섹션 앵커 (계약 본문 아님) |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-eventbus-integration.md](04-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [05-cli-usage.md](05-cli-usage.md) | CLI 사용 |
| [06-testing.md](06-testing.md) | 테스트 고려사항 |
| [07-notification-events.md](07-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [09-cross-module-notes.md](09-cross-module-notes.md) | 타 모듈 설계 시 참고 |
