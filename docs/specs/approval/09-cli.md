# Approval 모듈 세부 설계 - CLI 커맨드

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# CLI 커맨드

### `ante approval request`

```
ante approval request \
  --type budget_change \
  --title "전략 A 예산 증액 요청" \
  --body "최근 3개월 수익률 15%. 현재 비중 10%에서 25%로 확대 요청. 시장 변동성 낮은 구간이므로 리스크 허용 범위 내로 판단." \
  --params '{"bot_id": "bot-1", "amount": 25000000, "current": 10000000}' \
  [--reference-id <report_id>] \
  [--expires-in 72h] \
  [--format json]
```

### `ante approval list`

```
ante approval list [--status pending|approved|rejected|on_hold|expired] [--type budget_change] [--format json]
```

### `ante approval info <id>`

```
ante approval info <id> [--format json]
```

### `ante approval review <id>`

참조자(시스템 모듈 또는 역할 Agent)가 검토 의견을 첨부할 때 사용.

```
ante approval review <id> \
  --reviewer "agent:risk-analyst" \
  --result pass \
  --detail "리스크 허용 범위 내, 변동성 지표 안정적" \
  [--format json]
```

### `ante approval cancel <id>`

요청자(Agent)가 본인이 올린 결재를 철회할 때 사용. `pending` 또는 `on_hold` 상태에서만 가능.

```
ante approval cancel <id> \
  --requester "agent:strategy-dev" \
  [--format json]
```

### `ante approval reopen <id>`

거절된 요청을 수정하여 재상신할 때 사용. `rejected` 상태에서만 가능. body와 params를 갱신할 수 있다.

```
ante approval reopen <id> \
  --requester "agent:strategy-dev" \
  [--body "거절 사유를 반영하여 예산을 축소 조정함"] \
  [--params '{"bot_id": "bot-1", "amount": 15000000, "current": 10000000}'] \
  [--format json]
```

### `ante approval approve <id>` / `ante approval reject <id>`

사용자가 CLI에서 직접 승인·거절할 때 사용. Dashboard와 외부 메신저가 주요 경로이지만, CLI도 지원한다.

```
ante approval approve <id>
ante approval reject <id> --reason "현 시점 리스크 과다"
```
