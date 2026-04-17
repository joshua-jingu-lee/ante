# Trade 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/trade/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성, [bot.md](../bot/bot.md) Bot 실행 흐름, [strategy.md](../strategy/strategy.md) Signal/OrderAction

이 문서는 분할된 `trade` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-design-decisions.md](03-design-decisions.md) | 설계 결정 |
| [04-eventbus-integration.md](04-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [05-cli-usage.md](05-cli-usage.md) | CLI 사용 |
| [06-testing.md](06-testing.md) | 테스트 고려사항 |
| [07-notification-events.md](07-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [08-open-issues.md](08-open-issues.md) | 미결 사항 |
| [09-cross-module-notes.md](09-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 설계 결정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### 거래 기록 (TradeRecord)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### TradeType

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### TradeStatus

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### TradeRecord 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### TradeRecorder — 이벤트 기반 자동 기록

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 퍼블릭 메서드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### PositionHistory — 포지션 변동 추적

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### PositionSnapshot 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 퍼블릭 메서드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### PerformanceTracker — 성과 지표 산출

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### PerformanceMetrics 필드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### DailySummary 필드 (frozen dataclass)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### MonthlySummary 필드 (frozen dataclass)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### WeeklySummary 필드 (frozen dataclass)

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 퍼블릭 메서드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### SQLite 스키마

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### TradeService — 통합 인터페이스

상세 내용: [03-design-decisions.md](03-design-decisions.md)

#### 퍼블릭 메서드

상세 내용: [03-design-decisions.md](03-design-decisions.md)

### PositionReconciler — 포지션 정합성 검증 및 보정

상세 내용: [03-design-decisions.md](03-design-decisions.md)

## 이벤트 버스 연동 (EventBus Integration)

상세 내용: [04-eventbus-integration.md](04-eventbus-integration.md)

## CLI 사용

상세 내용: [05-cli-usage.md](05-cli-usage.md)

## 테스트 고려사항

상세 내용: [06-testing.md](06-testing.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [07-notification-events.md](07-notification-events.md)

### 체결 완료 — 매수

상세 내용: [07-notification-events.md](07-notification-events.md)

### 체결 완료 — 매도

상세 내용: [07-notification-events.md](07-notification-events.md)

### 주문 취소 실패

상세 내용: [07-notification-events.md](07-notification-events.md)

### 일일 성과 요약 (NotificationEvent)

상세 내용: [07-notification-events.md](07-notification-events.md)

### DailyReportScheduler

상세 내용: [07-notification-events.md](07-notification-events.md)

#### 실행 시각

상세 내용: [07-notification-events.md](07-notification-events.md)

#### 이벤트 발행

상세 내용: [07-notification-events.md](07-notification-events.md)

#### DailyReportEvent 필드

상세 내용: [07-notification-events.md](07-notification-events.md)

#### 일별 성과 산식

상세 내용: [07-notification-events.md](07-notification-events.md)

#### 퍼블릭 메서드

상세 내용: [07-notification-events.md](07-notification-events.md)

## 미결 사항

상세 내용: [08-open-issues.md](08-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [09-cross-module-notes.md](09-cross-module-notes.md)
