# DART OpenAPI 레퍼런스

> 원본: https://opendart.fss.or.kr/guide/main.do
> 금융감독원 전자공시시스템(DART) Open API

## 서비스 개요

| 항목 | 값 |
|------|-----|
| 제공자 | 금융감독원 (FSS) |
| 인증 | API 인증키 (`crtfc_key`, 40자리) |
| 일일 호출 한도 | 20,000건 |
| 응답 형식 | JSON / XML 선택 가능 |
| 인코딩 | UTF-8 |
| 데이터 범위 | 2015년 이후 (XBRL 의무 공시 이후) |

## Blind에서 사용하는 API

| API | 용도 | Phase |
|-----|------|:-----:|
| 고유번호 | corp_code ↔ stock_code 매핑 | 1 |
| 단일회사 주요계정 | 순이익, 순자산 등 주요 재무데이터 | 1 |
| 단일회사 전체 재무제표 | 상세 계정과목 (필요 시) | 2 |
| 단일회사 주요 재무지표 | ROE, 부채비율 등 (2023 3Q 이후) | 2 |
| 공시검색 | 공시일(rcept_dt) 기반 look-ahead bias 방지 | 1 |

---

## 1. 고유번호 (`corpCode`)

corp_code(DART 고유번호 8자리)와 stock_code(종목코드 6자리) 매핑 파일을 제공한다.
모든 DART API 호출에 corp_code가 필요하므로 **가장 먼저 수집**해야 한다.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/corpCode.xml
```

> 응답은 ZIP 파일 (바이너리). ZIP 내 XML에 전체 법인 목록 포함.

### 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:---:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |

### 응답 필드 (ZIP 내 XML)

| 필드 | 설명 |
|------|------|
| `corp_code` | 고유번호 (8자리) — DART API 호출 시 사용 |
| `corp_name` | 정식 회사명 |
| `corp_eng_name` | 영문 정식 회사명 |
| `stock_code` | 종목코드 (6자리, 상장사만) |
| `modify_date` | 최종변경일자 (YYYYMMDD) |

> **참고**: `stock_code`가 비어 있으면 비상장 법인. 상장사만 필터링하여 사용.

---

## 2. 공시검색 (`list`)

공시보고서를 조건 검색한다. Blind에서는 재무제표 공시의 **접수일자(rcept_dt)**를 확인하여 look-ahead bias를 방지하는 데 사용한다.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/list.json
GET https://opendart.fss.or.kr/api/list.xml
```

### 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:---:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | N | 고유번호 |
| `bgn_de` | STRING(8) | N | 검색시작 접수일자 (YYYYMMDD) |
| `end_de` | STRING(8) | N | 검색종료 접수일자 (YYYYMMDD) |
| `last_reprt_at` | STRING(1) | N | 최종보고서만 검색 (`Y`/`N`) |
| `pblntf_ty` | STRING(1) | N | 공시유형 (`A`~`J`) |
| `pblntf_detail_ty` | STRING(4) | N | 공시상세유형 코드 |
| `corp_cls` | STRING(1) | N | 법인구분 (`Y`:유가, `K`:코스닥, `N`:비상장, `E`:기타) |
| `sort` | STRING(4) | N | 정렬기준 (`date`/`crp`/`rpt`) |
| `sort_mth` | STRING(4) | N | 정렬방법 (`asc`/`desc`) |
| `page_no` | STRING(5) | N | 페이지번호 (기본: 1) |
| `page_count` | STRING(3) | N | 페이지당 건수 (1~100, 기본: 10) |

### 응답 필드

| 필드 | 설명 |
|------|------|
| `status` | 에러/정보 코드 |
| `message` | 에러/정보 메시지 |
| `page_no` | 현재 페이지번호 |
| `total_count` | 총 건수 |
| `total_page` | 총 페이지수 |
| `corp_name` | 종목명/법인명 |
| `corp_code` | 고유번호 |
| `report_nm` | 보고서명 |
| `rcept_no` | 접수번호 (14자리) — 다른 API 호출 시 사용 |
| `rcept_dt` | **접수일자** (YYYYMMDD) — look-ahead bias 방지 핵심 |
| `flr_nm` | 공시제출인명 |

---

## 3. 단일회사 주요계정 (`fnlttSinglAcnt`) — Phase 1 핵심

재무상태표(BS)와 손익계산서(IS)의 주요 계정과목을 제공한다.
Blind에서는 **순이익, 순자산** 등을 추출하여 PER/PBR/EPS/BPS 계산에 사용한다.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/fnlttSinglAcnt.json
GET https://opendart.fss.or.kr/api/fnlttSinglAcnt.xml
```

### 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:---:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | Y | 고유번호 (8자리) |
| `bsns_year` | STRING(4) | Y | 사업연도 (4자리, **2015년 이후**) |
| `reprt_code` | STRING(5) | Y | 보고서 코드 (아래 표 참조) |

#### 보고서 코드 (`reprt_code`)

| 코드 | 보고서 |
|:---:|--------|
| `11013` | 1분기보고서 |
| `11012` | 반기보고서 |
| `11014` | 3분기보고서 |
| `11011` | 사업보고서 (연간) |

### 응답 필드 (list 배열)

| 필드 | 타입 | 설명 |
|------|------|------|
| `rcept_no` | STRING | 접수번호 (14자리) |
| `bsns_year` | STRING | 사업연도 |
| `stock_code` | STRING | 종목코드 (6자리) |
| `reprt_code` | STRING | 보고서 코드 |
| `account_nm` | STRING | 계정명 (예: 자본총계, 당기순이익) |
| `fs_div` | STRING | `OFS`(개별) / `CFS`(연결) |
| `fs_nm` | STRING | 개별/연결 구분명 |
| `sj_div` | STRING | `BS`(재무상태표) / `IS`(손익계산서) |
| `sj_nm` | STRING | 재무제표명 |
| `thstrm_nm` | STRING | 당기명 (예: 제 13 기 3분기말) |
| `thstrm_dt` | STRING | 당기일자 (예: 2018.09.30) |
| `thstrm_amount` | NUMERIC | **당기금액** |
| `thstrm_add_amount` | NUMERIC | 당기누적금액 |
| `frmtrm_nm` | STRING | 전기명 |
| `frmtrm_dt` | STRING | 전기일자 |
| `frmtrm_amount` | NUMERIC | 전기금액 |
| `frmtrm_add_amount` | NUMERIC | 전기누적금액 |
| `bfefrmtrm_nm` | STRING | 전전기명 (사업보고서만) |
| `bfefrmtrm_dt` | STRING | 전전기일자 (사업보고서만) |
| `bfefrmtrm_amount` | NUMERIC | 전전기금액 (사업보고서만) |
| `ord` | STRING | 계정과목 정렬순서 |
| `currency` | STRING | 통화 단위 |

### Blind에서 추출할 주요 계정

| 계정명 (`account_nm`) | `sj_div` | 용도 |
|----------------------|:--------:|------|
| 당기순이익 | IS | PER, EPS 계산 |
| 자본총계 | BS | PBR, BPS 계산 |
| 매출액 | IS | revenue (FUNDAMENTAL 스키마) |
| 자산총계 | BS | 참조용 |
| 부채총계 | BS | 부채비율 계산 |

### 계산 공식 (data.go.kr 시가총액/상장주식수 + DART 재무제표)

```
PER = 시가총액 / 당기순이익
PBR = 시가총액 / 자본총계
EPS = 당기순이익 / 상장주식수
BPS = 자본총계 / 상장주식수
ROE = 당기순이익 / 자본총계
부채비율 = 부채총계 / 자본총계
```

> point-in-time 원칙: DART 공시일(`rcept_dt`)을 기준으로 반영 시점 결정.
> 분기 공시 시점까지는 이전 분기 수치 유지.

---

## 4. 단일회사 전체 재무제표 (`fnlttSinglAcntAll`)

모든 계정과목을 포함하는 전체 재무제표. 주요계정 API보다 상세하며, `fs_div` 파라미터로 개별/연결 선택.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json
GET https://opendart.fss.or.kr/api/fnlttSinglAcntAll.xml
```

### 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:---:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | Y | 고유번호 |
| `bsns_year` | STRING(4) | Y | 사업연도 (2015년 이후) |
| `reprt_code` | STRING(5) | Y | 보고서 코드 |
| `fs_div` | STRING(3) | Y | `OFS`(개별) / `CFS`(연결) |

### 응답 필드 (list 배열)

주요계정 API와 유사하나 추가 필드:

| 필드 | 타입 | 설명 |
|------|------|------|
| `account_id` | STRING | XBRL 표준계정ID |
| `account_detail` | STRING | 계정상세 (자본변동표에서 사용) |
| `sj_div` | STRING | `BS`/`IS`/`CIS`/`CF`/`SCE` (5종 재무제표 구분) |
| `frmtrm_q_nm` | STRING | 전기명 (분/반기) |
| `frmtrm_q_amount` | NUMERIC | 전기금액 (분/반기) |

> 나머지 필드는 단일회사 주요계정과 동일.

---

## 5. 다중회사 주요계정 (`fnlttMultiAcnt`)

복수 회사의 주요계정을 한 번에 조회. 벌크 수집 시 유용하나 **최대 100개 회사** 제한.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/fnlttMultiAcnt.json
GET https://opendart.fss.or.kr/api/fnlttMultiAcnt.xml
```

### 요청 파라미터

단일회사 주요계정과 동일. `corp_code`에 복수 고유번호를 콤마로 구분하여 전달 (최대 100건).

### 응답 필드

단일회사 주요계정과 동일.

---

## 6. 단일회사 주요 재무지표 (`fnlttSinglIndx`)

수익성, 안정성, 성장성, 활동성 지표를 제공한다.
**2023년 3분기 이후** 데이터만 제공되므로, 과거 데이터에는 직접 계산이 필요하다.

### 엔드포인트

```
GET https://opendart.fss.or.kr/api/fnlttSinglIndx.json
GET https://opendart.fss.or.kr/api/fnlttSinglIndx.xml
```

### 요청 파라미터

| 파라미터 | 타입 | 필수 | 설명 |
|---------|------|:---:|------|
| `crtfc_key` | STRING(40) | Y | API 인증키 |
| `corp_code` | STRING(8) | Y | 고유번호 |
| `bsns_year` | STRING(4) | Y | 사업연도 (**2023년 3Q 이후**) |
| `reprt_code` | STRING(5) | Y | 보고서 코드 |
| `idx_cl_code` | STRING(7) | Y | 지표분류코드 (아래 표 참조) |

#### 지표분류코드 (`idx_cl_code`)

| 코드 | 분류 | 포함 지표 예시 |
|:---:|------|------------|
| `M210000` | 수익성 | 영업이익률, 순이익률, ROE, ROA |
| `M220000` | 안정성 | 부채비율, 유동비율, 이자보상배율 |
| `M230000` | 성장성 | 매출액증가율, 영업이익증가율 |
| `M240000` | 활동성 | 총자산회전율, 재고자산회전율 |

### 응답 필드

| 필드 | 설명 |
|------|------|
| `stock_code` | 종목코드 (6자리) |
| `stlm_dt` | 결산기준일 (YYYY-MM-DD) |
| `idx_cl_code` | 지표분류코드 |
| `idx_cl_nm` | 지표분류명 (수익성/안정성/성장성/활동성) |
| `idx_code` | 지표코드 (예: M211000) |
| `idx_nm` | 지표명 (예: 영업이익률) |
| `idx_val` | 지표값 (예: 0.256) |

---

## 에러 코드 (공통)

| 코드 | 메시지 | 설명 |
|:---:|-------|------|
| `000` | 정상 | — |
| `010` | 등록되지 않은 키 | API 키 미등록 |
| `011` | 사용할 수 없는 키 | 일시적 사용 중지 |
| `012` | 접근할 수 없는 IP | IP 미등록 |
| `013` | 조회된 데이터 없음 | 결과 0건 |
| `014` | 파일 존재하지 않음 | — |
| `020` | 요청 제한 초과 | 일 20,000건 초과 |
| `021` | 조회 가능 회사 개수 초과 | 최대 100건 |
| `100` | 부적절한 필드 값 | 파라미터 값 오류 |
| `101` | 부적절한 접근 | — |
| `800` | 시스템 점검 중 | — |
| `900` | 정의되지 않은 오류 | — |
| `901` | 개인정보 보유기간 만료 | 계정 재인증 필요 |

---

## Blind 수집 전략 메모

### 벌크 수집 산출 (Phase 1)

| 항목 | 수치 |
|------|------|
| 대상 종목 | ~2,400 (KOSPI+KOSDAQ 상장사) |
| 수집 연도 | 2015~2025 (11년) |
| 보고서 종류 | 4종 (1Q, 반기, 3Q, 사업) |
| 총 호출 수 | ~2,400 × 11 × 4 = **105,600건** |
| 일일 한도 대비 | 20,000건/일 → **약 6일** 소요 |

### 수집 순서

1. **고유번호 파일** 다운로드 → corp_code ↔ stock_code 매핑 테이블 구축
2. **공시검색**으로 각 보고서의 rcept_dt(접수일자) 확보 → look-ahead bias 방지
3. **단일회사 주요계정**으로 순이익, 자본총계, 매출액 등 수집
4. data.go.kr의 시가총액/상장주식수와 조합하여 PER/PBR/EPS/BPS **직접 계산**

### 다중회사 API 활용

- `fnlttMultiAcnt`로 100개씩 묶어 호출하면 호출 횟수를 1/100로 줄일 수 있음
- 2,400종목 × 11년 × 4분기 = 105,600 → 100개 묶음 시 **1,056건** (하루 내 수집 가능)
- 단, 응답 크기가 커질 수 있으므로 타임아웃 주의
