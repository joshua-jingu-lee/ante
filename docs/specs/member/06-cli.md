# Member 모듈 세부 설계 - CLI 커맨드

> 인덱스: [README.md](README.md) | 호환 문서: [member.md](member.md)

# CLI 커맨드

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-member--멤버에이전트-관리)다. 이 문서는
Member 관점의 실행 경계와 보안 동작만 설명한다. 입력 계약(비대화형 옵션 기반, 비밀값
`--*-env`/`--*-file` 우선, 위험 명령 `--yes` 요구)은 [cli/02-design-decisions.md — 비대화형 입력 계약](../cli/02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract)을 따른다.

## 실행 경계

`member list/info`는 오프라인 조회가 가능하다. 그 외 member 상태·토큰·패스워드·복구키
변경 커맨드는 같은 `config_dir`의 서버가 실행 중이면 런타임 IPC로 서버에 위임한다.
서버는 MemberService 실행 후 필요한 세션 무효화, 토큰 무효화, 감사 로그,
member/security 알림을 같은 런타임 경로에서 처리한다.

서버가 정지된 상태에서는 bootstrap, recovery, 비상 revoke 같은 운영 복구를 위해
CLI가 MemberService를 직접 생성하는 maintenance fallback을 허용한다. 이 fallback은
account cold-path처럼 서버 topology를 바꾸지는 않지만 인증 상태를 바꾸므로, 서버
실행 중 직접 DB 수정은 금지한다.

## 권한 모델 (1.0 — master-only)

`member register`, `member suspend`, `member reactivate`, `member revoke`,
`member rotate-token`, `member update-scopes`(향후), `member set-password` 같은
member admin mutation CLI 명령은 **master-only**다. 권한 모델 SSOT는
[02-design-decisions.md — Member admin mutation 권한 모델](02-design-decisions.md#권한-범위-scope)이며,
서비스 진입 시점에 `MemberService._assert_master`가 호출자 principal을 검사하고
master가 아니면 `PermissionError`를 발생시킨다.

`ANTE_MEMBER_TOKEN`이 agent token(`ante_ak_*`)이거나 master 외 human 토큰이면
명령은 service layer에서 거부되어 exit 1로 종료한다. CLI 표면 가드가 사전에 거부할 수도
있으나, service layer 거부는 1.0 계약의 invariant다. agent 위임이 필요해지면
별도 정책 이슈에서 reserved scope `member:admin`을 활성화한 뒤 표면을 정렬한다.

`member list`, `member info`, `member list-invalid-roles`는 조회 명령이므로 본
master-only 정책의 적용 대상이 아니다. `member reset-password`와
`member regenerate-recovery-key`는 인증 수단이 recovery key 또는 현재 패스워드
자체이므로 별도 공개 명령 allowlist 경로를 따른다
([cli/03-commands.md — 공개 명령 allowlist](../cli/03-commands.md#공개-명령-allowlist--인증-면제) 참조).

> 후속 implementation 정렬: #1543 (Web API/CLI 표면 가드 master-only로 일치),
> #1544 (oracle host probe scope 기대값 정렬). 본 결정 SSOT는 #1542이며,
> 부모 #1511(oracle host probe scope drift)에서 시작된 정합 작업이다.

### `ante member list`

```
ante member list [--type human|agent] [--org strategy-lab] [--status active] [--format json]
```

출력에 각 멤버의 이모지가 표시된다.

> JSON 출력은 root 전역 옵션으로 지정한다: `ante --format json member <subcommand> ...`.
> `member list`처럼 서브커맨드 자체가 `--format`을 받는 명령은 trailing 형태도
> 유효하지만, `member info/set-emoji/suspend/reactivate/revoke/rotate-token` 등
> 아래 명령은 서브커맨드에 `--format`이 없으므로 leaf 위치 사용 시
> `No such option: --format`으로 실패한다.

### `ante member info <member_id>`

```
ante member info strategy-dev-01
```

출력에 멤버의 이모지가 표시된다.

### `ante member register`

**권한: master-only**. agent token 또는 master 외 human 토큰이면 service layer
`_assert_master`에서 거부되어 exit 1로 종료한다.

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
ante member set-emoji strategy-dev-01 🦊
```

### `ante member suspend <member_id>`

**권한: master-only**. agent token이면 service layer `_assert_master`에서 거부된다.

```
ante member suspend strategy-dev-01
```

### `ante member reactivate <member_id>`

**권한: master-only**. agent token이면 service layer `_assert_master`에서 거부된다.

```
ante member reactivate strategy-dev-01
```

### `ante member revoke <member_id> --yes`

**권한: master-only**. agent token이면 service layer `_assert_master`에서 거부된다.

```
ante member revoke strategy-dev-01 --yes
# ⚠️ 이 작업은 되돌릴 수 없습니다. --yes 누락 시 CLI_CONFIRMATION_REQUIRED로 실패합니다.
```

### `ante member rotate-token <member_id>`

**권한: master-only**. agent token이면 service layer `_assert_master`에서 거부된다.

```
ante member rotate-token strategy-dev-01
# 기존 토큰이 즉시 무효화됩니다.
# 새 토큰: ante_ak_3f7x...
```

### `ante member reset-password`

새 패스워드는 stdin prompt가 아니라 `--new-password-env <ENV_NAME>` 또는
`--new-password-file <PATH>`로 전달한다. 직접 `--new-password` 값 옵션은 shell history
노출 우려로 본 이슈에서 권장 채널에서 제외한다.

```
# 환경변수에서 새 패스워드 읽기
$ export ANTE_NEW_PASSWORD='새-패스워드-원문'
$ ante member reset-password \
    --recovery-key ANTE-RK-7F3X-... \
    --new-password-env ANTE_NEW_PASSWORD
# ✅ 패스워드가 변경되었습니다.

# 또는 파일에서 새 패스워드 읽기
$ ante member reset-password \
    --recovery-key ANTE-RK-7F3X-... \
    --new-password-file /run/secrets/ante_new_password
# ✅ 패스워드가 변경되었습니다.
```

`--new-password-env`/`--new-password-file` 모두 누락이면 prompt 없이 `CLI_MISSING_REQUIRED_INPUT`
(또는 도메인 specialize 코드)으로 실패한다. 환경변수가 설정되지 않으면 `MEMBER_PASSWORD_ENV_NOT_SET`,
파일이 존재하지 않으면 `MEMBER_PASSWORD_FILE_NOT_FOUND`로 실패한다.

### `ante member regenerate-recovery-key`

현재 패스워드는 stdin prompt가 아니라 `--password-env <ENV_NAME>` 또는
`--password-file <PATH>`로 전달한다.

```
# 환경변수에서 현재 패스워드 읽기
$ export ANTE_PASSWORD='현재-패스워드-원문'
$ ante member regenerate-recovery-key --password-env ANTE_PASSWORD
# ⚠️ 기존 복구 키가 폐기되었습니다.
# 새 복구 키: ANTE-RK-2M8P-Q5WN-...

# 또는 파일에서 현재 패스워드 읽기
$ ante member regenerate-recovery-key --password-file /run/secrets/ante_password
# ⚠️ 기존 복구 키가 폐기되었습니다.
# 새 복구 키: ANTE-RK-2M8P-Q5WN-...
```

`--password-env`/`--password-file` 모두 누락이면 prompt 없이 `CLI_MISSING_REQUIRED_INPUT`
(또는 도메인 specialize 코드)으로 실패한다. 환경변수가 설정되지 않으면 `MEMBER_PASSWORD_ENV_NOT_SET`,
파일이 존재하지 않으면 `MEMBER_PASSWORD_FILE_NOT_FOUND`로 실패한다.
