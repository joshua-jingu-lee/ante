# Member 모듈 세부 설계 - CLI 커맨드

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# CLI 커맨드

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-member--멤버에이전트-관리)다. 이 문서는
Member 관점의 실행 경계와 보안 동작만 설명한다.

## 실행 경계

`member list/info`는 오프라인 조회가 가능하다. 그 외 member 상태·토큰·패스워드·복구키
변경 커맨드는 같은 `config_dir`의 서버가 실행 중이면 런타임 IPC로 서버에 위임한다.
서버는 MemberService 실행 후 필요한 세션 무효화, 토큰 무효화, 감사 로그,
member/security 알림을 같은 런타임 경로에서 처리한다.

서버가 정지된 상태에서는 bootstrap, recovery, 비상 revoke 같은 운영 복구를 위해
CLI가 MemberService를 직접 생성하는 maintenance fallback을 허용한다. 이 fallback은
account cold-path처럼 서버 topology를 바꾸지는 않지만 인증 상태를 바꾸므로, 서버
실행 중 직접 DB 수정은 금지한다.

### `ante member list`

```
ante member list [--type human|agent] [--org strategy-lab] [--status active] [--format json]
```

출력에 각 멤버의 이모지가 표시된다.

### `ante member info <member_id>`

```
ante member info strategy-dev-01 [--format json]
```

출력에 멤버의 이모지가 표시된다.

### `ante member register`

master만 실행 가능.

```
ante member register \
  --id strategy-dev-01 \
  --type agent \
  --org strategy-lab \
  --name "전략 리서치 1호" \
  --scopes "strategy:write,report:write,data:read,backtest:run" \
  [--format json]

# 출력:
# ✅ 멤버 등록 완료
#   Member ID: strategy-dev-01
#   토큰: ante_ak_8k2m9p4q...
#   이 토큰은 다시 표시되지 않습니다.
```

### `ante member set-emoji <member_id> <emoji>`

```
ante member set-emoji strategy-dev-01 🦊 [--format json]
```

### `ante member suspend <member_id>`

```
ante member suspend strategy-dev-01 [--format json]
```

### `ante member reactivate <member_id>`

```
ante member reactivate strategy-dev-01 [--format json]
```

### `ante member revoke <member_id>`

```
ante member revoke strategy-dev-01 [--format json]
# ⚠️ 이 작업은 되돌릴 수 없습니다. 계속하시겠습니까? [y/N]
```

### `ante member rotate-token <member_id>`

```
ante member rotate-token strategy-dev-01 [--format json]
# 기존 토큰이 즉시 무효화됩니다.
# 새 토큰: ante_ak_3f7x...
```

### `ante member reset-password`

```
ante member reset-password --recovery-key ANTE-RK-7F3X-...
# 새 패스워드: ********
# 패스워드 확인: ********
# ✅ 패스워드가 변경되었습니다.
```

### `ante member regenerate-recovery-key`

```
ante member regenerate-recovery-key
# 현재 패스워드: ********
# ⚠️ 기존 복구 키가 폐기되었습니다.
# 새 복구 키: ANTE-RK-2M8P-Q5WN-...
```
