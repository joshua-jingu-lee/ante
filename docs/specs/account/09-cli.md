# Account 모듈 세부 설계 - CLI 인터페이스

> 인덱스: [README.md](README.md) | 호환 문서: [account.md](account.md)

# CLI 인터페이스

```bash
# 계좌 생성 (대화형)
ante account create

# 계좌 목록
ante account list
ante account list --status active

# 계좌 상세
ante account info <account_id>

# 계좌 정지/활성화
ante account suspend <account_id>
ante account activate <account_id>

# 계좌 삭제 (소프트 딜리트)
ante account delete <account_id>

# 인증 정보 조회 (마스킹)
ante account credentials <account_id>

# 인증 정보 재설정 (대화형, 기존 값을 덮어씀)
ante account set-credentials <account_id>

# 시스템 전체 Kill Switch
ante system halt                    # 전체 거래 정지
ante system activate                # 전체 거래 재개
```

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
