# Ante CLI Reference

> 이 문서는 `scripts/generate_cli_reference.py`에 의해 Click introspection으로 자동 생성됩니다.
> 직접 수정하지 마세요. CLI 코드 변경 후 스크립트를 재실행하세요.
>
> 마지막 갱신: 2026-03-20

## 목차

- [글로벌 옵션](#글로벌-옵션)
- [명령어 요약](#명령어-요약)
- [approval — 결재 관리.](#approval-결재-관리)
  - [ante approval approve](#ante-approval-approve)
  - [ante approval cancel](#ante-approval-cancel)
  - [ante approval info](#ante-approval-info)
  - [ante approval list](#ante-approval-list)
  - [ante approval reject](#ante-approval-reject)
  - [ante approval reopen](#ante-approval-reopen)
  - [ante approval request](#ante-approval-request)
  - [ante approval review](#ante-approval-review)
- [audit — 감사 로그 조회.](#audit-감사-로그-조회)
  - [ante audit list](#ante-audit-list)
- [backtest — 백테스트.](#backtest-백테스트)
  - [ante backtest history](#ante-backtest-history)
  - [ante backtest run](#ante-backtest-run)
- [bot — 봇 생성·시작·중지·조회.](#bot-봇-생성시작중지조회)
  - [ante bot create](#ante-bot-create)
  - [ante bot info](#ante-bot-info)
  - [ante bot list](#ante-bot-list)
  - [ante bot positions](#ante-bot-positions)
  - [ante bot remove](#ante-bot-remove)
  - [ante bot signal-key](#ante-bot-signal-key)
- [broker — 증권사 계좌 정보 조회.](#broker-증권사-계좌-정보-조회)
  - [ante broker balance](#ante-broker-balance)
  - [ante broker positions](#ante-broker-positions)
  - [ante broker reconcile](#ante-broker-reconcile)
  - [ante broker status](#ante-broker-status)
- [config — 설정 조회·변경.](#config-설정-조회변경)
  - [ante config get](#ante-config-get)
  - [ante config history](#ante-config-history)
  - [ante config set](#ante-config-set)
- [data — 데이터 관리.](#data-데이터-관리)
  - [ante data list](#ante-data-list)
  - [ante data schema](#ante-data-schema)
  - [ante data storage](#ante-data-storage)
  - [ante data validate](#ante-data-validate)
- [feed — DataFeed — 시세·재무 데이터 수집 파이프라인.](#feed-datafeed-시세재무-데이터-수집-파이프라인)
  - [ante feed config check](#ante-feed-config-check)
  - [ante feed config list](#ante-feed-config-list)
  - [ante feed config set](#ante-feed-config-set)
  - [ante feed init](#ante-feed-init)
  - [ante feed inject](#ante-feed-inject)
  - [ante feed run backfill](#ante-feed-run-backfill)
  - [ante feed run daily](#ante-feed-run-daily)
  - [ante feed start](#ante-feed-start)
  - [ante feed status](#ante-feed-status)
- [init](#init)
  - [ante init](#ante-init)
- [instrument — 종목 마스터 데이터 관리.](#instrument-종목-마스터-데이터-관리)
  - [ante instrument import](#ante-instrument-import)
  - [ante instrument list](#ante-instrument-list)
  - [ante instrument search](#ante-instrument-search)
  - [ante instrument sync](#ante-instrument-sync)
- [member — 멤버 등록·관리.](#member-멤버-등록관리)
  - [ante member bootstrap](#ante-member-bootstrap)
  - [ante member info](#ante-member-info)
  - [ante member list](#ante-member-list)
  - [ante member reactivate](#ante-member-reactivate)
  - [ante member regenerate-recovery-key](#ante-member-regenerate-recovery-key)
  - [ante member register](#ante-member-register)
  - [ante member reset-password](#ante-member-reset-password)
  - [ante member revoke](#ante-member-revoke)
  - [ante member rotate-token](#ante-member-rotate-token)
  - [ante member set-emoji](#ante-member-set-emoji)
  - [ante member suspend](#ante-member-suspend)
- [notification — 알림 관리.](#notification-알림-관리)
- [report — 리포트 관리.](#report-리포트-관리)
  - [ante report list](#ante-report-list)
  - [ante report performance](#ante-report-performance)
  - [ante report schema](#ante-report-schema)
  - [ante report submit](#ante-report-submit)
  - [ante report view](#ante-report-view)
- [rule — 거래 룰 조회·관리.](#rule-거래-룰-조회관리)
  - [ante rule info](#ante-rule-info)
  - [ante rule list](#ante-rule-list)
- [signal — 외부 시그널 채널 관리.](#signal-외부-시그널-채널-관리)
  - [ante signal connect](#ante-signal-connect)
- [strategy — 전략 관리.](#strategy-전략-관리)
  - [ante strategy info](#ante-strategy-info)
  - [ante strategy list](#ante-strategy-list)
  - [ante strategy performance](#ante-strategy-performance)
  - [ante strategy submit](#ante-strategy-submit)
  - [ante strategy validate](#ante-strategy-validate)
- [system — 시스템 시작·중지·상태 확인.](#system-시스템-시작중지상태-확인)
  - [ante system activate](#ante-system-activate)
  - [ante system halt](#ante-system-halt)
  - [ante system start](#ante-system-start)
  - [ante system status](#ante-system-status)
  - [ante system stop](#ante-system-stop)
- [trade — 거래 내역 조회.](#trade-거래-내역-조회)
  - [ante trade info](#ante-trade-info)
  - [ante trade list](#ante-trade-list)
- [treasury — 자금 현황 조회·관리.](#treasury-자금-현황-조회관리)
  - [ante treasury allocate](#ante-treasury-allocate)
  - [ante treasury deallocate](#ante-treasury-deallocate)
  - [ante treasury status](#ante-treasury-status)

---

## 글로벌 옵션

```bash
ante [OPTIONS] <command>
```

| 옵션 | 타입 | 기본값 | 설명 |
|------|------|--------|------|
| `--format` | text / json | text | 출력 형식 (text 또는 json) |
| `--config-dir` | PATH | — | 설정 디렉토리 경로 (기본: ~/.config/ante/ 또는 ./config/) |
| `--version` | BOOLEAN | false | Show the version and exit. |

---

## 명령어 요약

| 명령 | 설명 |
|------|------|
| `ante approval approve` | 결재 승인. |
| `ante approval cancel` | 결재 철회 (요청자만 가능). |
| `ante approval info` | 결재 상세 조회. |
| `ante approval list` | 결재 목록 조회. |
| `ante approval reject` | 결재 거절. |
| `ante approval reopen` | 거절된 결재 재상신. |
| `ante approval request` | 결재 요청 생성. |
| `ante approval review` | 검토 의견 추가. |
| `ante audit list` | 감사 로그 목록 조회. |
| `ante backtest history` | 전략별 백테스트 실행 이력 조회. |
| `ante backtest run` | 백테스트 실행. |
| `ante bot create` | 봇 생성. |
| `ante bot info` | 봇 상세 정보 조회. |
| `ante bot list` | 봇 목록 조회. |
| `ante bot positions` | 봇 보유 포지션 조회. |
| `ante bot remove` | 봇 삭제. |
| `ante bot signal-key` | 봇 시그널 키 조회 또는 재발급. |
| `ante broker balance` | 증권사 계좌 잔고 조회. |
| `ante broker positions` | 증권사 보유 종목 조회. |
| `ante broker reconcile` | 내부 데이터와 증권사 데이터 대사. |
| `ante broker status` | 증권사 연결 상태 조회. |
| `ante config get` | 설정 조회. 키 없이 호출하면 전체 목록. |
| `ante config history` | 설정 변경 이력 조회. |
| `ante config set` | 동적 설정 변경. 정적 설정은 변경 불가. |
| `ante data list` | 보유 데이터셋 목록. |
| `ante data schema` | 데이터 스키마 조회. |
| `ante data storage` | 저장 용량 현황. |
| `ante data validate` | Parquet 파일 무결성 검증. |
| `ante feed config check` | API 키 존재 여부를 확인한다. |
| `ante feed config list` | 등록된 API 키 목록을 마스킹하여 표시한다. |
| `ante feed config set` | API 키를 .feed/.env 파일에 저장한다. |
| `ante feed init` | DataFeed 운영 디렉토리를 초기화한다. |
| `ante feed inject` | 외부 CSV 파일에서 과거 데이터를 수동 주입한다. |
| `ante feed run backfill` | 과거 데이터를 1회 수집한다 (backfill). |
| `ante feed run daily` | 어제(또는 지정일) 데이터를 1회 수집한다 (daily). |
| `ante feed start` | 내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다. |
| `ante feed status` | 수집 상태를 조회한다. |
| `ante init` | 설정 디렉토리 및 기본 설정 파일 생성. |
| `ante instrument import` | CSV/JSON 파일에서 종목 데이터 import. |
| `ante instrument list` | 등록된 종목 목록 조회. |
| `ante instrument search` | 키워드로 종목 검색 (종목코드, 한글명, 영문명). |
| `ante instrument sync` | KIS API에서 종목 마스터 데이터를 동기화. |
| `ante member bootstrap` | 최초 master 계정 생성 (인증 불필요). |
| `ante member info` | 멤버 상세 정보 조회. |
| `ante member list` | 멤버 목록 조회. |
| `ante member reactivate` | 멤버 재활성화. |
| `ante member regenerate-recovery-key` | Recovery Key 재발급 (인증 불필요). |
| `ante member register` | 멤버 등록 (토큰 발급). |
| `ante member reset-password` | Recovery Key로 패스워드 리셋 (인증 불필요). |
| `ante member revoke` | 멤버 영구 폐기. |
| `ante member rotate-token` | 토큰 재발급 (기존 토큰 즉시 무효화). |
| `ante member set-emoji` | 멤버 이모지 설정/변경. |
| `ante member suspend` | 멤버 일시 정지. |
| `ante report list` | 리포트 목록 조회. |
| `ante report performance` | 기간별 성과 집계 조회. |
| `ante report schema` | 리포트 제출 스키마 조회. |
| `ante report submit` | 리포트 제출. |
| `ante report view` | 리포트 상세 조회. |
| `ante rule info` | 룰 상세 정보 조회. |
| `ante rule list` | 룰 목록 조회. |
| `ante signal connect` | 양방향 JSON Lines 시그널 채널 수립. |
| `ante strategy info` | 전략 상세 정보 조회 (메타데이터 + 파라미터). |
| `ante strategy list` | 등록된 전략 목록 조회. |
| `ante strategy performance` | 전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용). |
| `ante strategy submit` | 전략 제출 (검증 -> 로드 테스트 -> Registry 등록). |
| `ante strategy validate` | 전략 파일 정적 검증 (AST 기반). |
| `ante system activate` | 킬 스위치 해제 (거래 재개). |
| `ante system halt` | 킬 스위치 발동 (전체 거래 중지). |
| `ante system start` | 시스템 시작 (포어그라운드). |
| `ante system status` | 시스템 상태 표시. |
| `ante system stop` | 시스템 정상 종료 (SIGTERM). |
| `ante trade info` | 거래 상세 정보 조회. |
| `ante trade list` | 거래 목록 조회. |
| `ante treasury allocate` | 봇에 예산 할당. |
| `ante treasury deallocate` | 봇 예산 회수. |
| `ante treasury status` | 자금 현황 요약. |

---

## approval — 결재 관리.

### ante approval approve

결재 승인.

```bash
ante approval approve <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval cancel

결재 철회 (요청자만 가능).

```bash
ante approval cancel <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval info

결재 상세 조회.

```bash
ante approval info <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval list

결재 목록 조회.

```bash
ante approval list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 |
| `--type` | - | TEXT | — | 유형 필터 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval reject

결재 거절.

```bash
ante approval reject <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT |  | 거절 사유 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval reopen

거절된 결재 재상신.

```bash
ante approval reopen <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--body` | - | TEXT | — | 수정할 본문 (미지정 시 기존 값 유지) |
| `--params` | - | TEXT | — | 수정할 파라미터 (JSON, 미지정 시 기존 값 유지) |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval request

결재 요청 생성.

```bash
ante approval request [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--type` | O | TEXT | — | 결재 유형 |
| `--title` | O | TEXT | — | 요청 제목 |
| `--body` | - | TEXT |  | 본문 (사유, 현황, 기대 효과 등) |
| `--params` | - | TEXT | {} | 실행 파라미터 (JSON) |
| `--reference-id` | - | TEXT |  | 참조 ID (report_id 등) |
| `--expires-in` | - | TEXT |  | 만료 기한 (예: 72h, 7d) |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante approval review

검토 의견 추가.

```bash
ante approval review <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--result` | O | pass / warn / fail | — | 검토 결과 |
| `--detail` | - | TEXT |  | 검토 상세 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


---

## audit — 감사 로그 조회.

### ante audit list

감사 로그 목록 조회.

```bash
ante audit list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--member` | - | TEXT | — | 멤버 ID 필터 |
| `--action` | - | TEXT | — | 액션 필터 (prefix 매칭) |
| `--from-date` | - | TEXT | — | 시작 날짜 (YYYY-MM-DD) |
| `--to-date` | - | TEXT | — | 종료 날짜 (YYYY-MM-DD) |
| `--limit` | - | INT (1~200) | 20 | 조회 건수 |
| `--offset` | - | INTEGER | 0 | 오프셋 |


---

## backtest — 백테스트.

### ante backtest history

전략별 백테스트 실행 이력 조회.

```bash
ante backtest history <STRATEGY_NAME> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<STRATEGY_NAME>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--limit` | - | INTEGER | 20 | 조회 건수 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante backtest run

백테스트 실행.

```bash
ante backtest run <STRATEGY_PATH> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<STRATEGY_PATH>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--start` | O | TEXT | — | 시작일 (YYYY-MM-DD) |
| `--end` | O | TEXT | — | 종료일 (YYYY-MM-DD) |
| `--symbols` | - | TEXT | — | 종목 코드 (콤마 구분) |
| `--balance` | - | FLOAT | 10000000 | 초기 자금 |
| `--timeframe` | - | TEXT | 1d | 타임프레임 |
| `--data-path` | - | TEXT | data/ | 데이터 디렉토리 경로 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


---

## bot — 봇 생성·시작·중지·조회.

### ante bot create

봇 생성.

```bash
ante bot create [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--name` | O | TEXT | — | 봇 이름 |
| `--strategy` | O | TEXT | — | 전략 ID |
| `--type` | - | live / paper | live | 봇 타입 |
| `--interval` | - | INT (10~3600) | 60 | 실행 주기 (초, 10-3600) |
| `--id` | - | TEXT |  | 봇 ID (미지정 시 자동 생성) |
| `--param` | - | TEXT | — | 전략 파라미터 오버라이드 (key=value, 복수 지정 가능) |


### ante bot info

봇 상세 정보 조회.

```bash
ante bot info <BOT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |


### ante bot list

봇 목록 조회.

```bash
ante bot list
```


### ante bot positions

봇 보유 포지션 조회.

```bash
ante bot positions <BOT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |


### ante bot remove

봇 삭제.

```bash
ante bot remove <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--yes` | - | BOOLEAN | false | Confirm the action without prompting. |


### ante bot signal-key

봇 시그널 키 조회 또는 재발급.

```bash
ante bot signal-key <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--rotate` | - | BOOLEAN | false | 기존 키 폐기 + 새 키 발급 |


---

## broker — 증권사 계좌 정보 조회.

### ante broker balance

증권사 계좌 잔고 조회.

```bash
ante broker balance
```


### ante broker positions

증권사 보유 종목 조회.

```bash
ante broker positions
```


### ante broker reconcile

내부 데이터와 증권사 데이터 대사.

```bash
ante broker reconcile [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--fix` | - | BOOLEAN | false | 불일치 발견 시 자동 보정 수행 |


### ante broker status

증권사 연결 상태 조회.

```bash
ante broker status
```


---

## config — 설정 조회·변경.

### ante config get

설정 조회. 키 없이 호출하면 전체 목록.

```bash
ante config get <KEY>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | - |  |


### ante config history

설정 변경 이력 조회.

```bash
ante config history <KEY> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--limit`, `-n` | - | INTEGER | 20 | 조회 건수 (기본 20) |


### ante config set

동적 설정 변경. 정적 설정은 변경 불가.

```bash
ante config set <KEY> <VALUE>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | O |  |
| `<VALUE>` | O |  |


---

## data — 데이터 관리.

### ante data list

보유 데이터셋 목록.

```bash
ante data list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 디렉토리 경로 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante data schema

데이터 스키마 조회.

```bash
ante data schema [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 디렉토리 경로 |


### ante data storage

저장 용량 현황.

```bash
ante data storage [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 디렉토리 경로 |


### ante data validate

Parquet 파일 무결성 검증.

```bash
ante data validate [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--symbol` | - | TEXT | — | 검증할 종목 코드 (미지정 시 전체) |
| `--timeframe` | - | TEXT | 1d | 타임프레임 |
| `--fix` | - | BOOLEAN | false | 손상 파일을 .corrupted로 이동 |
| `--data-path` | - | TEXT | data/ | 데이터 디렉토리 경로 |


---

## feed — DataFeed — 시세·재무 데이터 수집 파이프라인.

### ante feed config check

API 키 존재 여부를 확인한다.

```bash
ante feed config check [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


### ante feed config list

등록된 API 키 목록을 마스킹하여 표시한다.

```bash
ante feed config list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


### ante feed config set

API 키를 .feed/.env 파일에 저장한다.

```bash
ante feed config set <KEY> <VALUE> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | O |  |
| `<VALUE>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


### ante feed init

DataFeed 운영 디렉토리를 초기화한다.

```bash
ante feed init <DATA_PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<DATA_PATH>` | - |  |


### ante feed inject

외부 CSV 파일에서 과거 데이터를 수동 주입한다.

```bash
ante feed inject <PATH> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<PATH>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--symbol` | O | TEXT | — | 종목 코드 (6자리) |
| `--timeframe` | - | TEXT | 1d | 타임프레임 (기본값: 1d) |
| `--source` | - | TEXT | external | 데이터 소스 식별자 |
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


### ante feed run backfill

과거 데이터를 1회 수집한다 (backfill).

```bash
ante feed run backfill [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |
| `--since` | - | TEXT | — | 수집 시작일 (YYYY-MM-DD, config 기본값 오버라이드) |
| `--until` | - | TEXT | — | 수집 종료일 (YYYY-MM-DD, 기본값: 오늘) |


### ante feed run daily

어제(또는 지정일) 데이터를 1회 수집한다 (daily).

```bash
ante feed run daily [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |
| `--date` | - | TEXT | — | 수집 대상일 (YYYY-MM-DD, 기본값: 어제) |


### ante feed start

내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다.

```bash
ante feed start [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


### ante feed status

수집 상태를 조회한다.

```bash
ante feed status [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | data/ | 데이터 저장소 경로 |


---

## init

### ante init

설정 디렉토리 및 기본 설정 파일 생성.

```bash
ante init [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--dir` | - | PATH | — | 설정 디렉토리 경로 (기본: ~/.config/ante/) |
| `--seed` | - | BOOLEAN | false | E2E 테스트용 시드 데이터 주입 |


---

## instrument — 종목 마스터 데이터 관리.

### ante instrument import

CSV/JSON 파일에서 종목 데이터 import.

```bash
ante instrument import <FILE_PATH> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<FILE_PATH>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--dry-run` | - | BOOLEAN | false | 실제 저장 없이 미리보기 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante instrument list

등록된 종목 목록 조회.

```bash
ante instrument list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--exchange` | - | TEXT | KRX | 거래소 (기본: KRX) |
| `--type` | - | TEXT | — | 종목 유형 필터 (stock, etf, etn 등) |
| `--listed-only` | - | BOOLEAN | false | 상장 종목만 표시 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante instrument search

키워드로 종목 검색 (종목코드, 한글명, 영문명).

```bash
ante instrument search <KEYWORD> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEYWORD>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--limit` | - | INTEGER | 20 | 최대 결과 수 |
| `--listed-only` | - | BOOLEAN | false | 상장 종목만 검색 |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante instrument sync

KIS API에서 종목 마스터 데이터를 동기화.

```bash
ante instrument sync [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--exchange` | - | TEXT | KRX | 거래소 (기본: KRX) |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


---

## member — 멤버 등록·관리.

### ante member bootstrap

최초 master 계정 생성 (인증 불필요).

```bash
ante member bootstrap [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--id` | O | TEXT | — | master 멤버 ID |
| `--name` | - | TEXT |  | 표시 이름 |


### ante member info

멤버 상세 정보 조회.

```bash
ante member info <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member list

멤버 목록 조회.

```bash
ante member list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--type` | - | human / agent | — | 멤버 타입 필터 |
| `--org` | - | TEXT | — | 조직 필터 |
| `--status` | - | active / suspended / revoked | — | 상태 필터 |


### ante member reactivate

멤버 재활성화.

```bash
ante member reactivate <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member regenerate-recovery-key

Recovery Key 재발급 (인증 불필요).

```bash
ante member regenerate-recovery-key
```


### ante member register

멤버 등록 (토큰 발급).

```bash
ante member register [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--id` | O | TEXT | — | 멤버 ID |
| `--type` | O | human / agent | — | 멤버 타입 |
| `--org` | - | TEXT | default | 소속 조직 |
| `--name` | - | TEXT |  | 표시 이름 |
| `--scopes` | - | TEXT |  | 권한 범위 (쉼표 구분) |


### ante member reset-password

Recovery Key로 패스워드 리셋 (인증 불필요).

```bash
ante member reset-password [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--recovery-key` | O | TEXT | — | Recovery Key |


### ante member revoke

멤버 영구 폐기.

```bash
ante member revoke <MEMBER_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--yes` | - | BOOLEAN | false | Confirm the action without prompting. |


### ante member rotate-token

토큰 재발급 (기존 토큰 즉시 무효화).

```bash
ante member rotate-token <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member set-emoji

멤버 이모지 설정/변경.

```bash
ante member set-emoji <MEMBER_ID> <EMOJI>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |
| `<EMOJI>` | O |  |


### ante member suspend

멤버 일시 정지.

```bash
ante member suspend <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


---

## notification — 알림 관리.

---

## report — 리포트 관리.

### ante report list

리포트 목록 조회.

```bash
ante report list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (pending/adopted/rejected) |
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


### ante report performance

기간별 성과 집계 조회.

```bash
ante report performance [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--period` | - | daily / monthly | daily | 집계 기간 (daily 또는 monthly) |
| `--bot-id` | - | TEXT | — | 봇 ID 필터 |
| `--start` | - | TEXT | — | 시작일 (YYYY-MM-DD, daily 전용) |
| `--end` | - | TEXT | — | 종료일 (YYYY-MM-DD, daily 전용) |
| `--year` | - | INTEGER | — | 연도 필터 (monthly 전용) |


### ante report schema

리포트 제출 스키마 조회.

```bash
ante report schema
```


### ante report submit

리포트 제출.

```bash
ante report submit <JSON_PATH> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<JSON_PATH>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |
| `--run` | - | TEXT | — | 참조할 백테스트 run_id |


### ante report view

리포트 상세 조회.

```bash
ante report view <REPORT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<REPORT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--db-path` | - | TEXT | db/ante.db | DB 경로 |


---

## rule — 거래 룰 조회·관리.

### ante rule info

룰 상세 정보 조회.

```bash
ante rule info <RULE_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<RULE_ID>` | O |  |


### ante rule list

룰 목록 조회.

```bash
ante rule list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--scope` | - | global / strategy | — | 룰 범위 필터 |


---

## signal — 외부 시그널 채널 관리.

### ante signal connect

양방향 JSON Lines 시그널 채널 수립.

```bash
ante signal connect [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--key` | O | TEXT | — | 시그널 키 (sk_...) |


---

## strategy — 전략 관리.

### ante strategy info

전략 상세 정보 조회 (메타데이터 + 파라미터).

```bash
ante strategy info <NAME>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<NAME>` | O |  |


### ante strategy list

등록된 전략 목록 조회.

```bash
ante strategy list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (registered/active/inactive/archived) |


### ante strategy performance

전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용).

```bash
ante strategy performance <NAME>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<NAME>` | O |  |


### ante strategy submit

전략 제출 (검증 -> 로드 테스트 -> Registry 등록).

```bash
ante strategy submit <PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<PATH>` | O |  |


### ante strategy validate

전략 파일 정적 검증 (AST 기반).

```bash
ante strategy validate <PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<PATH>` | O |  |


---

## system — 시스템 시작·중지·상태 확인.

### ante system activate

킬 스위치 해제 (거래 재개).

```bash
ante system activate [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT |  | 사유 |


### ante system halt

킬 스위치 발동 (전체 거래 중지).

```bash
ante system halt [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT |  | 사유 |


### ante system start

시스템 시작 (포어그라운드).

```bash
ante system start [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--config-dir` | - | PATH | — | 설정 디렉토리 경로 |


### ante system status

시스템 상태 표시.

```bash
ante system status
```


### ante system stop

시스템 정상 종료 (SIGTERM).

```bash
ante system stop
```


---

## trade — 거래 내역 조회.

### ante trade info

거래 상세 정보 조회.

```bash
ante trade info <TRADE_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<TRADE_ID>` | O |  |


### ante trade list

거래 목록 조회.

```bash
ante trade list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--bot` | - | TEXT | — | 봇 ID 필터 |
| `--from` | - | TEXT | — | 시작일 (YYYY-MM-DD) |
| `--to` | - | TEXT | — | 종료일 (YYYY-MM-DD) |
| `--limit` | - | INTEGER | 50 | 최대 조회 수 |


---

## treasury — 자금 현황 조회·관리.

### ante treasury allocate

봇에 예산 할당.

```bash
ante treasury allocate <BOT_ID> <AMOUNT>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |
| `<AMOUNT>` | O |  |


### ante treasury deallocate

봇 예산 회수.

```bash
ante treasury deallocate <BOT_ID> <AMOUNT>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |
| `<AMOUNT>` | O |  |


### ante treasury status

자금 현황 요약.

```bash
ante treasury status
```


---

