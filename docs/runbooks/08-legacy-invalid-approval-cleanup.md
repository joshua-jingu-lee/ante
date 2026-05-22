# Legacy Invalid-Type Approval Cleanup Runbook

> 관련 이슈: #1418 (epic), #1469 (write path 차단, close), #1470 (approve guard, close), #1472 (본 runbook)
> SSOT: `src/ante/approval/service.py` `_VALID_APPROVAL_TYPES = frozenset(t.value for t in ApprovalType)` / `src/ante/approval/models.py` `ApprovalType` enum
> 인덱스: [README.md](README.md)

## 목적

`ApprovalType` enum SSOT 에 없는 `type` 값을 가진 approval row 가 DB 에 남아
있을 때, 운영자가 그 row 를 안전하게 식별하고 cleanup 하는 절차를 정의한다.

#1469 이후 CLI/서비스 write path 가 invalid type 을 거부하고, #1470 이후
`approve()`/`_execute_approved()` 가드가 PENDING 상태의 invalid row 가 승인
되어 silent success 되는 경로를 차단했으므로, 신규 invalid-type row 는 생성
되지 않는다. 본 runbook 은 **그 이전에 생성된 legacy row** 의 정리 절차다.

## 자동 cleanup 정책 (금지)

- **자동 migration / silent rewrite 금지.** 운영자가 row 단위로 명시 cancel 한다.
- **자동 batch / 일괄 삭제 금지.** 운영자가 식별 → 검토 → row by row cancel 한다.
- DB row 의 직접 DELETE 도 허용되지 않는다 (audit 추적 가치 보존). 본 runbook 은
  `ante approval cancel-invalid <id>` 만 사용해 status 를 `cancelled` 로 전이
  시키고 history append 로 흔적을 남긴다.

## 정상 type vs invalid type 구분 기준

판정 SSOT 는 `src/ante/approval/service.py` 의
`_VALID_APPROVAL_TYPES = frozenset(t.value for t in ApprovalType)` 다. 이 frozenset
에 포함되지 않은 `type` 값은 invalid 다.

| 구분 | 예시 | cleanup 대상 |
|------|------|-------------|
| 정상 type | `ApprovalType` enum SSOT 의 모든 멤버 (`strategy_adopt`, `strategy_retire`, `budget_change`, `rule_change`, `bot_create`, `bot_stop`, `bot_resume`, `bot_delete`, `bot_change_strategy`, `bot_assign_strategy`) | **아니오** — 일반 `ante approval cancel` 로 처리 |
| invalid type | enum 외 임의 문자열 (`oracle_invalid_type`, legacy migration 잔여물 등) | **예** — 본 runbook 절차 적용 |

신규 `ApprovalType` 멤버가 추가되면 자동으로 invalid 분류에서 빠진다 (SSOT 단일
출처). 새 type 추가가 의도라면 본 runbook 이 아니라 별도 enum 변경 스펙
(`src/ante/approval/models.py`) 으로 진행한다.

## 절차

### 0. 사전 확인

- **서버 가동 상태**: `ante system status` 로 IPC 서버가 RUNNING 인지 확인.
  `cancel-invalid` 명령은 `runtime IPC` 분류이므로 서버 정지 중에는 동작하지
  않는다 (cold-path fallback 없음). 서버 정지 시 `ante system start` 후 다시
  실행한다.
- **DB backup 권장**: SQLite 의 `.backup` 또는 파일 복사로 사전 백업을 만든다.
  본 runbook 의 cleanup 은 `history` append + status 변경을 수반하며, **row
  상태의 수동 복구가 불가**하므로 DB backup restore 가 유일한 rollback 경로다
  (아래 Rollback 절 참고).

### 1. 식별 — `ante approval audit-types`

```bash
ante approval audit-types --format json > /tmp/invalid-approvals-$(date +%Y%m%d-%H%M%S).json
```

- 분류는 `offline` 이며 scope `approval:read` 가 필요하다.
- 옵션:
  - `--status pending|approved|rejected|cancelled|on_hold|expired|execution_failed` — 상태 필터 (생략 시 모든 상태).
  - `--db-path <path>` — DB 경로 override (미지정 시 `config_dir` 기반 resolver).
  - `--format json|text` — 출력 형식.
- 컬럼: id, type, status, requester, created_at, expires_at.
- 출력 파일을 cleanup batch snapshot 으로 보관한다 (사후 검증 및 rollback 시 참조).

JSON 출력 예시:

```json
[
  {
    "id": "11111111-1111-1111-1111-111111111111",
    "type": "oracle_invalid_type",
    "status": "pending",
    "requester": "agent-bad",
    "created_at": "2026-04-01T00:00:00+00:00",
    "expires_at": ""
  }
]
```

### 2. 검토

각 row 가 정말 cleanup 대상인지 확인한다:

- `type` 이 `ApprovalType` 에 없는지 (정상 type 은 절대 결과에 포함되지 않지만,
  운영자의 이중 확인).
- `status` 가 `pending`, `on_hold`, `execution_failed` 중 하나인지 (cancel 가능
  상태). 그 외 상태(approved/rejected/cancelled/expired) 는 cleanup 대상이
  아니며 `cancel-invalid` 호출 시 service 가드로 거부된다 — 이미 종결된 row
  이므로 추가 조치 불필요.

### 3. Cleanup — `ante approval cancel-invalid <id>`

```bash
ante approval cancel-invalid <approval_id> --format json
```

- 분류는 `runtime IPC` 이며 scope `approval:admin` 이 필수다. 일반
  `approval cancel` 의 requester ownership rule 을 우회하기 때문이다.
- 실행 동작 (`ApprovalService.cancel_invalid_type_request`):
  - 대상 row 의 `type` 이 `_VALID_APPROVAL_TYPES` 에 있으면 거부 (정상 type
    invariant 보호).
  - 처리 가능 상태(`pending`, `on_hold`, `execution_failed`) 외면 거부.
  - status → `cancelled`, `resolved_by` / `resolved_at` 기록.
  - history append: `{action: "cancelled_invalid_type", actor: <member_id>, at: <ISO>, detail: "legacy invalid type cleanup"}`.
  - 기본값으로 `suppress_notification=True` — `ApprovalResolvedEvent` /
    `NotificationEvent` 를 발행하지 않아 운영자/Agent 에게 cleanup 알림 노이즈
    가 전달되지 않는다.
- 서버에 `AuditLogger` 가 주입된 환경(production)에서는 IPC 핸들러가 성공 후
  `audit_log` 테이블에 `(member_id=<actor>, action="approval.cancel_invalid",
  resource="approval:<id>", detail=<type>)` 를 기록한다.

복수 row 처리: snapshot JSON 의 각 row 를 row by row 로 실행한다. 일괄 처리
스크립트는 본 PR scope 가 아니다 (Non-goal). 한 row 씩 검토 → cancel 하는
운영 패턴을 유지한다.

### 4. 사후 검증

```bash
# (a) audit-types 결과가 비었는지 확인 (--status 미지정: 모든 상태)
ante approval audit-types --format json

# (b) cleanup 한 row 들이 cancelled 로 전이됐는지 확인
ante approval audit-types --status cancelled --format json
```

(a) 의 출력에서 cleanup 직전 batch 의 row 들이 모두 status=`cancelled` 로
전이됐고, 처리 가능 상태(pending/on_hold/execution_failed) 의 invalid row 가
남아 있지 않은지 확인한다. legacy cleanup 이 누적되면 status=`cancelled` 인
invalid row 들이 결과에 남을 수 있으며, 이는 정상이다 (history append 보존).

AuditLogger 기록은 다음 둘 중 하나의 경로로 확인한다:

- SQL 직접 조회 (서버 정지 가능):
  ```sql
  SELECT id, member_id, action, resource, detail, created_at
    FROM audit_log
   WHERE action = 'approval.cancel_invalid'
   ORDER BY created_at DESC;
  ```
- CLI `ante audit` 조회 명령이 제공되는 환경에서는 같은 action filter로 확인한다.

### 5. Rollback

- **DB backup restore 가 유일한 rollback 경로다.** `cancel_invalid_type_request`
  는 history append + status 전이를 수반하며, 이 변경은 row 상태의 수동 복구로
  되돌릴 수 없다.
- Rollback 필요 시 절차:
  1. `ante system stop` 으로 서버 정지 (서버가 가동 중이면 DB 파일 충돌 위험).
  2. 사전 단계(0) 에서 만든 DB backup 파일로 `db.path` 원복.
  3. `ante system start` 로 서버 재기동.
- backup 이 없으면 rollback 불가. 따라서 사전 backup 은 본 runbook 의 **필수
  단계**다.

## Audit / 추적 한계

- IPC 경로 (`approval.cancel_invalid`) 는 `AuditLogger` 가 주입된 환경에서
  `audit_log` 테이블에 기록을 남긴다. 본 runbook 의 production 사용 경로다.
- `ServiceRegistry.audit_logger` 가 `None` 인 환경(테스트 / legacy 마이그레이션)
  에서는 audit 호출이 skip 되며, ApprovalRequest 의 `history` append
  (`action: "cancelled_invalid_type"`) 가 fallback 추적 경로다.
- 추가 조회 표면 노출은 본 PR scope 가 아니다 (Non-goal).

## 관련 spec 링크

- Epic: #1418 invalid-type approval 후속 정리.
- #1469 — CLI/서비스 write path 가드 (close).
- #1470 — `approve()`/`_execute_approved()` 가드 (close).
- 본 runbook (#1472) — operator cleanup 절차.
- spec: [docs/specs/approval/08-approval-service.md](../specs/approval/08-approval-service.md) Administrative cancellation 절.
- spec: [docs/specs/approval/09-cli.md](../specs/approval/09-cli.md) `audit-types` / `cancel-invalid` 절.
- spec: [docs/specs/cli/03-commands.md](../specs/cli/03-commands.md) 실행 분류 표.
- spec: [docs/specs/ipc/ipc.md](../specs/ipc/ipc.md) `approval.cancel_invalid` mutating IPC.
