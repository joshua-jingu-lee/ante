# Bot 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/bot/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 봇 모듈, [strategy.md](../strategy/strategy.md) 전략 인터페이스, D-003

이 문서는 분할된 `bot` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-eventbus-integration.md](04-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [05-notification-events.md](05-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [06-cli-usage.md](06-cli-usage.md) | CLI 사용법 |
| [07-testing.md](07-testing.md) | 테스트 고려사항 |
| [08-cross-module-notes.md](08-cross-module-notes.md) | 타 모듈 설계 시 참고 |
| [09-open-issues.md](09-open-issues.md) | 미결 사항 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 설계 결정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 봇 상태 머신

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### BotConfig

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### Bot 클래스

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### BotManager

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 봇 유형별 차이: LIVE vs VIRTUAL (Account.trading_mode 기준)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### SQLite 스키마

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 봇 실행 흐름 (전체)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 외부 시그널 채널

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 예외 격리 (D-003)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 봇 자동 재시작 정책

상세 내용: [03-design-decisions.md](03-design-decisions.md)

## 이벤트 버스 연동 (EventBus Integration)

상세 내용: [04-eventbus-integration.md](04-eventbus-integration.md)

### BotStepCompletedEvent

상세 내용: [04-eventbus-integration.md](04-eventbus-integration.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [05-notification-events.md](05-notification-events.md)

### 봇 시작

상세 내용: [05-notification-events.md](05-notification-events.md)

### 봇 중지

상세 내용: [05-notification-events.md](05-notification-events.md)

### 봇 에러

상세 내용: [05-notification-events.md](05-notification-events.md)

### 재시작 한도 소진

상세 내용: [05-notification-events.md](05-notification-events.md)

## CLI 사용법

상세 내용: [06-cli-usage.md](06-cli-usage.md)

## 테스트 고려사항

상세 내용: [07-testing.md](07-testing.md)

## 타 모듈 설계 시 참고

상세 내용: [08-cross-module-notes.md](08-cross-module-notes.md)

## 미결 사항

상세 내용: [09-open-issues.md](09-open-issues.md)
