# Rule Engine 모듈 세부 설계 - RuleEngineManager

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# RuleEngineManager

> 소스: `src/ante/rule/manager.py`

계좌별 RuleEngine 인스턴스를 관리하는 상위 계층.

### 생성자

```python
RuleEngineManager(eventbus: EventBus, account_service: AccountService)
```

### 퍼블릭 메서드

| 메서드 | 시그니처 | 설명 |
|--------|----------|------|
| `create_engine` | `(self, account_id: str, rule_configs: list[dict]) -> RuleEngine` | 계좌별 RuleEngine 생성. EventBus에 자동 구독 |
| `get` | `(self, account_id: str) -> RuleEngine` | 계좌의 RuleEngine 인스턴스 반환 |
| `initialize_all` | `async (self, accounts: list[Account], config: Config) -> None` | 시스템 시작 시 모든 계좌의 RuleEngine 초기화. `config`는 `accounts.{account_id}.rules` seed/fallback source이며, 런타임 SSOT는 `dynamic_config` |

### initialize_all 동작

각 계좌에 대해 RuleEngine을 생성하고, 계좌별 룰 설정을 로드한다.
`dynamic_config`에 `accounts.{account_id}.rules`가 있으면 그 값이 우선하며,
없을 때만 정적 Config seed를 fallback으로 사용한다. `TradingHoursRule`의 시간대와 거래
시간은 Account 모델에서 자동 주입한다. 런타임 변경은 `ConfigChangedEvent`를 통해 대상
계좌 RuleEngine에 반영한다.
