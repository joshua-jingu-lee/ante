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
