# DataFeed 모듈 세부 설계 - CLI

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# CLI

Ante CLI의 `feed` 서브커맨드로 제공된다.

### `ante feed init <data_path>`

Ante 데이터 저장소에 DataFeed 운영 디렉토리를 초기화한다.

**동작:**
1. `{data_path}/.feed/` 디렉토리 생성
2. `{data_path}/.feed/config.toml` 기본 설정 파일 생성
3. `{data_path}/.feed/checkpoints/` 디렉토리 생성
4. `{data_path}/.feed/reports/` 디렉토리 생성
5. API 키 설정 안내 출력

**출력 예시:**
```
$ ante feed init /path/to/ante/data

Created /path/to/ante/data/.feed/config.toml
Created /path/to/ante/data/.feed/checkpoints/
Created /path/to/ante/data/.feed/reports/

──────────────────────────────────────────────────
API 키 설정이 필요합니다.

DataFeed은 공공 데이터 API를 통해 시세·재무 데이터를 수집합니다.
각 API를 사용하려면 해당 서비스에서 발급받은 인증키를 등록해야 합니다.

  ANTE_DATAGOKR_API_KEY  data.go.kr 공공데이터포털 서비스키
                          발급: https://www.data.go.kr → 마이페이지 → 인증키 발급

  ANTE_DART_API_KEY      금융감독원 DART OpenAPI 인증키
                          발급: https://opendart.fss.or.kr → 인증키 신청

설정:
  ante feed config set ANTE_DATAGOKR_API_KEY your_key_here
  ante feed config set ANTE_DART_API_KEY your_key_here

확인:
  ante feed config check

환경변수가 설정되어 있으면 .env 파일보다 우선합니다.
──────────────────────────────────────────────────
```

### `ante feed start`

내장 스케줄러로 backfill/daily를 자동 실행하는 상주 프로세스.

### `ante feed run backfill`

Backfill을 1회 실행 후 종료. 외부 스케줄러 또는 수동 실행용.

### `ante feed run daily`

Daily 수집을 1회 실행 후 종료.

### `ante feed status`

수집 상태 조회. 체크포인트 현황, 최근 리포트 요약.

### `ante feed config set <KEY> <VALUE>`

API 키 등 설정값을 `{data}/.feed/.env`에 저장한다.

**동작:**
1. `{data}/.feed/.env` 파일이 없으면 생성
2. 해당 KEY가 이미 존재하면 값을 덮어쓰기
3. 파일 퍼미션 `0600` 설정 (소유자만 읽기/쓰기)

**사용 예시:**
```
$ ante feed config set ANTE_DATAGOKR_API_KEY abc123def456
Saved ANTE_DATAGOKR_API_KEY to /path/to/ante/data/.feed/.env

$ ante feed config set ANTE_DART_API_KEY xyz789
Saved ANTE_DART_API_KEY to /path/to/ante/data/.feed/.env
```

**지원 키:**

| KEY | 설명 |
|-----|------|
| `ANTE_DATAGOKR_API_KEY` | data.go.kr 공공데이터포털 서비스키 |
| `ANTE_DART_API_KEY` | 금융감독원 DART OpenAPI 인증키 |

**우선순위**: 환경변수 > `.feed/.env`. 환경변수가 설정되어 있으면 `.env` 값보다 우선한다.

### `ante feed config list`

등록된 설정값 목록을 마스킹하여 표시한다.

**동작:**
1. `.feed/.env` 및 환경변수에서 키 로드 (우선순위 적용)
2. 각 키의 값을 마스킹하여 출력 (앞 3자 + `***` + 뒤 3자)
3. 미설정 키는 `(미설정)`으로 표시

**출력 예시:**
```
$ ante feed config list

  ANTE_DATAGOKR_API_KEY  abc***456  (source: .env)
  ANTE_DART_API_KEY      xyz***789  (source: env)

$ ante feed config list

  ANTE_DATAGOKR_API_KEY  (미설정)
  ANTE_DART_API_KEY      abc***789  (source: .env)
```

### `ante feed config check`

등록된 API 키의 존재 여부와 유효성을 확인한다.

**동작:**
1. `.feed/.env` 및 환경변수에서 키 로드 (우선순위 적용)
2. 각 키의 존재 여부 확인
3. 키가 존재하면 해당 API에 경량 요청을 보내 유효성 검증

**출력 예시:**
```
$ ante feed config check

API Key Status
──────────────────────────────────────────────────
  ANTE_DATAGOKR_API_KEY  ✓ 설정됨 (source: .env)  ✓ 유효
  ANTE_DART_API_KEY      ✓ 설정됨 (source: env)   ✓ 유효
──────────────────────────────────────────────────

$ ante feed config check

API Key Status
──────────────────────────────────────────────────
  ANTE_DATAGOKR_API_KEY  ✗ 미설정
  ANTE_DART_API_KEY      ✓ 설정됨 (source: .env)  ✗ 인증 실패
──────────────────────────────────────────────────
설정: ante feed config set <KEY> <VALUE>
```

### `ante feed inject <path> --symbol <종목> [--timeframe <주기>] [--source <소스>]`

외부 파일(CSV 등)에서 과거 데이터를 수동 주입한다. DataStore의 ParquetStore를 통해 저장하며, 쓰기 소유권 규칙을 따른다.

**동작:**
1. CSV 파일 로드
2. Normalizer로 스키마 정규화 (YahooNormalizer, DefaultNormalizer 등 `--source`에 따라 선택)
3. 4계층 검증 (validate.py)
4. ParquetStore.write()로 저장

**옵션:**

| 옵션 | 기본값 | 설명 |
|------|--------|------|
| `--symbol` | (필수) | 종목 코드 (6자리) |
| `--timeframe` | `1d` | 타임프레임 |
| `--source` | `external` | 데이터 소스 식별자 (normalizer 선택에 사용) |

**출력 예시:**
```
$ ante feed inject samsung_2024.csv --symbol 005930

Loaded 245 rows from samsung_2024.csv
Normalized: source=external, schema=OHLCV
Validated: 245 rows passed
Written to ohlcv/krx/1d/005930/

Injected 245 rows for 005930 (1d)
```
