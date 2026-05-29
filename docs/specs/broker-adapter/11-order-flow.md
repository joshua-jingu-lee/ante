# Broker Adapter 모듈 세부 설계 - 주문 처리 흐름

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 주문 처리 흐름

### market/limit 주문 (즉시 실행)

```
Bot → OrderRequestEvent (market/limit)
  → RuleEngine 검증 → OrderValidatedEvent
  → Treasury 자금 예약 → OrderApprovedEvent
  → APIGateway rate limit → BrokerAdapter.place_order()
  → KIS API 주문 접수 → 주문번호 반환 → OrderSubmittedEvent → OrderTracker.open(…)
  → 체결 확인 → OrderFilledEvent
        - 빠른 경로: 실시간 체결 통보 스트림 (선택적, 저지연)
        - 백스톱  : REST get_order_history 폴 (정합성 보증, 항상)
        둘 다 단일 멱등 choke point(FillApplier)로 수렴 → 포지션 정확히 1회 반영
  → Treasury 자금 정산 + Trade 포지션 업데이트
```

**체결 확인 경로 (#1946)**: `OrderFilledEvent`는 실시간 체결 통보 스트림(빠른
경로)으로만 발행하지 않는다. 스트림 유무·모의투자·실전투자 무관하게 체결이 내부에
반영되도록, REST `get_order_history` 백스톱 폴(`FillReconcileScheduler`)이 정합성을
보증한다. 두 경로는 `FillApplier`(단일 멱등 choke point)로 수렴하여 같은 체결을
몇 번 관측하든 포지션은 정확히 한 번 반영된다. 상세는
[18-fill-recovery.md](18-fill-recovery.md)를 참조한다.

### stop/stop_limit 주문 (에뮬레이션)

매수 stop / stop_limit은 등록 시점에 자금을 잠그지 않고, 트리거 발동 후 변환된 일반 매수 주문이 정상 reserve 절차를 거친다 (#1337). 매도 stop은 자금 reserve와 무관하다.

```
Bot → OrderRequestEvent (stop/stop_limit)
  → RuleEngine 검증 → OrderValidatedEvent
  → Treasury 분기 처리:
        - 매수 stop/stop_limit  → reserve 없이 OrderApprovedEvent(reserved_amount=0.0)
        - 매도 stop/stop_limit  → reserve 없이 OrderApprovedEvent(reserved_amount=0.0)
  → StopOrderManager에 등록 (가격 모니터링 대기. 자금 잠금 없음.)
  ↓
[가격 모니터링 중 — stop_price 도달 시]
  → stop → market 주문으로 변환된 OrderRequestEvent 발행
  → stop_limit → limit 주문으로 변환된 OrderRequestEvent 발행 (price 사용)
  → 변환 주문이 일반 매수 흐름 진입:
        RuleEngine 검증 → OrderValidatedEvent
        → Treasury reserve_for_order (매수 시 처음 자금 잠금)
        → OrderApprovedEvent (reserved_amount > 0)
        → BrokerAdapter.place_order()
  → 이하 동일 (체결 → 정산)
```

**자금 처리 invariant (#1337)**:

- 등록 시점 자금 잠금 없음. 사용자(또는 다른 봇)는 같은 자금으로 다른 매수 주문을 자유롭게 걸 수 있다.
- 트리거 변환 주문은 일반 `OrderRequestEvent`와 구분되지 않으므로 RuleEngine/Treasury는 변환 주문을 stop이 아닌 일반 주문으로 처리해 한 번만 reserve를 수행한다 (double reserve 방지).
- 트리거 시점에 자금 부족이면 일반 매수 주문 실패와 동일하게 거부된다.
- stop 주문 취소·만료 시 Treasury 호출 불필요 (잠근 게 없으므로 풀 것도 없음).

상세 모듈 분담은 [`treasury/04-treasury-interface.md`](../treasury/04-treasury-interface.md)의 "Reserve 정책" 섹션과 [`api-gateway/api-gateway.md`](../api-gateway/api-gateway.md)의 "StopOrderManager — 자금 처리 정책 (#1337)" 섹션을 참조한다.
