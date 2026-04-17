# Broker Adapter 모듈 세부 설계 - 주문 처리 흐름

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 주문 처리 흐름

### market/limit 주문 (즉시 실행)

```
Bot → OrderRequestEvent (market/limit)
  → RuleEngine 검증 → OrderValidatedEvent
  → Treasury 자금 예약 → OrderApprovedEvent
  → APIGateway rate limit → BrokerAdapter.place_order()
  → KIS API 주문 접수 → 주문번호 반환
  → 실시간 스트리밍으로 체결 확인 → OrderFilledEvent
  → Treasury 자금 정산 + Trade 포지션 업데이트
```

### stop/stop_limit 주문 (에뮬레이션)

```
Bot → OrderRequestEvent (stop/stop_limit)
  → RuleEngine 검증 → OrderValidatedEvent
  → Treasury 자금 예약 → OrderApprovedEvent
  → StopOrderManager에 등록 (가격 모니터링 대기)
  ↓
[가격 모니터링 중 — stop_price 도달 시]
  → stop → market 주문으로 변환
  → stop_limit → limit 주문으로 변환 (price 사용)
  → BrokerAdapter.place_order() 호출
  → 이하 동일 (체결 → 정산)
```
