# Rule Engine 모듈 세부 설계 - REST API

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# REST API

> 참조: [web-api.md](../web-api/web-api.md) 계좌 관리 섹션

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/accounts/{account_id}/rules` | 계좌의 리스크 룰 목록 조회 |
| PUT | `/api/accounts/{account_id}/rules/{rule_type}` | 개별 룰 설정 수정 |

### GET /api/accounts/{account_id}/rules

DynamicConfig에서 `accounts.{account_id}.rules` 키를 읽어 RULE_REGISTRY 기반으로 구조화하여
반환한다. DynamicConfig 값이 없을 때만 정적 Config seed를 fallback으로 읽는다.

**응답**:
```json
{
  "rules": [
    {
      "type": "daily_loss_limit",
      "enabled": true,
      "params": {
        "max_daily_loss_rate": 0.05,
        "action": "halt"
      }
    }
  ]
}
```

- RULE_REGISTRY에 등록된 룰 타입만 반환한다.
- 저장 value는 flat rule config list지만 API 응답은 `type`, `enabled`, `params`로 분리한다.

### PUT /api/accounts/{account_id}/rules/{rule_type}

**요청 Body**:
```json
{
  "enabled": true,
  "params": {
    "max_daily_loss_rate": 0.03,
    "action": "halt"
  }
}
```

**검증 흐름**:
1. `rule_type`이 RULE_REGISTRY에 존재하는지 확인 (404 if not)
2. `params`의 각 키가 해당 룰의 param_schema에 정의된 타입·범위에 맞는지 검증 (422 if invalid)
3. DynamicConfig의 `accounts.{account_id}.rules` 리스트를 조회한다.
4. 해당 `rule_type` 항목을 교체하거나 새로 추가한다.
5. DynamicConfigService `set(key="accounts.{account_id}.rules", category="rule")`로 리스트 전체를 저장한다.
6. `ConfigChangedEvent(category="rule", key="accounts.{account_id}.rules")` 발행 → 대상 계좌 RuleEngine 자동 리로드

**에러 응답**:
- 404: 유효하지 않은 rule_type
- 422: params 검증 실패 (타입 불일치, 범위 초과 등)
