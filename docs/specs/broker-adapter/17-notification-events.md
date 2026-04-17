# Broker Adapter 모듈 세부 설계 - 알림 이벤트 정의 (Notification Events)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# 알림 이벤트 정의 (Notification Events)

### 1. 포지션 불일치 감지

> 소스: `src/ante/trade/reconciler.py` — PositionReconciler

**트리거**: 대사(Reconcile) 수행 중 봇의 내부 포지션과 브로커 실제 포지션의 수량이 불일치할 때

**데이터 수집**:
- `TradeService.get_positions(bot_id)` → 내부 포지션 수량
- `BrokerAdapter.get_account_positions()` → 브로커 실제 수량

**발행 메시지**:

```
level: critical
title: 포지션 불일치
category: broker

봇: `{bot_id}` · 종목: `{symbol}`
내부: {internal_qty}주 · 브로커: {broker_qty}주
사유: {reason}
```

### 2. 서킷 브레이커 차단

> 소스: `src/ante/broker/circuit_breaker.py` — CircuitBreaker

**트리거**: 연속 실패 횟수가 임계치(`failure_threshold`)에 도달하여 CLOSED/HALF_OPEN → OPEN으로 전환될 때

**데이터 수집**:
- `CircuitBreaker._name` → 브로커 이름
- `old_state`, `new_state` → 상태 전환 정보
- `reason` → 전환 사유

**발행 메시지**:

```
level: error
title: 서킷 브레이커 차단
category: broker

브로커 `{broker_name}`
{old_state} → *{new_state}* ({reason})
```

### 3. 서킷 브레이커 복구

> 소스: `src/ante/broker/circuit_breaker.py` — CircuitBreaker

**트리거**: HALF_OPEN 상태에서 API 호출 성공하여 CLOSED로 전환될 때

**데이터 수집**:
- `CircuitBreaker._name` → 브로커 이름
- `old_state`, `new_state` → 상태 전환 정보
- `reason` → 전환 사유

**발행 메시지**:

```
level: info
title: 서킷 브레이커 복구
category: broker

브로커 `{broker_name}`
{old_state} → *{new_state}* ({reason})
```
