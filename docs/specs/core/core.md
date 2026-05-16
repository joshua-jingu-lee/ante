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

**범위 불변식**: 본 절은 exchange-vocabulary 유효성 계약(canonical 5종 비거부 / `*` 규칙 /
legacy read 호환 / 에러 계층 409·422·non-zero / 축 A·B)을 정의한다. surface별 source 지원·
preset wiring·enforcement·구현 동작·정렬은 #1577/#1578에 위임되며 본 절에서 완전 명세하지
않는다. #1577/#1578 구현자는 본 절의 vocabulary 계약을 상위 기준으로 삼고 surface 동작을 그
아래에서 정렬한다. 따라서 아래 표의 각 행은 vocabulary 계약과 에러 계층까지만 계약화하며,
surface 운영/소스/핸들러 디테일은 후속 이슈 정렬 사안으로 표기한다.

| 표면 | canonical | `*` | non-canonical 신규 입력 거부 계약 | 비고 |
|------|-----------|-----|-----------------------------------|------|
| Instrument CLI `list`/`import` | 허용 | 거부 | non-zero exit + 구조화 error payload (`{status:"error", code, message}`) | #1577 enforcement. **주 신규 입력 표면** (oracle `ORACLE_INVALID_EXCHANGE` 출처) |
| Instrument CLI `sync` | 허용 (vocabulary 측면은 동일: canonical 5종만 유효, non-canonical 거부) | 거부 | non-zero exit + 구조화 error payload | **source-bound 표면.** `sync`는 KIS API(KRX 도메인)에서만 마스터를 가져와 전달 `exchange`를 저장 라벨로 쓴다(`src/ante/cli/commands/instrument.py`의 `sync`→`KISAdapter.get_instruments`, `docs/specs/instrument/` source 계약). 따라서 canonical이지만 source 미지원 exchange(`NYSE/NASDAQ/AMEX` 등 비-KRX)에 대한 sync 동작·에러 계약은 **source-supported-exchange 정렬 사안으로 #1577에 위임**(backtest `--exchange`처럼 spec-vs-implementation gap). 본 SSOT는 "sync는 source-bound이며 source 미지원 canonical 값 처리 계약은 #1577" 까지만 명시하고 완전 명세하지 않는다 |
| Account CLI preset (`account create` 등) | canonical 5종은 invalid-exchange로 거부되지 않음 (축 A); preset 미제공 canonical 값은 축 B 제약 | 거부 | non-zero exit | 축 A: `*`/non-canonical은 거부. 축 B: canonical이지만 1.0 preset 미제공 값(`NYSE/NASDAQ/AMEX`)은 **preset/broker 가용성 제약**이지 invalid-exchange 거부가 아니다(별개 차원). 구체적 preset wiring(어떤 preset이 어떤 exchange를 자동 구성하는가)은 축 B canonical-known 표·축 B 정의를 상위 기준으로 삼아 **#1578에서 정렬**한다 — 본 행은 vocabulary 계약(축 A 비거부 / `*`·non-canonical 거부)만 명시한다 |
| AccountService (생성/검증) | canonical 5종 허용 (축 A: non-canonical만 서비스 검증 에러) | 거부 | 서비스 검증 에러 | `exchange`는 identity 필드(`docs/specs/account/03-data-model.md:96`). canonical 5종은 서비스 exchange 검증에서 거부되지 않는다. 1.0 account preset이 `NYSE/NASDAQ/AMEX`를 미제공하는 것은 **축 B(preset/broker 가용성) 제약**이며 "invalid exchange 거부"가 아니다(별개 차원) |
| Account Web — `POST /api/accounts` (cold-path 계좌 생성) | — | — | **cold-path 차단 계층은 409** (계좌 생성은 cold-path 전용, `exchange` 포함 입력 무관) | **422 아님.** 진입 가드의 구체 동작·핸들러는 #1578에서 정렬한다 — 본 행은 "cold-path → 409, 스키마 층 422 아님"의 에러 계층만 명시한다 |
| Account Web — `PUT /api/accounts/{account_id}` structural/identity 변경 (`exchange` 등) | — | — | **structural/identity 변경 차단 계층은 409** | **422 아님.** `exchange`는 생성 후 수정 불가 identity 필드(`docs/specs/account/03-data-model.md:96`)이므로 런타임 변경 시도는 cold-path 계층(409)에서 차단된다. structural 필드 집합·가드 구현은 #1578에서 정렬한다 |
| Account Web — `PUT /api/accounts/{account_id}` mutable-only (`name`/`timezone`/`trading_hours_start`/`trading_hours_end`) | — | — | (exchange 검증 범위 밖) | **409 아님 — 런타임 허용 계층.** mutable-only 업데이트는 정상 런타임 경로이며 cold-path 409로 차단되지 않는다. mutable 필드 집합의 구현 정렬은 #1578에 위임한다 |
| Account Web OpenAPI/schema 레벨 | — | — | 빈 문자열/형식 오류는 **422** | cold-path 문서(스키마 검증) 전용. 런타임 차단(409)과 다른 층 |
| DataStore path API — `write`/`append`/신규 경로 생성 | 허용 | 거부 | 신규 경로 생성 시 non-canonical·`*` 거부 | feed/data CLI 옵션이 아니라 DataStore 메서드 인자 표면. `*`는 경로로 해석 불가. 거부의 구현 동작(예외 처리 방식 등)은 #1578에서 정렬하며, 본 행은 "신규 경로 생성 시 non-canonical·`*` 거부"의 vocabulary 계약만 명시한다 |
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
  `list`/`import`(및 vocabulary 측면에서 동일한 `sync`) 행에 따라 non-canonical 신규 입력은
  non-zero exit + 구조화 error payload로 거부되어야 한다(enforcement는 #1577). `sync`의
  source 미지원 canonical 값(`NYSE/NASDAQ/AMEX` 등 비-KRX) 처리 계약은 source-bound 표면
  사안으로 #1577에 위임된다 — 본 SSOT 단독으로는 vocabulary 거부(non-canonical)만 판정한다.
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

## Canonical Symbol/Timeframe Vocabulary

> 이 절은 Ante 전역에서 OHLCV bar `timeframe`과 신규 입력 `symbol`이 의미하는
> **canonical vocabulary와 적용 범위의 계약 SSOT**다.
> 결정 배경·근거·소비자 영향은 ADR [D-017](../../decisions/D-017-canonical-symbol-timeframe-vocabulary.md)에 정리되어 있으며,
> 본 절이 normative 계약 본문이다. ADR은 본 절을 링크하고 계약 본문을 중복 기재하지 않는다.

OHLCV bar `timeframe`과 KRX `symbol`은 data / web-api / cli / strategy / backtest가
공유하는 식별 차원이다. 1.0 시점에 각 표면이 인라인 SSOT 표기(`ante.data.schemas.TIMEFRAMES`)나
분산된 normative 서술을 갖고 있어 단일 계약이 부재했고, 본 절이 그 계약을 확정한다.
**런타임 enforcement·코드 동작 변경은 본 절의 범위가 아니다**(코드 레벨 SSOT는 #1613,
표면별 enforcement는 #1603/#1604/#1605/#1606/#1611/#1594/#1614로 위임). 본 절은 "무엇이
canonical이고 어느 경계에서 어떻게 거부되어야 하는지"의 계약만 정의한다.

### Canonical timeframe set

```
CanonicalTimeframe = [1m, 5m, 15m, 1h, 1d]
```

- canonical OHLCV bar timeframe 값은 **고정 집합·고정 순서**다. 위 5종이 신규 입력 검증
  vocabulary 전체이며, 표기 순서(`1m → 5m → 15m → 1h → 1d`)는 순서 의존 소비자(예:
  `src/ante/cli/commands/data.py`의 iteration)를 위해 계약상 고정한다.
- 값은 위 리터럴과 **정확히 일치**해야 한다(exact-literal). alias(예: `1min`, `D`,
  `daily`)·대소문자 정규화·사용자 정의 timeframe set은 1.0 비목표다. 입력 정규화(no-alias·
  no-normalization)도 적용하지 않는다.
- 코드 레벨 SSOT(상수 단일화 — `TIMEFRAMES`/`_OHLCV_TIMEFRAMES` 등 산재 상수 정렬)는
  #1613의 범위다. 본 절은 값 집합·순서 자체의 계약만 고정한다.

### KRX symbol shape

- 신규 입력 KRX `symbol`의 경계는 **6자리 ASCII digit**이다: `^[0-9]{6}$`.
- 비-KRX symbol format(예: 미국 ticker `AAPL`)은 1.0 비목표다. 1.0 시점 신규 입력
  symbol 검증 vocabulary는 KRX 6자리 숫자 형태로 한정한다.
- 코드 레벨 SSOT(`_KRX_SYMBOL_PATTERN`/`_KRX_NUMERIC_SYMBOL_PATTERN` 등 산재 regex
  정렬)는 #1613의 범위다. 본 절은 신규 입력 형태 계약만 고정한다.

### symbol/timeframe 축 구분

`timeframe`·`symbol` 리터럴이 등장하는 위치는 아래 **여섯 축**으로 분리되며 서로
규율 SSOT가 다르다. 본 절(축 A의 OHLCV bar timeframe canonical set, 축 E의 KRX
symbol shape 신규 입력 형태)만 SSOT로 소유한다. 나머지 축은 각자의 스펙이 규율하며
본 계약이 값을 재정의하지 않는다.

| 축 | 대상 | 의미 | 규율 SSOT | 본 계약과의 관계 |
|----|------|------|-----------|------------------|
| **A** | OHLCV bar timeframe (`1m`/`5m`/`15m`/`1h`/`1d`) | 신규 입력 timeframe vocabulary | **본 절(`### Canonical timeframe set`)** | 본 계약 SSOT |
| **B** | subminute 파티셔닝 해상도 (`10s`/`30s`) | Parquet 일별 파티셔닝 단위 | `docs/specs/data-feed/04-schema.md` | 별개 축. timeframe vocabulary가 아니라 저장 파티셔닝 해상도. 본 계약 밖 |
| **C** | `tick` / `fundamental` data_type | OHLCV가 아닌 데이터 유형 | `docs/specs/data-pipeline/01·02·03` | 별개 축. timeframe이 아니라 data_type. 본 계약 밖 |
| **D** | write-ownership (`<1d`+`tick`=Collector / `1d`+`fundamental`=DataFeed) | 파티션 쓰기 소유자 | `docs/specs/data-pipeline/02-write-ownership.md` | 별개 축. 어느 모듈이 쓰는가의 소유권 분배이며 입력 vocabulary 계약이 아니다 |
| **E** | 신규 입력 strict ASCII 검증 vs legacy parquet path migration 판별 | 신규 입력 경계 vs 기존 경로 호환 | 신규 입력=본 절(`### KRX symbol shape`), legacy path migration 판별=`src/ante/data/store.py`(`\d` 보존) | 신규 입력 형태만 본 계약 SSOT. legacy 경로 판별 regex는 별개 축(아래 "Legacy 호환 정책") |
| **F** | fundamental cadence/periodicity (`quarterly`/`annual`) | 재무 데이터 주기 | (현재 `dataset.timeframe` 필드에 overload — 정리는 후보 D deferral) | **별개 축. 본 canonical OHLCV-timeframe 계약에 포함하지 않는다.** 현재 `dataset.timeframe` 필드(`docs/dashboard/user-stories/backtest-data.md:79`·`docs/dashboard/mockups/backtest-data-fundamental.html:127`, fundamental parquet `quarterly.parquet`/`annual.parquet`)에 overload된 cross-surface 불일치는 #1612가 만든 것이 아니다. 본 절은 "fundamental cadence는 OHLCV bar timeframe과 별개 축이며 그 필드 의미 정리는 후보 D" 까지만 명문화하고 값 정의·필드 재설계는 하지 않는다 |

(D-016 `### exchange vs market vs source vs broker_type` 절과 동형 구조: 같은 리터럴이라도
어느 축의 값인지에 따라 규율 SSOT가 다르며 값을 섞지 않는다.)

### Per-surface 허용/거부 + 검증·에러 계약 매트릭스

검증은 **표면별로 분리**된다. 같은 vocabulary라도 어느 경계에서 어떤 에러 계약으로
거부되는지는 표면마다 다르다.

**범위 불변식**: 본 절은 OHLCV bar timeframe·KRX symbol vocabulary 유효성 계약
(canonical set·고정 순서·exact-literal / KRX 6자리 / legacy read 호환)을 정의한다.
surface별 enforcement·에러코드·구현 동작·정렬은 아래 후속 이슈에 위임되며 본 절에서
완전 명세하지 않는다. 후속 이슈 구현자는 본 절의 vocabulary 계약을 상위 기준으로
삼고 surface 동작을 그 아래에서 정렬한다. 따라서 아래 표의 각 행은 vocabulary 계약과
거부 경계까지만 계약화하며, surface 운영/핸들러 디테일은 후속 이슈 정렬 사안으로
표기한다.

| 표면 | OHLCV timeframe 허용 | non-canonical 거부 계약 | 비고 |
|------|----------------------|--------------------------|------|
| Backtest run CLI | `{1m,5m,15m,1h,1d}` | non-zero exit + 구조화 error payload | enforcement·에러코드는 **#1603 정렬 사안**. 본 행은 vocabulary 계약만 명시 |
| Backtest programmatic API | `{1m,5m,15m,1h,1d}` | 검증 에러 | enforcement·에러 계층은 **#1604 정렬 사안** |
| `data validate` CLI | `{1m,5m,15m,1h,1d}` | non-zero exit + 구조화 error payload | enforcement·에러코드는 **#1605 정렬 사안** |
| `feed inject` | `{1m,5m,15m,1h,1d}` | 거부 (구조화 error) | enforcement·에러 계층은 **#1606 정렬 사안** |
| Instrument import KRX symbol | KRX `^[0-9]{6}$` (축 E 신규 입력) | non-zero exit + 구조화 error payload | symbol shape enforcement는 **#1611 정렬 사안** |
| Data API `timeframe` filter (`GET /api/data/datasets`) | `{1m,5m,15m,1h,1d}` | **400 (기구현)** | `timeframe`은 #1594에서 vocabulary 외 값 **400 거부 기구현**. `symbol`은 별개 — invalid `symbol` vocabulary 거부는 **#1594 아님**, exchange-aware symbol SSOT 후속(#1613 코드 SSOT 체인) **정렬 사안**이며 현재 invalid `symbol`은 **200 empty 유지**(web-api/05 `GET /api/data/datasets` 계약과 정합) |
| Live DataCollector write·경로 생성 | **OHLCV `{1m,5m,15m,1h}`만** (`1d`는 write-ownership상 DataFeed 소유라 제외, `tick`은 별도 data_type라 제외) | enforcement 미구현 (현재 spec-vs-impl gap) | ingress enforcement는 **#1614 정렬 사안** (Depends on #1613). 본 행은 "Collector write vocabulary는 OHLCV `{1m,5m,15m,1h}`로 한정(축 D상 `1d`·축 C상 `tick` 제외)" 경계만 명시 |

판정 보조 노트:
- 시나리오 1(OHLCV timeframe canonical 여부): 위 `### Canonical timeframe set`의
  `{1m,5m,15m,1h,1d}` 5종만 canonical이며, alias·정규화 없이 exact-literal 일치만
  허용된다.
- 시나리오 2(`10s`/`30s`가 canonical timeframe인가): "symbol/timeframe 축 구분"
  표 축 B에 따라 `10s`/`30s`는 timeframe vocabulary가 아니라 subminute 파티셔닝
  해상도(`data-feed/04-schema.md` 규율)다.
- 시나리오 3(`quarterly`/`annual`이 canonical timeframe인가): 축 F에 따라 fundamental
  cadence는 OHLCV bar timeframe과 별개 축이며, 본 canonical 계약에 포함하지 않는다
  (`dataset.timeframe` 필드 overload 정리는 후보 D deferral).
- 시나리오 4(Collector가 `1d`를 쓰는가): 축 D(write-ownership, `data-pipeline/02`
  규율)에 따라 `1d`는 DataFeed 소유이며 Collector write vocabulary는 OHLCV
  `{1m,5m,15m,1h}`로 한정된다(#1614).

### Legacy out-of-vocabulary 호환 정책

- 검증은 **신규 입력 경계에만** 적용한다.
- 기존 영속 Parquet path / SQLite row의 out-of-vocab timeframe·symbol 값은 read에서
  거부하지 않는다. **자동 삭제·자동 마이그레이션하지 않는다**. 별도 마이그레이션
  결정이 내려지기 전까지 기존 데이터는 그대로 읽힌다.
- 즉 "out-of-vocab 값이 거부된다"는 새 데이터를 *쓰거나 입력으로 받을 때*만 적용되며,
  이미 저장된 데이터의 읽기 호환성은 깨지 않는다.
- 신규 입력 strict ASCII 검증(축 E)과 legacy parquet path migration 판별은 **별개 축**이다.
  `src/ante/data/store.py`의 path migration 판별 regex(`\d`)는 기존 경로를 식별하기
  위한 것이며, 신규 입력 검증(`^[0-9]{6}$`)으로 대체·강화되지 않는다(legacy 무손상 보존).

### 소비자 목록 + 후속 이슈 매핑

본 절은 계약 정의 + 영향 스펙 최소 포인터까지다. 실제 동작 정렬은 후속 이슈로 위임한다.

| 소비자 / 작업 | 위치 (코드 변경 없음, 본 이슈 범위 밖) | 후속 이슈 |
|---------------|----------------------------------------|-----------|
| 코드 레벨 SSOT 도입(`ante.core.market_data_vocab` 신설, `TIMEFRAMES`/KRX regex 소비자 위임) | `src/ante/data/schemas.py:56` `TIMEFRAMES`, `src/ante/data/__init__.py:22,41` re-export + `__all__` | #1613 |
| `DEFAULT_RETENTION` timeframe dict keys (보존 정책 dict 키 — 독립 소비자 행) | `src/ante/data/retention.py:13` `_OHLCV_TIMEFRAMES`, `:37` `DEFAULT_RETENTION` timeframe dict keys | #1613 (코드 SSOT). 보존 기간 값 자체는 retention 정책 고유 (`data-pipeline/03` 보존 정책 표) |
| Backtest run CLI timeframe enforcement | (#1603 범위) | #1603 |
| Backtest programmatic API timeframe enforcement | (#1604 범위) | #1604 |
| `data validate` CLI timeframe enforcement | `src/ante/cli/commands/data.py:27,35` `TIMEFRAMES` 순서 의존 iteration | #1605 |
| `feed inject` timeframe enforcement | (#1606 범위) | #1606 |
| Instrument import KRX symbol shape enforcement | `src/ante/data/store.py:34` `_KRX_SYMBOL_PATTERN`(`^\d{6}$`) + `:74` `migrate_parquet_paths` legacy 판별, `src/ante/rule/engine.py:55` `_KRX_NUMERIC_SYMBOL_PATTERN`(`^[0-9]{6}$`) OrderRequestEvent preflight (#1299) | #1611 |
| Data API `timeframe` filter (기구현 400) | `src/ante/web/routes/data.py:65,85` #1594 timeframe 400 filter (기구현) | #1594 |
| Data API `symbol` filter 잔여 vocabulary 거부 (현재 200 empty 유지 — 독립 행) | `src/ante/web/routes/data.py` datasets `symbol` query (현재 invalid `symbol`은 200 empty, **#1594 아님**, web-api/05 계약과 정합) | **#1613 코드 SSOT 체인** (exchange-aware symbol SSOT 후속 정렬 사안) |
| **Live DataCollector write·경로 생성** (OHLCV `{1m,5m,15m,1h}`만, `1d`·`tick` 제외 — 독립 행) | `src/ante/data/collector.py:61-150` `DataCollector.start/add_data/_collect_loop/_flush` live write | **#1614** (Depends on #1613) |
| fundamental cadence `dataset.timeframe` overload reconciliation (축 F — 후보 D deferral 행) | `docs/dashboard/user-stories/backtest-data.md`, `docs/dashboard/mockups/backtest-data-fundamental.html` (본 이슈 무편집) | **후보 D** (deferral, 사람 등록 surface) |

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
