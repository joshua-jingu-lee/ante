# data.go.kr 금융위원회_주식시세정보 API 레퍼런스

> 원본: 공공데이터 오픈API 활용가이드 — 금융위원회_주식시세정보 (PDF)

## 서비스 개요

| 항목 | 값 |
|------|-----|
| API명(영문) | `getStockSecuritiesInfoService` |
| API명(국문) | 금융위원회_주식시세정보 |
| 서비스 URL | `https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService` |
| 인증 | serviceKey (공공데이터포털 인증키) |
| 인터페이스 | REST (GET) |
| 응답 형식 | XML (기본), JSON 선택 가능 |
| 데이터 갱신주기 | 일 1회 |
| 서비스 시작일 | 2021-11-16 |

## 상세기능 목록

| 번호 | 상세기능명(영문) | 상세기능명(국문) | Blind 사용 여부 |
|------|------------|------------|:-----------:|
| 1 | `getStockPriceInfo` | 주식시세 | **O** (Phase 1 핵심) |
| 2 | `getPreemptiveRightCertificatePriceInfo` | 신주인수권증서시세 | X |
| 3 | `getSecuritiesPriceInfo` | 수익증권시세 | X (ETF 전략 도입 시 재검토) |
| 4 | `getPreemptiveRightSecuritiesPriceInfo` | 신주인수권증권시세 | X |

---

## 1. 주식시세 (`getStockPriceInfo`) — Phase 1 핵심

### 엔드포인트

```
GET https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo
```

### 제약

| 항목 | 값 |
|------|-----|
| 초당 최대 트랜잭션 | 30 tps |
| 평균 응답 시간 | 500 ms |
| 최대 메시지 사이즈 | 4000 byte |

### 요청 파라미터

#### 필수 (항목구분 = 1)

| 파라미터 | 국문 | 크기 | 설명 | 샘플 |
|---------|------|:---:|------|------|
| `serviceKey` | 서비스키 | 400 | 공공데이터포털 인증키 | — |
| `numOfRows` | 한 페이지 결과 수 | 4 | 페이지당 행 수 | `1000` |
| `pageNo` | 페이지 번호 | 4 | 페이지 번호 | `1` |
| `resultType` | 결과형식 | 4 | `xml` 또는 `json` (기본: xml) | `json` |

#### 옵션 (항목구분 = 0) — 주요 필터

| 파라미터 | 국문 | 크기 | 설명 | 샘플 |
|---------|------|:---:|------|------|
| `basDt` | 기준일자 | 8 | 일치 검색 (YYYYMMDD) | `20220919` |
| `beginBasDt` | 기준일자 | 8 | 기준일자 >= 검색값 | `20220919` |
| `endBasDt` | 기준일자 | 8 | 기준일자 < 검색값 | `20220919` |
| `likeBasDt` | 기준일자 | 8 | 기준일자 LIKE 검색 | `20220919` |
| `likeSrtnCd` | 단축코드 | 9 | 단축코드 LIKE 검색 | `900110` |
| `isinCd` | ISIN코드 | 12 | ISIN코드 일치 검색 | `HK0000057197` |
| `likeIsinCd` | ISIN코드 | 12 | ISIN코드 LIKE 검색 | `HK0000057198` |
| `itmsNm` | 종목명 | 120 | 종목명 일치 검색 | `이스트아시아홀딩스` |
| `likeItmsNm` | 종목명 | 120 | 종목명 LIKE 검색 | `이스트아시아홀딩스` |
| `mrktCls` | 시장구분 | 40 | `KOSPI` / `KOSDAQ` / `KONEX` | `KOSDAQ` |

#### 옵션 — 범위 필터

| 파라미터 | 국문 | 크기 | 설명 |
|---------|------|:---:|------|
| `beginVs` / `endVs` | 대비 | 10 | 전일 대비 등락 범위 |
| `beginFltRt` / `endFltRt` | 등락률 | 11 | 등락률 범위 |
| `beginTrqu` / `endTrqu` | 거래량 | 12 | 거래량 범위 |
| `beginTrPrc` / `endTrPrc` | 거래대금 | 21 | 거래대금 범위 |
| `beginLstgStCnt` / `endLstgStCnt` | 상장주식수 | 15 | 상장주식수 범위 |
| `beginMrktTotAmt` / `endMrktTotAmt` | 시가총액 | 21 | 시가총액 범위 |

### 응답 필드

#### 헤더

| 필드 | 국문 | 설명 |
|------|------|------|
| `resultCode` | 결과코드 | `00` = 정상 |
| `resultMsg` | 결과메시지 | `NORMAL SERVICE.` |

#### 페이징

| 필드 | 국문 | 설명 |
|------|------|------|
| `numOfRows` | 한 페이지 결과 수 | 요청한 페이지 크기 |
| `pageNo` | 페이지 번호 | 현재 페이지 |
| `totalCount` | 전체 결과 수 | 전체 레코드 수 |

#### 데이터 (item)

| 필드 | 국문 | 크기 | 설명 | Ante 매핑 |
|------|------|:---:|------|----------|
| `basDt` | 기준일자 | 8 | YYYYMMDD | `timestamp` (OHLCV) / `date` (FUNDAMENTAL) |
| `srtnCd` | 단축코드 | 9 | 6자리 종목코드 | `symbol` |
| `isinCd` | ISIN코드 | 12 | 국제 고유번호 | 메타데이터 참조용 |
| `itmsNm` | 종목명 | 120 | 종목 명칭 | 메타데이터 참조용 |
| `mrktCtg` | 시장구분 | 40 | KOSPI/KOSDAQ/KONEX | 메타데이터 참조용 |
| `clpr` | 종가 | 12 | 정규시장 최종가격 | `close` (Float64) |
| `vs` | 대비 | 10 | 전일 대비 등락 | — (계산 가능) |
| `fltRt` | 등락률 | 11 | 전일 대비 등락 비율 | — (계산 가능) |
| `mkp` | 시가 | 12 | 정규시장 최초가격 | `open` (Float64) |
| `hipr` | 고가 | 12 | 하루 중 최고가 | `high` (Float64) |
| `lopr` | 저가 | 12 | 하루 중 최저가 | `low` (Float64) |
| `trqu` | 거래량 | 12 | 체결수량 누적합계 | `volume` (Int64) |
| `trPrc` | 거래대금 | 21 | 체결가격*체결수량 누적합계 | `amount` (Int64) |
| `lstgStCnt` | 상장주식수 | 15 | 종목 상장주식수 | `shares_listed` (Int64, FUNDAMENTAL) |
| `mrktTotAmt` | 시가총액 | 21 | 종가*상장주식수 | `market_cap` (Int64, FUNDAMENTAL) |

### 요청/응답 예제

**요청:**
```
https://apis.data.go.kr/1160100/service/GetStockSecuritiesInfoService/getStockPriceInfo?serviceKey=인증키&numOfRows=1&pageNo=1
```

**응답 (XML):**
```xml
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<response>
  <header>
    <resultCode>00</resultCode>
    <resultMsg>NORMAL SERVICE.</resultMsg>
  </header>
  <body>
    <numOfRows>1</numOfRows>
    <pageNo>1</pageNo>
    <totalCount>1713576</totalCount>
    <items>
      <item>
        <basDt>20220919</basDt>
        <srtnCd>900110</srtnCd>
        <isinCd>HK0000057197</isinCd>
        <itmsNm>이스트아시아홀딩스</itmsNm>
        <mrktCtg>KOSDAQ</mrktCtg>
        <clpr>167</clpr>
        <vs>-8</vs>
        <fltRt>-4.57</fltRt>
        <mkp>173</mkp>
        <hipr>176</hipr>
        <lopr>167</lopr>
        <trqu>2788311</trqu>
        <trPrc>475708047</trPrc>
        <lstgStCnt>219932050</lstgStCnt>
        <mrktTotAmt>36728652350</mrktTotAmt>
      </item>
    </items>
  </body>
</response>
```

---

## Blind 수집 전략 메모

- **날짜별 전종목 조회** 방식 (`basDt` 파라미터) 사용
  - 1일 = ~2,400건 (KOSPI+KOSDAQ) → 약 3페이지 (numOfRows=1000)
  - 10년치(~2,450영업일) → ~7,350 API 호출 → 일일 한도(10,000건) 내
- 단일 호출로 OHLCV(6개) + 거래대금 + 시가총액 + 상장주식수 동시 확보
- `resultType=json` 사용 권장 (파싱 편의)
- 모든 응답 값은 **문자열**이므로 숫자 변환 필요

---

## 에러 코드

| 코드 | 메시지 | 설명 |
|:---:|-------|------|
| 1 | APPLICATION_ERROR | 어플리케이션 에러 |
| 10 | INVALID_REQUEST_PARAMETER_ERROR | 잘못된 요청 파라미터 |
| 12 | NO_OPENAPI_SERVICE_ERROR | 서비스 없거나 폐기됨 |
| 20 | SERVICE_ACCESS_DENIED_ERROR | 서비스 접근거부 |
| 22 | LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR | 요청 제한 횟수 초과 |
| 30 | SERVICE_KEY_IS_NOT_REGISTERED_ERROR | 등록되지 않은 서비스키 |
| 31 | DEADLINE_HAS_EXPIRED_ERROR | 기한 만료된 서비스키 |
| 32 | UNREGISTERED_IP_ERROR | 등록되지 않은 IP |
| 99 | UNKNOWN_ERROR | 기타 에러 |
