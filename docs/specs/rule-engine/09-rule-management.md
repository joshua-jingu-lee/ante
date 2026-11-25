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
      "max_daily_loss_percent": 0.05
    },
    {
      "type": "total_exposure_limit",
      "enabled": true,
      "max_exposure_percent": 0.8
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
  (KIS 모의투자/실거래 모두 KRX 장중에만 주문 수용).
  `test` broker는 default가 없다(24h 거래 가정).
- merge 정책: type-key 기반. stored 항목이 default와 같은 `type`이면 stored가
  default를 override한다. 사용자/Agent는 `enabled: false`로 default를 명시
  비활성화할 수 있으며, audit/CLI 응답에서 그 결정이 드러나야 한다
  (effective view는 후속 이슈).
- reload: `ConfigChangedEvent` 처리 시에도 같은 merge 정책이 적용되어, update
  이후 reload 결과가 default를 잃지 않는다.

CLI `rule update`는 stored rules만 갱신한다. effective rules의 별도 노출은 본
스펙의 후속 이슈에서 다룬다.
`enabled`(CLI `--enabled/--disabled`, IPC `rule.update.enabled`)를 생략하거나
`null`로 보내면 동적 설정(`accounts.{id}.rules`)에 저장된 같은 type의 항목의 값을
유지하고, 그 항목이 없으면 `true`다(데몬 없이 직접 실행할 때 동적 설정이 비어 있으면
정적 TOML seed에 있는 같은 type 항목의 값을 쓴다).

`rule update`의 params(CLI `--param`·`--params-json`, IPC `rule.update.params`)는 규칙
항목의 `type`·`id`·`enabled`를 담을 수 없다 — 담으면 저장하지 않고 요청을 거부한다(규칙
종류는 명령의 인자로, 켜고 끄기는 `enabled`로 지정한다). 이 세 key는 API 응답에서 params와
분리되는 key와 같다.

params의 `priority`는 규칙의 평가 순서([03-two-layer-evaluation.md](03-two-layer-evaluation.md))로
항목에 저장되며, 정수(bool 제외)가 아니면 저장하지 않고 거부한다.

params에는 공통 key(`name`·`description`·`priority`)와 그 규칙이 읽는 key만 담을 수 있다. 그 밖의
key(오타, 다른 규칙의 key 등)가 있으면 저장하지 않고 거부한다. 규칙별 key는
[06-rule-catalog.md](06-rule-catalog.md)에 있고, 정본은 코드다.

### Static TOML seed

정적 TOML은 운영 중 룰 수정의 저장소가 아니다. 초기 계좌 seed나 복구용 기본값이 필요할
때만 같은 key shape를 만들 수 있는 TOML 구조를 둔다.

```toml
[accounts.domestic]
rules = [
  { type = "daily_loss_limit", enabled = true, max_daily_loss_percent = 0.05 },
  { type = "total_exposure_limit", enabled = true, max_exposure_percent = 0.8 },
]

[accounts.us-stock]
rules = [
  { type = "daily_loss_limit", enabled = true, max_daily_loss_percent = 0.03 },
  { type = "total_exposure_limit", enabled = true, max_exposure_percent = 0.7 },
]
```

시스템 시작 시 dynamic_config에 `accounts.{account_id}.rules`가 있으면 그 값을 우선한다.
행이 없을 때만 정적 TOML seed를 읽어 RuleEngine 초기화에 사용한다. 행이 있는데 값이
리스트가 아니거나 읽지 못하면 seed나 기본 룰로 가지 않는다 — 그 계좌의 RuleEngine은
계좌 룰 없이 `rules_unavailable` 상태로 떠서 그 계좌의 신규 주문과 정정을
`account_not_ready: rules_unavailable`로 거부하고, 알림 서비스가 켜져 있으면 기동 뒤
운영자 알림을 한 번 보낸다. 다른 계좌와 데몬은 정상으로 뜬다. 그 계좌에 `ante rule update`로
룰을 한 번 저장하면 저장값이 그 룰을 담은 리스트로 다시 쓰이고 차단이 풀린다(데몬이 떠
있으면 재기동 없이). 깨지기 전의 다른 룰은 복원되지 않는다 —
`ante config history accounts.<account_id>.rules`로 이전 값을 확인해 다시 저장한다.
리스트 안의 항목으로 룰을 만들거나 정렬하다 예외가 나도(사전이 아닌 항목, 비교할 수 없는
`priority`, 규칙이 읽지 않는 key, 범위 밖·NaN·Inf 값, 문자열이 아닌 `id`, 없거나 등록된 문자열이 아닌
`type` 등 — `enabled`와 무관)
그 계좌만 같은 방식으로 막히고 다른 계좌와 데몬은 뜬다. 이때 다른 항목은 저장값에 그대로 남는다.
등록된 type마다 첫 항목의 원인(규칙이 읽지 않는 key, 범위 밖 값, 비교할 수 없는 `priority`, 문자열이 아닌
`id`)은 그 type으로 `ante rule update`를 한 번 하면 풀린다(그런 type이 여럿이면 type마다 한 번).
`rule update`는 저장하기 전에 사전이 아닌 항목, `type`이 없거나 등록된 문자열이 아닌 항목(첫 항목이어도),
등록된 같은 type의 둘째 이후 항목 가운데 룰로 만들 수 없는 것을 저장값에서 버리므로, 이 셋으로 막힌
계좌는 어느 type으로든 한 번 하면 풀린다. 같은 type의 멀쩡한 둘째 이후 항목은 남는다. 버린 항목은
경고 로그(데몬 경로에서는 운영자 알림도)와 `rule update`의 응답으로 드러나고, 원문은 `ante config history`의
이전 값(seed에서 읽었으면 설정 파일)에 남는다(판정의 세부는 [07-rule-engine-core.md](07-rule-engine-core.md)).
`rule update`의 응답(데몬 없는 CLI와 IPC `rule.update`가 같은 모양)에는 기존 키에 더해 `dropped_items`가
늘 실린다. 버린 항목마다 `{"stored_index": <읽은 목록에서의 위치>, "rule_type": <type이 문자열이면 그 값, 아니면 null>}`을
읽은 순서대로 담고, 버린 것이 없으면 `[]`이다. 저장값의 다른 내용(파라미터 값)은 싣지 않는다. text 출력은
`dropped_items`가 비어 있지 않을 때만 둘째 줄에 그 수와 위치·유형 이름(repr로 이스케이프)과 원문의 위치를 알린다.
런타임 수정은 항상 dynamic_config에 기록한다.

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
