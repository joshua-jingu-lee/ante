# DataStore 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 설계 결정

### 데이터 스키마 (정규화된 형태)

모든 시세 데이터의 공통 스키마 상수:

> 아래 스키마 표의 `symbol` 서술(`종목 코드 (6자리)` 등)은 **Phase1 KRX 데이터 형태**이며,
> 신규 입력 `symbol` 검증 계약 SSOT는 [core.md `## Canonical Symbol/Timeframe Vocabulary`
> `### KRX symbol shape`](../core/core.md#canonical-symboltimeframe-vocabulary)(resolved
> exchange == KRX 한정)이다. 비-KRX exchange의 symbol format은 1.0 비목표이며 본 SSOT가
> 제약하지 않는다. 본 스키마 표는 저장 형태 서술이며 신규 입력 검증 계약을 재정의하지 않는다.

**OHLCV_SCHEMA**

| 필드 | 타입 | 설명 |
|------|------|------|
| `timestamp` | Datetime (ns, UTC) | UTC 기준 |
| `symbol` | Utf8 | 종목 코드 (6자리) |
| `open` | Float64 | 시가 |
| `high` | Float64 | 고가 |
| `low` | Float64 | 저가 |
| `close` | Float64 | 종가 |
| `volume` | Int64 | 거래량 |
| `amount` | Int64 | 거래대금 |
| `source` | Utf8 | 데이터 소스 ("kis", "data_go_kr", "external", ...) |

**TICK_SCHEMA**

| 필드 | 타입 | 설명 |
|------|------|------|
| `timestamp` | Datetime (ns) | 시각 |
| `symbol` | Utf8 | 종목 코드 |
| `price` | Float64 | 체결가 |
| `volume` | Int64 | 체결량 |
| `side` | Utf8 | 매수/매도 구분 |

> 실제 수집은 Phase 2 이후. 스키마는 `schemas.py`에 정의 완료.

**FUNDAMENTAL_SCHEMA**

| 필드 | 타입 | 설명 | Phase 1 |
|------|------|------|:-------:|
| `date` | Date | 기준일 | O |
| `symbol` | Utf8 | 종목코드 (6자리) | O |
| `market_cap` | Int64 | 시가총액 | O |
| `shares_listed` | Int64 | 상장주식수 | O |
| `shares_outstanding` | Int64 | 유통주식수 | — |
| `foreign_ratio` | Float64 | 외국인 지분율 (%) | — |
| `foreign_shares` | Int64 | 외국인 보유주식수 | — |
| `per` | Float64 | PER (null 허용) | O (계산) |
| `pbr` | Float64 | PBR (null 허용) | O (계산) |
| `eps` | Float64 | 주당순이익 (null 허용) | O (계산) |
| `bps` | Float64 | 주당순자산 (null 허용) | O (계산) |
| `roe` | Float64 | 자기자본이익률 | — |
| `debt_to_equity` | Float64 | 부채비율 | — |
| `revenue` | Int64 | 매출액 | — |
| `net_income` | Int64 | 순이익 | — |
| `div_yield` | Float64 | 배당수익률 | — |
| `dps` | Float64 | 주당배당금 | — |
| `source` | Utf8 | 데이터 소스 | O |

> Phase 1에서 제공되지 않는 필드는 null 허용.
> PER/PBR/EPS/BPS는 data.go.kr(시가총액, 상장주식수) + DART(순이익, 자본총계)로 **직접 계산**.

> canonical symbol/timeframe 계약 SSOT: [core.md `## Canonical Symbol/Timeframe Vocabulary`](../core/core.md#canonical-symboltimeframe-vocabulary).
> 아래 `TIMEFRAMES: list[str]`의 OHLCV bar timeframe vocabulary(`1m, 5m, 15m, 1h, 1d`) 계약 본문은
> core.md 절이 SSOT이며, 이 코드 상수는 #1613(코드 레벨 SSOT 단일화)에서 파생 정렬된다.

**편의 상수 및 검증 함수**:
- `OHLCV_COLUMNS: list[str]` — `OHLCV_SCHEMA`의 키 목록
- `FUNDAMENTAL_COLUMNS: list[str]` — `FUNDAMENTAL_SCHEMA`의 키 목록
- `TIMEFRAMES: list[str]` — 지원 타임프레임 (`["1m", "5m", "15m", "1h", "1d"]`, 계약 SSOT: core.md canonical timeframe set, 코드 상수 단일화는 #1613 파생)
- `validate_ohlcv(df) -> bool` — OHLCV DataFrame의 필수 필드(`timestamp`, `symbol`, OHLC, `volume`, `source`) 존재 여부 검증
- `validate_fundamental(df) -> bool` — FUNDAMENTAL DataFrame의 필수 필드(`date`, `symbol`, `source`) 존재 여부 검증

소스: `src/ante/data/schemas.py`

### Normalizer — 스키마 정규화

> 소스: `src/ante/data/normalizer.py`

다양한 소스의 DataFrame을 공통 스키마로 정규화한다.
BaseNormalizer ABC를 기반으로 소스별 서브클래스를 구현하고, DataNormalizer가 파사드로 위임한다.

**BaseNormalizer ABC**:

| 프로퍼티/메서드 | 반환값 | 설명 |
|----------------|--------|------|
| `source_name` (추상) | `str` | 소스 식별자 (예: `"kis"`, `"data_go_kr"`) |
| `column_mapping` (추상) | `dict[str, str]` | 소스 컬럼 → 표준 컬럼 매핑 |
| `normalize` | `pl.DataFrame` | DataFrame을 공통 스키마로 정규화 |
| `transform` | `pl.DataFrame` | 소스별 추가 변환 (오버라이드 가능) |

**소스별 구현체**:
- `KISNormalizer`: KIS API 응답 (`stck_bsop_date` → `date`, `stck_clpr` → `close` 등) — Collector 사용
- `YahooNormalizer`: Yahoo Finance (`Date` → `timestamp`, `Open` → `open` 등) — DataFeed inject 사용
- `DefaultNormalizer`: 일반적 컬럼명 (`date`/`datetime`/`time` → `timestamp` 등) — DataFeed inject 사용
- `DataGoKrNormalizer`: data.go.kr 응답 정규화 — DataFeed 사용. **dual-schema 출력**:
  - `normalize_ohlcv(df)` → OHLCV_SCHEMA (`basDt`→`timestamp`, `mkp`→`open`, `clpr`→`close`, `trqu`→`volume`, `trPrc`→`amount` 등)
  - `normalize_fundamental(df)` → FUNDAMENTAL_SCHEMA 일부 (`basDt`→`date`, `srtnCd`→`symbol`, `mrktTotAmt`→`market_cap`, `lstgStCnt`→`shares_listed`)
  - 동일한 API 응답에서 두 스키마를 각각 추출. 모든 응답 값이 문자열이므로 숫자 변환 필수
- `DARTNormalizer`: DART API 재무제표 → FUNDAMENTAL_SCHEMA 일부 — DataFeed 사용. **피벗 변환**:
  - DART 응답은 계정과목별 행 구조 → 종목별 컬럼 구조로 피벗
  - `corp_code` → `symbol` (dart_corp_codes.json 매핑), `reprt_code` → `date` (보고서 기준일)
  - 계정과목 매핑: `매출액`/`수익(매출액)` → `revenue`, `당기순이익`/`당기순이익(손실)` → `net_income`, `자본총계`/`부채총계`/`자산총계` → 계산용 중간값(`total_equity`, `total_debt`, `total_assets`)
  - `fs_div` = `CFS`(연결) 우선, 없으면 `OFS`(개별) 폴백
  - `thstrm_amount` 콤마 제거 후 숫자 변환
  - **파생 지표(PER/PBR/EPS/BPS/ROE/부채비율)는 계산하지 않음** — orchestrator가 두 소스 데이터를 결합하여 계산

> **파생 지표 계산 책임**: DARTNormalizer는 DART 응답의 정규화(피벗 + 타입 변환)만 담당한다.
> data.go.kr 데이터(시가총액, 상장주식수)와 DART 데이터(순이익, 자본총계 등)를 결합하는
> 파생 지표 계산(EPS, BPS, PER, PBR, ROE, 부채비율)은 DataFeed orchestrator에서 수행한다.

**Normalizer 레지스트리**:

| 함수 | 파라미터 | 반환값 | 설명 |
|------|----------|--------|------|
| `get_normalizer` | source: str | BaseNormalizer | 소스명으로 Normalizer 인스턴스 조회. 미등록 시 `DefaultNormalizer` |
| `register_normalizer` | source: str, cls: type[BaseNormalizer] | None | 커스텀 Normalizer를 레지스트리에 등록 |

기본 등록: `kis` → KISNormalizer, `yahoo` → YahooNormalizer, `default`/`external` → DefaultNormalizer, `data_go_kr` → DataGoKrNormalizer.
DARTNormalizer는 BaseNormalizer(OHLCV)와 다른 스키마를 출력하므로 별도 레지스트리에 등록.

**DataNormalizer 파사드** (하위 호환):

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `normalize` | df: pl.DataFrame, source: str = "external", format_hint: str \| None = None | pl.DataFrame | `get_normalizer(source)`로 적절한 서브클래스에 위임 |

**정규화 과정**: 컬럼 매핑 → timestamp UTC 정규화 → 숫자 컬럼 타입 변환 → source/symbol 컬럼 추가 → 스키마 컬럼만 선택 → timestamp 기준 정렬

### Data root contract

DataStore의 canonical root는 Config의 `data.path`이다. 기본값은
`<config_dir>/data`이며, `system.toml`의 상대 경로는 `config_dir` 기준으로
정규화한다. 모든 DataStore 소비자(DataFeed, Backtest, Strategy, CLI)는 명시적
override가 없으면 이 root를 사용한다.

과거 `parquet.base_path`는 legacy alias이며 신규 스펙과 예시는 `data.path`를
SSOT로 삼는다.

### Parquet 파일 구조

```
{data.path}/
├── ohlcv/
│   ├── 1m/                    # 1분봉 (Collector 소유)
│   │   ├── KRX/               # 거래소별 디렉토리
│   │   │   ├── 005930/        # 종목별 디렉토리
│   │   │   │   ├── 2026-01.parquet
│   │   │   │   ├── 2026-02.parquet
│   │   │   │   └── 2026-03.parquet
│   │   │   └── 000660/
│   │   │       └── ...
│   │   └── NYSE/
│   │       └── AAPL/
│   │           └── 2026-01.parquet
│   ├── 5m/                    # 5분봉 (Collector 소유)
│   ├── 1h/                    # 1시간봉 (Collector 소유)
│   └── 1d/                    # 일봉 (DataFeed 소유)
│       ├── KRX/
│       │   └── 005930/
│       │       └── ...
│       └── NYSE/
│           └── AAPL/
│               └── ...
├── fundamental/               # (DataFeed 소유)
│   ├── KRX/
│   │   └── {symbol}/{YYYY-MM}.parquet
│   └── NYSE/
│       └── {symbol}/{YYYY-MM}.parquet
├── tick/                      # 틱 데이터 (Collector 소유, 선택)
│   ├── KRX/
│   │   └── 005930/
│   │       └── 2026-03-12.parquet
│   └── NYSE/
│       └── AAPL/
│           └── 2026-03-12.parquet
└── .feed/                     # DataFeed 운영 데이터 (`docs/specs/data-feed/data-feed.md` 참조)
```

계층 원칙: **데이터 유형 > 해상도 > 거래소 > 심볼 > 시간 파티션** (OHLCV), **데이터 유형 > 거래소 > 심볼 > 시간 파티션** (fundamental, tick)

**파티셔닝 전략**:
- OHLCV: `ohlcv/{timeframe}/{exchange}/{symbol}/{YYYY-MM}.parquet` — 월 단위 파티셔닝
- fundamental: `fundamental/{exchange}/{symbol}/{YYYY-MM}.parquet`
- 틱: `tick/{exchange}/{symbol}/{YYYY-MM-DD}.parquet` — 일 단위 파티셔닝
- 일봉은 한 파일에 수년치 저장 가능 (파일 크기 작음)

**근거**:
- 종목별 디렉토리로 특정 종목 데이터 빠른 접근
- 월 단위 파티셔닝으로 파일 크기 적정 유지 (1분봉 기준 종목당 월 ~2MB)
- N100 서버의 60GB 용량 제약 대응 — 보존 정책으로 오래된 데이터 삭제/이관

### DataCollector — 실시간 데이터 수집

봇 운영 중 실시간 시세 데이터를 수집하여 Parquet에 적재한다.
APIGateway를 통해 시세를 조회하고, 메모리 버퍼에 적재 후 일정 조건에서 ParquetStore로 flush한다.

**쓰기 대상**: 1d 미만 타임프레임(`1m`, `5m`, `15m`, `1h`)과 틱 데이터만 수집한다. 일봉(`1d`) 이상은 DataFeed 소유이므로 Collector는 쓰지 않는다. KIS API가 일봉 데이터를 반환하더라도 폐기한다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async start` | symbols: list[str], timeframes: list[str] | None | 데이터 수집 시작 (asyncio Task 생성) |
| `async stop` | — | None | 수집 중지 및 잔여 버퍼 flush |
| `async add_data` | symbol: str, timeframe: str, row: dict | None | 외부에서 직접 데이터 추가 (이벤트 기반 수집 시 사용) |
| `async flush_all` | — | int | 모든 버퍼 데이터를 Parquet에 flush. flush된 총 건수 반환 |
| `set_data_callback` | callback: DataCallback | None | 데이터 수집 콜백 설정. 시그니처: `async (symbol, tf) -> list[dict]` |

**생성자 파라미터**: `store: ParquetStore`, `eventbus: EventBus`, `buffer_size: int = 100`, `flush_interval: float = 300.0`, `collect_interval: float = 60.0`

**버퍼 설정**: 기본 버퍼 크기 100건, flush 간격 300초, 수집 간격 60초.

소스: `src/ante/data/collector.py`

### ParquetStore — Parquet 파일 관리

Parquet 파일 읽기/쓰기/관리를 담당한다. **모든 모듈이 Parquet에 접근할 때 사용하는 유일한 인터페이스**다.

**생성자 파라미터**: `base_path: str | Path`, `compression: str = "snappy"`

**프로퍼티**: `base_path: Path` — 데이터 저장소 루트 경로. Ante 인스턴스 안에서 생성할 때는 Config resolver가 정규화한 `data.path`를 주입한다. 테스트나 독립 도구에서 명시적으로 넘긴 상대 경로는 호출자의 작업 디렉토리 기준으로 해석할 수 있지만, 서버/CLI 기본 경로 계약에는 사용하지 않는다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async read` | symbol: str, timeframe: str, start: str \| None, end: str \| None, limit: int \| None, data_type: str = "ohlcv", exchange: str = "KRX" | pl.DataFrame | 데이터 읽기. `data_type`으로 스키마 자동 판별 |
| `async write` | symbol: str, timeframe: str, data: pl.DataFrame, data_type: str = "ohlcv", exchange: str = "KRX" | int | 파티션 단위 **merge** (월별 파티셔닝, 중복 제거 후 정렬). 기존 파일이 있으면 concat → unique → sort. 반환은 이번 write로 실제 새로 저장된 **net-new 행 수**(파티션별 `max(0, len(merged) - len(existing))`의 합, #1993). 모든 파티션 write는 임시파일 + 원자 rename으로 수행한다(중단 시 손상 파일 미잔존, #2413). |
| `async append` | symbol: str, timeframe: str, rows: list[dict], data_type: str = "ohlcv", exchange: str = "KRX" | None | 내부적으로 `write()`에 위임. Collector 전용 |
| `list_symbols` | timeframe: str = "1d", data_type: str = "ohlcv", exchange: str = "KRX" | list[str] | 보유 데이터의 종목 목록 |
| `get_date_range` | symbol: str, timeframe: str, data_type: str = "ohlcv", exchange: str = "KRX" | tuple[str, str] \| None | 종목의 데이터 기간 조회 |
| `get_row_count` | symbol: str, timeframe: str, data_type: str = "ohlcv", exchange: str = "KRX" | int | 종목의 총 행 수 조회. Parquet 메타데이터만 읽어 빠르게 반환 |
| `get_storage_usage` | — | dict[str, int] | 저장 용량 현황 (바이트) |
| `async validate` | symbol: str, timeframe: str, fix: bool = False, data_type: str = "ohlcv", exchange: str = "KRX" | dict | Parquet 파일 무결성 검증. fix=True 시 손상 파일을 `.corrupted` 확장자로 이동 |
| `delete_file` | symbol: str, timeframe: str, month: str, data_type: str = "ohlcv", exchange: str = "KRX" | bool | 특정 Parquet 파일 삭제. 성공 여부 반환 |

`_resolve_path()` 내부 메서드는 `exchange` 파라미터를 받아 경로를 생성한다:
- OHLCV: `{base_path}/ohlcv/{timeframe}/{exchange}/{symbol}/{YYYY-MM}.parquet`
- fundamental: `{base_path}/fundamental/{exchange}/{symbol}/{YYYY-MM}.parquet`
- tick: `{base_path}/tick/{exchange}/{symbol}/{YYYY-MM-DD}.parquet`

**기존 데이터 마이그레이션**: exchange 미명시 기존 데이터(OHLCV 경로에 exchange 디렉토리가 없는 경우)는 `KRX/` 하위로 자동 이동한다. 마이그레이션은 시스템 시작 또는 `ante update`의 post-update migration에서 자동 감지·실행한다. 별도 public `ante data migrate` 명령은 CLI SSOT에 포함하지 않는다.

> canonical exchange 계약 SSOT: [core.md `## Canonical Exchange Vocabulary`](../core/core.md#canonical-exchange-vocabulary).
> DataStore path API에서 non-canonical·`*` 거부는 `write`/`append`/신규 경로 생성에만 적용되는
> 것이 목표다. 기존 영속 Parquet path(legacy out-of-vocab 포함)의 `read`는 거부·자동 삭제하지
> 않는다(Legacy 호환 정책이 매트릭스 read 행에 우선). 표면별 enforcement 정렬은 #1578에서
> 다룬다(현재 코드/스펙 drift).

소스: `src/ante/data/store.py`

#### 파티션 저장 원자성 및 0바이트 파티션 자동복구 (#2413)

파티션 persist(`_persist_partition`)는 durability 불변을 다음과 같이 보장한다. 이는
checkpoint JSON/secrets 저장이 이미 적용하고 있던 write-then-rename 원자성
([data-feed/10-checkpoints-and-reports.md](../data-feed/10-checkpoints-and-reports.md))을
파티션 write에도 확장한 것이며, 새 durability 계약을 도입하는 것이 아니다.

- **원자적 write**: 모든 파티션 write(신규 파티션·merge 결과)는 같은 디렉토리의
  임시 파일에 기록한 뒤 원자 `os.replace`로 교체한다. write 도중 프로세스가
  중단(OOM/`kill`/전원 손실)되어도 최종 경로에는 부분 parquet이 남지 않으며, 실패 시
  임시 파일은 즉시 정리된다. 기존 유효 파티션은 replace 전까지 손대지 않으므로 write
  중단이 기존 데이터를 손상시키지 않는다.
  - **파일 권한**: `mkstemp`가 만든 tmp는 `0o600`이라 그대로 replace하면 파티션이
    owner-only가 되어 분리된 reader 계정/그룹이 EACCES를 만난다(LXC 배포). 따라서
    기존 target이 있으면 **그 operator mode를 보존**하고(0o600 등 의도 존중), 없으면
    `0o644` 고정을 쓴다(hot-path에서 umask probe 하지 않는다).
- **기존 파일 처리(0바이트-only 자동복구)**: 원자성 도입 **이전** 비원자 write가
  중단돼 남은 **0바이트** 파티션만 자동복구한다(관찰된 stuck의 원인). 그 외 손상은
  자동 개입하지 않고 안전하게 보존한다.
  - **0바이트 파티션** → 그 파일을 **부재로 간주**하고 신규 group을 그대로 write한다
    (read/concat/격리 없음). `store_recovered`(비게이트) 경고로 "0바이트 손상 파티션
    자동복구"를 표면화해 보고된 영구 stuck을 해소하고, 반환은 신규-파티션과 동일한
    net-new다. (`stat`이 실패하면 0바이트로 단정하지 않고 아래 일반 경로로 보낸다.)
  - **비어있지 않은 기존 파티션** → `read → concat(diagonal_relaxed) → dedup → 원자
    write`. read(읽기 불가·권한/환경 오류) 또는 concat(non-coercible 스키마)이 raise하면
    **기존 파일을 절대 덮어쓰지 않고** `store_merge`(게이트 → 재시도)만 기록하고 net-new
    0을 반환한다(pre-#2413 보존 동작). **비-0바이트 unreadable은 자동복구하지 않는다**
    (loud-stuck). 오분류=silent data loss이므로 자동 격리/self-heal 대신 preserve로
    편향하며, 복구는 사용자가 `ante data validate --fix` + range 재backfill로 수행한다.
  - **부재** → 신규 group 원자 write.
- **경고 타입 분리**: `drain_warnings()`가 반환하는 항목의 `type`은 `store_merge`
  (읽기/결합 실패 → 기존 보존) 또는 `store_recovered`(0바이트 자동복구)다. checkpoint
  전진 게이트는 `store_merge`만 소비하므로, 0바이트 자동복구(`store_recovered`)는
  게이트를 유발하지 않고 checkpoint를 전진시켜 stuck을 해소한다.
  두 값은 **정적 리터럴**이다 — 리포트 경고 `type`이 유계 정적 집합이어야 한다는
  규범(및 그 위에 성립하는 리포트 경고 유계화)의 SSOT는
  [data-feed/10-checkpoints-and-reports.md `경고 유계화`](../data-feed/10-checkpoints-and-reports.md#경고-유계화-bounded-warnings)다.
  런타임 값(경로·메시지 등)으로 `type`을 동적 조립하지 않는다.
- **known-limitation**:
  - checkpoint 재개 실행에서 0바이트 파티션을 자동복구하면, 재생성은 현재 group(증분
    경로에선 해당 실행분)만 담으므로 동일 파티션의 pre-checkpoint 구간은 재수집되지 않아
    forward-only 침묵 공백이 남을 수 있다. 이 사실은 자동복구 경고/로그로 표면화하며,
    완전 복구는 명시 range 재backfill(`ante feed run backfill --start … --end …` 또는
    `ante data validate --fix` 후 재수집)로 수행한다.
  - 비-0바이트 unreadable 파티션은 자동복구하지 않고 loud-stuck(`store_merge`)으로 남긴다
    — `ante data validate --fix`(사용자 발동, `.corrupted`로 격리)로 치운 뒤 재backfill로
    복구한다.
  - hard-kill이 replace 전에 남긴 orphan `*.tmp`(read glob `*.parquet` 밖)는
    **`validate(fix=True)`(사용자 발동, write-scoped)에서만** 회수하며 `stale_tmp_removed`
    로 리포트한다. write hot-path·read-scoped 경로는 파일시스템을 변조하지 않는다.
    프로세스 시작 시 전역 GC(모든 파티션 dir 스윕)와 `get_storage_usage`/read glob의
    `.tmp` 비가시는 본 이슈 범위 밖 follow-up이다.

### 데이터 보존 정책

오래된 데이터를 삭제하여 용량을 관리한다.

> 아래 보존 정책 표의 OHLCV timeframe 키(`1m`/`5m`/`15m`/`1h`/`1d`)는 [core.md
> `## Canonical Symbol/Timeframe Vocabulary`](../core/core.md#canonical-symboltimeframe-vocabulary)
> canonical OHLCV timeframe set에서 **파생**되며(보존 기간 값만 retention 정책 고유,
> 코드 상수 단일화는 #1613 파생), `fundamental` 행은 timeframe이 아니라 **data_type
> (축 C) retention 키**다. 따라서 표 헤더 `Timeframe`은 OHLCV bar timeframe 한정
> 명칭이며 이 표의 키는 OHLCV timeframe + `fundamental` data_type 혼합 retention
> 키다. 보존 기간 수치·행·코드 범위·#1614·후보 D는 본 pointer로 변경되지 않는다.

**1.0 기본 보존 기간**:

| Timeframe | 보존 기간 |
|-----------|----------|
| 1m | 365일 (1년) |
| 5m | 365일 (1년) |
| 15m | 365일 (1년) |
| 1h | 365일 (1년) |
| 1d | 3,650일 (10년) |
| fundamental | 무기한 (삭제 안 함) |

`flow`와 `event` 보존 정책은 1.0 계약에 포함하지 않는다. `flow`는 pykrx Phase 2에서
수급 데이터 수집을 도입할 때 수집 범위, 파티션 구조, 보존 기간을 함께 확정한다.
`event`는 후속 데이터 확장 단계에서 별도 계약으로 정의한다.

> DataFeed 소유 데이터(1d, fundamental)의 보존 정책도 이 테이블에서 통합 관리한다.
> RetentionPolicy는 소유자와 무관하게 `data_type`과 `timeframe` 기준으로 적용된다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async enforce` | now: datetime \| None = None | dict[str, int] | 보존 정책 적용. 삭제된 파일 수를 timeframe별로 반환. `now`는 테스트용 기준 시간 |

**생성자 파라미터**: `store: ParquetStore`, `retention_days: dict[str, int] | None = None`

**프로퍼티**: `retention_days: dict[str, int]` — 현재 보존 기간 설정. `-1`은 무기한 보존.

소스: `src/ante/data/retention.py`

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
