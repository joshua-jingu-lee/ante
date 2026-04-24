# CLI 모듈 세부 설계 - 커맨드 상세

> 인덱스: [README.md](README.md) | 호환 문서: [cli.md](cli.md)

# 커맨드 상세

### `ante system` — 시스템 제어

```bash
ante system start                  # 시스템 시작
ante system stop                   # 시스템 정상 종료
ante system status                 # 시스템 상태 조회
ante system halt [--account <account_id>]   # 거래 긴급 중지 (계좌 지정 시 해당 계좌만, 생략 시 전체)
ante system activate [--account <account_id>]  # halt 해제, 거래 재개 (계좌 지정 시 해당 계좌만, 생략 시 전체)
```

### `ante account` — 계좌 관리

```bash
ante account list                             # 계좌 목록
ante account info <account_id>                # 계좌 상세 정보
ante account add <account_id> --exchange <거래소> --currency <통화> --broker-type <타입>  # 계좌 등록
ante account suspend <account_id> --reason <사유>  # 계좌 거래 정지
ante account activate <account_id>            # 계좌 거래 재개
ante account delete <account_id>              # 계좌 삭제 (연결된 봇이 없을 때만)
```

### `ante bot` — 봇 관리

```bash
ante bot list [--account <account_id>]  # 봇 목록 (계좌별 필터링)
ante bot create <name> --strategy <path> --account <account_id> [--balance <금액>] [--param key=value ...]
ante bot remove <bot_id>           # 봇 삭제
ante bot info <bot_id>             # 봇 상세 정보
ante bot positions <bot_id>        # 봇 현재 포지션
ante bot signal-key <bot_id> [--rotate]  # 외부 시그널 키 조회·갱신
```

### `ante trade` — 거래 이력

```bash
ante trade list [--account <account_id>] [--bot <bot_id>] [--strategy <name>] [--days N] [--limit N]
ante trade info <trade_id>         # 거래 상세
```

### `ante strategy` — 전략 관리

```bash
ante strategy validate <path>      # 전략 파일 정적 검증 (AST)
ante strategy list                 # 등록된 전략 목록
ante strategy info <name>          # 전략 상세 (메타데이터, 파라미터)
ante strategy performance <name>   # 전략 전체 성과 (모든 봇 집계, Agent 피드백용)
```

### `ante treasury` — 자금 관리

```bash
ante treasury status [--account <account_id>]    # 자금 현황 (계좌별 필터링)
ante treasury allocate <bot_id> <금액>           # 봇에 자금 할당
ante treasury deallocate <bot_id>                # 봇 자금 회수

# 일별 자산 스냅샷 조회
ante treasury snapshot [--account <account_id>]                        # 최근 스냅샷 (대시보드 D-1)
ante treasury snapshot --from <날짜> --to <날짜> [--account <account_id>]  # 기간별 스냅샷 (대시보드 D-2 차트)
ante treasury snapshot --date <날짜> [--account <account_id>]          # 특정일 스냅샷
```

> 스냅샷 스펙: [treasury.md — 일별 자산 스냅샷](../treasury/treasury.md#일별-자산-스냅샷-daily-asset-snapshot)

### `ante rule` — 거래 룰 관리

```bash
ante rule list                     # 전역 + 전략별 룰 목록
ante rule info <rule_id>           # 룰 상세
```

### `ante broker` — 증권사 연동

```bash
ante broker balance [--account <account_id>]     # 실제 증권사 잔고 조회
ante broker positions [--account <account_id>]   # 실제 증권사 포지션 조회
ante broker reconcile [--account <account_id>]   # 시스템↔증권사 포지션 대사
ante broker status [--account <account_id>]      # 증권사 연결 상태
```

### `ante data` — 데이터 관리

모든 data 커맨드는 `@require_auth`와 `@require_scope("data:read")` 데코레이터 적용.

```bash
ante data list [--data-path <경로>] [--db-path <경로>]            # 보유 데이터셋 목록 (종목명 병기, InstrumentService 연동)
ante data schema [--data-path <경로>]                             # OHLCV 데이터 스키마 조회
ante data storage [--data-path <경로>]                            # 저장 용량 현황 (MB 단위, timeframe별)
ante data validate [--symbol <종목>] [--timeframe <주기>] [--fix] [--data-path <경로>]  # Parquet 파일 무결성 검증
```

### `ante backtest` — 백테스트

```bash
ante backtest run <strategy_path> --start <날짜> --end <날짜> [--symbols <종목,...>] [--balance <초기자금>] [--timeframe <주기>] [--data-path <경로>]  # 진행률 바 표시 (text 모드)
```

### `ante report` — 리포트

```bash
ante report schema                 # 리포트 제출 스키마 조회 (Agent용)
ante report submit <json_path> [--db-path <경로>]     # 리포트 제출
ante report list [--status <상태>] [--db-path <경로>]  # 리포트 목록 조회
ante report view <report_id> [--db-path <경로>]        # 리포트 상세 조회
ante report performance [--period daily|monthly] [--bot-id <봇ID>] [--start <날짜>] [--end <날짜>] [--year <연도>]  # 기간별 성과 집계
```

### `ante feed` — 데이터 피드 (DataFeed)

CLI 정의는 `src/ante/feed/cli.py`에 있으며 `ante.cli.main`에서 서브커맨드로 등록된다.
모든 feed 커맨드는 `@require_auth`와 `@require_scope` 데코레이터로 인증/권한 검증을 수행한다.

```bash
ante feed init [data_path]               # 운영 디렉토리 초기화, 기본 config 생성 (scope: data:write)
ante feed status [--data-path <경로>]     # 수집 상태 조회 (scope: data:read)
ante feed config set <KEY> <VALUE> [--data-path <경로>]       # API 키를 .feed/.env에 저장 (scope: data:write)
ante feed config list [--data-path <경로>]                    # 등록된 설정값 목록 (마스킹 표시) (scope: data:read)
ante feed config check [--data-path <경로>]                   # API 키 존재 여부 확인 (scope: data:read)
ante feed inject <path> --symbol <종목> [--timeframe <주기>] [--source <소스>] [--data-path <경로>]  # CSV 파일에서 데이터 주입 (scope: data:write)
ante feed run backfill [--since <날짜>] [--data-path <경로>]  # 과거 데이터 1회 수집 (scope: data:write)
ante feed run daily [--date <날짜>] [--data-path <경로>]      # 어제(또는 지정일) 데이터 1회 수집 (scope: data:write)
ante feed start [--data-path <경로>]                          # 내장 스케줄러로 backfill/daily 자동 실행하는 상주 프로세스 (scope: data:write)
```

> 상세: [data-feed.md](../data-feed/data-feed.md)

### `ante config` — 설정 관리

```bash
ante config get [key]              # 설정 조회 (키 생략 시 전체 목록)
ante config set <key> <value>      # 동적 설정 변경
ante config history <key>          # 설정 변경 이력 조회
```

### `ante approval` — 승인 요청 관리

```bash
ante approval request <type> --data <json>  # 승인 요청 생성
ante approval list [--status <상태>]        # 승인 요청 목록
ante approval info <approval_id>            # 승인 요청 상세
ante approval review <approval_id>          # 승인 요청 리뷰 (상세 + 승인/거부 안내)
ante approval cancel <approval_id>          # 승인 요청 취소
ante approval approve <approval_id>         # 승인 요청 승인
ante approval reject <approval_id>          # 승인 요청 거부
ante approval reopen <approval_id> [--data <json>]  # 거절된 요청 재상신 (params/body 수정 가능)
```

### `ante init` — 시스템 초기 설정

설치 후 최초 1회 실행하는 **비대화형** 설정 커맨드. 인증 면제.
파일시스템 골격(`system.toml`·`secrets.env`·빈 DB) 생성 + master 계정 + 가상 탐색용 테스트 계좌를 1회 생성한다.

```bash
ante init [--member-id owner] [--name Owner] [--dir <경로>]
```

**플래그:**

| 플래그 | 기본값 | 설명 |
|--------|--------|------|
| `--member-id` | `owner` | master 멤버 ID |
| `--name` | `Owner` | master 표시 이름 |
| `--dir` | `~/.config/ante/` | 설정 디렉토리 경로 |

**생성 산출물:**

파일 3개와 DB 레코드 2개를 생성한다.

- 파일: `<dir>/system.toml`, `<dir>/secrets.env` (placeholder 주석), `<dir>/db/ante.db` (스키마 적용)
- DB 레코드: master member 1개, default test account (`broker_type="test"`) 1개

**내부 실행 순서**: 1. 디렉토리 생성 → 2. master bootstrap → 3. test account 생성

**출력:**

패스워드·토큰·recovery key를 **자동 생성**하여 1회만 출력한다. 사용자는 입력하지 않는다.

**멱등성 (I4 — 파일 + master 레코드 기반 재진입):**

- 3개 파일 + master row + test account row가 **모두 존재**하면 거부 (`"init이 이미 완료된 상태입니다"`, exit code 1)
- 그 외 경로에서는 **누락된 것만** 생성. 즉:
  - 파일 누락 → 누락 파일 재생성
  - master row 없음 → master bootstrap 실행 (비밀값 즉시 출력하여 후속 단계 실패 시에도 복구 가능)
  - test account row 없음 → test account 생성

**옵셔널 도메인 입력 (Telegram / KIS 실계좌 / DataFeed):**

`ante init`은 이들을 다루지 않는다. 필요 시 다음 명령을 사용한다:

- KIS 실계좌: `ante account add <account_id> ...`
- Telegram: `<dir>/secrets.env` 직접 편집 (`TELEGRAM_BOT_TOKEN=`, `TELEGRAM_CHAT_ID=`)
- DataFeed API 키: `ante feed config set ANTE_DATAGOKR_API_KEY <key>` / `ANTE_DART_API_KEY`

**비범위:**

- 대화형 프롬프트: 없음
- 시드 데이터 주입: 지원하지 않음 (PR #609 이후 관련 인프라 제거됨)

### `ante member` — 멤버(에이전트) 관리

> master 계정 생성은 `ante init`에 통합되었다. 별도 `ante member bootstrap` 명령은 제거됨(재설계 2026-04).

```bash
ante member register <name> --role <역할>               # 멤버 등록
ante member list [--status <상태>]                      # 멤버 목록
ante member info <member_id>                            # 멤버 상세
ante member suspend <member_id>                         # 멤버 일시 정지
ante member reactivate <member_id>                      # 멤버 재활성화
ante member revoke <member_id>                          # 멤버 권한 영구 해제
ante member rotate-token <member_id>                    # 인증 토큰 갱신
ante member set-emoji <member_id> <emoji>               # 멤버 이모지 설정
ante member reset-password <member_id>                  # 비밀번호 초기화
ante member regenerate-recovery-key <member_id>         # 복구 키 재발급
```

### `ante instrument` — 종목 관리

```bash
ante instrument list [--exchange <거래소>] [--listed-only]  # 종목 목록
ante instrument sync [--exchange <거래소>]                  # KIS API에서 종목 마스터 동기화
ante instrument search <query> [--listed-only]              # 종목 검색
ante instrument import <filepath> [--dry-run]               # CSV/JSON 종목 데이터 주입
```

### `ante notification` — 알림 관리

```bash
ante notification list [--level <레벨>] [--limit N] [--failed]  # 알림 발송 이력 조회
```

### `ante signal` — 외부 시그널 채널

```bash
ante signal connect --key <sk_...>   # 양방향 JSON Lines 시그널 채널 수립
```
