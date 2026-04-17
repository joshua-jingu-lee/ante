# Broker Adapter 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/broker/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 증권사 연동, [treasury.md](../treasury/treasury.md) 자금 관리 연동

이 문서는 분할된 `broker-adapter` 스펙의 호환용 개요 문서다.
전체 인덱스는 [README.md](README.md)를, 세부 내용은 아래 하위 문서를 참조한다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) | 분할 인덱스 |
| [01-overview.md](01-overview.md) | 개요 |
| [02-reference-implementations.md](02-reference-implementations.md) | 참고 구현체 분석 |
| [03-adapter-layer.md](03-adapter-layer.md) | 어댑터 계층 구조 |
| [04-broker-adapter-interface.md](04-broker-adapter-interface.md) | BrokerAdapter 인터페이스 (ABC) |
| [05-broker-registry.md](05-broker-registry.md) | BROKER_REGISTRY — 브로커 타입 레지스트리 |
| [06-broker-presets.md](06-broker-presets.md) | BROKER_PRESETS — 브로커 기본값 프리셋 |
| [07-kis-base-adapter.md](07-kis-base-adapter.md) | KISBaseAdapter — KIS 공통 레이어 |
| [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md) | KISDomesticAdapter — 국내주식 전용 |
| [09-kis-overseas-adapter.md](09-kis-overseas-adapter.md) | KISOverseasAdapter — 해외주식 전용 (1.1 범위) |
| [10-commission-info.md](10-commission-info.md) | CommissionInfo |
| [11-order-flow.md](11-order-flow.md) | 주문 처리 흐름 |
| [12-test-broker-adapter.md](12-test-broker-adapter.md) | TestBrokerAdapter — 개발/검증용 테스트 브로커 |
| [13-setup-and-initialization.md](13-setup-and-initialization.md) | 설정 및 초기화 |
| [14-cli.md](14-cli.md) | CLI 인터페이스 |
| [15-reconciliation.md](15-reconciliation.md) | 대사 (Reconciliation) |
| [16-eventbus-integration.md](16-eventbus-integration.md) | 이벤트 버스 연동 (EventBus Integration) |
| [17-notification-events.md](17-notification-events.md) | 알림 이벤트 정의 (Notification Events) |
| [18-open-issues.md](18-open-issues.md) | 미결 사항 |
| [19-scope-out.md](19-scope-out.md) | 스펙 아웃 (Scope-out) |

## 개요

상세 내용: [01-overview.md](01-overview.md)

## 참고 구현체 분석

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### 한국투자증권 Open API 구조

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### FreqTrade의 거래소 추상화

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

### Ante Broker Adapter 설계 방향

상세 내용: [02-reference-implementations.md](02-reference-implementations.md)

## 어댑터 계층 구조

상세 내용: [03-adapter-layer.md](03-adapter-layer.md)

## BrokerAdapter 인터페이스 (ABC)

상세 내용: [04-broker-adapter-interface.md](04-broker-adapter-interface.md)

### 클래스 변수

상세 내용: [04-broker-adapter-interface.md](04-broker-adapter-interface.md)

### 인스턴스 속성

상세 내용: [04-broker-adapter-interface.md](04-broker-adapter-interface.md)

### 메서드 시그니처

상세 내용: [04-broker-adapter-interface.md](04-broker-adapter-interface.md)

## BROKER_REGISTRY — 브로커 타입 레지스트리

상세 내용: [05-broker-registry.md](05-broker-registry.md)

## BROKER_PRESETS — 브로커 기본값 프리셋

상세 내용: [06-broker-presets.md](06-broker-presets.md)

## KISBaseAdapter — KIS 공통 레이어

상세 내용: [07-kis-base-adapter.md](07-kis-base-adapter.md)

### 공통 로직

상세 내용: [07-kis-base-adapter.md](07-kis-base-adapter.md)

### KIS API 특성 요약

상세 내용: [07-kis-base-adapter.md](07-kis-base-adapter.md)

## KISDomesticAdapter — 국내주식 전용

상세 내용: [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md)

### 분리된 국내 전용 로직

상세 내용: [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md)

### 주요 API 엔드포인트

상세 내용: [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md)

### KIS 주문 유형 매핑

상세 내용: [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md)

### KIS 주문 상태 코드 매핑

상세 내용: [08-kis-domestic-adapter.md](08-kis-domestic-adapter.md)

## KISOverseasAdapter — 해외주식 전용 (1.1 범위)

상세 내용: [09-kis-overseas-adapter.md](09-kis-overseas-adapter.md)

### 국내/해외 분리 요약

상세 내용: [09-kis-overseas-adapter.md](09-kis-overseas-adapter.md)

## CommissionInfo

상세 내용: [10-commission-info.md](10-commission-info.md)

### CircuitBreaker

상세 내용: [10-commission-info.md](10-commission-info.md)

### 에러 코드 분류

상세 내용: [10-commission-info.md](10-commission-info.md)

### 에러 처리 및 재시도

상세 내용: [10-commission-info.md](10-commission-info.md)

### ~~실시간 스트리밍 — KISStreamClient~~ (스펙 아웃)

상세 내용: [10-commission-info.md](10-commission-info.md)

## 주문 처리 흐름

상세 내용: [11-order-flow.md](11-order-flow.md)

### market/limit 주문 (즉시 실행)

상세 내용: [11-order-flow.md](11-order-flow.md)

### stop/stop_limit 주문 (에뮬레이션)

상세 내용: [11-order-flow.md](11-order-flow.md)

## TestBrokerAdapter — 개발/검증용 테스트 브로커

상세 내용: [12-test-broker-adapter.md](12-test-broker-adapter.md)

### MockBrokerAdapter와의 차이

상세 내용: [12-test-broker-adapter.md](12-test-broker-adapter.md)

### 생성자 파라미터

상세 내용: [12-test-broker-adapter.md](12-test-broker-adapter.md)

### PriceSimulator — GBM 기반 가격 시뮬레이션

상세 내용: [12-test-broker-adapter.md](12-test-broker-adapter.md)

### 체결 시뮬레이션

상세 내용: [12-test-broker-adapter.md](12-test-broker-adapter.md)

## 설정 및 초기화

상세 내용: [13-setup-and-initialization.md](13-setup-and-initialization.md)

### 브로커 전환

상세 내용: [13-setup-and-initialization.md](13-setup-and-initialization.md)

### 설정 예시

상세 내용: [13-setup-and-initialization.md](13-setup-and-initialization.md)

## CLI 인터페이스

상세 내용: [14-cli.md](14-cli.md)

## 대사 (Reconciliation)

상세 내용: [15-reconciliation.md](15-reconciliation.md)

### PositionReconciler — 포지션 정합성 검증·보정

상세 내용: [15-reconciliation.md](15-reconciliation.md)

### OrderRegistry — order_id → bot_id 매핑

상세 내용: [15-reconciliation.md](15-reconciliation.md)

### ReconcileScheduler — 주기적 대사

상세 내용: [15-reconciliation.md](15-reconciliation.md)

### 대사 실행 시점

상세 내용: [15-reconciliation.md](15-reconciliation.md)

## 이벤트 버스 연동 (EventBus Integration)

상세 내용: [16-eventbus-integration.md](16-eventbus-integration.md)

## 알림 이벤트 정의 (Notification Events)

상세 내용: [17-notification-events.md](17-notification-events.md)

### 1. 포지션 불일치 감지

상세 내용: [17-notification-events.md](17-notification-events.md)

### 2. 서킷 브레이커 차단

상세 내용: [17-notification-events.md](17-notification-events.md)

### 3. 서킷 브레이커 복구

상세 내용: [17-notification-events.md](17-notification-events.md)

## 미결 사항

상세 내용: [18-open-issues.md](18-open-issues.md)

## 스펙 아웃 (Scope-out)

상세 내용: [19-scope-out.md](19-scope-out.md)

### 실시간 스트리밍 (`realtime_price_stream`, `realtime_order_stream`)

상세 내용: [19-scope-out.md](19-scope-out.md)

### KISOverseasAdapter 구현

상세 내용: [19-scope-out.md](19-scope-out.md)
