# Account 모듈 세부 설계 - EventBus 연동

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# EventBus 연동

### 발행 이벤트

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `AccountSuspendedEvent` | `suspend()` 또는 `delete()` 호출 시 | BotManager (소속 봇 전체 중지) |
| `AccountActivatedEvent` | `activate()` 호출 시 | — |
| `AccountDeletedEvent` | `delete()` 호출 시 | — |

### 구독 이벤트

Account 모듈 자체는 다른 이벤트를 구독하지 않는다. 수동적(조회 대상) 엔티티에 가깝다.

### Kill Switch 통합

기존 `SystemState` 모듈을 제거하고, Kill Switch를 Account.status로 일원화한다.

```bash
# 계좌별 Kill Switch
ante account suspend domestic       # domestic만 거래 정지
ante account activate domestic      # domestic 거래 재개

# 시스템 전체 Kill Switch (편의 명령, 모든 ACTIVE 계좌를 suspend)
ante system halt                    # 전체 거래 정지
ante system activate                # 전체 거래 재개
```

`ante system halt`는 모든 ACTIVE 계좌를 SUSPENDED로 전환한다. `ante system activate`는 모든 SUSPENDED 계좌를 ACTIVE로 복구한다. DELETED 계좌는 영향받지 않는다.

기존 `TradingStateChangedEvent`는 `AccountSuspendedEvent` / `AccountActivatedEvent`로 대체되며, BotManager가 이를 구독하여 해당 계좌의 봇만 중지/재개한다.
