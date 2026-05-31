# Ante CLI Reference

Ante가 제공하는 모든 CLI 명령어를 정리한 문서입니다. 각 명령어의 사용법, 옵션, 필수 권한(scope)을 확인할 수 있습니다.

> 마지막 갱신: 2026-05-31

> 이 문서는 `scripts/generate_cli_reference.py`로 자동 생성됩니다. 명령어 상세를 직접 편집하지 말고 Click 데코레이터나 생성 스크립트를 수정한 뒤 재생성하세요.

명령 그룹이 Ante의 어떤 모듈과 운영 영역을 제어하는지 먼저 보려면 [모듈과 운영 영역](modules.md)을 확인하세요.

## 목차

- [글로벌 옵션](#글로벌-옵션)
- [명령어 요약](#명령어-요약)
- [account — 계좌 생성·조회·관리.](#account-계좌-생성조회관리)
  - [ante account create](#ante-account-create)
  - [ante account list](#ante-account-list)
  - [ante account info](#ante-account-info)
  - [ante account suspend](#ante-account-suspend)
  - [ante account activate](#ante-account-activate)
  - [ante account delete](#ante-account-delete)
  - [ante account credentials](#ante-account-credentials)
  - [ante account set-credentials](#ante-account-set-credentials)
  - [ante account repair-timezone](#ante-account-repair-timezone)
- [audit — 감사 로그 조회.](#audit-감사-로그-조회)
  - [ante audit list](#ante-audit-list)
- [approval — 결재 관리.](#approval-결재-관리)
  - [ante approval request](#ante-approval-request)
  - [ante approval list](#ante-approval-list)
  - [ante approval info](#ante-approval-info)
  - [ante approval review](#ante-approval-review)
  - [ante approval reopen](#ante-approval-reopen)
  - [ante approval audit-types](#ante-approval-audit-types)
  - [ante approval cancel-invalid](#ante-approval-cancel-invalid)
  - [ante approval cancel](#ante-approval-cancel)
  - [ante approval approve](#ante-approval-approve)
  - [ante approval reject](#ante-approval-reject)
- [init](#init)
  - [ante init](#ante-init)
- [bot — 봇 생성·시작·중지·조회.](#bot-봇-생성시작중지조회)
  - [ante bot list](#ante-bot-list)
  - [ante bot info](#ante-bot-info)
  - [ante bot create](#ante-bot-create)
  - [ante bot remove](#ante-bot-remove)
  - [ante bot signal-key](#ante-bot-signal-key)
  - [ante bot positions](#ante-bot-positions)
  - [ante bot update](#ante-bot-update)
  - [ante bot logs](#ante-bot-logs)
  - [ante bot start](#ante-bot-start)
  - [ante bot stop](#ante-bot-stop)
  - [ante bot status](#ante-bot-status)
- [broker — 증권사 계좌 정보 조회.](#broker-증권사-계좌-정보-조회)
  - [ante broker status](#ante-broker-status)
  - [ante broker balance](#ante-broker-balance)
  - [ante broker positions](#ante-broker-positions)
  - [ante broker reconcile](#ante-broker-reconcile)
- [config — 설정 조회·변경.](#config-설정-조회변경)
  - [ante config get](#ante-config-get)
  - [ante config set](#ante-config-set)
  - [ante config history](#ante-config-history)
- [strategy — 전략 관리.](#strategy-전략-관리)
  - [ante strategy validate](#ante-strategy-validate)
  - [ante strategy submit](#ante-strategy-submit)
  - [ante strategy list](#ante-strategy-list)
  - [ante strategy set-status](#ante-strategy-set-status)
  - [ante strategy info](#ante-strategy-info)
  - [ante strategy summary](#ante-strategy-summary)
  - [ante strategy performance](#ante-strategy-performance)
- [data — 데이터 관리.](#data-데이터-관리)
  - [ante data list](#ante-data-list)
  - [ante data info](#ante-data-info)
  - [ante data delete](#ante-data-delete)
  - [ante data schema](#ante-data-schema)
  - [ante data storage](#ante-data-storage)
  - [ante data validate](#ante-data-validate)
- [backtest — 백테스트.](#backtest-백테스트)
  - [ante backtest run](#ante-backtest-run)
  - [ante backtest history](#ante-backtest-history)
- [report — 리포트 관리.](#report-리포트-관리)
  - [ante report schema](#ante-report-schema)
  - [ante report submit](#ante-report-submit)
  - [ante report list](#ante-report-list)
  - [ante report performance](#ante-report-performance)
  - [ante report view](#ante-report-view)
- [instrument — 종목 마스터 데이터 관리.](#instrument-종목-마스터-데이터-관리)
  - [ante instrument list](#ante-instrument-list)
  - [ante instrument sync](#ante-instrument-sync)
  - [ante instrument search](#ante-instrument-search)
  - [ante instrument import](#ante-instrument-import)
- [member — 멤버 등록·관리.](#member-멤버-등록관리)
  - [ante member list](#ante-member-list)
  - [ante member info](#ante-member-info)
  - [ante member list-invalid-roles](#ante-member-list-invalid-roles)
  - [ante member register](#ante-member-register)
  - [ante member set-emoji](#ante-member-set-emoji)
  - [ante member update-scopes](#ante-member-update-scopes)
  - [ante member suspend](#ante-member-suspend)
  - [ante member reactivate](#ante-member-reactivate)
  - [ante member revoke](#ante-member-revoke)
  - [ante member rotate-token](#ante-member-rotate-token)
  - [ante member reset-password](#ante-member-reset-password)
  - [ante member regenerate-recovery-key](#ante-member-regenerate-recovery-key)
- [rule — 거래 룰 조회·관리.](#rule-거래-룰-조회관리)
  - [ante rule list](#ante-rule-list)
  - [ante rule info](#ante-rule-info)
  - [ante rule update](#ante-rule-update)
- [signal — 외부 시그널 채널 관리.](#signal-외부-시그널-채널-관리)
  - [ante signal connect](#ante-signal-connect)
- [system — 시스템 시작·중지·상태 확인.](#system-시스템-시작중지상태-확인)
  - [ante system start](#ante-system-start)
  - [ante system stop](#ante-system-stop)
  - [ante system status](#ante-system-status)
  - [ante system halt](#ante-system-halt)
  - [ante system clear-halt](#ante-system-clear-halt)
- [trade — 거래 내역 조회.](#trade-거래-내역-조회)
  - [ante trade list](#ante-trade-list)
  - [ante trade info](#ante-trade-info)
- [treasury — 자금 현황 조회·관리.](#treasury-자금-현황-조회관리)
  - [ante treasury status](#ante-treasury-status)
  - [ante treasury transactions](#ante-treasury-transactions)
  - [ante treasury budgets](#ante-treasury-budgets)
  - [ante treasury set-balance](#ante-treasury-set-balance)
  - [ante treasury allocate](#ante-treasury-allocate)
  - [ante treasury deallocate](#ante-treasury-deallocate)
  - [ante treasury snapshot](#ante-treasury-snapshot)
  - [ante treasury portfolio value](#ante-treasury-portfolio-value)
  - [ante treasury portfolio history](#ante-treasury-portfolio-history)
- [update](#update)
  - [ante update](#ante-update)
- [feed — DataFeed — 시세·재무 데이터 수집 파이프라인.](#feed-datafeed-시세재무-데이터-수집-파이프라인)
  - [ante feed config set](#ante-feed-config-set)
  - [ante feed config list](#ante-feed-config-list)
  - [ante feed config check](#ante-feed-config-check)
  - [ante feed run backfill](#ante-feed-run-backfill)
  - [ante feed run daily](#ante-feed-run-daily)
  - [ante feed start](#ante-feed-start)
  - [ante feed init](#ante-feed-init)
  - [ante feed status](#ante-feed-status)
  - [ante feed inject](#ante-feed-inject)

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

| 명령 | 설명 | scope | 토큰 |
|------|------|-------|------|
| `ante account create` | 비대화형 계좌 생성 (cold-path 전용). | `account:write` | H·A |
| `ante account list` | 계좌 목록 조회. | `account:read` | H·A |
| `ante account info` | 계좌 상세 정보 조회. | `account:read` | H·A |
| `ante account suspend` | 계좌 거래 정지. | `account:write` | H·A |
| `ante account activate` | 계좌 활성화. | `account:write` | H·A |
| `ante account delete` | 계좌 삭제 (소프트 딜리트, cold-path 전용). | `account:write` | H·A |
| `ante account credentials` | 인증 정보 조회 (마스킹). | `account:read` | H·A |
| `ante account set-credentials` | 인증 정보 재설정 (비대화형, cold-path 전용). | `account:write` | H·A |
| `ante account repair-timezone` | legacy invalid IANA timezone 계좌를 복구한다 (cold-path 전용). | `account:write` | H·A |
| `ante audit list` | 감사 로그 목록 조회. | `audit:read` | H·A |
| `ante approval request` | 결재 요청 생성. | `approval:write` | H·A |
| `ante approval list` | 결재 목록 조회. | `approval:read` | H·A |
| `ante approval info` | 결재 상세 조회. | `approval:read` | H·A |
| `ante approval review` | 검토 의견 추가. | `approval:read` | H·A |
| `ante approval reopen` | 거절된 결재 재상신. | `approval:write` | H·A |
| `ante approval audit-types` | ``ApprovalType`` enum 외 ``type`` 을 가진 legacy invalid row 식별. | `approval:read` | H·A |
| `ante approval cancel-invalid` | legacy invalid-type approval row 의 administrative cancellation. | `approval:admin` | H·A |
| `ante approval cancel` | 결재 철회 (요청자만 가능). | `approval:write` | H·A |
| `ante approval approve` | 결재 승인. | `approval:admin` | H·A |
| `ante approval reject` | 결재 거절. | `approval:admin` | H·A |
| `ante init` | 비대화형 최소 초기 설정. | — | — |
| `ante bot list` | 봇 목록 조회. | `bot:read` | H·A |
| `ante bot info` | 봇 상세 정보 조회. | `bot:read` | H·A |
| `ante bot create` | 봇 생성. | `bot:admin` | H·A |
| `ante bot remove` | 봇 삭제. | `bot:admin` | H·A |
| `ante bot signal-key` | 봇 시그널 키 조회 또는 재발급. | `bot:admin` | H·A |
| `ante bot positions` | 봇 보유 포지션 조회. | `bot:read` | H·A |
| `ante bot update` | 중지 상태 봇 설정 수정. | `bot:admin` | H·A |
| `ante bot logs` | 봇 실행 로그 조회. | `bot:read` | H·A |
| `ante bot start` | 봇 시작. | `bot:admin` | H·A |
| `ante bot stop` | 봇 중지. | `bot:admin` | H·A |
| `ante bot status` | 봇 live 상태 조회. | `bot:read` | H·A |
| `ante broker status` | 증권사 연결 상태 조회. | `broker:read` | H·A |
| `ante broker balance` | 증권사 계좌 잔고 조회. | `broker:read` | H·A |
| `ante broker positions` | 증권사 보유 종목 조회. | `broker:read` | H·A |
| `ante broker reconcile` | 내부 데이터와 증권사 데이터 대사. | `broker:read` | H·A |
| `ante config get` | 설정 조회. 키 없이 호출하면 전체 목록. | `config:read` | H·A |
| `ante config set` | 동적 설정 변경. 정적 설정은 변경 불가. | `config:write` | H·A |
| `ante config history` | 설정 변경 이력 조회. | `config:read` | H·A |
| `ante strategy validate` | 전략 파일 정적 검증 (AST 기반). | `strategy:write` | H·A |
| `ante strategy submit` | 전략 제출 (검증 -> 로드 테스트 -> Registry 등록). | `strategy:write` | H·A |
| `ante strategy list` | 등록된 전략 목록 조회. | `strategy:read` | H·A |
| `ante strategy set-status` | 전략 상태 변경. | `strategy:write` | H·A |
| `ante strategy info` | 전략 상세 정보 조회 (메타데이터 + 파라미터). | `strategy:read` | H·A |
| `ante strategy summary` | 전략 기간별 성과 집계. | `strategy:read` | H·A |
| `ante strategy performance` | 전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용). | `strategy:read` | H·A |
| `ante data list` | 보유 데이터셋 목록. | `data:read` | H·A |
| `ante data info` | 데이터셋 상세 조회. | `data:read` | H·A |
| `ante data delete` | 데이터셋 삭제. | `data:write` | H·A |
| `ante data schema` | 데이터 스키마 조회. | `data:read` | H·A |
| `ante data storage` | 저장 용량 현황. | `data:read` | H·A |
| `ante data validate` | Parquet 파일 무결성 검증. | `data:read` | H·A |
| `ante backtest run` | 백테스트 실행. | `backtest:run` | H·A |
| `ante backtest history` | 전략별 백테스트 실행 이력 조회. | `backtest:run` | H·A |
| `ante report schema` | 리포트 제출 스키마 조회. | `report:read` | H·A |
| `ante report submit` | 리포트 제출. | `report:write` | H·A |
| `ante report list` | 리포트 목록 조회. | `report:read` | H·A |
| `ante report performance` | 기간별 성과 집계 조회. | `report:read` | H·A |
| `ante report view` | 리포트 상세 조회. | `report:read` | H·A |
| `ante instrument list` | 등록된 종목 목록 조회. | `data:read` | H·A |
| `ante instrument sync` | KIS API에서 종목 마스터 데이터를 동기화. | `data:write` | H·A |
| `ante instrument search` | 키워드로 종목 검색 (종목코드, 한글명, 영문명). | `data:read` | H·A |
| `ante instrument import` | CSV/JSON 파일에서 종목 데이터 import. | `data:write` | H·A |
| `ante member list` | 멤버 목록 조회. | `member:read` | H·A |
| `ante member info` | 멤버 상세 정보 조회. | `member:read` | H·A |
| `ante member list-invalid-roles` | ``MemberRole`` enum 외 role 을 가진 legacy member row 식별. | `member:read` | H·A |
| `ante member register` | 멤버 등록 (토큰 발급). | master-only | H(master) |
| `ante member set-emoji` | 멤버 이모지 설정/변경. | master-only | H(master) |
| `ante member update-scopes` | 멤버 권한 범위 변경. | master-only | H(master) |
| `ante member suspend` | 멤버 일시 정지. | master-only | H(master) |
| `ante member reactivate` | 멤버 재활성화. | master-only | H(master) |
| `ante member revoke` | 멤버 영구 폐기. | master-only | H(master) |
| `ante member rotate-token` | 토큰 재발급 (기존 토큰 즉시 무효화). | master-only | H(master) |
| `ante member reset-password` | Recovery Key로 패스워드 리셋 (인증 불필요). | — | — |
| `ante member regenerate-recovery-key` | Recovery Key 재발급 (인증 불필요). | — | — |
| `ante rule list` | 룰 목록 조회. | `rule:read` | H·A |
| `ante rule info` | 룰 상세 정보 조회. | `rule:read` | H·A |
| `ante rule update` | 계좌 룰 설정 수정. | `rule:admin` | H·A |
| `ante signal connect` | 양방향 JSON Lines 시그널 채널 수립. | — | — |
| `ante system start` | 시스템 시작 (포어그라운드). | `system:admin` | H·A |
| `ante system stop` | 시스템 정상 종료 (SIGTERM). | `system:admin` | H·A |
| `ante system status` | 시스템 상태 표시. | `system:read` | H·A |
| `ante system halt` | 킬 스위치 발동 (전체 거래 중지). | `system:admin` | H·A |
| `ante system clear-halt` | 킬 스위치 해제 (전역 정지 해제 — 봇은 자동 재시작되지 않음). | `system:admin` | H·A |
| `ante trade list` | 거래 목록 조회. | `trade:read` | H·A |
| `ante trade info` | 거래 상세 정보 조회. | `trade:read` | H·A |
| `ante treasury status` | 자금 현황 요약. | `treasury:read` | H·A |
| `ante treasury transactions` | 자금 변동 이력 조회. | `treasury:read` | H·A |
| `ante treasury budgets` | 봇별 예산 목록 조회. | `treasury:read` | H·A |
| `ante treasury set-balance` | 계좌 총 잔고 수동 설정. | `treasury:admin` | H·A |
| `ante treasury allocate` | 봇에 예산 할당. | `treasury:admin` | H·A |
| `ante treasury deallocate` | 봇 예산 회수. | `treasury:admin` | H·A |
| `ante treasury snapshot` | 일별 자산 스냅샷 조회. | `treasury:read` | H·A |
| `ante treasury portfolio value` | 총 자산 가치 조회. | `treasury:read` | H·A |
| `ante treasury portfolio history` | 기간별 자산 추이 조회. | `treasury:read` | H·A |
| `ante update` | ante를 최신 버전으로 업데이트합니다. | — | — |
| `ante feed config set` | API 키를 .feed/.env 파일에 저장한다. | `data:write` | H·A |
| `ante feed config list` | 등록된 API 키 목록을 마스킹하여 표시한다. | `data:read` | H·A |
| `ante feed config check` | API 키 존재 여부를 확인한다. | `data:read` | H·A |
| `ante feed run backfill` | 과거 데이터를 1회 수집한다 (backfill). | `data:write` | H·A |
| `ante feed run daily` | 어제(또는 지정일) 데이터를 1회 수집한다 (daily). | `data:write` | H·A |
| `ante feed start` | 내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다. | `data:write` | H·A |
| `ante feed init` | DataFeed 운영 디렉토리를 초기화한다. | `data:write` | H·A |
| `ante feed status` | 수집 상태를 조회한다. | `data:read` | H·A |
| `ante feed inject` | 외부 CSV 파일에서 과거 데이터를 수동 주입한다. | `data:write` | H·A |

> **H**: Human 토큰 (scope 무제한) · **A**: Agent 토큰 (해당 scope 필요) · **H(master)**: Human master 전용 (#1543) · **—**: 인증 불필요

---

## account — 계좌 생성·조회·관리.

### ante account create

비대화형 계좌 생성 (cold-path 전용).

필수 옵션: ``--broker-type``, ``--account-id``, ``--name``, ``--trading-mode``.
credential은 ``BrokerPreset.required_credentials`` 키를 모두 충족해야 하며,
``--credential`` / ``--credential-env`` / ``--credential-file``로만 제공한다.

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account create [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--broker-type` | - | TEXT | — | 브로커 타입 (BROKER_REGISTRY 등록 값, 예: test, kis-domestic) |
| `--account-id` | - | TEXT | — | 신규 계좌 식별자 |
| `--name` | - | TEXT | — | 계좌 표시 이름 |
| `--trading-mode` | - | virtual / live | — | 거래 모드 (virtual 또는 live) |
| `--credential` | - | TEXT | — | credential 직접 값 (테스트/로컬 편의용, 비권장 — shell history 노출) |
| `--credential-env` | - | TEXT | — | credential을 환경변수에서 읽는다 (권장 채널) |
| `--credential-file` | - | TEXT | — | credential을 파일에서 읽는다 (권장 채널) |
| `--broker-config` | - | TEXT | — | broker-specific 설정 (free-form pass-through, 예: is_paper=true) |
| `--market-order-reserve-buffer-rate` | - | FLOAT | — | 시장가 매수 reserve buffer 비율 (예: 0.005=0.5%). omit 시 BrokerPreset 기본값을 사용한다. NaN/Infinity/음수는 거부된다. |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account list

계좌 목록 조회.

- **필요 scope**: `account:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (active/suspended/deleted) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account info

계좌 상세 정보 조회.

- **필요 scope**: `account:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account info <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account suspend

계좌 거래 정지.

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account suspend <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT | CLI 수동 정지 | 정지 사유 |


### ante account activate

계좌 활성화.

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account activate <ACCOUNT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |


### ante account delete

계좌 삭제 (소프트 딜리트, cold-path 전용).

1.0 정책: account.delete는 IPC runtime command가 아니다. active Ante
runtime이 있으면 차단되며, 서버 정지 상태에서만 AccountService.delete를
직접 호출한다. 소속 봇이 살아 있는 계좌는 AccountHasActiveBotsError로
차단된다(orphan bot 무결성).

SSOT: ``--yes`` 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED``로 실패
(`docs/specs/cli/02-design-decisions.md` 위험 명령 확인 방식 표).

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account delete <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--yes` | - | BOOLEAN | false | 확인 없이 삭제 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account credentials

인증 정보 조회 (마스킹).

- **필요 scope**: `account:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account credentials <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account set-credentials

인증 정보 재설정 (비대화형, cold-path 전용).

SSOT: ``BrokerPreset.required_credentials``를 **모두** 충족해야 하며,
부분 갱신은 허용하지 않는다(`docs/specs/cli/03-commands.md`
`account set-credentials` 입력 계약).
BREAKING CHANGE: 이전 ``--app-key`` / ``--app-secret`` 옵션은 제거되었다.
``--credential`` / ``--credential-env`` / ``--credential-file``를 사용한다.

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account set-credentials <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--credential` | - | TEXT | — | credential 직접 값 (테스트/로컬 편의용, 비권장 — shell history 노출) |
| `--credential-env` | - | TEXT | — | credential을 환경변수에서 읽는다 (권장 채널) |
| `--credential-file` | - | TEXT | — | credential을 파일에서 읽는다 (권장 채널) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante account repair-timezone

legacy invalid IANA timezone 계좌를 복구한다 (cold-path 전용).

``_row_to_account`` 가 stored invalid timezone 을 보존하면서
``Account.timezone_invalid`` marker 를 노출한 row 를 운영자가 명시한
valid IANA timezone 으로 갱신한다. 내부적으로
``AccountService.repair_timezone`` → ``update(timezone=...)`` 으로
위임하며, cold-path 의미론 (서버 정지 필요) 은 본 CLI 와 service
boundary 양쪽에서 차단한다.

실패 코드:

- ``ACCOUNT_RUNTIME_ACTIVE`` 또는
  ``ACCOUNT_STRUCTURAL_CHANGE_REQUIRES_STOPPED_SERVER``: 서버 실행 중
  차단 (cold-path).
- ``ACCOUNT_INVALID_TIMEZONE``: ``new_timezone`` 이 IANA 등록 누락.
- ``ACCOUNT_NOT_FOUND``: ``account_id`` 가 존재하지 않음.

- **필요 scope**: `account:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante account repair-timezone <ACCOUNT_ID> <NEW_TIMEZONE> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ACCOUNT_ID>` | O |  |
| `<NEW_TIMEZONE>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## audit — 감사 로그 조회.

### ante audit list

감사 로그 목록 조회.

- **필요 scope**: `audit:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--offset` | - | INT (0~) | 0 | 오프셋 |


---

## approval — 결재 관리.

### ante approval request

결재 요청 생성.

- **필요 scope**: `approval:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante approval request --type <APPROVAL_TYPE> --title <TITLE> [OPTIONS]
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
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval list

결재 목록 조회.

- **필요 scope**: `approval:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante approval list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 |
| `--type` | - | TEXT | — | 유형 필터 |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval info

결재 상세 조회.

- **필요 scope**: `approval:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval review

검토 의견 추가.

- **필요 scope**: `approval:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante approval review <ID> --result <REVIEW_RESULT> [OPTIONS]
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
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval reopen

거절된 결재 재상신.

- **필요 scope**: `approval:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval audit-types

``ApprovalType`` enum 외 ``type`` 을 가진 legacy invalid row 식별.

분류는 ``offline`` (DB 직접 조회) 이며 ``approval list`` 와 동일하게
``ApprovalService.initialize()`` 가 수반된다. 정상 type row 는 enum SSOT
의 모든 멤버를 ``NOT IN`` 으로 제외하므로 결과에서 자동으로 빠진다.

출력 컬럼: id, type, status, requester, created_at, expires_at.

- **필요 scope**: `approval:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante approval audit-types [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (예: pending) |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval cancel-invalid

legacy invalid-type approval row 의 administrative cancellation.

일반 ``ante approval cancel`` 의 requester ownership rule 을 우회한다 —
invalid-type row 의 requester 는 신뢰할 수 없거나 사라졌을 수 있다. 이
명령은 ``approval:admin`` scope 가 필수이며, 정상 type row 는 서비스 가드
에서 거부된다.

분류는 ``runtime IPC`` 이므로 서버 가동 중에만 동작하며, 서버 정지 시에는
``ante system start`` 후 다시 실행한다. cold-path fallback 은 제공하지
않는다 (Non-goal).

- **필요 scope**: `approval:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante approval cancel-invalid <ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval cancel

결재 철회 (요청자만 가능).

- **필요 scope**: `approval:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval approve

결재 승인.

- **필요 scope**: `approval:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante approval reject

결재 거절.

- **필요 scope**: `approval:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## init

### ante init

비대화형 최소 초기 설정.

멱등성 (I4 — 파일 + master 레코드 기반 재진입):
파일(3) + master row + test account row 5-state 가드로 재구성된다.
모든 상태 완료 시 거부, 그 외 경로에서는 누락된 것만 생성한다.

- **필요 scope**: —
- **토큰**: 인증 불필요

```bash
ante init [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--member-id` | - | TEXT | owner | master 멤버 ID |
| `--name` | - | TEXT | Owner | master 표시 이름 |
| `--dir` | - | PATH | — | 설정 디렉토리 경로 (기본: ~/.config/ante/) |


---

## bot — 봇 생성·시작·중지·조회.

### ante bot list

봇 목록 조회.

- **필요 scope**: `bot:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | - | TEXT | — | 계좌 ID로 필터링 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante bot info

봇 상세 정보 조회.

- **필요 scope**: `bot:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot info <BOT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |


### ante bot create

봇 생성.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot create --name <NAME> --strategy <STRATEGY> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--name` | O | TEXT | — | 봇 이름 |
| `--strategy` | O | TEXT | — | 전략 ID |
| `--account` | - | TEXT | — | 계좌 ID (미지정 시 단일 active 계좌 자동 선택, 0개/2개 이상 시 에러) |
| `--interval` | - | INT (10~3600) | 60 | 실행 주기 (초, 10-3600) |
| `--id` | - | TEXT |  | 봇 ID (미지정 시 자동 생성) |
| `--param` | - | TEXT | — | 전략 파라미터 오버라이드 (key=value, 복수 지정 가능) |


### ante bot remove

봇 삭제.

서버가 실행 중이면 기존 IPC 경로를 사용하고, 서버가 정지되어 있으면
cold-path service가 persisted DB/signal key/snapshot/treasury state를 정리한다.
`--yes` 누락 시 prompt 없이 `CLI_CONFIRMATION_REQUIRED` 에러로 종료한다.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--yes` | - | BOOLEAN | false | 삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패 |


### ante bot signal-key

봇 시그널 키 조회 또는 재발급.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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


### ante bot positions

봇 보유 포지션 조회.

- **필요 scope**: `bot:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot positions <BOT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |


### ante bot update

중지 상태 봇 설정 수정.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot update <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--name` | - | TEXT | — | 봇 이름 |
| `--strategy` | - | TEXT | — | 전략 ID |
| `--interval` | - | INT (10~3600) | — | 실행 주기(초) |
| `--budget` | - | FLOAT | — | 목표 할당 예산 |
| `--auto-restart`, `--no-auto-restart` | - | BOOLEAN | — | 오류 시 자동 재시작 여부 |
| `--max-restart-attempts` | - | INT (1~10) | — |  |
| `--restart-cooldown-seconds` | - | INT (10~600) | — |  |
| `--step-timeout-seconds` | - | INT (5~120) | — |  |
| `--max-signals-per-step` | - | INT (1~200) | — |  |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante bot logs

봇 실행 로그 조회.

- **필요 scope**: `bot:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot logs <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--limit` | - | INT (1~100) | 50 | 조회 수 |
| `--offset` | - | INT (0~) | 0 | 시작 offset |
| `--from` | - | TEXT | — | 시작일/시각 |
| `--to` | - | TEXT | — | 종료일/시각 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante bot start

봇 시작.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot start <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante bot stop

봇 중지.

- **필요 scope**: `bot:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot stop <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante bot status

봇 live 상태 조회.

- **필요 scope**: `bot:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante bot status <BOT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## broker — 증권사 계좌 정보 조회.

### ante broker status

증권사 연결 상태 조회.

- **필요 scope**: `broker:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante broker status --account <ACCOUNT_ID>
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante broker balance

증권사 계좌 잔고 조회.

- **필요 scope**: `broker:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante broker balance --account <ACCOUNT_ID>
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante broker positions

증권사 보유 종목 조회.

- **필요 scope**: `broker:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante broker positions --account <ACCOUNT_ID>
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante broker reconcile

내부 데이터와 증권사 데이터 대사.

- **필요 scope**: `broker:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante broker reconcile --account <ACCOUNT_ID> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |
| `--fix` | - | BOOLEAN | false | 불일치 발견 시 자동 보정 수행 |


---

## config — 설정 조회·변경.

### ante config get

설정 조회. 키 없이 호출하면 전체 목록.

- **필요 scope**: `config:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante config get <KEY> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | - |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante config set

동적 설정 변경. 정적 설정은 변경 불가.

- **필요 scope**: `config:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante config set <KEY> <VALUE> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<KEY>` | O |  |
| `<VALUE>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante config history

설정 변경 이력 조회.

- **필요 scope**: `config:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--limit`, `-n` | - | INT (1~) | 20 | 조회 건수 (기본 20) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## strategy — 전략 관리.

### ante strategy validate

전략 파일 정적 검증 (AST 기반).

- **필요 scope**: `strategy:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy validate <PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<PATH>` | O |  |


### ante strategy submit

전략 제출 (검증 -> 로드 테스트 -> Registry 등록).

- **필요 scope**: `strategy:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy submit <PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<PATH>` | O |  |


### ante strategy list

등록된 전략 목록 조회.

- **필요 scope**: `strategy:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (registered/adopted/archived) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante strategy set-status

전략 상태 변경.

- **필요 scope**: `strategy:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy set-status <STRATEGY_ID> --status <STATUS> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<STRATEGY_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | O | adopted / archived | — | 변경할 전략 상태 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante strategy info

전략 상세 정보 조회 (메타데이터 + 파라미터).

- **필요 scope**: `strategy:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy info <NAME> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<NAME>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante strategy summary

전략 기간별 성과 집계.

- **필요 scope**: `strategy:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy summary <STRATEGY_ID> --period <PERIOD> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<STRATEGY_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--period` | O | daily / weekly / monthly | — | 집계 기간 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante strategy performance

전략 전체 성과 집계 (모든 봇 합산, Agent 피드백용).

--account-id 옵션은 필수다. 미지정 시 fallback 없이 명시적으로 실패한다
(Edge resolver 정렬, query 정책 일관).

- **필요 scope**: `strategy:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante strategy performance <NAME> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<NAME>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account-id` | - | TEXT | — | 계좌 ID (필수, 미지정 시 STRATEGY_MISSING_REQUIRED_ACCOUNT 에러) |


---

## data — 데이터 관리.

### ante data list

보유 데이터셋 목록.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--symbol` | - | TEXT | — | 종목 코드 exact-match 필터 |
| `--timeframe` | - | TEXT | — | 타임프레임 필터 |
| `--type` | - | ohlcv / fundamental | — | 데이터 유형 필터 |
| `--offset` | - | INT (0~) | 0 | 조회 offset |
| `--limit` | - | INT (1~) | 50 | 조회 개수 |
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante data info

데이터셋 상세 조회.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data info <DATASET_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<DATASET_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante data delete

데이터셋 삭제.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data delete <DATASET_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<DATASET_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--type` | - | ohlcv / fundamental | — | dataset_id 파생 유형과 일치해야 하는 데이터 유형 |
| `--yes` | - | BOOLEAN | false | 삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패 |
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante data schema

데이터 스키마 조회.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data schema [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |


### ante data storage

저장 용량 현황.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data storage [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |


### ante data validate

Parquet 파일 무결성 검증.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante data validate [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--symbol` | - | TEXT | — | 검증할 종목 코드 (미지정 시 전체) |
| `--timeframe` | - | TEXT | 1d | 타임프레임 |
| `--fix` | - | BOOLEAN | false | 손상 파일을 .corrupted로 이동 |
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |


---

## backtest — 백테스트.

### ante backtest run

백테스트 실행.

- **필요 scope**: `backtest:run`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante backtest run <STRATEGY_PATH> --start <START> --end <END> [OPTIONS]
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
| `--exchange` | - | TEXT | KRX | 거래소 (기본: KRX) |
| `--data-path` | - | TEXT | — | 데이터 디렉토리 경로 (미지정 시 config_dir 기반) |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


### ante backtest history

전략별 백테스트 실행 이력 조회.

- **필요 scope**: `backtest:run`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--limit` | - | INT (1~) | 20 | 조회 건수 |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


---

## report — 리포트 관리.

### ante report schema

리포트 제출 스키마 조회.

- **필요 scope**: `report:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante report schema [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante report submit

리포트 제출.

- **필요 scope**: `report:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |
| `--run` | - | TEXT | — | 참조할 백테스트 run_id |


### ante report list

리포트 목록 조회.

- **필요 scope**: `report:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante report list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--status` | - | TEXT | — | 상태 필터 (draft/submitted/reviewed/adopted/rejected/archived) |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


### ante report performance

기간별 성과 집계 조회.

- **필요 scope**: `report:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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


### ante report view

리포트 상세 조회.

- **필요 scope**: `report:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


---

## instrument — 종목 마스터 데이터 관리.

### ante instrument list

등록된 종목 목록 조회.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante instrument list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--exchange` | - | TEXT | KRX | 거래소 (기본: KRX) |
| `--type` | - | TEXT | — | 종목 유형 필터 (stock, etf, etn 등) |
| `--listed-only` | - | BOOLEAN | false | 상장 종목만 표시 |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


### ante instrument sync

KIS API에서 종목 마스터 데이터를 동기화.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante instrument sync [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--exchange` | - | TEXT | KRX | 거래소 (기본: KRX) |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


### ante instrument search

키워드로 종목 검색 (종목코드, 한글명, 영문명).

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--limit` | - | INT (1~) | 20 | 최대 결과 수 |
| `--listed-only` | - | BOOLEAN | false | 상장 종목만 검색 |
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


### ante instrument import

CSV/JSON 파일에서 종목 데이터 import.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--db-path` | - | TEXT | — | DB 경로 (미지정 시 config_dir 기반) |


---

## member — 멤버 등록·관리.

### ante member list

멤버 목록 조회.

- **필요 scope**: `member:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante member list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--type` | - | human / agent | — | 멤버 타입 필터 |
| `--org` | - | TEXT | — | 조직 필터 |
| `--status` | - | active / suspended / revoked | — | 상태 필터 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante member info

멤버 상세 정보 조회.

- **필요 scope**: `member:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante member info <MEMBER_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante member list-invalid-roles

``MemberRole`` enum 외 role 을 가진 legacy member row 식별.

본 명령은 canonical config 의 ``db.path`` (``get_db_path()``) 단일 DB 에
대해서만 invalid-role row 를 식별한다. 다른 DB 파일 대상 점검은 본 PR scope
가 아니며, 필요하면 별도 이슈로 분리한다.

``actionable`` 카테고리는 ``status != revoked`` 인 invalid-role row 이며,
운영자가 ``ante member revoke --yes -- <member_id>`` 로 cleanup 해야 한다.
``legacy_revoked`` 는 이미 revoke 된 historical row 다.

분류는 ``offline`` 이지만 ``MemberService.initialize()`` 가 schema migration
DDL 을 수반한다 — 따라서 "read-only" 가 아니다. ``ante member list`` /
``info`` 와 동일한 ``_create_service()`` 패턴을 사용하며 runtime IPC 는
우회한다.

``token_hash`` 는 모든 출력 모드에서 노출되지 않는다 (보안 SSOT).

- **필요 scope**: `member:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante member list-invalid-roles [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante member register

멤버 등록 (토큰 발급).

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member register --id <MEMBER_ID> --type <MEMBER_TYPE> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--id` | O | TEXT | — | 멤버 ID |
| `--type` | O | human / agent | — | 멤버 타입 |
| `--org` | - | TEXT | default | 소속 조직 |
| `--name` | - | TEXT |  | 표시 이름 |
| `--scopes` | - | TEXT |  | 권한 범위 (쉼표 구분) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante member set-emoji

멤버 이모지 설정/변경.

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member set-emoji <MEMBER_ID> <EMOJI>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |
| `<EMOJI>` | O |  |


### ante member update-scopes

멤버 권한 범위 변경.

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member update-scopes <MEMBER_ID> --scopes <SCOPES> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--scopes` | O | TEXT | — | 권한 범위 목록 (쉼표 구분, 빈 문자열은 권한 없음) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante member suspend

멤버 일시 정지.

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member suspend <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member reactivate

멤버 재활성화.

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member reactivate <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member revoke

멤버 영구 폐기.

``--yes`` 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED`` 에러로 종료한다.

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

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
| `--yes` | - | BOOLEAN | false | 삭제를 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패 |


### ante member rotate-token

토큰 재발급 (기존 토큰 즉시 무효화).

- **필요 scope**: master-only
- **토큰**: 🔑 Human master 전용 (#1543)

```bash
ante member rotate-token <MEMBER_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<MEMBER_ID>` | O |  |


### ante member reset-password

Recovery Key로 패스워드 리셋 (인증 불필요).

새 패스워드는 ``--new-password-env <ENV_NAME>`` 또는
``--new-password-file <PATH>``로만 받으며, 둘 다 없거나 둘 다 지정하면 prompt
없이 ``CLI_MISSING_REQUIRED_INPUT``로 실패한다.

- **필요 scope**: —
- **토큰**: 인증 불필요

```bash
ante member reset-password --recovery-key <RECOVERY_KEY> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--recovery-key` | O | TEXT | — | Recovery Key |
| `--new-password-env` | - | TEXT | — | 새 패스워드를 담은 환경변수의 *이름* (값이 아닌 변수명만 받음) |
| `--new-password-file` | - | PATH | — | 새 패스워드를 담은 파일의 경로 (파일 내용 strip) |


### ante member regenerate-recovery-key

Recovery Key 재발급 (인증 불필요).

현재 패스워드는 ``--password-env <ENV_NAME>`` 또는 ``--password-file <PATH>``로만
받으며, 둘 다 없거나 둘 다 지정하면 prompt 없이 ``CLI_MISSING_REQUIRED_INPUT``로
실패한다.

- **필요 scope**: —
- **토큰**: 인증 불필요

```bash
ante member regenerate-recovery-key [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--password-env` | - | TEXT | — | 현재 패스워드를 담은 환경변수의 *이름* (값이 아닌 변수명만 받음) |
| `--password-file` | - | PATH | — | 현재 패스워드를 담은 파일의 경로 (파일 내용 strip) |


---

## rule — 거래 룰 조회·관리.

### ante rule list

룰 목록 조회.

- **필요 scope**: `rule:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante rule list --account <ACCOUNT_ID> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |
| `--scope` | - | global / strategy | — | 룰 범위 필터 |


### ante rule info

룰 상세 정보 조회.

- **필요 scope**: `rule:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante rule info <RULE_ID> --account <ACCOUNT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<RULE_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante rule update

계좌 룰 설정 수정.

- **필요 scope**: `rule:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante rule update <RULE_TYPE> --account <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<RULE_TYPE>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |
| `--enabled`, `--disabled` | - | BOOLEAN | true | 룰 활성화 여부 |
| `--param` | - | TEXT | — | 룰 파라미터 (key=value, 복수 지정 가능) |
| `--params-json` | - | TEXT | — | 룰 파라미터 JSON object |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## signal — 외부 시그널 채널 관리.

### ante signal connect

양방향 JSON Lines 시그널 채널 수립.

- **필요 scope**: —
- **토큰**: 인증 불필요

```bash
ante signal connect --key <KEY> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--key` | O | TEXT | — | 시그널 키 (sk_...) |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## system — 시스템 시작·중지·상태 확인.

### ante system start

시스템 시작 (포어그라운드).

- **필요 scope**: `system:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante system start [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--config-dir` | - | PATH | — | 설정 디렉토리 경로 |


### ante system stop

시스템 정상 종료 (SIGTERM).

- **필요 scope**: `system:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante system stop
```


### ante system status

시스템 상태 표시.

- **필요 scope**: `system:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante system status [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante system halt

킬 스위치 발동 (전체 거래 중지).

- **필요 scope**: `system:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante system halt [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT |  | 사유 |


### ante system clear-halt

킬 스위치 해제 (전역 정지 해제 — 봇은 자동 재시작되지 않음).

- **필요 scope**: `system:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante system clear-halt [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--reason` | - | TEXT |  | 사유 |


---

## trade — 거래 내역 조회.

### ante trade list

거래 목록 조회.

- **필요 scope**: `trade:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante trade list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--bot` | - | TEXT | — | 봇 ID 필터 |
| `--strategy` | - | TEXT | — | 전략 ID 필터 |
| `--from` | - | TEXT | — | 시작일 (YYYY-MM-DD) |
| `--to` | - | TEXT | — | 종료일 (YYYY-MM-DD) |
| `--limit` | - | INT (1~) | 50 | 최대 조회 수 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante trade info

거래 상세 정보 조회.

- **필요 scope**: `trade:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante trade info <TRADE_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<TRADE_ID>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## treasury — 자금 현황 조회·관리.

### ante treasury status

자금 현황 요약.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury status --account <ACCOUNT_ID> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury transactions

자금 변동 이력 조회.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury transactions [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | - | TEXT | — | 계좌 ID 필터 |
| `--type` | - | allocate / deallocate / release / fill / bot_stopped_release | — | 거래 유형 필터 |
| `--bot` | - | TEXT | — | 봇 ID 필터 |
| `--from` | - | TEXT | — |  |
| `--to` | - | TEXT | — |  |
| `--limit` | - | INT (1~100) | 20 | 조회 수 |
| `--offset` | - | INT (0~) | 0 | 시작 offset |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury budgets

봇별 예산 목록 조회.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury budgets [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | - | TEXT | — | 계좌 ID 필터 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury set-balance

계좌 총 잔고 수동 설정.

- **필요 scope**: `treasury:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury set-balance <AMOUNT> --account <ACCOUNT_ID> [OPTIONS]
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<AMOUNT>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury allocate

봇에 예산 할당.

- **필요 scope**: `treasury:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury allocate <BOT_ID> <AMOUNT> --account <ACCOUNT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |
| `<AMOUNT>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante treasury deallocate

봇 예산 회수.

- **필요 scope**: `treasury:admin`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury deallocate <BOT_ID> <AMOUNT> --account <ACCOUNT_ID>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<BOT_ID>` | O |  |
| `<AMOUNT>` | O |  |

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | O | TEXT | — | 계좌 ID |


### ante treasury snapshot

일별 자산 스냅샷 조회.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury snapshot --account <ACCOUNT_ID> [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--date` | - | TEXT | — | 특정 날짜 조회 (YYYY-MM-DD) |
| `--from` | - | TEXT | — | 기간 조회 시작일 (YYYY-MM-DD) |
| `--to` | - | TEXT | — | 기간 조회 종료일 (YYYY-MM-DD) |
| `--account` | O | TEXT | — | 계좌 ID |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury portfolio value

총 자산 가치 조회.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury portfolio value [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | - | TEXT | — | 계좌 ID |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


### ante treasury portfolio history

기간별 자산 추이 조회.

- **필요 scope**: `treasury:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante treasury portfolio history [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--account` | - | TEXT | — | 계좌 ID |
| `--from` | - | TEXT | — |  |
| `--to` | - | TEXT | — |  |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## update

### ante update

ante를 최신 버전으로 업데이트합니다.

게이트 평가 우선순위 (SSOT: docs/specs/cli/02-design-decisions.md
"위험 명령 확인 방식"):
``--check`` → ``--yes`` confirmation(``CLI_CONFIRMATION_REQUIRED``)
→ server-running/``--force``(``UPDATE_SERVER_RUNNING``) → 실제 update.

`--check`은 PyPI 버전 조회만 수행하는 dry-run이다 (`--yes`/server-running
무관, 최우선). `--check`이 아닌 실제 업데이트 실행은 `--yes`가 반드시
필요하며, 누락 시 prompt 없이 ``CLI_CONFIRMATION_REQUIRED`` 에러로
종료한다. `--yes` 게이트는 server 상태 검사와 PyPI 조회 **앞에**
평가하므로, 서버 실행/네트워크 느림·실패 환경에서도 `--yes` 누락
호출은 server-running 안내나 PyPI 실패가 아닌 동일한 구조화 에러
코드로 거절된다.

- **필요 scope**: —
- **토큰**: 인증 불필요

```bash
ante update [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--check` | - | BOOLEAN | false | 업데이트 가능 여부만 확인 |
| `--version` | - | TEXT | — | 특정 버전으로 업데이트 |
| `--yes`, `-y` | - | BOOLEAN | false | 실제 업데이트 실행 확인 (위험 명령). 누락 시 prompt 없이 에러로 실패 |
| `--force` | - | BOOLEAN | false | 서버 실행 중이면 자동 중지 |
| `--format` | - | text / json | — | 출력 형식 (text 또는 json) |


---

## feed — DataFeed — 시세·재무 데이터 수집 파이프라인.

### ante feed config set

API 키를 .feed/.env 파일에 저장한다.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

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
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


### ante feed config list

등록된 API 키 목록을 마스킹하여 표시한다.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed config list [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


### ante feed config check

API 키 존재 여부를 확인한다.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed config check [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


### ante feed run backfill

과거 데이터를 1회 수집한다 (backfill).

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed run backfill [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |
| `--since` | - | TEXT | — | 수집 시작일 (YYYY-MM-DD, config 기본값 오버라이드) |


### ante feed run daily

어제(또는 지정일) 데이터를 1회 수집한다 (daily).

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed run daily [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |
| `--date` | - | TEXT | — | 수집 대상일 (YYYY-MM-DD, 기본값: 어제) |


### ante feed start

내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스를 시작한다.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed start [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


### ante feed init

DataFeed 운영 디렉토리를 초기화한다.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed init <DATA_PATH>
```

**Arguments:**

| 인자 | 필수 | 설명 |
|------|------|------|
| `<DATA_PATH>` | - |  |


### ante feed status

수집 상태를 조회한다.

- **필요 scope**: `data:read`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed status [OPTIONS]
```

**Options:**

| 옵션 | 필수 | 타입 | 기본값 | 설명 |
|------|------|------|--------|------|
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


### ante feed inject

외부 CSV 파일에서 과거 데이터를 수동 주입한다.

- **필요 scope**: `data:write`
- **토큰**: 🔑 Human(무제한) / Agent(scope 필요)

```bash
ante feed inject <PATH> --symbol <SYMBOL> [OPTIONS]
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
| `--data-path` | - | TEXT | — | 데이터 저장소 경로 (미지정 시 config_dir 기반) |


---

