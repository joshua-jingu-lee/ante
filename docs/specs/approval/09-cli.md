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

### `ante approval audit-types` (#1472 SPLIT-D)

`ApprovalType` enum SSOT 외 `type` 값을 가진 legacy invalid row 를 식별한다.
운영자 cleanup 의 사전 식별 단계로 사용된다. 분류는 `offline` (DB 직접 조회)
이며 scope `approval:read` 가 필요하다. 정상 type row 는 결과에서 자동으로
제외된다.

```
ante approval audit-types \
  [--status pending|approved|rejected|cancelled|on_hold|expired|execution_failed] \
  [--db-path <path>] \
  [--format json]
```

출력 컬럼: id, type, status, requester, created_at, expires_at.

cleanup runbook 사용 예시는 [docs/runbooks/archive/08-legacy-invalid-approval-cleanup.md](../../../docs/runbooks/archive/08-legacy-invalid-approval-cleanup.md) 참고.

### `ante approval cancel-invalid <id>` (#1472 SPLIT-D)

`audit-types` 로 식별된 legacy invalid-type row 의 administrative cleanup.
일반 `ante approval cancel` 의 requester ownership rule 을 우회하므로
`approval:admin` scope 가 필수다. 분류는 `runtime IPC` 로, 서버가 가동
중이어야 한다 (cold-path fallback 없음). 정상 type row 는 service 가드에서
거부된다.

```
ante approval cancel-invalid <id> \
  [--format json]
```

성공 시 service `history` 에 `cancelled_invalid_type` 액션이 append 되고,
서버에 `AuditLogger` 가 주입된 환경(production)에서는 `audit_log` 테이블에
`action="approval.cancel_invalid"` 기록이 남는다.
