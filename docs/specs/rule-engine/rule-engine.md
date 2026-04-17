# Rule Engine 모듈 세부 설계


> :warning: 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/rule/` 을 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 주문 처리 흐름, [AGENTS.md](../../../AGENTS.md) 거래 룰 (2중 구조), [notification.md](../notification/notification.md) 알림 발송

이 문서는 분할된 `rule-engine` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
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

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### FreqTrade의 보호 메커니즘

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### NautilusTrader의 리스크 엔진

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### Ante 룰 엔진 설계 방향

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 2계층 평가 흐름

상세 내용: [03-two-layer-evaluation.md](03-two-layer-evaluation.md)

### 룰 충돌 해결 규칙

상세 내용: [03-two-layer-evaluation.md](03-two-layer-evaluation.md)

## 룰 인터페이스 (Rule ABC)

상세 내용: [04-rule-interface.md](04-rule-interface.md)

### Rule 클래스 메서드

상세 내용: [04-rule-interface.md](04-rule-interface.md)

### RuleResult (Enum)

상세 내용: [04-rule-interface.md](04-rule-interface.md)

### RuleAction (Enum)

상세 내용: [04-rule-interface.md](04-rule-interface.md)

### RuleEvaluation (dataclass, frozen)

상세 내용: [04-rule-interface.md](04-rule-interface.md)

## RuleContext

상세 내용: [05-rule-context.md](05-rule-context.md)

### EvaluationResult (dataclass)

상세 내용: [05-rule-context.md](05-rule-context.md)

## 구체적 룰 목록

상세 내용: [06-rule-catalog.md](06-rule-catalog.md)

### 계좌 룰 (Account Rules)

상세 내용: [06-rule-catalog.md](06-rule-catalog.md)

### 전략별 룰 (Strategy Rules)

상세 내용: [06-rule-catalog.md](06-rule-catalog.md)

## RuleEngine 코어

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 생성자

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 의존성

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 이벤트 구독

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 룰 레지스트리

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 퍼블릭 메서드

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

### 주요 동작

상세 내용: [07-rule-engine-core.md](07-rule-engine-core.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [08-notification-events.md](08-notification-events.md)

### 일일 손실 한도 초과

상세 내용: [08-notification-events.md](08-notification-events.md)

### 총 노출 한도 초과

상세 내용: [08-notification-events.md](08-notification-events.md)

## 룰 정의 및 관리

상세 내용: [09-rule-management.md](09-rule-management.md)

## RuleEngineManager

상세 내용: [10-rule-engine-manager.md](10-rule-engine-manager.md)

### 생성자

상세 내용: [10-rule-engine-manager.md](10-rule-engine-manager.md)

### 퍼블릭 메서드

상세 내용: [10-rule-engine-manager.md](10-rule-engine-manager.md)

### initialize_all 동작

상세 내용: [10-rule-engine-manager.md](10-rule-engine-manager.md)

## REST API

상세 내용: [11-rest-api.md](11-rest-api.md)

### GET /api/accounts/{account_id}/rules

상세 내용: [11-rest-api.md](11-rest-api.md)

### PUT /api/accounts/{account_id}/rules/{rule_type}

상세 내용: [11-rest-api.md](11-rest-api.md)

## CLI 인터페이스

상세 내용: [12-cli.md](12-cli.md)

## 미결 사항

상세 내용: [13-open-issues.md](13-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [14-cross-module-notes.md](14-cross-module-notes.md)
