# Account 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/account/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 계좌 관리, [bot.md](../bot/bot.md) 봇 모듈, [treasury.md](../treasury/treasury.md) 자금 관리, [broker-adapter.md](../broker-adapter/broker-adapter.md) 브로커 어댑터

이 문서는 분할된 `account` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-design-decisions.md](02-design-decisions.md) | 설계 결정 |
| [03-data-model.md](03-data-model.md) | 데이터 모델 |
| [04-account-service.md](04-account-service.md) | AccountService 인터페이스 |
| [05-eventbus-integration.md](05-eventbus-integration.md) | EventBus 연동 |
| [06-database-schema.md](06-database-schema.md) | 데이터베이스 스키마 |
| [07-account-layout-v1.md](07-account-layout-v1.md) | 1.0 시점 계좌 구성 |
| [08-config-migration.md](08-config-migration.md) | config/defaults.py 마이그레이션 |
| [09-cli.md](09-cli.md) | CLI 인터페이스 |
| [10-web-api.md](10-web-api.md) | Web API 엔드포인트 |
| [11-scope-out.md](11-scope-out.md) | Scope Out (1.0에서 제외) |
| [12-open-issues.md](12-open-issues.md) | 미결 사항 |
| [13-cross-module-notes.md](13-cross-module-notes.md) | 타 모듈 설계 시 참고 |

## 개요

상세 내용: [01-overview.md](01-overview.md)

### Account가 하지 않는 것

상세 내용: [01-overview.md](01-overview.md)

### Account 중심의 모듈 구조

상세 내용: [01-overview.md](01-overview.md)

## 설계 결정

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### D-ACC-01: 왜 Account가 최상위 엔티티인가

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### D-ACC-02: KIS 국내/해외가 같은 계좌번호인데 왜 분리하는가

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### D-ACC-03: Strategy는 왜 Account 밖인가

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### D-ACC-04: Data Store와 Backtest는 왜 Account 밖인가

상세 내용: [02-design-decisions.md](02-design-decisions.md)

### D-ACC-05: ante init에서 계좌를 어떻게 다루는가

상세 내용: [02-design-decisions.md](02-design-decisions.md)

## 데이터 모델

상세 내용: [03-data-model.md](03-data-model.md)

### AccountStatus

상세 내용: [03-data-model.md](03-data-model.md)

### TradingMode

상세 내용: [03-data-model.md](03-data-model.md)

### Account

상세 내용: [03-data-model.md](03-data-model.md)

### 필드 설명

상세 내용: [03-data-model.md](03-data-model.md)

### 불변 필드 정책 (D-ACC-06)

상세 내용: [03-data-model.md](03-data-model.md)

### BrokerPreset

상세 내용: [03-data-model.md](03-data-model.md)

### BROKER_PRESETS

상세 내용: [03-data-model.md](03-data-model.md)

### BROKER_REGISTRY

상세 내용: [03-data-model.md](03-data-model.md)

## AccountService 인터페이스

상세 내용: [04-account-service.md](04-account-service.md)

### 생성자

상세 내용: [04-account-service.md](04-account-service.md)

### 퍼블릭 메서드

상세 내용: [04-account-service.md](04-account-service.md)

### 브로커 인스턴스 생성

상세 내용: [04-account-service.md](04-account-service.md)

### 에러 클래스

상세 내용: [04-account-service.md](04-account-service.md)

## EventBus 연동

상세 내용: [05-eventbus-integration.md](05-eventbus-integration.md)

### 발행 이벤트

상세 내용: [05-eventbus-integration.md](05-eventbus-integration.md)

### 구독 이벤트

상세 내용: [05-eventbus-integration.md](05-eventbus-integration.md)

### Kill Switch 통합

상세 내용: [05-eventbus-integration.md](05-eventbus-integration.md)

## 데이터베이스 스키마

상세 내용: [06-database-schema.md](06-database-schema.md)

### credentials 암호화

상세 내용: [06-database-schema.md](06-database-schema.md)

## 1.0 시점 계좌 구성

상세 내용: [07-account-layout-v1.md](07-account-layout-v1.md)

## config/defaults.py 마이그레이션

상세 내용: [08-config-migration.md](08-config-migration.md)

### Account로 이동하는 설정

상세 내용: [08-config-migration.md](08-config-migration.md)

### 시스템 레벨에 유지하는 설정

상세 내용: [08-config-migration.md](08-config-migration.md)

### 삭제 또는 Account 파생으로 전환하는 설정

상세 내용: [08-config-migration.md](08-config-migration.md)

## CLI 인터페이스

상세 내용: [09-cli.md](09-cli.md)

### CLI 출력 예시

상세 내용: [09-cli.md](09-cli.md)

## Web API 엔드포인트

상세 내용: [10-web-api.md](10-web-api.md)

### 계좌 전용 엔드포인트

상세 내용: [10-web-api.md](10-web-api.md)

### 기존 엔드포인트 계좌 필터

상세 내용: [10-web-api.md](10-web-api.md)

## Scope Out (1.0에서 제외)

상세 내용: [11-scope-out.md](11-scope-out.md)

## 미결 사항

상세 내용: [12-open-issues.md](12-open-issues.md)

## 타 모듈 설계 시 참고

상세 내용: [13-cross-module-notes.md](13-cross-module-notes.md)
