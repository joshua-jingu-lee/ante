# Broker Adapter 모듈 세부 설계


> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/broker/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 증권사 연동, [treasury.md](../treasury/treasury.md) 자금 관리 연동

이 디렉토리는 300줄을 넘던 모듈 스펙을 주제별 문서로 분할해 관리한다.
기존 링크와 앵커 호환을 위해 [broker-adapter.md](broker-adapter.md)를 개요 문서로 유지한다.

| 문서 | 내용 |
|---|---|
| [broker-adapter.md](broker-adapter.md) | 호환용 개요 문서 및 기존 섹션 앵커 |
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
