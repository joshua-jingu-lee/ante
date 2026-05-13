# Approval 모듈 세부 설계 - CLI 커맨드

> 인덱스: [README.md](README.md) | 호환 문서: [approval.md](approval.md)

# CLI 커맨드

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-approval--승인-요청-관리)다. 이 문서는
Approval 도메인의 사용 의도와 주요 예시만 설명한다.

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
  --result pass \
  --detail "리스크 허용 범위 내, 변동성 지표 안정적" \
  [--format json]
```

### `ante approval cancel <id>`

요청자(Agent)가 본인이 올린 결재를 철회할 때 사용. `pending` 또는 `on_hold` 상태에서만 가능.

```
ante approval cancel <id> \
  [--format json]
```

### `ante approval reopen <id>`

거절된 요청을 수정하여 재상신할 때 사용. `rejected` 상태에서만 가능. body와 params를 갱신할 수 있다.

```
ante approval reopen <id> \
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

### `ante approval audit-types` / `ante approval cancel-invalid`

운영자가 `ApprovalType` SSOT(enum)에 없는 legacy invalid type approval row를 식별하고 정리하기
위한 admin 도구다. `#1469`(write-path 검증) 이전에 저장된 invalid pending row가 DB에 남아 있을
경우, `approve`/`cancel` 경로로는 종결할 수 없다(#1470 가드가 approve를, requester 제약이 일반
cancel을 차단한다). 본 명령들은 `approval:admin` scope를 요구한다.

```
# invalid type row 식별 (read-only)
ante approval audit-types [--format json] [--db-path <경로>]

# invalid type row 강제 cancel (status → cancelled, history 에 force_cancelled 기록)
ante approval cancel-invalid --id <approval_id> [--reason "legacy cleanup"] [--format json]
```

상세 절차는 [runbooks/07-legacy-invalid-approval-cleanup.md](../../runbooks/07-legacy-invalid-approval-cleanup.md)
를 참조한다.
