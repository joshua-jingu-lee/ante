# 모듈과 운영 영역

Ante를 처음 운용하는 사용자와 AI 에이전트가 "이 명령은 시스템의 무엇을 건드리는가"를 빠르게 판단하기 위한 지도입니다.

[핵심 개념](concepts.md)은 Ante의 큰 흐름을 설명하고, 이 문서는 그 흐름을 이루는 주요 모듈과 CLI 명령 그룹의 책임을 설명합니다. 더 깊은 구현 경계는 [아키텍처 모듈 맵](../docs/architecture/module-map.md)과 [모듈 스펙 인덱스](../docs/specs/README.md)를 봅니다.

## 읽는 법

- **모듈**은 Ante 안에서 하나의 책임을 맡는 경계입니다. 예: `Strategy`, `Bot`, `Treasury`.
- **운영 영역**은 CLI에서 사용자가 제어하는 표면입니다. 예: `ante strategy`, `ante bot`, `ante treasury`.
- 하나의 운영 영역이 하나의 모듈과 거의 대응되는 경우가 많지만, 항상 1:1은 아닙니다. 예를 들어 `ante broker`는 브로커 계좌를 새로 만드는 명령이 아니라, 이미 연결된 증권사 어댑터의 live 상태를 조회·대사하는 표면입니다.

## 한눈에 보는 운영 지도

| CLI 그룹 | 제어 대상 | 의미 | 먼저 알아야 할 점 |
|---|---|---|---|
| `init` | 초기 설정, master 멤버, 기본 테스트 계좌 | Ante 인스턴스의 파일·DB 골격을 만든다 | 이미 초기화된 설정 디렉토리는 덮어쓰지 않는다 |
| `member` | Member | 사용자와 AI 에이전트의 정체성·토큰·권한을 관리한다 | Agent는 scope로 제한되고, master human은 최종 관리자다 |
| `account` | Account | 거래 계좌의 로컬 정의, 브로커 종류, 인증정보, 거래 모드를 관리한다 | 생성·삭제·인증정보 변경은 서버 정지 상태에서만 하는 cold-path 작업이다 |
| `broker` | Broker Adapter | 증권사 API의 live 상태, 잔고, 포지션, 대사를 조회한다 | `account`가 계좌 정의라면 `broker`는 외부 증권사와의 연결 상태다 |
| `treasury` | Treasury | Ante 내부의 자금 현황, 봇별 예산, 자산 스냅샷을 관리한다 | 주문 직전 자금 게이트의 기준이 된다 |
| `strategy` | Strategy Registry, Validator | 전략 파일을 검증·등록하고 상태와 성과를 조회한다 | 전략은 주문을 직접 내지 않고 `Signal`만 반환한다 |
| `backtest` | Backtest Engine | 전략을 과거 데이터로 격리 시뮬레이션한다 | 실거래 전 가설을 확인하는 안전 게이트다 |
| `bot` | Bot Manager | 등록된 전략을 특정 계좌에서 실행하는 런타임 인스턴스를 관리한다 | 하나의 봇은 하나의 실행 단위이며 계좌와 전략에 연결된다 |
| `signal` | Signal Channel | 외부 에이전트가 JSON Lines로 시그널을 주고받는 채널을 연다 | 외부 시그널 전략에서 사용한다 |
| `rule` | Rule Engine | 계좌·전략에 적용되는 거래 룰을 조회·수정한다 | 모든 주문은 전역 룰과 전략별 룰을 통과해야 한다 |
| `approval` | Approval | Agent 요청을 사용자가 승인·반려하는 결재 흐름을 관리한다 | 전략 채택처럼 실제 자본에 닿는 결정은 사용자의 최종 판단을 거친다 |
| `data` | DataStore | 보유 시세·재무 데이터셋을 조회·검증·삭제한다 | 저장된 Parquet 데이터의 읽기·관리 표면이다 |
| `feed` | DataFeed | 공공 API에서 백테스트용 데이터를 수집·주입한다 | `data`가 저장소라면 `feed`는 저장소를 채우는 배치 수집 파이프라인이다 |
| `instrument` | Instrument | 종목 코드, 이름, 거래소 같은 종목 마스터 데이터를 관리한다 | 전략과 데이터 조회가 같은 종목 어휘를 쓰도록 돕는다 |
| `trade` | Trade | 체결·취소·거부 등 거래 이력을 조회한다 | 성과 분석과 사후 점검의 원천 기록이다 |
| `report` | Report Store | 백테스트·운영 리포트를 저장하고 조회한다 | 결재 요청의 근거 자료로 연결된다 |
| `audit` | Audit | 누가 언제 무엇을 했는지 감사 로그를 조회한다 | Agent 활동 추적과 사고 분석에 사용한다 |
| `config` | Config | 런타임 설정을 조회·변경한다 | 정적 설정과 동적 설정의 변경 가능 범위가 다르다 |
| `system` | System Runtime | 서버 시작·종료·상태·전역 정지를 제어한다 | `halt`는 전체 거래를 멈추는 운영 안전장치다 |
| `update` | 패키지 업데이트 | Ante 패키지와 후속 마이그레이션을 실행한다 | 실제 운영 환경에서는 백업 후 실행한다 |

## 권한 모델

Ante CLI는 기본적으로 **default-deny**로 동작합니다. 인증 없이 실행할 수 있도록 명시된 부트스트랩·복구 명령을 제외하면, 대부분의 명령은 `ANTE_MEMBER_TOKEN`으로 인증된 멤버만 실행할 수 있습니다.

| 구분 | 의미 | 운용 기준 |
|---|---|---|
| Human master | 사용자의 대표 계정이다. scope 제한 없이 모든 명령을 실행할 수 있다 | 최종 승인, 멤버 관리, 긴급 정지 같은 대표 권한에 사용한다 |
| Agent | AI 에이전트 계정이다. 등록 시 부여된 scope 안에서만 명령을 실행할 수 있다 | 역할에 필요한 최소 scope만 부여한다 |
| 공개 명령 | 토큰 없이 실행 가능한 초기화·복구 경로다 | `ante init`, recovery key 기반 복구처럼 토큰을 아직 쓸 수 없거나 잃어버린 상황에 한정한다 |
| master-only | scope가 아니라 human master 자체를 요구하는 명령이다 | 멤버 등록, scope 변경, 토큰 재발급처럼 권한 체계를 바꾸는 작업에 적용된다 |

Scope는 `도메인:권한` 형식입니다. 예를 들어 `strategy:write`는 전략 검증·등록 계열 작업을 허용하고, `bot:admin`은 봇 생성·시작·중지 같은 운영 작업을 허용합니다. 권한 동사는 대체로 다음 의미를 가집니다.

| 권한 | 대략적 의미 |
|---|---|
| `read` | 조회한다 |
| `write` | 리소스를 만들거나 내용을 바꾼다 |
| `admin` | 실행 상태나 운영상 위험이 큰 설정을 바꾼다 |
| `run` | 백테스트처럼 별도 실행 작업을 수행한다 |

명령별 정확한 필요 scope와 토큰 조건은 [CLI 레퍼런스](cli.md)의 `필요 scope`와 `토큰` 항목을 봅니다. Agent를 어떻게 나눠 등록할지는 [에이전트 가이드](agent.md), scope가 막지 못하는 보안 한계는 [보안 주의사항](security.md)을 봅니다.

## 주요 흐름과 모듈

### 전략을 실거래까지 올리는 흐름

| 단계 | 중심 모듈 | 관련 CLI |
|---|---|---|
| 전략 작성 | Strategy | 파일 작성 |
| 정적 검증 | Strategy Validator | `ante strategy validate` |
| 백테스트 | Backtest, DataStore | `ante backtest run` |
| 근거 정리 | Report Store | `ante report submit/list/view` |
| 채택 판단 | Approval | `ante approval request/approve/reject` |
| 실행 단위 생성 | Bot Manager | `ante bot create` |
| 운영 시작 | Bot, Rule Engine, Treasury, Broker Adapter | `ante bot start` |
| 결과 관찰 | Trade, Treasury, Report | `ante trade`, `ante treasury`, `ante report` |

### 주문 한 건이 지나가는 흐름

| 순서 | 모듈 | 맡는 일 |
|---|---|---|
| 1 | Strategy 또는 Signal Channel | 매매 의도인 `Signal`을 만든다 |
| 2 | Bot | `Signal`을 주문 요청 이벤트로 바꾼다 |
| 3 | Rule Engine | 전역 룰과 전략별 룰로 주문을 검증한다 |
| 4 | Treasury | 가용 자금과 예약 가능 금액을 확인한다 |
| 5 | API Gateway | 외부 API 호출을 큐잉하고 rate limit을 지킨다 |
| 6 | Broker Adapter | 증권사 API로 주문을 제출하고 체결 결과를 받는다 |
| 7 | Trade, Treasury, Notification | 기록, 잔고 반영, 알림을 처리한다 |

## 모듈 사전

> 패턴: **무엇인가 → 무엇을 제어하나 → 무엇과 이어지나 → 관련 명령**

### 거래 결정과 실행

- **Strategy (전략)** — "언제·무엇을·얼마나 사고팔까"를 담은 Python 클래스다.
  *제어:* 전략 파일 검증, Registry 등록, 상태 변경, 성과 조회. · *이어짐:* Bot이 Strategy를 로드해 주기적으로 실행한다. · *명령:* `ante strategy validate / submit / list / info / set-status / performance`

- **Signal (시그널)** — 전략이 반환하는 매매 의도다. 종목, 방향, 수량, 주문 유형, 사유를 담는다.
  *제어:* 직접 관리 대상이라기보다 전략과 주문 흐름 사이의 표준 메시지다. · *이어짐:* Bot이 Signal을 주문 이벤트로 변환한다. · *명령:* 런타임 내부, 외부 시그널은 `ante signal connect`

- **Bot (봇)** — 등록된 전략을 특정 계좌에서 실제로 돌리는 실행 인스턴스다.
  *제어:* 생성, 시작, 중지, 삭제, 설정 변경, 포지션·로그 조회. · *이어짐:* Strategy, Account, Rule Engine, Treasury, Broker Adapter. · *명령:* `ante bot create / start / stop / status / positions / logs`

- **Signal Channel (시그널 채널)** — 외부 에이전트가 장기 실행 JSON Lines 채널로 시그널을 전달하는 통로다.
  *제어:* 시그널 키 기반 연결. · *이어짐:* 외부 시그널 수신 전략과 Bot. · *명령:* `ante signal connect`

### 계좌, 자금, 증권사

- **Account (계좌)** — 거래소, 통화, 브로커 종류, 인증정보, 거래 모드를 묶는 최상위 운영 단위다.
  *제어:* 계좌 생성·조회·정지·재활성화·삭제, 브로커 인증정보 갱신. · *이어짐:* Bot, Treasury, Rule Engine, Broker Adapter가 계좌 아래에 모인다. · *명령:* `ante account create / list / info / suspend / activate / delete`

- **Treasury (자금 관리)** — Ante 내부에서 계좌 잔고와 봇별 예산을 추적하고, 주문 전 가용 자금을 확인하는 모듈이다.
  *제어:* 잔고 요약, 자금 배정·회수, 거래 내역, 일별 자산 스냅샷. · *이어짐:* 주문 승인 직전 자금 게이트, Trade 체결 기록. · *명령:* `ante treasury status / allocate / deallocate / budgets / snapshot`

- **Broker Adapter (증권사 어댑터)** — KIS 같은 증권사 API를 Ante의 공통 인터페이스로 감싸는 모듈이다.
  *제어:* live 연결 상태, 외부 잔고·포지션 조회, 내부 기록과 외부 상태 대사. · *이어짐:* Account 인증정보, API Gateway, Trade reconciliation. · *명령:* `ante broker status / balance / positions / reconcile`

- **API Gateway** — 여러 봇의 외부 API 호출을 큐잉·캐싱·rate limit 처리하는 내부 모듈이다.
  *제어:* 별도 공개 CLI 표면은 없다. · *이어짐:* Treasury 통과 후 Broker Adapter 앞단. · *명령:* 공개 명령 없음

### 안전 게이트

- **Rule Engine (거래 룰)** — 모든 주문을 전역 룰과 전략별 룰로 검증한다.
  *제어:* 계좌별 룰 조회·수정. · *이어짐:* Bot의 주문 요청, Treasury 자금 확인. · *명령:* `ante rule list / info / update`

- **Backtest (백테스트)** — 전략을 과거 데이터로 격리 시뮬레이션해 실거래 전 가설을 검증한다.
  *제어:* 백테스트 실행과 이력 조회. · *이어짐:* Strategy, DataStore, Report Store, Approval. · *명령:* `ante backtest run / history`

- **Approval (결재)** — Agent가 낸 요청을 사용자가 승인·반려하는 의사결정 모듈이다.
  *제어:* 요청 생성, 조회, 검토 의견, 승인, 반려, 철회. · *이어짐:* 전략 채택, 봇 생성, 예산 변경 같은 운영 결정. · *명령:* `ante approval request / list / info / review / approve / reject`

- **System Halt (전역 정지)** — 모든 활성 계좌를 정지시켜 새 거래를 막는 운영 안전장치다.
  *제어:* 전역 정지와 해제. · *이어짐:* Account 상태, Bot 운영 상태. · *명령:* `ante system halt / clear-halt`

### 데이터와 종목

- **Instrument (종목 마스터)** — 종목 코드, 이름, 거래소, 유형 같은 기준 데이터를 관리한다.
  *제어:* 종목 조회, 검색, 동기화, 파일 import. · *이어짐:* Strategy의 symbol, DataStore 경로, Broker 주문. · *명령:* `ante instrument list / search / sync / import`

- **DataStore (데이터 저장소)** — 시세·재무 데이터의 유일한 Parquet 읽기·쓰기 접근 계층이다.
  *제어:* 보유 데이터셋 조회, 스키마 확인, 저장 용량 확인, 무결성 검증, 삭제. · *이어짐:* StrategyContext, Backtest, DataFeed, 실시간 Collector. · *명령:* `ante data list / info / schema / storage / validate / delete`

- **DataFeed (데이터 피드)** — data.go.kr, DART 같은 외부 공공 API에서 백테스트용 데이터를 배치 수집하는 ETL 파이프라인이다.
  *제어:* API 키 설정, 운영 디렉토리 초기화, backfill/daily 수집, 스케줄러 시작, CSV 주입. · *이어짐:* DataStore에 정규화된 데이터를 저장한다. · *명령:* `ante feed init / config / run backfill / run daily / start / inject`

### 기록과 피드백

- **Trade (거래 기록)** — 주문 체결, 취소, 거부, 실패를 영속 저장하고 포지션 변동을 추적한다.
  *제어:* 거래 목록과 상세 조회. · *이어짐:* Broker 체결 이벤트, Treasury 잔고, Strategy 성과. · *명령:* `ante trade list / info`

- **Report Store (리포트 저장소)** — 백테스트·운영 리포트를 저장하고 성과 피드백을 제공한다.
  *제어:* 리포트 스키마 조회, 제출, 목록·상세·성과 조회. · *이어짐:* Approval의 근거 자료, Agent의 전략 개선. · *명령:* `ante report schema / submit / list / view / performance`

- **Audit (감사 로그)** — 멤버가 수행한 주요 행동을 기록하고 조회한다.
  *제어:* 멤버·액션·기간별 감사 로그 조회. · *이어짐:* Member 인증, Approval, 운영 명령 전반. · *명령:* `ante audit list`

- **Notification (알림)** — 결재 요청, 체결, 위험 이벤트 같은 알림을 외부 채널로 보낸다.
  *제어:* 현재 사용자 가이드의 직접 CLI 표면은 제한적이다. · *이어짐:* Approval, Trade, Rule Engine, System Halt. · *명령:* 공개 leaf 명령 없음

### 행위자와 기반

- **Member (멤버)** — 사용자와 AI 에이전트의 정체성, 토큰, 권한(scope)을 관리한다.
  *제어:* 멤버 등록, 조회, scope 변경, 정지·재활성화, 토큰 재발급, 복구키 관리. · *이어짐:* 모든 인증 필요한 CLI 명령, Audit. · *명령:* `ante member register / list / update-scopes / suspend / rotate-token`

- **Config (설정)** — 정적 TOML, 비밀값 env, 동적 SQLite 설정을 통합해 읽고 일부 값을 런타임에 바꾼다.
  *제어:* 설정 조회, 동적 설정 변경, 변경 이력 조회. · *이어짐:* System Runtime, Logging, Approval, DataFeed 등. · *명령:* `ante config get / set / history`

- **EventBus** — 주문, 시스템 이벤트, 알림을 느슨하게 잇는 내부 이벤트 발행·구독 인프라다.
  *제어:* 공개 CLI 표면은 없다. · *이어짐:* 주문 흐름과 모듈 간 비동기 통신 전반. · *명령:* 공개 명령 없음

- **CLI/IPC** — 사용자와 Agent가 함께 쓰는 운영 인터페이스와, CLI가 서버 프로세스에 명령을 위임하는 통신 계층이다.
  *제어:* 명령 실행, JSON 출력, 런타임 명령 위임. · *이어짐:* 모든 운영 모듈. · *명령:* `ante --format json ...`, 런타임 명령 전반

## 자주 헷갈리는 경계

### `account`와 `broker`

`account`는 Ante 안에 저장되는 계좌 정의를 다룹니다. 브로커 종류, 거래 모드, 인증정보, 계좌 상태가 여기에 속합니다.

`broker`는 그 계좌 정의를 사용해 외부 증권사 API의 현재 상태를 조회하거나 내부 상태와 대사합니다. 계좌를 새로 만들거나 인증정보를 바꾸는 일은 `broker`가 아니라 `account`의 책임입니다.

### `treasury`와 `broker balance`

`treasury`는 Ante 내부의 자금 관리 기준입니다. 봇별 예산, 예약 금액, 가상 계좌 잔고, 일별 스냅샷을 다룹니다.

`broker balance`는 증권사 API가 돌려주는 외부 계좌 상태입니다. 운영 중에는 두 값이 어긋날 수 있으므로 `broker reconcile`과 Trade/Treasury 기록으로 차이를 점검합니다.

### `data`와 `feed`

`data`는 이미 저장된 데이터셋을 읽고 관리하는 표면입니다.

`feed`는 외부 API에서 데이터를 가져와 DataStore에 채우는 수집 파이프라인입니다. 백테스트 데이터가 부족하면 보통 `data` 명령으로 상태를 확인하고, `feed` 명령으로 채웁니다.

### `strategy`와 `bot`

`strategy`는 매매 판단 로직의 정의와 등록 상태를 다룹니다.

`bot`은 등록된 전략을 특정 계좌·주기·예산 조건으로 실행하는 런타임 인스턴스입니다. 같은 전략을 여러 봇에 실어 서로 다른 계좌나 설정으로 운영할 수 있습니다.

### `approval`과 `rule`

`approval`은 사용자의 최종 판단을 받는 사람 중심 게이트입니다.

`rule`은 실행 중 모든 주문에 적용되는 시스템 중심 게이트입니다. 승인된 전략이라도 룰과 자금 확인을 통과하지 못하면 주문은 차단됩니다.

## 다음 단계

- 전체 흐름이 필요하면 [핵심 개념](concepts.md)을 봅니다.
- 실제 명령 형식이 필요하면 [CLI 레퍼런스](cli.md)를 봅니다.
- 전략을 직접 작성하려면 [전략 작성 가이드](strategy.md)를 봅니다.
- 구현 책임 경계가 필요하면 [아키텍처 모듈 맵](../docs/architecture/module-map.md)을 봅니다.
