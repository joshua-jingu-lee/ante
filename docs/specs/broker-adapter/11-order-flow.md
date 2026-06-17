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

### Active-order readiness gate (계층 3, 최후보루, #2396)

> 계약 확정: #2396. 실제 동작은 구현 #2397(축 i readiness 모델, 선행) + #2398(축 ii active-order gate) 머지 후. 본 절은 스펙 계약만 정의한다.

`gateway.submit_order`(`_on_order_approved` 경로)는 active-order readiness gate(계층 3, fail-closed)를 적용한다. 이는 [account/02-design-decisions.md — D-ACC-09](../account/02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다)의 3계층 defense-in-depth 중 최후보루다.

- **위치**: `_get_broker` 직전 `runtime_readiness.active_trading_ready(account_id)`를 체크한다. `not_ready`면 broker를 호출하지 않는다.
- **fail-closed**: registry 미주입 / 조회 예외도 `not_ready`로 취급해 차단한다. 런타임 저하(토큰 만료·세션 단절, `is_connected` 미토글)는 계층3 fail-closed가 백스톱이다([must_fix E]).

**reserve 해제 정합 (load-bearing invariant, [must_fix I], normative)**: 계층 3 시점엔 이미 Treasury reserve가 잡혀 있다(계층1·2를 통과한 후 `OrderApprovedEvent`가 발행됐기 때문). 따라서 계층3 거부는 **반드시** `OrderApprovedEvent` payload의 `bot_id` + `order_id` + `account_id`를 보존한 `OrderFailedEvent`로 귀결되어야 한다. Treasury `_on_order_failed`가 이 이벤트를 구독해 `release_reservation(bot_id, order_id)` + `_is_my_event(account_id)`로 reserve를 정확 해제한다(`reserved_amount`는 해제 키가 아니다 — 내부 ledger 조회).

구현상 `submit_order`가 `error_code="account_not_ready"`인 `APIError`를 raise하면, 기존 `_on_order_approved`의 except가 `OrderFailedEvent`로 자동 변환한다. **직접 raise만 하고 `OrderFailedEvent`를 미발행(except 우회)하면 reserve가 영구 고착되어 회귀**하므로 normative로 명시한다.

**defense-in-depth 3계층 census (단일 EventBus 파이프라인)**:

| 계층 | 위치 | 발행 이벤트 | reserve 상태 |
|---|---|---|---|
| 계층1 | `RuleEngine._on_order_request` (account_id 필터 직후) | `OrderRejectedEvent` | reserve 이전 — 누수 없음 |
| 계층2 | `Treasury._on_order_validated` (reserve 직전) | `OrderRejectedEvent` | reserve 미실행 — 해제 불요 |
| 계층3 | `gateway.submit_order` (`_get_broker` 직전) | `OrderFailedEvent` | reserve 잡힘 — 정확 해제 트리거 |

reason 토큰은 `account_not_ready`로 통일(SSOT)하고, 상세는 missing flag 목록 suffix로 붙인다. 세 계층 모두 `NotificationEvent(level=error, category=system)`를 1회 발행해 운영자 가시성을 보장한다.
