# Account 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# CLI 인터페이스

CLI 명령 시그니처와 실행 분류의 SSOT는
[cli/03-commands.md](../cli/03-commands.md#ante-account--계좌-관리)다. 이 문서는
Account 관점의 lifecycle 경계와 출력 예시만 설명한다.

```bash
# 계좌 생성 (대화형, cold-path 전용)
ante account create

# 계좌 목록
ante account list
ante account list --status active

# 계좌 상세
ante account info <account_id>

# 계좌 정지/활성화
ante account suspend <account_id>
ante account activate <account_id>

# 계좌 삭제 (소프트 딜리트, cold-path 전용)
ante account delete <account_id>

# 인증 정보 조회 (마스킹)
ante account credentials <account_id>

# 인증 정보 재설정 (대화형, 기존 값을 덮어씀, cold-path 전용)
ante account set-credentials <account_id>

# 시스템 전체 Kill Switch
ante system halt                    # 전체 거래 정지
ante system activate                # 전체 거래 재개
```

### 런타임/Cold-path 분류

| 커맨드 | 분류 | 서버 실행 중 동작 |
|---|---|---|
| `ante account list` | 런타임 허용/오프라인 조회 | 실행 가능 |
| `ante account info <account_id>` | 런타임 허용/오프라인 조회 | 실행 가능 |
| `ante account credentials <account_id>` | 런타임 허용/오프라인 조회 | 마스킹 조회만 가능 |
| `ante account suspend <account_id>` | 런타임 허용 | IPC로 서버 `AccountService.suspend()` 호출 |
| `ante account activate <account_id>` | 런타임 허용 | IPC로 서버 `AccountService.activate()` 호출 |
| `ante account create` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |
| `ante account delete <account_id>` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |
| `ante account set-credentials <account_id>` | cold-path 전용 | 서버 실행 중이면 DB 수정 전 거부 |

cold-path 전용 명령은 같은 `config_dir`의 PID/socket guard로 서버 실행 여부를 먼저 확인한다.
서버가 실행 중이면 `ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER` 에러로 종료한다.

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
