# Account 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# CLI 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-account--계좌-관리)다. 이 문서는
Account 관점의 lifecycle 경계와 출력 예시만 설명한다. 입력 계약(비대화형 옵션 기반,
비밀값 우선순위, 위험 명령 `--yes` 요구)은 [cli/02-design-decisions.md — 비대화형 입력 계약](../cli/02-design-decisions.md#비대화형-입력-계약-cli-non-interactive-input-contract)을 따른다.

```bash
# 계좌 생성 (cold-path 전용 — 서버 정지 상태에서만 실행)
ante account create \
  --broker-type kis-domestic \
  --account-id domestic \
  --name "국내 주식" \
  --trading-mode live \
  --credential-env app_key=KIS_APP_KEY \
  --credential-env app_secret=KIS_APP_SECRET \
  --credential account_no=5012XXXX-01

# (대안) credential을 파일에서 읽기
ante account create \
  --broker-type kis-domestic \
  --account-id domestic \
  --name "국내 주식" \
  --trading-mode live \
  --credential-file app_key=/run/secrets/kis_app_key \
  --credential-file app_secret=/run/secrets/kis_app_secret \
  --credential account_no=5012XXXX-01

# (KIS 모의투자 엔드포인트 계좌) broker-specific 설정은 --broker-config로 전달
ante account create \
  --broker-type kis-domestic \
  --account-id domestic-demo \
  --name "국내 모의투자" \
  --trading-mode virtual \
  --credential-env app_key=KIS_PAPER_APP_KEY \
  --credential-env app_secret=KIS_PAPER_APP_SECRET \
  --credential account_no=5012XXXX-01 \
  --broker-config is_paper=true

# 계좌 목록
ante account list
ante account list --status active

# 계좌 상세
ante account info <account_id>

# 계좌 정지/활성화
ante account suspend <account_id>
ante account activate <account_id>

# 계좌 삭제 (소프트 딜리트, cold-path 전용 — --yes 필수)
ante account delete <account_id> --yes

# 인증 정보 조회 (마스킹)
ante account credentials <account_id>

# 인증 정보 재설정 (cold-path 전용 — 서버 정지 상태에서만 실행)
# "재설정" 의미상 BrokerPreset.required_credentials를 모두 충족해야 함 (부분 갱신 불가).
ante account set-credentials <account_id> \
  --credential-env app_key=KIS_APP_KEY \
  --credential-env app_secret=KIS_APP_SECRET \
  --credential account_no=5012XXXX-01

# 시스템 전역 Kill Switch
ante system halt                    # 전체 거래 정지 (모든 ACTIVE 계좌를 SUSPENDED로 전환)
ante system clear-halt              # 전역 정지 해제 (모든 SUSPENDED 계좌를 ACTIVE로 복구; 봇 자동 재시작 아님)
```

### 런타임/Cold-path 분류

| 커맨드 | 분류 | 서버 실행 중 동작 |
|---|---|---|
| `ante account list` | 런타임 허용/오프라인 조회 | 실행 가능 |
| `ante account info <account_id>` | 런타임 허용/오프라인 조회 | 실행 가능 |
| `ante account credentials <account_id>` | 런타임 허용/오프라인 조회 | 마스킹 조회만 가능 |
| `ante account suspend <account_id>` | 런타임 허용 | IPC로 서버 `AccountService.suspend()` 호출 |
| `ante account activate <account_id>` | 런타임 허용 | IPC로 서버 `AccountService.activate()` 호출 |
| `ante account create --broker-type ... --account-id ... --name ... --trading-mode ... [--credential ...]` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |
| `ante account delete <account_id> --yes` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |
| `ante account set-credentials <account_id> [--credential ...]` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |

cold-path 전용 명령은 active Ante runtime guard로 서버 실행 여부를 먼저 확인한다.
1.0 정책상 동일 OS user/home server 기준으로 active runtime은 항상 단일이며,
runtime이 살아 있으면 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER` 에러로 종료한다.
`ante account delete`는 IPC 런타임 커맨드가 아니다. cold-path CLI에서 직접
`AccountService.delete()`를 호출하며, 해당 계좌에 활성(non-deleted) 봇이 남아 있으면
삭제는 `AccountHasActiveBotsError`로 차단된다(orphan bot 무결성).
활성 봇이 남아 있으면 `ante bot remove <bot_id> --yes`로 먼저 제거한다. `bot remove`는
서버 실행 중에는 IPC, 서버 정지 중에는 cold-path cleanup으로 동작하므로 계좌 삭제
복구를 위해 별도의 `ante system start`/`ante system stop` 왕복이 필요하지 않다.

### CLI 출력 예시

```
$ ante account list

 ID          이름        거래소   통화   브로커          상태
─────────────────────────────────────────────────────────────
 test        테스트      TEST     KRW    test            active
 domestic    국내 주식   KRX      KRW    kis-domestic    active
```

```
$ ante account info domestic

계좌 정보
─────────────────────────────────
  ID            : domestic
  이름          : 국내 주식
  거래소        : KRX
  통화          : KRW
  브로커        : kis-domestic
  매수 수수료   : 0.015%
  매도 수수료   : 0.195%
  거래 모드     : live
  상태          : active
  소속 봇       : 2개 (실행 중 1개)
  생성일        : 2026-03-15
```

```
$ ante account credentials domestic

인증 정보 (domestic)
─────────────────────────────────
  APP KEY       : PSxx****xxxx
  APP SECRET    : ************
  계좌번호      : 5012****-01
```

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
