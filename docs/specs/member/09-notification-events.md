# Member 모듈 세부 설계 - 알림 이벤트 정의 (Notification Events)

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# 알림 이벤트 정의 (Notification Events)

### 1. 인증 실패

> 소스: `src/ante/member/auth_service.py` — AuthService, `src/ante/member/recovery_key_manager.py` — RecoveryKeyManager

**트리거**: 토큰 인증, 패스워드 인증, 또는 recovery key 인증이 실패할 때 (만료, 무효, 상태 비활성 등)

**데이터 수집**:
- `member_id` → 인증 시도 대상 (식별 불가 시 "알 수 없는 멤버")
- `reason` → 실패 사유 (만료된 토큰, 유효하지 않은 토큰, 정지된 계정 등)

**발행 메시지**:

```
level: warning
title: 인증 실패
category: member

멤버 `{member_id}`
사유: {reason}
```

### 2. 패스워드 변경

> 소스: `src/ante/member/recovery_key_manager.py` — RecoveryKeyManager

**트리거**: `change_password()` 성공 시
**데이터 수집**: member_id

**발행 메시지**:

```
level: warning
title: 패스워드 변경
category: security

멤버 `{member_id}`의 패스워드가 변경되었습니다.
기존 세션이 무효화되었습니다.
본인이 아닌 경우 즉시 토큰을 재발급하세요.
```

### 3. 패스워드 리셋 (Recovery Key)

> 소스: `src/ante/member/recovery_key_manager.py` — RecoveryKeyManager

**트리거**: `reset_password()` 성공 시
**데이터 수집**: member_id

**발행 메시지**:

```
level: warning
title: 패스워드 리셋
category: security

멤버 `{member_id}`의 패스워드가 recovery key로 리셋되었습니다.
기존 세션이 무효화되었습니다.
본인이 아닌 경우 즉시 recovery key를 재발급하세요.
```
