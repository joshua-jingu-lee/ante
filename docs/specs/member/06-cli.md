# Member 모듈 세부 설계 - CLI 커맨드

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# CLI 커맨드

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
