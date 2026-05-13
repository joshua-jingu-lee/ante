# Member 모듈 운영 — invalid-role row cleanup

> 인덱스: [README.md](README.md) | 관련: [05-member-service.md](05-member-service.md), [06-cli.md](06-cli.md), [09-notification-events.md](09-notification-events.md)
> 도입: #1468 (split #1417/D). 의존: #1465 (write path), #1466 (auth read-path).

## 1. 배경

#1465 (split #1417/A) 가 `MemberService.register` 와 Web API ingress 에서
`MemberRole` enum 멤버가 아닌 ``role`` 입력을 막고, #1466 (split #1417/B) 가
auth read-path 에서 invalid-role principal 의 인증을 거부한 뒤에도, 그 이전에
DB 에 만들어진 `role="oracle_invalid_role"` 같은 row 는 그대로 남는다.

본 cleanup 은 운영자가 그런 legacy row 를 안전하게 식별하고 교정하기 위한
도구와 절차다. 자동 마이그레이션은 의도적으로 도입하지 않는다 — 잘못된 일괄
변경이 더 큰 사고를 만들 수 있으므로 식별 / 검토 / 명시적 교정 순서를 강제한다.

## 2. 절차

### 2.1 식별 (read-only)

`ante member audit-roles` 로 invalid-role row 를 식별한다. 본 명령은 DB 를
수정하지 않는다.

```bash
# 텍스트 출력 (운영자 확인용)
$ ante member audit-roles
invalid-role member 1건 식별됨:
  agent-leak-1         type=agent  role='oracle_invalid_role'        status=active     created_at=2026-05-09 10:01:23

# JSON 출력 (자동화용)
$ ante member audit-roles --format json
{
  "invalid_members": [
    {
      "member_id": "agent-leak-1",
      "type": "agent",
      "role": "oracle_invalid_role",
      "org": "default",
      "name": "agent-leak-1",
      "status": "active",
      "created_at": "2026-05-09 10:01:23",
      "created_by": "oracle"
    }
  ]
}
```

`audit-roles` 는 `member:read` scope 로 동작하며, master/admin/default 같은
정상 role row 는 결과에서 제외된다 (정상 role row 영향 없음 회귀).

### 2.2 검토

식별된 row 별로 cleanup 방향을 결정한다. 후보는 두 가지다:

1. **교정**: row 의 실제 의도 (agent / default 권한) 가 분명하면
   `repair-role` 로 enum 멤버로 교정한다.
2. **폐기**: row 가 더 이상 필요 없다면 `member revoke <id> --yes` 로 폐기한다
   (`#1465` 이후 register 가 막혔으므로 신규 invalid-role row 는 생성되지
   않는다).

폐기와 교정은 상호 배타가 아니다 — 의심스러운 경우 `suspend` 로 일시 정지한
뒤 추가 조사 후 결정해도 된다.

### 2.3 교정

`ante member repair-role` 로 invalid-role row 의 ``role`` 을 enum 멤버로
바꾼다.

```bash
$ ante member repair-role --member-id agent-leak-1 --role default
invalid-role 교정 완료: agent-leak-1 → default
```

invariants (구현 SSOT: `MemberService.repair_role`):

- caller 는 master 여야 한다. 비-master 는 `PermissionDeniedError` 로 거부된다.
- `--role` 은 `MemberRole` enum 멤버여야 한다 (`admin` / `default`). CLI 단의
  `click.Choice` 가 `master` 를 옵션에서 제외하며, 서비스 단에서도 권한 상승
  방지를 위해 한 번 더 차단한다.
- 대상 row 의 현재 ``role`` 은 enum SSOT 에 없어야 한다. 이미 valid 한 row 를
  재교정하는 호출은 거부된다.
- type-role 불변식이 그대로 적용된다 — agent 를 admin 으로 교정할 수 없다.

성공 시 `MemberRoleRepairedEvent` 가 발행된다. 이벤트는 다음 필드를 포함한다:

| 필드 | 의미 |
|------|------|
| `member_id` | 교정한 row 의 멤버 ID |
| `old_role` | 교정 전 invalid role |
| `new_role` | 교정 후 enum 멤버 (`admin` 또는 `default`) |
| `repaired_by` | 호출한 master 의 멤버 ID |

### 2.4 폐기 (대안)

row 가 더 이상 필요 없다면 master 권한으로 폐기한다.

```bash
$ ante member revoke agent-leak-1 --yes
멤버 폐기 완료: agent-leak-1
```

revoke 는 `token_hash` 를 초기화해 즉시 인증을 무효화하고 (`#1466` auth
read-path 가드와 별개의 추가 방어선), `MemberRevokedEvent` 를 발행한다.

## 3. 사후 확인

- `ante member audit-roles` 를 다시 실행해 invalid-role row 가 0건임을 확인한다.
- `MemberRoleRepairedEvent` / `MemberRevokedEvent` 가 cleanup audit log 에 남아
  있어야 한다. 모니터링은 NotificationEvent / log subscriber 에 위임한다
  (`07-eventbus-integration.md`, `09-notification-events.md`).

## 4. 비목표

- **자동 일괄 마이그레이션**: 본 절차는 식별 / 검토 / 명시적 교정을 강제한다.
  bulk auto-fix 를 제공하지 않는다.
- **write path 차단**: `#1465` 가 담당한다.
- **auth read-path 차단**: `#1466` 가 담당한다.
- **frontend role type 분리**: `#1467` 가 담당한다.
