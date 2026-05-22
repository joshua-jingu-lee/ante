# Member 모듈 세부 설계 - MemberService

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# MemberService

MemberService는 내부적으로 책임을 분리하여 `AuthService`(인증), `TokenManager`(토큰 라이프사이클), `RecoveryKeyManager`(패스워드/복구키)에 위임한다. 외부에서는 MemberService 단일 인터페이스로 접근한다.

**생성자 파라미터:**

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `db` | Database | (필수) | SQLite 연결 인스턴스 |
| `eventbus` | EventBus | (필수) | 이벤트 발행용 |
| `token_ttl_days` | int | 90 | 토큰 만료 기간 (일). 등록·재발급 시 적용 |

**메서드:**

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `initialize` | — | None | 스키마 생성 |
| `bootstrap_master` | member_id, password, name, emoji | tuple[Member, str, str] | master 생성 + (token, recovery_key) 반환. 최초 1회만. 이미 존재 시 에러. CLI에서는 `ante init`이 내부 호출 |
| `register` | member_id, type, role, org, name, scopes, registered_by, emoji | tuple[Member, str] | 멤버 등록 + 토큰 반환. **권한: master-only** (`_assert_master` 강제) |
| `authenticate` | token | Member | 토큰으로 멤버 식별. 타입 접두어 검증 포함 |
| `authenticate_password` | member_id, password | Member | 패스워드 인증 (human 복구/maintenance) |
| `get` | member_id | Member ∣ None | 단건 조회 |
| `list` | type, org, status, limit, offset | list[Member] | 필터 조회 |
| `suspend` | member_id, suspended_by | Member | 일시 정지. master는 정지 불가. **권한: master-only** (`_assert_master` 강제) |
| `reactivate` | member_id, reactivated_by | Member | 재활성화. **권한: master-only** (`_assert_master` 강제) |
| `revoke` | member_id, revoked_by | Member | 영구 폐기. 토큰 해시 삭제. master는 폐기 불가. **권한: master-only** (`_assert_master` 강제) |
| `rotate_token` | member_id, rotated_by | tuple[Member, str] | 토큰 재발급 (기존 토큰 즉시 무효화). **권한: master-only** (`_assert_master` 강제) |
| `change_password` | member_id, old_password, new_password | None | 패스워드 변경 (human만). **권한: master-only** (`_assert_master` 강제) |
| `reset_password` | member_id, recovery_key, new_password | None | recovery key로 패스워드 리셋 (human만). 인증 수단이 recovery key 자체이므로 `_assert_master`를 우회한다(공개 명령 allowlist) |
| `regenerate_recovery_key` | member_id, password | str | 복구 키 재발급. 현재 패스워드 확인 필수. 인증 수단이 현재 패스워드 자체이므로 `_assert_master`를 우회한다(공개 명령 allowlist) |
| `update_emoji` | member_id, emoji, updated_by | Member | 멤버 이모지 변경. 단일 이모지 검증 + 중복 체크 |
| `update_scopes` | member_id, scopes, updated_by | Member | 권한 범위 변경. **권한: master-only** (`_assert_master` 강제) |
| `update_last_active` | member_id | None | 마지막 활동 시각 갱신 |

### 런타임 경계

서버 실행 중 member 상태·토큰·패스워드·복구키 변경은 IPC를 통해 서버
프로세스의 MemberService에서 실행한다. CLI가 서버와 같은 `config_dir`을 쓰고 서버가
실행 중이면 직접 DB 수정 대신 IPC를 사용해야 한다.

서버 런타임 경로는 MemberService 호출 후 다음 후처리를 같은 프로세스에서 수행한다:

| 작업 | 필수 후처리 |
|------|-------------|
| `rotate_token` | 기존 토큰 해시 폐기. 새 토큰은 1회만 반환 |
| `reset_password`, `change_password` | 보안 알림 |
| `regenerate_recovery_key` | 기존 recovery key 폐기 + 보안 알림 |
| `register`, `update_emoji`, `update_scopes`, `reactivate` | 감사 로그와 member 이벤트 발행 |

서버 정지 상태에서는 recovery/maintenance 목적으로 CLI가 MemberService를 직접 생성할
수 있다. 이 경우에도 동일한 DB 불변식과 감사 기록을 남겨야 하며, 서버 재시작 후 새
인증 상태가 canonical DB에서 로드된다.

### 불변식 검증

모든 상태 변경 메서드는 다음 불변식을 사전 검증한다:

```python
def _assert_invariants(self, member: Member, action: str) -> None:
    # master는 정지·폐기·역할 변경 불가
    if member.role == "master" and action in ("suspend", "revoke", "change_role"):
        raise PermissionError("master는 정지·폐기·역할 변경할 수 없습니다")

    # agent 타입은 master/admin 역할 불가
    if member.type == "agent" and member.role in ("master", "admin"):
        raise PermissionError("agent 타입은 master 또는 admin 역할을 가질 수 없습니다")
```

### Member admin mutation 권한 모델 (1.0 — master-only)

권한 모델 SSOT는 [02-design-decisions.md — Member admin mutation 권한 모델](02-design-decisions.md#권한-범위-scope)이며, MemberService는 다음을 일관 보장한다.

- `register`, `suspend`, `reactivate`, `revoke`, `rotate_token`, `update_scopes`,
  `change_password` 등 member admin mutation은 **master-only**다. service layer
  진입 시점에 `_assert_master(actor)`가 호출자 principal을 검사하고, master가 아니면
  `PermissionError`를 발생시킨다. 매핑 책임은 표면(CLI/IPC)이 진다.
- `member:admin` scope는 vocabulary에 정의되어 있으나 1.0 계약에서는 **reserved
  (현재 미사용)**다. agent token에 `member:admin`이 부여되어 있어도 mutation은
  `_assert_master`에서 거부된다. agent 위임 정책이 마련되기 전까지 본 invariant는
  변경되지 않는다.
- `reset_password`와 `regenerate_recovery_key`는 인증 수단이 recovery key/현재
  패스워드 자체이므로 master 토큰을 요구하지 않는 공개 명령 allowlist 경로다
  ([cli/03-commands.md — 공개 명령 allowlist](../cli/03-commands.md#공개-명령-allowlist--인증-면제) 참조).

> 후속 implementation 정렬: #1543 (CLI 표면 가드 master-only로 일치),
> #1544 (oracle host probe scope 기대값 정렬). 본 결정 SSOT는 #1542이며,
> 부모 #1511(oracle host probe scope drift)에서 시작된 정합 작업이다.
