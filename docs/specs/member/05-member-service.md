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
| `bootstrap_master` | member_id, password, name, emoji | tuple[Member, str, str] | master 생성 + (token, recovery_key) 반환. 최초 1회만. 이미 존재 시 에러 |
| `register` | member_id, type, role, org, name, scopes, registered_by, emoji | tuple[Member, str] | 멤버 등록 + 토큰 반환. master만 호출 가능 |
| `authenticate` | token | Member | 토큰으로 멤버 식별. 타입 접두어 검증 포함 |
| `authenticate_password` | member_id, password | Member | 패스워드 인증 (human 대시보드 로그인) |
| `get` | member_id | Member ∣ None | 단건 조회 |
| `list` | type, org, status, limit, offset | list[Member] | 필터 조회 |
| `suspend` | member_id, suspended_by | Member | 일시 정지. master는 정지 불가 |
| `reactivate` | member_id, reactivated_by | Member | 재활성화 |
| `revoke` | member_id, revoked_by | Member | 영구 폐기. 토큰 해시 삭제. master는 폐기 불가 |
| `rotate_token` | member_id, rotated_by | tuple[Member, str] | 토큰 재발급 (기존 토큰 즉시 무효화) |
| `change_password` | member_id, old_password, new_password | None | 패스워드 변경 (human만) |
| `reset_password` | member_id, recovery_key, new_password | None | recovery key로 패스워드 리셋 (human만) |
| `regenerate_recovery_key` | member_id, password | str | 복구 키 재발급. 현재 패스워드 확인 필수 |
| `update_emoji` | member_id, emoji, updated_by | Member | 멤버 이모지 변경. 단일 이모지 검증 + 중복 체크 |
| `update_scopes` | member_id, scopes, updated_by | Member | 권한 범위 변경. master만 호출 가능 |
| `update_last_active` | member_id | None | 마지막 활동 시각 갱신 |

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
