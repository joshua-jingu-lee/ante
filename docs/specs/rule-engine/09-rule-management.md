# Rule Engine 모듈 세부 설계 - 룰 정의 및 관리

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# 룰 정의 및 관리

계좌별 룰의 런타임 SSOT는 SQLite `dynamic_config` 테이블이다.
정적 TOML(`system.toml`)은 초기 bootstrap seed 또는 dynamic_config가 비어 있을 때의
fallback으로만 사용한다. 웹/API에서 룰을 수정하면 `dynamic_config`에 저장하고,
`ConfigChangedEvent`를 통해 해당 계좌의 RuleEngine이 재로드한다.

### DynamicConfig key namespace

| 범위 | key | category | value |
|------|-----|----------|-------|
| 계좌별 룰 | `accounts.{account_id}.rules` | `rule` | `list[RuleConfig]` |
| 전략별 룰 | `rules.strategy.{strategy_id}` | `strategy_rule` | `list[RuleConfig]` |

계좌별 룰 value는 rule config 객체의 리스트다. 개별 rule REST API는 특정 rule을 수정해도
저장 시 같은 `accounts.{account_id}.rules` 리스트 전체를 갱신한다. 따라서
`accounts.{account_id}.rules.{rule_type}` 같은 per-rule dynamic_config key는 사용하지 않는다.

```json
{
  "key": "accounts.domestic.rules",
  "category": "rule",
  "value": [
    {
      "type": "daily_loss_limit",
      "enabled": true,
      "max_daily_loss_rate": 0.05,
      "action": "halt"
    },
    {
      "type": "total_exposure_limit",
      "enabled": true,
      "max_exposure_rate": 0.8
    }
  ]
}
```

> `trading_hours` 룰의 시간대와 거래 시간은 Account 모델에서 자동 주입되므로, 룰 설정에서 별도로 지정하지 않는다. Account의 `trading_hours_start`, `trading_hours_end`, `timezone` 필드가 곧 TradingHoursRule의 설정이 된다.

### Stored rules vs effective rules

`accounts.{account_id}.rules` config는 사용자/Agent가 명시한 explicit
overrides(stored rules)다. 시스템이 RuleEngine에 적용하는 effective rules는
broker_type별 defaults와 stored overrides의 merge다.

- broker_type별 defaults: `kis-domestic`은 `trading_hours`를 자동 포함한다
  (KIS 모의투자/실거래 모두 KRX 장중에만 주문 수용; A7 oracle 회귀 #1296).
  `test` broker는 default가 없다(24h 거래 가정).
- merge 정책: type-key 기반. stored 항목이 default와 같은 `type`이면 stored가
  default를 override한다. 사용자/Agent는 `enabled: false`로 default를 명시
  비활성화할 수 있으며, audit/UI/API 응답에서 그 결정이 드러나야 한다
  (UI/API의 effective view는 후속 이슈).
- reload: `ConfigChangedEvent` 처리 시에도 같은 merge 정책이 적용되어, PUT
  이후 reload 결과가 default를 잃지 않는다.

GET/PUT API(`/api/accounts/{id}/rules*`)는 stored rules만 노출한다. effective
rules의 별도 노출은 본 스펙의 후속 이슈에서 다룬다.

### Static TOML seed

정적 TOML은 운영 중 룰 수정의 저장소가 아니다. 초기 계좌 seed나 복구용 기본값이 필요할
때만 같은 key shape를 만들 수 있는 TOML 구조를 둔다.

```toml
[accounts.domestic]
rules = [
  { type = "daily_loss_limit", enabled = true, max_daily_loss_rate = 0.05, action = "halt" },
  { type = "total_exposure_limit", enabled = true, max_exposure_rate = 0.8 },
]

[accounts.us-stock]
rules = [
  { type = "daily_loss_limit", enabled = true, max_daily_loss_rate = 0.03, action = "halt" },
  { type = "total_exposure_limit", enabled = true, max_exposure_rate = 0.7 },
]
```

시스템 시작 시 dynamic_config에 `accounts.{account_id}.rules`가 있으면 그 값을 우선한다.
없을 때만 정적 TOML seed를 읽어 RuleEngine 초기화에 사용한다. 런타임 수정은 항상
dynamic_config에 기록한다.

### 전략별 룰

전략별 룰은 계좌 설정 하위가 아니라 전략 key 하위에 정의한다:

```json
{
  "key": "rules.strategy.my_strategy",
  "category": "strategy_rule",
  "value": [
    {
      "type": "position_size",
      "enabled": true,
      "max_position_percent": 0.10,
      "max_position_amount": 1000.0
    }
  ]
}
```

API 응답에서는 rule type, enabled, params를 분리해 반환하지만 저장 value는
RuleEngine이 로드하는 flat rule config list를 유지한다.

```json
{
  "rules": [
    {
      "type": "position_size",
      "enabled": true,
      "params": {
        "max_position_percent": 0.10,
        "max_position_amount": 1000.0
      }
    }
  ]
}
```
