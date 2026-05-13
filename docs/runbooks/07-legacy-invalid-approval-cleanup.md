# Legacy Invalid Approval Type Cleanup

> 운영 런북 — invalid `ApprovalType` row 식별 및 정리 절차 (#1418 → #1472)

## 배경

`ApprovalType` enum SSOT(`src/ante/approval/models.py`)에 정의된 10개 유형 외의
값은 `ante approval request` 와 `ApprovalService.create()` 양쪽 모두에서 거부된다
(#1469). 또한 invalid type pending row를 `approve()` 로 진행시키려는 시도는
`ValueError` 로 차단되며, executor 미등록도 `EXECUTION_FAILED` 로 마감된다 (#1470).

하지만 이 가드들이 도입되기 이전(또는 raw SQL/마이그레이션으로 직접 INSERT된)에
저장된 invalid type approval row는 DB에 그대로 남을 수 있다. 그 row는 다음 경로
모두에서 종결될 수 없다.

- `ante approval approve <id>` → #1470 enum 가드가 `ValueError`로 차단.
- `ante approval reject <id>` → 동작은 하지만 invalid type을 "정상 reject" 처럼
  처리해 audit trail에 노이즈가 남는다.
- `ante approval cancel <id>` → `requester` 본인만 호출 가능 (`#1186`). 다른
  agent가 만든 row 는 운영자가 정리할 수 없다.
- 자연 만료 (`expire_stale`) → `expires_at` 이 지정된 row 만 만료된다.

이 런북은 운영자가 위 row를 안전하게 식별하고 정리하기 위한 절차를 정의한다.

## 식별

### `ante approval audit-types`

`ApprovalType` SSOT에 없는 모든 approval row를 출력한다 (read-only).

```bash
# table 모드 (사람 친화)
ante approval audit-types

# json 모드 (스크립트 친화)
ante approval audit-types --format json
```

출력 컬럼:

| 컬럼 | 설명 |
|------|------|
| `id` | approval row의 UUID |
| `type` | 저장된 invalid type 문자열 |
| `status` | 현재 상태 (pending / approved / rejected / ...) |
| `requester` | 요청을 만든 member_id |
| `title` | 요청 제목 |
| `created_at` | 생성 시각 (ISO 8601) |
| `resolved_at` | 종결 시각. 비어있으면 미종결. |

`status=pending` 이고 `resolved_at` 이 비어있는 row가 정리 대상이다. 이미 종결된
(`approved`/`rejected`/`cancelled`/`expired`/`execution_failed`) row도 audit 결과에
포함되지만, 정리 대상은 아니다 (audit trail 보존).

### 직접 SQL 조회 (참고)

CLI 없이 직접 확인할 때:

```sql
SELECT id, type, status, requester, title, created_at, resolved_at
FROM approvals
WHERE type NOT IN (
  'strategy_adopt','strategy_retire','bot_create','bot_assign_strategy',
  'bot_change_strategy','bot_stop','bot_resume','bot_delete',
  'budget_change','rule_change'
)
ORDER BY created_at ASC;
```

valid type 목록은 `ApprovalType` enum이 SSOT이므로, enum이 변경되면 본 SQL도
업데이트한다. 자동화 스크립트는 CLI (`audit-types --format json`) 사용을 권장한다.

## Cleanup

### `ante approval cancel-invalid`

invalid type 미종결 row를 운영자 권한으로 cancel 처리한다. `approval:admin`
scope가 필요하다.

```bash
ante approval cancel-invalid --id <approval_id> --reason "legacy cleanup"
```

수행 내용:

1. row를 조회해 `type not in ApprovalType` 인지 확인. valid 면 거부.
2. `resolved_at` 이 비어있는지 확인. 이미 종결된 row면 거부 (audit 보존).
3. `status` 를 `cancelled` 로 전이하고 `resolved_at`/`resolved_by` 를 기록.
4. `history` 에 `force_cancelled` action 을 append.
   - 일반 `cancelled` action 과 구별되어 사후 audit 시 운영자 강제 정리임을
     식별할 수 있다.
5. `ApprovalResolvedEvent` 와 결재 처리 완료 notification을 발행.

### 절차

1. `ante approval audit-types --format json` 으로 invalid row 목록을 확보한다.
2. 각 row 에 대해 `ante approval info <id>` 로 본문/params 를 확인한다.
   - row를 만든 agent와 시점, audit 흔적이 보존되는지 확인.
3. 정리 대상 row마다 `ante approval cancel-invalid --id <id> --reason ...` 실행.
4. 실행 후 `ante approval info <id>` 로 다음을 검증:
   - `status == "cancelled"`
   - `resolved_at` 이 비어있지 않음
   - `history` 에 `force_cancelled` action 이 마지막에 추가됨
5. (선택) 처리 완료 알림이 expected notification channel(Telegram 등)에 도달했는지
   확인한다.

### audit/log 확인

- 모든 force-cancel 동작은 `logger.warning("invalid approval type force-cancel: ...")`
  로 기록된다. 로그 디렉토리(`<config_dir>/logs/`) 또는 journald에서 추출 가능.
- DB `approvals.history` 컬럼에 `{"action": "force_cancelled", "actor": ..., "at": ..., "detail": ...}`
  엔트리가 영구 보존된다. 일반 cancel(`action: "cancelled"`) 과 구별된다.
- EventBus 의 `ApprovalResolvedEvent` 가 발행되므로 downstream 구독자(notification,
  audit logger)가 정상 cancel과 동일한 경로로 추적한다.

## Pass condition

- 운영자가 invalid type approval row를 CLI 한 줄로 식별할 수 있다 (`audit-types`).
- 운영자가 cancel/cleanup 경로로 invalid pending row를 안전하게 종결할 수 있다
  (`cancel-invalid`).
- 정리된 row는 `history` 와 `ApprovalResolvedEvent` 양쪽 모두에서 audit 가능하다.
- 정상 (valid type) approval row는 본 절차로 강제 종결되지 않는다.

## 비범위

- CLI write path 입력 검증 (#1469)
- approve guard / executor missing 처리 (#1470)
- frontend unknown type 표시 (#1471)
- 자동 migration/삭제 — 운영자 명시적 cleanup 만 지원한다.
