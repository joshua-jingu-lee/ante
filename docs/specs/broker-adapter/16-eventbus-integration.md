# Broker Adapter 모듈 세부 설계 - 이벤트 버스 연동 (EventBus Integration)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `CircuitBreakerEvent` | 서킷 브레이커 상태 전환 시 (CLOSED↔OPEN↔HALF_OPEN) | 로깅, 모니터링 |
| `StreamConnectedEvent` | 웹소켓 연결 수립 시 | 로깅 |
| `StreamDisconnectedEvent` | 웹소켓 연결 해제 시 | 로깅 |
| `PositionMismatchEvent` | 대사 중 포지션 불일치 감지 시 | 로깅, 감사 |
| `ReconcileEvent` | 대사 완료 시 | 로깅 |
| `NotificationEvent` | 포지션 불일치, 서킷 브레이커 차단/복구 시 | NotificationService → Telegram 어댑터 (category: "broker") |
