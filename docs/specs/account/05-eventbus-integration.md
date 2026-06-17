# Account 모듈 세부 설계 - EventBus 연동

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# EventBus 연동

### 발행 이벤트

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `AccountSuspendedEvent` | `suspend()` 호출 시 | BotManager (소속 봇 전체 중지), RuleEngine, Notification |
| `AccountActivatedEvent` | `activate()` 호출 시 | BotManager (계좌 상태 변화 인지 + 로깅만; 자동 재시작은 수행하지 않음), RuleEngine, Notification |

`AccountCreatedEvent`와 `AccountDeletedEvent`는 1.0 런타임 EventBus 계약에 포함하지 않는다.
계좌 생성/삭제는 cold-path 전용이며 active Ante runtime이 없는 상태에서만 수행되므로,
EventBus 구독자에게 새 topology를 전파할 대상이 없다. cold-path delete는 consumer
wiring을 트리거하지 않으며, 따라서 `AccountDeletedEvent`는 `ante.eventbus.events`에
정의되지 않고 `AccountService.delete()`도 publish하지 않는다. 구조 변경 이력은 필요 시
감사 로그나 cold-path maintenance 결과로 남긴다.

### 구독 이벤트

Account 모듈 자체는 다른 이벤트를 구독하지 않는다. 수동적(조회 대상) 엔티티에 가깝다.

### Kill Switch 통합

기존 `SystemState` 모듈을 제거하고, Kill Switch를 Account.status로 일원화한다.

```bash
# 계좌별 Kill Switch
ante account suspend domestic       # domestic만 거래 정지
ante account activate domestic      # domestic 거래 재개

# 시스템 전역 Kill Switch (편의 명령)
ante system halt                    # 전체 거래 정지 (모든 ACTIVE 계좌를 SUSPENDED로 전환)
ante system clear-halt              # 전역 정지 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 자동 재시작은 수행하지 않음)
```

`ante system halt`는 모든 ACTIVE 계좌를 SUSPENDED로 전환한다. `ante system clear-halt`는 모든 SUSPENDED 계좌를 ACTIVE로 복구한다. DELETED 계좌는 영향받지 않는다. `clear-halt`는 계좌 상태만 ACTIVE로 복구할 뿐 자동 재시작은 수행하지 않는다 (BotManager는 `AccountActivatedEvent` 수신 시 로깅만 수행).

기존 `TradingStateChangedEvent`는 `AccountSuspendedEvent` / `AccountActivatedEvent`로 대체된다.

- `AccountSuspendedEvent`: BotManager가 해당 계좌의 소속 봇을 중지한다.
- `AccountActivatedEvent`: BotManager는 계좌 상태 변화를 인지하고 로깅만 수행한다. 자동 재시작은 수행하지 않는다.

재시작은 운영자가 명시적으로 `ante bot start <bot_id>` CLI로 수행한다. 런타임 중에는
IPC가 같은 BotManager 인스턴스를 통해 검증·실행·이벤트·감사 경로를 사용한다.

### Runtime readiness 자동축 vs SUSPENDED user축 (직교)

> 계약 확정: #2396. 실제 동작은 구현 #2397(축 i readiness 모델)·#2398(축 ii active-order gate) 머지 후. 본 절은 스펙 계약만 정의한다.

Kill Switch(`AccountStatus.SUSPENDED`)는 **user-initiated 축**이고, runtime readiness(`RuntimeReadinessRegistry`, [02-design-decisions.md — D-ACC-09](02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다))는 **service-health 자동축**이다. 두 축은 직교하며 효과만 일관한다.

| 항목 | SUSPENDED (user축) | runtime readiness (자동축) |
|---|---|---|
| 트리거 | `ante account suspend` / `system halt` (운영자) | startup 스케줄러 등록 실패 / 런타임 broker 저하 (자동) |
| SSOT | `Account.status` | `RuntimeReadinessRegistry` |
| 봇 영향 | `AccountSuspendedEvent` → BotManager 봇 중지 | **봇 stop 안 함** — active-order만 gate |
| active-order 효과 | 차단 | 차단 (둘 중 하나라도 막으면 거부) |
| `AccountStatus` 변경 | 직접 변경(SUSPENDED) | **변경 금지** (SUSPENDED 자동 전이 금지 — user 결정 침해 방지) |
| 회복 | `ante account activate` / `system clear-halt` (운영자) | self-healing background retry loop 유한시간 ready 전이 |

readiness `not_ready`는 SUSPENDED와 달리 봇을 stop하지 않는다. 봇은 계속 신호를 생성할 수 있으나 active-order만 gate(거부)된다([rule-engine/07-rule-engine-core.md](../rule-engine/07-rule-engine-core.md) "account readiness gate" 참조).

### Readiness SSOT 이중 실패모드 ([must_fix G], normative)

readiness `mark_not_ready`는 **두 실패모드 양쪽**에서 명시 호출한다 — `dict key 부재`만으로 not_ready를 표상하던 모호성을 제거한다.

1. **전역 gate**: `connected_count == 0`이면 `_init_fill_recovery` / `_init_reconcile`가 미호출되어 **전 계좌 키가 부재**한다. 이 경우 전 계좌에 대해 `mark_not_ready(id, flag, reason)`를 명시 호출한다.
2. **per-account continue**: 개별 계좌의 `get_broker` 실패로 그 계좌만 continue될 때, 해당 계좌에 대해 `mark_not_ready(id, flag, reason)`를 명시 호출한다.

readiness 전이 알림 방식(`RuntimeReadinessChangedEvent` 신설 vs registry 내부 + `NotificationEvent`만)은 open question으로 둔다(v1 미포함).
