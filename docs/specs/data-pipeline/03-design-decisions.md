# DataStore 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [data-pipeline.md](data-pipeline.md)

# 설계 결정

### 데이터 스키마 (정규화된 형태)

모든 시세 데이터의 공통 스키마 상수:

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

**편의 상수 및 검증 함수**:
- `OHLCV_COLUMNS: list[str]` — `OHLCV_SCHEMA`의 키 목록
- `FUNDAMENTAL_COLUMNS: list[str]` — `FUNDAMENTAL_SCHEMA`의 키 목록
- `TIMEFRAMES: list[str]` — 지원 타임프레임 (`["1m", "5m", "15m", "1h", "1d"]`)
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

### Parquet 파일 구조

```
data/
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

**생성자 파라미터**: `base_path: str | Path = "data/"`, `compression: str = "snappy"`

**프로퍼티**: `base_path: Path` — 데이터 저장소 루트 경로

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async read` | symbol: str, timeframe: str, start: str \| None, end: str \| None, limit: int \| None, data_type: str = "ohlcv", exchange: str = "KRX" | pl.DataFrame | 데이터 읽기. `data_type`으로 스키마 자동 판별 |
| `async write` | symbol: str, timeframe: str, data: pl.DataFrame, data_type: str = "ohlcv", exchange: str = "KRX" | None | 파티션 단위 **merge** (월별 파티셔닝, 중복 제거 후 정렬). 기존 파일이 있으면 concat → unique → sort |
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

**기존 데이터 마이그레이션**: exchange 미명시 기존 데이터(OHLCV 경로에 exchange 디렉토리가 없는 경우)는 `KRX/` 하위로 자동 이동한다. 마이그레이션은 시스템 시작 시 자동 감지·실행하거나, CLI 명령 `ante data migrate`로 수동 실행할 수 있다.

소스: `src/ante/data/store.py`

### 데이터 보존 정책

오래된 데이터를 삭제하여 용량을 관리한다.

**기본 보존 기간**:

| Timeframe | 보존 기간 |
|-----------|----------|
| 1m | 365일 (1년) |
| 5m | 365일 (1년) |
| 15m | 365일 (1년) |
| 1h | 365일 (1년) |
| 1d | 3,650일 (10년) |
| fundamental | 무기한 (삭제 안 함) |
| flow | TBD (Phase 2, pykrx 도입과 함께 결정) |
| event | TBD (Phase 2) |

> DataFeed 소유 데이터(1d, fundamental, flow, event)의 보존 정책도 이 테이블에서 통합 관리한다.
> RetentionPolicy는 소유자와 무관하게 `data_type`과 `timeframe` 기준으로 적용된다.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `async enforce` | now: datetime \| None = None | dict[str, int] | 보존 정책 적용. 삭제된 파일 수를 timeframe별로 반환. `now`는 테스트용 기준 시간 |

**생성자 파라미터**: `store: ParquetStore`, `retention_days: dict[str, int] | None = None`

**프로퍼티**: `retention_days: dict[str, int]` — 현재 보존 기간 설정. `-1`은 무기한 보존.

소스: `src/ante/data/retention.py`

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조
