# Core 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/core/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) 모듈 구성

## 개요

Core 모듈은 **모든 모듈이 공유하는 기반 인프라**를 제공한다.
시스템 전체에서 단일 인스턴스로 공유되며, 개별 도메인 모듈은 Core가 제공하는 계약에 따라 협력한다.

**주요 기능**:
- **Database**: SQLite WAL 모드 비동기 래퍼 — writer/reader 분리로 동시 읽기/쓰기 지원

> 시스템 로그(JSONL·Fingerprint 등)는 별도 모듈 스펙 [logging/README.md](../logging/README.md)에서 관리한다.

## Database 인터페이스

### 생성자

```python
Database(db_path: str)
```

`db_path`는 Config 스펙의 Ante instance/path contract에 따라 정규화된
canonical DB 경로이다. 기본값은 `<config_dir>/db/ante.db`이며, CWD 기준
`db/ante.db`를 Core에서 직접 조합하지 않는다.

### 퍼블릭 메서드

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `connect` | — | None | DB 연결 초기화. writer + reader 두 연결 생성 |
| `close` | — | None | 모든 연결 종료 |
| `execute` | sql: str, params: tuple = () | None | INSERT/UPDATE/DELETE 실행 (writer 사용, 자동 커밋) |
| `fetch_one` | sql: str, params: tuple = () | dict \| None | 단일 행 조회 (reader 사용). dict(컬럼명 → 값) 반환 |
| `fetch_all` | sql: str, params: tuple = () | list[dict] | 다중 행 조회 (reader 사용) |
| `execute_script` | sql: str | None | DDL 스크립트 실행 (테이블 생성 등, writer 사용) |

### SQLite PRAGMA 설정

연결 초기화 시 다음 PRAGMA를 설정한다:

| PRAGMA | 값 | 설명 |
|--------|-----|------|
| `journal_mode` | WAL | Write-Ahead Logging — 동시 읽기/쓰기 지원 |
| `synchronous` | NORMAL | WAL 모드에서 안전한 성능 최적화 |
| `temp_store` | MEMORY | 임시 테이블을 메모리에 저장 |
| `foreign_keys` | ON | 외래 키 제약 활성화 |
| `busy_timeout` | 5000 | 잠금 대기 타임아웃 (밀리초) |

### 설계 근거

1. **Writer/Reader 분리**: 쓰기 작업은 writer 연결, 읽기 작업은 reader 연결을 사용하여 WAL 모드의 동시성 이점을 활용
2. **aiosqlite 래핑**: asyncio 기반 시스템에서 DB I/O가 이벤트 루프를 차단하지 않도록 비동기 래퍼 사용
3. **dict 반환**: `aiosqlite.Row`를 dict로 변환하여 모듈 간 데이터 전달을 단순화
4. **자동 커밋**: `execute()` 호출 시 자동 커밋으로 트랜잭션 관리 단순화

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## Canonical Exchange Vocabulary

> 이 절은 Ante 전역에서 `exchange`가 의미하는 **canonical vocabulary와 적용 범위의 계약 SSOT**다.
> 결정 배경·근거·소비자 영향은 ADR [D-016](../../decisions/D-016-canonical-exchange-vocabulary.md)에 정리되어 있으며,
> 본 절이 normative 계약 본문이다. ADR은 본 절을 링크하고 계약 본문을 중복 기재하지 않는다.

`exchange`는 instrument / account / data / strategy / backtest가 공유하는 식별 차원이다.
1.0 시점에 각 표면이 서로 다른 허용값 집합과 검증 동작을 갖고 있어 SSOT가 부재했고, 본 절이
그 단일 계약을 확정한다. **런타임 enforcement·코드 동작 변경은 본 절의 범위가 아니다**(후속 이슈
#1576/#1577/#1578/#1579로 위임). 본 절은 "무엇이 canonical이고 어느 경계에서 어떻게 거부되어야
하는지"의 계약만 정의한다.

### Canonical set

```
CanonicalExchange = {KRX, NYSE, NASDAQ, AMEX, TEST}
```

- canonical exchange 값은 **대문자 고정 집합**이다. 위 5종이 신규 입력 검증 vocabulary 전체다.
- 대소문자 정규화·별칭(alias)·사용자 정의 exchange set은 1.0 비목표다. 입력은 위 리터럴과
  정확히 일치해야 한다.
- 코드 레벨 SSOT(상수 단일화)는 #1576의 범위다. 본 절은 값 집합 자체의 계약만 고정한다.

### Wildcard 정책

- `*`는 **실제 exchange가 아니다.** `StrategyMeta.exchange` 전용 wildcard로, "OHLCV만 있으면
  어떤 시장에서도 동작하는 범용 전략"을 의미한다.
- `*`가 허용되는 표면은 **`StrategyMeta.exchange` 단 하나**다.
- account / instrument / DataStore write·append·경로 해석(신규 경로 생성) / backtest
  `--exchange` override 등 다른 모든 신규 입력·경로 식별 경계에서 `*`는 거부된다(실제
  거래소 식별자·경로가 아니므로). 기존 경로 read 호환은 `*` 거부가 아니라 "Legacy
  out-of-vocabulary 호환 정책"이 규율한다(`*`는 저장된 legacy 경로가 될 수 없으므로
  read에 신규 입력 검증을 적용하지 않는다).

### Canonical-known vs 1.0 runtime/account-supported

canonical-known(=검증 vocabulary)과 1.0 시점 account preset이 실제 제공하는 exchange는 다르다.

| exchange | canonical-known | 1.0 account preset 제공 | 비고 |
|----------|-----------------|-------------------------|------|
| `KRX` | O | O | `kis-domestic` preset (`docs/specs/account/03-data-model.md`의 `BROKER_PRESETS` `kis-domestic` 항목, `exchange="KRX"`) |
| `TEST` | O | O | `test` preset (`docs/specs/account/03-data-model.md`의 `BROKER_PRESETS` `test` 항목, `exchange="TEST"`) |
| `NYSE` | O | X | canonical-known이나 1.0 account preset 미제공 |
| `NASDAQ` | O | X | canonical-known이나 1.0 account preset 미제공 |
| `AMEX` | O | X | canonical-known이나 1.0 account preset 미제공 |

canonical-known은 신규 입력이 거부되지 않아야 하는 vocabulary이고, account preset 제공 여부는
"1.0에서 실제 계좌를 만들 수 있는가"와 별개 차원이다. `NYSE/NASDAQ/AMEX`는 canonical vocabulary
이지만 1.0 account preset은 `KRX`,`TEST`만 제공한다.

이 둘은 **별개의 두 축**이다:
- **축 A — exchange-vocabulary 유효성**: 신규 입력 값이 canonical 5종(`{KRX, NYSE, NASDAQ, AMEX, TEST}`)
  안인지로 판정한다. canonical 5종은 어떤 표면에서도 "invalid exchange"로 거부되지 않는다.
  오직 non-canonical(예: `ORACLE_INVALID_EXCHANGE`)만 invalid-exchange 거부 대상이다.
- **축 B — 1.0 운영/preset 가용성**: 1.0 account preset은 `KRX`,`TEST`만 제공한다. canonical
  이지만 1.0 preset이 없는 값(`NYSE/NASDAQ/AMEX`)을 특정 경로(예: preset 기반 `account create`)로
  계좌 생성할 수 있는지는 preset/broker-config 제약이며, 이는 invalid-exchange 거부가 **아니다**
  (별개 에러/제약 차원).

**불변식**: 어떤 표면도 canonical 5종 값을 "invalid exchange"로 거부하지 않는다. 표면별
제약(1.0 preset 미제공, cold-path 409, read legacy 호환 등)은 exchange-vocabulary 유효성(축 A)과
구분되는 별개 축이다. (#1578 구현자는 이 불변식으로 자가검증한다: canonical 입력 `exchange="NYSE"`가
서비스 검증 에러가 되면 축 A 위반이다.)

### exchange vs market vs source vs broker_type

`exchange`는 아래 차원들과 **별개**이며 서로 값을 섞지 않는다.

| 차원 | 값 예 | 의미 | exchange와의 관계 |
|------|-------|------|-------------------|
| `exchange` | `KRX`, `NYSE`, `NASDAQ`, `AMEX`, `TEST` | 거래소 (canonical vocabulary) | — |
| market / category | `KOSPI`, `KOSDAQ`, `KONEX` | KRX 내부 시장구분 | **거래소가 아니다.** `exchange=KRX`의 하위 market. exchange 자리에 올 수 없다 |
| `source` | `data_go_kr`, `dart`, `yahoo` | 데이터 출처 | exchange와 별개 차원. 검증·경로에서 교차하지 않는다 |
| `broker_type` | `kis-domestic`, `test` | 브로커 어댑터 종류 | exchange와 별개 차원. preset이 broker_type→exchange를 매핑할 뿐 동일하지 않다 |

`KOSPI`/`KOSDAQ`/`KONEX`는 `exchange` 값이 아니라 KRX 내부 market/category다(`docs/specs/data-feed/04-schema.md`의 `market` 필드 참조). broker adapter market code(`KOSPI`/`KOSDAQ`) 정규화는 1.0 비목표다.

### Per-surface 허용/거부 + 검증·에러 계약 매트릭스

검증은 **표면별로 분리**된다. 같은 vocabulary라도 어느 경계에서 어떤 에러 계약으로 거부되는지는
표면마다 다르다.

| 표면 | canonical | `*` | non-canonical 신규 입력 거부 계약 | 비고 |
|------|-----------|-----|-----------------------------------|------|
| Instrument CLI `list`/`sync`/`import` | 허용 | 거부 | non-zero exit + 구조화 error payload (`{status:"error", code, message}`) | #1577 enforcement. **주 신규 입력 표면** (oracle `ORACLE_INVALID_EXCHANGE` 출처) |
| Account CLI preset (`account create` 등) | canonical 5종은 invalid-exchange로 거부되지 않음 (축 A); 1.0 preset 자동 구성은 `KRX`/`TEST` preset만 (축 B) | 거부 | non-zero exit | 축 A: `*`/non-canonical은 거부. 축 B: 1.0 preset 경로는 `KRX`(`kis-domestic`)/`TEST`(`test`) preset만 자동 구성하며, preset 미제공 canonical 값(`NYSE/NASDAQ/AMEX`)은 **preset/broker 가용성 제약**이지 invalid-exchange 거부가 아니다(별개 차원) |
| AccountService (생성/검증) | canonical 5종 허용 (축 A: non-canonical만 서비스 검증 에러) | 거부 | 서비스 검증 에러 | `exchange`는 identity 필드(`docs/specs/account/03-data-model.md:96`). canonical 5종은 서비스 exchange 검증에서 거부되지 않는다. 1.0 account preset이 `NYSE/NASDAQ/AMEX`를 미제공하는 것은 **축 B(preset/broker 가용성) 제약**이며 "invalid exchange 거부"가 아니다(별개 차원) |
| Account Web — `POST /api/accounts` (cold-path 계좌 생성) | — | — | **cold-path 가드가 입력 무관 즉시 409** (invariant I1; `src/ante/web/routes/accounts.py`의 `create_account` 핸들러가 진입 즉시 409 raise) | **422 아님.** `exchange` 포함 모든 입력이 런타임에 차단됨 (계좌 생성은 cold-path 전용) |
| Account Web — `PUT /api/accounts/{account_id}` structural/identity 변경 (`exchange` 등) | — | — | **structural 가드가 409** (invariant I1/I4; `src/ante/web/routes/accounts.py`의 `STRUCTURAL_FIELDS`에 `exchange` 포함) | **422 아님.** `exchange`는 생성 후 수정 불가 identity 필드(`docs/specs/account/03-data-model.md:96`)이므로 런타임 변경 시도가 cold-path 409로 차단됨 |
| Account Web — `PUT /api/accounts/{account_id}` mutable-only (`name`/`timezone`/`trading_hours_start`/`trading_hours_end`) | — | — | (exchange 검증 범위 밖) | **409 아님 — 런타임 허용.** `src/ante/web/routes/accounts.py`의 `MUTABLE_FIELDS` 4종은 정상 런타임 업데이트다. #1578 구현자는 이 경로를 cold-path 409로 막지 않는다 |
| Account Web OpenAPI/schema 레벨 | — | — | 빈 문자열/형식 오류는 **422** | cold-path 문서(스키마 검증) 전용. 런타임 차단(409)과 다른 층 |
| DataStore path API — `write`/`append`/신규 경로 생성 | 허용 | 거부 | 신규 경로 생성 시 non-canonical·`*` 거부(스펙상 예외 처리) | feed/data CLI 옵션이 아니라 DataStore 메서드 인자 표면. `*`는 경로로 해석 불가 |
| DataStore path API — `read`(기존 경로, legacy out-of-vocab 포함) | 허용 | (입력 검증 미적용) | **거부하지 않음.** 신규 입력 검증을 기존 경로 read 인자에 적용하지 않는다 | "Legacy out-of-vocabulary 호환 정책" 절 우선. 이미 저장된 legacy 경로(예: `.../ohlcv/1d/LSE/...`)는 그대로 읽힌다 |
| `StrategyMeta.exchange` | 허용 | **허용** | validator 에러 | **`*` 유일 허용 표면** (`docs/specs/strategy/03-09-strategy-validator.md`) |
| Backtest `--exchange` override | (목표: canonical만) | (목표: 거부) | **현재 CLI/`src/ante/backtest/`에 미구현 — spec-vs-implementation gap** | #1578 정렬 대상(옵션 신설 포함). 기존 표면처럼 서술하지 않는다 |

판정 보조 노트:
- 시나리오 1(스펙만으로 `*` 허용 여부 판단): 위 표에서 `*` 허용은 `StrategyMeta.exchange`
  단 하나다. `Instrument.exchange`/`Account.exchange`/DataStore `write`·`append`·신규 경로
  생성은 모두 `*` 거부다(`*`는 실제 거래소 식별자·경로가 아니므로). DataStore `read`는
  신규 입력 검증을 적용하지 않으므로 `*` 거부 판정 대상이 아니다 — `*`는 저장된 legacy
  경로가 될 수 없고, 기존 경로 read 호환은 "Legacy out-of-vocabulary 호환 정책"이 규율한다.
- 시나리오 2(`ORACLE_INVALID_EXCHANGE`가 신규 입력에서 거부되어야 하는가): Instrument CLI
  `list`/`sync`/`import` 행에 따라 non-canonical 신규 입력은 non-zero exit + 구조화 error
  payload로 거부되어야 한다(enforcement는 #1577).
- 시나리오 3(`KOSPI`는 exchange인가): "exchange vs market vs source vs broker_type" 절에 따라
  `KOSPI`는 exchange가 아니라 KRX 내부 market/category다.

### Legacy out-of-vocabulary 호환 정책

- 검증은 **신규 입력 경계에만** 적용한다.
- 기존 영속 row(SQLite) / 기존 Parquet path의 out-of-vocab `exchange` 값은 read에서 거부하지
  않는다. **자동 삭제·자동 마이그레이션하지 않는다**(에픽 #1561 비목표). 별도 마이그레이션
  결정이 내려지기 전까지 기존 데이터는 그대로 읽힌다.
- 즉 "out-of-vocab 값이 거부된다"는 새 데이터를 *쓰거나 입력으로 받을 때*만 적용되며, 이미
  저장된 데이터의 읽기 호환성은 깨지 않는다.
- 이 정책은 위 매트릭스의 **DataStore `read`(기존 경로, legacy 포함)** 행에 우선한다:
  DataStore에서 non-canonical·`*` 거부는 `write`/`append`/신규 경로 생성에만 적용되고,
  기존 경로(예: `.../ohlcv/1d/LSE/...`) read 인자에는 신규 입력 검증을 적용하지 않는다.
  `*`는 저장된 legacy 경로가 될 수 없으므로 경로 해석·write에서의 `*` 거부와도 충돌하지 않는다.

### 소비자 목록 + 후속 이슈 매핑

본 절은 계약 정의 + 영향 스펙 최소 포인터까지다. 실제 동작 정렬은 후속 이슈로 위임한다.

| 소비자 / 작업 | 후속 이슈 |
|---------------|-----------|
| 코드 레벨 SSOT 도입(canonical 상수 단일화) | #1576 |
| Instrument CLI enforcement(주 신규 입력 표면) | #1577 |
| account / data / backtest / strategy 경계면 정렬 + backtest `--exchange` 옵션 신설 | #1578 |
| 회귀 테스트 고정 | #1579 |
| 에픽 | #1561 |

## Logging 연계

시스템 로그 인프라는 별도 모듈 스펙 [logging/README.md](../logging/README.md)로 분리되어 있다. Core는 시스템 초기화 순서상 로깅 설정(`setup_logging`)을 Database 이전 단계에서 수행한다.

**요약**:
- 이중 핸들러 — stdout 평문(사람) + 파일 JSONL(자동 분석)
- `ANTE_LOG_JSONL=1` 환경변수 게이트로 점진 도입
- `ANTE_ENV`로 환경 식별 (`production` / `staging` / `test`)
- 이벤트 로그([eventbus](../eventbus/eventbus.md))·감사 로그([audit](../audit/audit.md))와 완전 분리

## 시스템 초기화 순서

모듈 간 의존 관계에 따라 다음 순서로 초기화한다:

```
1. Config.load() + Config.validate()      # 정적 설정 로드 + 검증
2. Instance path resolver 확정             # config_dir 기준 DB/data/PID/socket/logs 경로 정규화
3. Logging 초기화                          # logging.directory 참조
4. Database 초기화                         # db.path 참조, SQLite 연결, WAL 모드 설정
5. EventBus 초기화
6. AccountService 초기화                   # DB + EventBus 주입, 기존 Account 로드
7. DynamicConfigService 초기화             # DB + EventBus 주입
8. TreasuryManager 초기화                  # 계좌별 Treasury 생성
9. TradeService 초기화                     # DB + EventBus (PositionHistory, TradeRecorder, PerformanceTracker)
10. RuleEngineManager 초기화               # 계좌별 RuleEngine 생성 (Config + DynamicConfig + EventBus + AccountService)
11. APIGateway 초기화                      # AccountService 주입, 계좌별 BrokerAdapter 라우팅
12. BotManager 초기화                      # EventBus + StrategyRegistry + APIGateway factories
13. NotificationService 초기화             # EventBus + 알림 어댑터
14. WebAPI 시작                            # FastAPI (모든 서비스 주입)
15. BotManager.restore_bots()              # DB에서 봇 설정 복원 + 시작
```

계좌 topology는 6~12단계에서 서버 시작 시점의 DB 상태를 기준으로 고정된다.
계좌 생성/삭제/credentials·broker_config·commission 변경은 cold-path 전용이며, 서버 실행 중
hot-add/hot-remove를 수행하지 않는다.

## 이벤트 버스 연동 (EventBus Integration)

| 이벤트 | 발행 시점 | 구독자 |
|--------|----------|--------|
| `AccountSuspendedEvent` | 계좌 거래 중단 시 (Account.status → SUSPENDED) | BotManager (해당 계좌 봇 중지), 로깅 |
| `AccountActivatedEvent` | 계좌 거래 재개 시 (Account.status → ACTIVE) | BotManager (로깅만; 자동 재시작은 수행하지 않음), 로깅 |
| `NotificationEvent` | 계좌 상태 변경, 시스템 시작/종료 시 | NotificationService → Telegram 어댑터 (category: "system") |

## 알림 이벤트 정의 (Notification Events)

### 1. 계좌 상태 변경 (계좌별 킬 스위치)

> 소스: `src/ante/account/service.py` — AccountService

**트리거**: 계좌 거래 상태가 변경될 때 (ACTIVE ↔ SUSPENDED)

**데이터 수집**:
- `account_id` → 대상 계좌
- `old_status`, `new_status` → 상태 전환 정보
- `reason` → 변경 사유 (일일 손실 한도 초과, 사용자 요청 등)

**발행 메시지**:

```
level: critical
title: 계좌 상태 변경
category: system

계좌: {account_id}
{old_status} → *{new_status}*
사유: {reason}
```

### 2. 시스템 시작

> 소스: `src/ante/main.py` — _run()

**트리거**: Ante 시스템 초기화가 완료되고 종료 시그널 대기 상태에 진입할 때

**데이터 수집**: 없음 (고정 메시지)

**발행 메시지**:

```
level: info
title: 시스템 시작
category: system

Ante 시스템이 시작되었습니다.
```

### 3. 시스템 종료

> 소스: `src/ante/main.py` — _shutdown()

**트리거**: 종료 시그널(SIGTERM/SIGINT)을 수신하여 시스템 종료 절차가 시작될 때

**데이터 수집**: 없음 (고정 메시지)

**발행 메시지**:

```
level: info
title: 시스템 종료
category: system

Ante 시스템이 종료됩니다.
```

## 텔레그램 시스템 명령 응답

**`/halt` 응답 메시지 — 결과 분기:**

| 조건 | 응답 |
|------|------|
| 성공 | 아래 메시지 |
| 이미 전체 정지됨 | `이미 거래가 중지된 상태입니다.` |

```
🚨 전체 거래가 중지되었습니다.
사유: {reason}
해제하려면 /clear_halt 를 입력하세요.
```

**`/clear_halt` 응답 메시지 — 결과 분기:**

| 조건 | 응답 |
|------|------|
| 성공 | `✅ 거래가 재개되었습니다.` |
| 이미 전체 활성 | `이미 거래가 활성 상태입니다.` |
