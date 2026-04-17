# DataFeed 모듈 세부 설계 - 데이터 소스

> 인덱스: [README.md](README.md) | 호환 문서: [data-feed.md](data-feed.md)

# 데이터 소스

### data.go.kr — Phase 1 주력

`getStockPriceInfo` 단일 호출로 OHLCV + 거래대금 + 시가총액 + 상장주식수를 동시 확보.

> API 레퍼런스: [docs/references/dashboard/data-go-kr-stock-price-api.md](../../references/dashboard/data-go-kr-stock-price-api.md)

| 제약 | 값 |
|------|-----|
| 일일 호출 한도 | 10,000건 |
| 초당 트랜잭션 | 30 tps |
| 평균 응답 시간 | 500ms |
| 데이터 갱신 | 영업일 D+1, 오후 1시 이후 |
| 서비스 시작일 | 2021-11-16 (이전 데이터는 API에서 제공하지 않을 수 있음) |
| 수집 방식 | 날짜별 전종목 조회 (`basDt` 파라미터) |

**요청 규격:**
- 엔드포인트: `GET /1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo`
- 필수 파라미터: `serviceKey`, `numOfRows=1000`, `pageNo`, `resultType=json`
- 날짜 필터: `basDt=YYYYMMDD` (일치 검색)
- 1일 = ~2,400건 (KOSPI+KOSDAQ) → 약 3페이지

**응답 필드 → Ante 매핑:**

| API 필드 | 국문 | Ante 매핑 | 대상 스키마 |
|----------|------|----------|-----------|
| `basDt` | 기준일자 | `timestamp` / `date` | OHLCV / FUNDAMENTAL |
| `srtnCd` | 단축코드 | `symbol` | 공통 |
| `mkp` | 시가 | `open` (Float64) | OHLCV |
| `hipr` | 고가 | `high` (Float64) | OHLCV |
| `lopr` | 저가 | `low` (Float64) | OHLCV |
| `clpr` | 종가 | `close` (Float64) | OHLCV |
| `trqu` | 거래량 | `volume` (Int64) | OHLCV |
| `trPrc` | 거래대금 | `amount` (Int64) | OHLCV |
| `lstgStCnt` | 상장주식수 | `shares_listed` (Int64) | FUNDAMENTAL |
| `mrktTotAmt` | 시가총액 | `market_cap` (Int64) | FUNDAMENTAL |
| `itmsNm` | 종목명 | `name` | INSTRUMENTS |
| `mrktCtg` | 시장구분 | `market` | INSTRUMENTS |

> **모든 응답 값은 문자열**이므로 DataGoKrNormalizer에서 숫자 타입 변환이 필요하다.

**벌크 수집 산출:**
- 10년치(~2,450 영업일) × 3페이지/일 = ~7,350 호출 → 일일 한도 내 **1일 완료 가능**

**HTTP 200 에러 응답 처리**: data.go.kr은 오류 시에도 HTTP 200으로 응답하고 body에 에러 코드를 담는다.
HTTP 상태 코드만으로 성공 여부를 판단하면 안 된다.

**에러 코드:**

| 코드 | 메시지 | 행동 |
|:---:|-------|------|
| 00 | NORMAL SERVICE | 정상 |
| 10 | INVALID_REQUEST_PARAMETER_ERROR | 재시도 불가, 파라미터 점검 |
| 12 | NO_OPENAPI_SERVICE_ERROR | 재시도 불가, 서비스 폐기 확인 |
| 22 | LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR | 일일 한도 초과 → 수집 중단 |
| 30 | SERVICE_KEY_IS_NOT_REGISTERED_ERROR | 재시도 불가, 키 확인 → CRITICAL |
| 31 | DEADLINE_HAS_EXPIRED_ERROR | 키 갱신 필요 → CRITICAL |
| 99 | UNKNOWN_ERROR | 1회 재시도 후 스킵 |

**서비스키 이중 인코딩 방지**: 디코딩된(원본) 키를 사용하고 라이브러리의 자동 인코딩에 맡긴다.

### DART OpenAPI — 재무제표

> API 레퍼런스: [docs/references/dashboard/dart-openapi.md](../../references/dashboard/dart-openapi.md)

| 제약 | 값 |
|------|-----|
| 인증 | API 인증키 (`crtfc_key`, 40자리) |
| 일일 호출 한도 | 20,000건 |
| 응답 형식 | JSON / XML 선택 가능 |
| 데이터 범위 | 2015년 이후 (XBRL 의무 공시 이후) |
| 선행 작업 | 고유번호(corp_code) 매핑 파일 다운로드 필수 → `{data}/.feed/dart_corp_codes.json`에 캐싱 |

**사용 API:**

| API | 엔드포인트 | 용도 | Phase |
|-----|----------|------|:-----:|
| 고유번호 | `corpCode.xml` | corp_code ↔ stock_code 매핑 (ZIP 바이너리 응답) | 1 |
| 공시검색 | `list.json` | 보고서별 접수일자(rcept_dt) 확보 — look-ahead bias 방지 | 1 |
| 다중회사 주요계정 | `fnlttMultiAcnt.json` | 순이익, 자본총계 등 (최대 **100개 회사**씩 묶어 호출) | 1 |
| 단일회사 전체 재무제표 | `fnlttSinglAcntAll.json` | 상세 계정과목 (필요 시) | 2 |
| 단일회사 주요 재무지표 | `fnlttSinglIndx.json` | ROE, 부채비율 등 (**2023 3Q 이후**만 제공) | 2 |

**보고서 코드 (`reprt_code`):**

| 코드 | 보고서 |
|:---:|--------|
| `11013` | 1분기보고서 |
| `11012` | 반기보고서 |
| `11014` | 3분기보고서 |
| `11011` | 사업보고서 (연간) |

**연결/개별 재무제표 구분 (`fs_div`):**
- `CFS`: 연결재무제표 (우선 사용)
- `OFS`: 개별재무제표 (연결이 없는 경우 대체)

**수집 순서:**
1. 고유번호 ZIP 다운로드 → `stock_code` 비어있는 비상장사 필터링 → corp_code ↔ stock_code 매핑 테이블 구축
2. 공시검색(`list`) → 각 보고서의 `rcept_dt`(접수일자) 확보 (look-ahead bias 방지)
3. 다중회사 주요계정(`fnlttMultiAcnt`) → 100개씩 묶어 순이익, 자본총계, 매출액, 부채총계 수집

**추출 대상 계정 (`account_nm`):**

| 계정명 | 재무제표 구분 (`sj_div`) | 용도 |
|--------|:---:|------|
| 당기순이익 | IS (손익계산서) | PER, EPS 계산 |
| 자본총계 | BS (재무상태표) | PBR, BPS 계산 |
| 매출액 | IS (손익계산서) | `revenue` (FUNDAMENTAL 스키마) |
| 부채총계 | BS (재무상태표) | `debt_to_equity` 계산 |

**벌크 수집 산출:**

| 방식 | 산출 | 소요 |
|------|------|------|
| 단일회사 API | ~2,400종목 × 11년 × 4분기 = **105,600건** | ~6일 (20,000건/일) |
| 다중회사 API (100개 묶음) | 105,600 / 100 = **1,056건** | **1일 완료 가능** |

> 다중회사 API 사용 시 응답 크기가 커질 수 있으므로 타임아웃에 주의한다.

**PER/PBR/EPS/BPS/ROE/부채비율 계산** (data.go.kr 시가총액·상장주식수 + DART 재무제표):
```
PER = 시가총액 / 당기순이익
PBR = 시가총액 / 자본총계
EPS = 당기순이익 / 상장주식수
BPS = 자본총계 / 상장주식수
ROE = 당기순이익 / 자본총계
부채비율 = 부채총계 / 자본총계
```

> point-in-time 원칙: DART 공시일(`rcept_dt`)을 기준으로 반영 시점을 결정한다.
> 분기 공시 시점까지는 이전 분기 수치를 유지하여 look-ahead bias를 방지한다.

**에러 코드:**

| 코드 | 메시지 | 행동 |
|:---:|-------|------|
| `000` | 정상 | — |
| `010` | 등록되지 않은 키 | 재시도 불가 → CRITICAL |
| `013` | 조회된 데이터 없음 | 정상 처리 (해당 기간 데이터 없음) |
| `020` | 요청 제한 초과 | 일일 한도 → 수집 중단 |
| `021` | 조회 가능 회사 개수 초과 | 배치 크기 100 초과 → 구현 버그 |
| `100` | 부적절한 필드 값 | 재시도 불가, 파라미터 점검 |
| `800` | 시스템 점검 중 | 재시도 가능, backoff |
| `900` | 정의되지 않은 오류 | 1회 재시도 후 스킵 |
| `901` | 개인정보 보유기간 만료 | 계정 재인증 필요 → CRITICAL |

### pykrx — 백업 / Phase 2

| 역할 | 설명 |
|------|------|
| 백업 | data.go.kr 장애 시 OHLCV 대체 수집 |
| Phase 2 전용 | 수급(투자자별 매매, 공매도), 외국인 지분 — 대안 없음 |

> 비공식 스크래핑이므로 주 소스로 의존하지 않는다.
