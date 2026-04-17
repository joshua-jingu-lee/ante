# DataFeed 모듈 세부 설계 - 설계 결정

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 설계 결정

### 운영 모델 — DataStore 경유 저장

DataFeed는 `ante.data.store.ParquetStore.write()`를 호출하여 저장한다.
자체 Parquet 읽기/쓰기 구현(`store/parquet.py`)을 두지 않는다.

**쓰기 모드는 overwrite(파티션 덮어쓰기)**다. 동일 파티션에 대해 `write()`를 재호출하면 기존 데이터를 완전 교체한다.
이로써 **멱등성이 보장**되므로 장애 후 재시도 시 중복이나 데이터 손상 없이 안전하게 복구할 수 있다.

### 쓰기 소유권

DataFeed가 소유하는 데이터 영역:

| 데이터 | 쓰기 방식 | 근거 |
|--------|----------|------|
| OHLCV 일봉 (`1d`) | 파티션 덮어쓰기 | data.go.kr에서 완전한 일봉을 수집, 더 높은 신뢰도 |
| `fundamental` | 파티션 덮어쓰기 | DART에서 재무제표 수집 |
| `flow` (Phase 2) | 파티션 덮어쓰기 | pykrx에서 수급 데이터 수집 |
| `event` (Phase 2) | 파티션 덮어쓰기 | DART에서 기업 이벤트 수집 |

분봉(`1m`, `5m` 등 1d 미만)과 틱 데이터는 Collector 소유이므로 DataFeed가 쓰지 않는다.
Collector는 반대로 1d 미만 타임프레임만 수집하며, 일봉 이상 데이터는 수신하더라도 폐기한다.

### 활성화 모델

코드는 `pip install ante`에 항상 포함되지만, `ante feed init`을 실행하기 전까지 비활성 상태이며 아무 동작도 하지 않는다.

**활성화 조건**: `{data}/.feed/config.toml`이 존재하면 활성 상태.

**API 키 없이도 init 가능**: init은 디렉토리와 config만 생성한다.
API 키가 없으면 수집 시작 시 해당 소스를 스킵하고 리포트에 기록한다.

### 저장소 구조

```
{data}/                                  # Ante 데이터 저장소
├── .feed/                           # DataFeed 운영 데이터
│   ├── config.toml                      # 설정 (수집 대상, 스케줄, 가드, 라우팅)
│   ├── .env                             # API 키 저장 (ante feed config set으로 관리)
│   ├── instruments.parquet              # 종목 메타데이터 (symbol ↔ name ↔ exchange)
│   ├── dart_corp_codes.json             # DART 고유번호 매핑 (corp_code ↔ stock_code)
│   ├── lock                             # 실행 중 lock (동시 실행 방지, PID 기록)
│   ├── checkpoints/                     # 체크포인트 (소스별/데이터유형별)
│   └── reports/                         # 수집/품질 리포트 이력
│       └── {YYYY-MM-DD}-{mode}.json
│
├── ohlcv/                               # DataFeed → 1d만 소유
│   └── 1d/{symbol}/{YYYY-MM}.parquet    # 거래소 계층 없음 (ParquetStore 구현)
│
├── fundamental/                         # DataFeed 소유
│   └── krx/{symbol}/{YYYY-MM}.parquet
│
├── flow/                                # Phase 2, DataFeed 소유
│   └── krx/{symbol}/{YYYY-MM}.parquet
│
└── event/                               # Phase 2, DataFeed 소유
    └── krx/{symbol}.parquet
```

계층 원칙: **데이터 유형 > 거래소 > 해상도 > 심볼 > 시간 파티션**

### 설정 관리 — FeedConfig

> 소스: `src/ante/feed/config.py`

설정 관리를 담당하는 `FeedConfig` 클래스. `ante feed init/config *` CLI의 백엔드.

| 메서드 | 파라미터 | 반환값 | 설명 |
|--------|----------|--------|------|
| `is_initialized` | — | bool | `config.toml` 존재 여부로 활성화 상태 확인 |
| `init` | — | list[str] | 피드 디렉토리 초기화 (config.toml, checkpoints/, reports/ 생성). 생성된 경로 목록 반환 |
| `load_api_keys` | — | dict[str, str \| None] | API 키 로드 (환경변수 > .env 파일 우선순위) |
| `set_api_key` | key: str, value: str | Path | .env에 키 저장, 퍼미션 0600 설정 |
| `list_api_keys` | — | list[dict[str, str]] | 마스킹된 키 목록 (앞3 + *** + 뒤3) |
| `check_api_keys` | — | list[dict[str, str \| bool]] | 키 존재 여부 확인 (유효성 검증은 스텁) |

**프로퍼티**: `feed_dir`, `env_path`, `config_path`

**공개 API** (`ante.feed.__init__`): `FeedConfig`, `FeedInjector`

### 설정 파일 형식

설정은 **설정 파일**, **API 키 파일**, **소스 상수**로 구성된다.

| 구분 | 위치 | 내용 |
|------|------|------|
| **설정 파일** | `{data}/.feed/config.toml` | 수집 대상, 스케줄, 방어 가드, 라우팅, 로그 레벨, 프로세스 우선순위 |
| **API 키** | `{data}/.feed/.env` | `ante feed config set`으로 관리. 환경변수가 설정되어 있으면 환경변수가 우선 |
| **소스 상수** | 각 소스 모듈에 하드코딩 | base_url, tps_limit, daily_limit 등 API 스펙 종속 값 |

**API 키 우선순위**: 환경변수 > `{data}/.feed/.env` 파일.
`ante feed config set`으로 `.env`에 저장하거나, 환경변수를 직접 설정한다.

> 소스별 API 상수(base_url, tps_limit 등)는 API 스펙에 종속된 값이므로 소스 모듈에 하드코딩한다.

**설정 파일** (`{data}/.feed/config.toml`):

```toml
[general]
log_level = "INFO"               # DEBUG, INFO, WARNING, ERROR (stdout 출력, 디버깅용)
nice_value = 10               # 프로세스 우선순위 (높을수록 양보, 0~19)

# 수집 스케줄
[schedule]
daily_at = "16:00"            # KST, 매일 이 시각에 daily 수집 시작
backfill_at = "01:00"         # KST, backfill 미완료 시 이 시각에 재개
backfill_since = "2015-01-01" # backfill 시작 기준일 (이 날짜 이후 데이터를 수집)

# 방어 가드 — 수집을 차단하는 조건
[guard]
blocked_days = []                                # 수집 차단 요일 (예: ["sat", "sun"])
blocked_hours = ["09:00-15:30"]                  # KST, 수집 차단 시간대
pause_during_trading = true                      # true면 blocked_hours 적용

# 소스 → 거래소 라우팅 (N:N)
[routing]
data_go_kr = ["krx"]
dart = ["krx"]
# Phase 2+
# pykrx = ["krx"]
# bloomberg = ["krx", "nasdaq", "nyse"]
# yahoo = ["nasdaq", "nyse"]

# 수집 대상 정의
# 디렉토리 구조: data/{data_type}/{exchange}/{timeframe}/{symbol}/...

[ohlcv.krx]
timeframes = ["1d"]               # DataFeed가 수집하는 타임프레임 (일봉만)
symbols = "all"                   # "all" = 전종목, 또는 ["005930", "000660", ...]

[fundamental.krx]
symbols = "all"

# [flow.krx]                      # Phase 2
# symbols = "all"

# [event.krx]                     # Phase 2
# symbols = "all"
```

### 소스-거래소 관계 (N:N)

소스와 거래소는 **다대다 관계**다. 하나의 소스가 여러 거래소에 데이터를 공급할 수 있고, 하나의 거래소가 여러 소스에서 데이터를 받을 수 있다.

```
소스 (Source)              거래소 (Exchange)
┌────────────┐            ┌──────┐
│ data.go.kr │ ──────────→│ KRX  │
│ DART       │ ──────────→│      │
│ pykrx      │ ──────────→│      │
└────────────┘            └──────┘
┌────────────┐            ┌────────┐
│ bloomberg  │ ──────────→│ KRX    │
│            │ ──────────→│ NASDAQ │
│            │ ──────────→│ NYSE   │
└────────────┘            └────────┘
```

- 소스는 데이터를 추출만 하고 **저장 위치를 알 필요 없음**
- orchestrator가 `routing` 설정을 보고 적절한 거래소 경로로 라우팅
- 새 소스나 거래소 추가 시 `config.toml`의 routing만 수정
