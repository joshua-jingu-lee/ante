# Rule Engine 모듈 세부 설계 - REST API

> 인덱스: [README.md](README.md) | 호환 문서: [rule-engine.md](rule-engine.md)

# REST API

> 참조: [web-api.md](../web-api/web-api.md) 계좌 관리 섹션

| Method | Path | 설명 |
|--------|------|------|
| GET | `/api/accounts/{account_id}/rules` | 계좌의 리스크 룰 목록 조회 |
| PUT | `/api/accounts/{account_id}/rules/{rule_type}` | 개별 룰 설정 수정 |

### GET /api/accounts/{account_id}/rules

Config에서 `accounts.{account_id}.rules` 키를 읽어 RULE_REGISTRY 기반으로 구조화하여 반환한다.

**응답**:
```json
{
  "rules": [
    {
      "type": "daily_loss_limit",
      "name": "일일 손실 한도",
      "enabled": true,
      "priority": 10,
      "config": {
        "max_daily_loss_rate": 0.05,
        "action": "halt"
      },
      "param_schema": {
        "max_daily_loss_rate": {"type": "float", "min": 0.0, "max": 1.0, "description": "일일 최대 손실률"},
        "action": {"type": "enum", "values": ["notify", "halt"], "description": "한도 초과 시 조치"}
      }
    }
  ]
}
```

- `param_schema`는 RULE_REGISTRY에서 해당 룰 클래스의 `get_param_schema()` 메서드로 추출
- RULE_REGISTRY에 등록된 6종 룰 타입 전체를 반환하되, Config에 설정이 없는 룰은 `enabled: false` + 기본 config로 표시

### PUT /api/accounts/{account_id}/rules/{rule_type}

**요청 Body**:
```json
{
  "enabled": true,
  "config": {
    "max_daily_loss_rate": 0.03,
    "action": "halt"
  }
}
```

**검증 흐름**:
1. `rule_type`이 RULE_REGISTRY에 존재하는지 확인 (404 if not)
2. `config`의 각 키가 해당 룰의 param_schema에 정의된 타입·범위에 맞는지 검증 (422 if invalid)
3. Config API(`PUT /api/config/accounts.{account_id}.rules.{rule_type}`)에 위임
4. `ConfigChangedEvent` 발행 → RuleEngineManager가 자동 리로드

**에러 응답**:
- 404: 유효하지 않은 rule_type
- 422: config 파라미터 검증 실패 (타입 불일치, 범위 초과 등)
