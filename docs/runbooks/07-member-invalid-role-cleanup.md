# Member Invalid-Role Cleanup Runbook

> 관련 이슈: #1417 (epic), #1465 (write path 차단, close), #1466 (auth read-path guard, close), #1468 (본 runbook)
> SSOT: `src/ante/member/models.py:16` `MemberRole` enum / `src/ante/member/auth_service.py:27` `_VALID_MEMBER_ROLES`
> 인덱스: [README.md](README.md)

## 목적

`MemberRole` enum SSOT(`master` / `admin` / `default`)에 없는 `role` 값을 가진
member row 가 DB 에 남아 있을 때, 운영자가 그 row 를 안전하게 식별하고 cleanup
하는 절차를 정의한다.

#1465 이후 write path 가 invalid role 을 거부하고, #1466 이후 auth read-path 가
legacy invalid-role token/password 인증을 거부하므로 신규 invalid-role row 는
생성되지 않는다. 본 runbook 은 **그 이전에 생성된 legacy row** 의 정리 절차다.

## 자동 cleanup 정책 (금지)

- **자동 migration / silent rewrite 금지.** 운영자가 row 단위로 명시 revoke 한다.
- **자동 삭제 금지.** invalid-role row 도 audit/추적 가치가 있으므로 DB 에서 직접
  지우지 않는다. `ante member revoke <member_id>` 만 사용한다.
- 일괄 cleanup 스크립트도 허용하지 않는다. 한 row 씩 검토 → revoke 한다.

## 절차

### 1. 식별 — `ante member list-invalid-roles`

```bash
ante member list-invalid-roles --format json
```

분류는 `offline` 이지만 `MemberService.initialize()` 가 schema migration DDL 을
수반한다 (read-only 가 아니다). runtime IPC 는 우회한다.

JSON 출력 스키마:

```json
{
  "recommended_action": "review_then_revoke",
  "valid_roles": ["master", "admin", "default"],
  "actionable_count": 1,
  "legacy_revoked_count": 0,
  "actionable": [
    {
      "member_id": "agent-bad",
      "role": "oracle_invalid_role",
      "type": "agent",
      "name": "agent-bad",
      "status": "active",
      "created_at": "2026-04-01 00:00:00",
      "has_token": true,
      "token_expires_at": "2026-07-01 00:00:00",
      "revoke_command": "ante member revoke agent-bad"
    }
  ],
  "legacy_revoked": []
}
```

- `actionable`: `role` 이 invalid 이고 `status != revoked` 인 row. 운영자 cleanup 대상.
- `legacy_revoked`: 이미 revoke 된 invalid-role row. 추가 조치 불필요(audit 추적용).
- `has_token` / `token_expires_at` 만 노출되고, `token_hash` 자체는 **모든 출력
  모드에서 절대 표시되지 않는다**.

### 2. 검토

각 `actionable` row 의 `role` 이 정말 invalid 한지, 그리고 그 row 가 실제
운영자가 의도해서 생성한 것이 아닌지 확인한다.

- `MemberRole` 에 새 값을 추가하려는 게 의도라면 본 runbook 이 아니라 별도 enum
  변경 스펙 (`src/ante/member/models.py`) 으로 진행한다.
- legacy migration 잔여물(예: `oracle_invalid_role` 같이 명시적으로 invalid 임을
  드러내는 값) 이면 다음 단계로 진행한다.

### 3. Revoke — `ante member revoke <member_id> --yes`

```bash
ante member revoke <member_id> --yes
```

이 명령은 다음을 수행한다 (`MemberService.revoke`):

- `members.status = 'revoked'`
- `members.token_hash = ''` (토큰 무효화)
- `members.revoked_at = <UTC now>`

`--yes` 누락 시 `CLI_CONFIRMATION_REQUIRED` 로 실패한다.

### 4. 사후 검증

```bash
ante member list-invalid-roles --format json
```

- `actionable_count == 0` 인지 확인한다.
- `legacy_revoked_count` 는 누적될 수 있다(이전에 revoke 한 invalid-role row 들이
  계속 표시됨). 이는 정상이며, 운영자가 동일 row 를 반복 처리하지 않게 도와준다.

## Audit 한계

- Web API revoke 경로(`POST /api/members/<id>/revoke`)는 `audit_logger.log` 로
  audit 기록을 남긴다.
- CLI `ante member revoke` 는 본 PR (#1468) 시점에서 audit 기록을 **남기지 않는다.**
  CLI revoke audit 보강은 별도 audit 정책 이슈에서 다룬다.
- 따라서 본 runbook 으로 CLI cleanup 을 수행할 때는, 운영 일지에 수동으로 revoke
  내역(`member_id`, 시각, 사유)을 기록하기를 권장한다.

## 관련 spec 링크

- Epic: #1417 invalid-role member 생성 후속 정리.
- #1465 — write path `_assert_role_enum` (close).
- #1466 — auth read-path `_VALID_MEMBER_ROLES` guard (close).
- 본 runbook (#1468) — operator cleanup 절차.
- frontend role type 분리: #1467 (별도 범위).
