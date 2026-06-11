# Broker Adapter 모듈 세부 설계 - KISDomesticAdapter — 국내주식 전용

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# KISDomesticAdapter — 국내주식 전용

구현: `src/ante/broker/kis.py` 참조

KISBaseAdapter를 상속하여 국내주식 전용 로직을 구현한다. 기존 `KISAdapter`를 리네이밍한 것이다.

```python
class KISDomesticAdapter(KISBaseAdapter):
    broker_id = "kis-domestic"
    broker_name = "한국투자증권 국내"
    broker_short_name = "KIS"
```

### 분리된 국내 전용 로직

| 항목 | 설명 |
|------|------|
| `currency` | `"KRW"` 반환 |
| API 경로 | `/uapi/domestic-stock/v1/` |
| 주문 파라미터 | `ORD_DVSN`, `PDNO` (6자리 종목코드), `EXCG_ID_DVSN_CD` (`KRX`) |
| 잔고 조회 | 원화 단일 (`TTTC8434R`) |
| 시세 조회 | `fid_cond_mrkt_div_code: "J"` |
| 심볼 정규화 | 6자리 숫자 (`005930`) |
| 호가 단위 | 가격대별 (100/500/1000원) |
| 모의투자 TR | `T` → `V` 접두사 |

### 주요 API 엔드포인트

| 기능 | 엔드포인트 | HTTP 메서드 |
|------|-----------|------------|
| 잔고 조회 | `/uapi/domestic-stock/v1/trading/inquire-balance` | GET |
| 현재가 조회 | `/uapi/domestic-stock/v1/quotations/inquire-price` | GET |
| 주문 접수 | `/uapi/domestic-stock/v1/trading/order-cash` | POST |
| 주문 취소/정정 | `/uapi/domestic-stock/v1/trading/order-rvsecncl` | POST |
| 미체결 조회 | `/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl` | GET |

### order-cash TR ID 매핑

주문 접수(`order-cash`) 호출 시 `place_order`는 `is_paper` × `side` 조합으로 아래 KIS 공식 현행 TR ID를 전송한다. **order-cash 한정**이며, 취소/정정(`order-rvsecncl`, `VTTC0803U`/`TTTC0803U`)·잔고·현재가 등 다른 TR ID는 이 표의 범위 밖이다.

| 환경 | 매수 | 매도 |
|------|------|------|
| 모의 | `VTTC0012U` | `VTTC0011U` |
| 실전 | `TTTC0012U` | `TTTC0011U` |

> 출처: [KIS open-trading-api `order_cash.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py) 및 KIS Developers 포털(2축 검증). 구버전 TR ID(`VTTC0802U`/`TTTC0802U`/`VTTC0801U`/`TTTC0311U`)는 deprecated 되어 모의 매수 시 `40910000 모의투자 주문이 불가한 계좌입니다`로 거절되므로 현행 매핑으로 갱신했다(#2342).

### order-cash 주문 바디 계약 (#2344)

주문 접수(`order-cash`, `place_order` → `_build_order_data`)는 `is_paper` × `side` × `order_type` 무관하게 아래 바디를 전송한다. **order-cash 한정**이며 취소/정정(`order-rvsecncl`)·잔고·현재가 등은 이 표의 범위 밖이다. `EXCG_ID_DVSN_CD`는 모듈 레벨 상수 `DEFAULT_EXCG_ID_DVSN_CD="KRX"`로 주입한다(에픽 #2354 일관성 목표의 공유 단일 출처 — 후속 이슈가 재사용).

| 필드 | 값 | 설명 |
|------|------|------|
| `CANO` | `account_no[:8]` | 종합계좌번호 |
| `ACNT_PRDT_CD` | `account_no[8:10]` | 계좌상품코드 |
| `PDNO` | `normalize_symbol(symbol)` (6자리) | 종목코드 |
| `ORD_DVSN` | `order_type` 매핑(시장가 `'01'`/지정가 `'00'` 등) | 주문구분 |
| `ORD_QTY` | `str(int(quantity))` | 주문수량 |
| `ORD_UNPR` | 시장가 `'0'` / 지정가 `str(int(price))` | 주문단가 |
| `EXCG_ID_DVSN_CD` | `'KRX'` | 거래소ID구분코드(국내 KRX 기본·NXT/SOR 미지원) |

- **출처**: [KIS open-trading-api `order_cash.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_cash/order_cash.py). 공식 예제는 `order_cash()` 인자로 `excg_id_dvsn_cd`를 필수로 받고 누락 시 `ValueError`로 가드하며, 요청 바디에 `"EXCG_ID_DVSN_CD": excg_id_dvsn_cd`로 포함한다. ante 이전 바디에는 이 필드가 빠져 공식 현행 계약과 drift 상태였다.
- **`40910000` 인과 caveat**: 2026-06-11 KST 모의 smoke에서 #2342 TR ID 갱신 후에도 모의 매수가 `40910000 모의투자 주문이 불가한 계좌입니다`로 실패했다. 본 계약 정합이 그 실패의 직접 원인인지는 **미확정**이며, 머지 후 다음 거래일 모의 smoke(`buy 1 → fill/position → sell 1 → flatten`)로 검증한다. 지속 실패 시 계좌 자격/provisioning 가설은 별도 이슈로 분리한다(본 이슈는 contract drift 해소로 종결).
- **비목표(`SLL_TYPE`/`CNDT_PRIC`)**: 공식 예제 바디에는 `SLL_TYPE`(매도유형)·`CNDT_PRIC`(조건가격)이 존재하나, 필수 `ValueError` 가드는 `EXCG_ID_DVSN_CD`에만 있고 거절 근거 관측이 없어 본 PR 비목표다. 추측성 빈 문자열 필드 추가는 행동 변화 위험만 있으므로 제외하며, 거절 근거가 관측되면 후속 이슈로 다룬다.

### order-rvsecncl 취소 바디 계약 (#2345)

주문 취소(`order-rvsecncl`, `cancel_order`)는 레거시 TR ID `VTTC0803U`(모의)/`TTTC0803U`(실전)로 아래 바디를 전송한다. **취소 한정**이며 정정(modify)·order-cash·잔고 등은 이 표의 범위 밖이다.

| 필드 | 값 | 설명 |
|------|------|------|
| `CANO` | `account_no[:8]` | 종합계좌번호 |
| `ACNT_PRDT_CD` | `account_no[8:10]` | 계좌상품코드 |
| `ORGN_ODNO` | `order_id` | 원주문번호(ODNO) |
| `ORD_DVSN` | `'01'` | 주문구분 |
| `RVSE_CNCL_DVSN_CD` | `'02'` | 정정취소구분(02=취소) |
| `ORD_QTY` | `'0'` | 주문수량(전량취소 시 0) |
| `ORD_UNPR` | `'0'` | 주문단가 |
| `QTY_ALL_ORD_YN` | `'Y'` | 잔량전부주문여부 |
| `KRX_FWDG_ORD_ORGNO` | 원주문 캡처값(조건부) | 한국거래소전송주문조직번호 |

`KRX_FWDG_ORD_ORGNO`(한국거래소전송주문조직번호)는 원주문별 값으로, 누락 시 mis-route/거절 위험이 있다. ante는 이 값을 다음 규칙으로 처리한다:

- **원천**: 원주문 접수(`order-cash`) 성공 응답 `output`의 동일 필드명 `KRX_FWDG_ORD_ORGNO`를 직접 캡처한다(공식 order-cash 결과 컬럼에 `ODNO`/`ORD_TMD`와 함께 정의). `inquire-psbl-rvsecncl` 조회의 `ord_gno_brno`(주문채번지점번호)는 동일성 미보장(오값 위험)이라 **사용하지 않는다**.
- **캐시 키 scope**: 어댑터 인스턴스(=계좌, `gateway._get_broker(account_id)`로 계좌별 분리) + 제출 KST 영업일(YYYYMMDD). KIS `odno`는 영업일 재사용이 가능하므로 영업일까지 키에 포함해 재사용 odno에 과거 조직번호를 붙이는 오값을 차단한다.
- **주입/생략**: `cancel_order`는 캐시 hit & 영업일 일치 시에만 `KRX_FWDG_ORD_ORGNO`를 주입한다. 캐시 miss(인메모리 미보존)·응답에 필드 없음·영업일 불일치 시에는 **필드를 생략**(기존 8필드 동작 유지)하고 debug 로그를 남긴다. 취소 경로에서 **추가 조회/네트워크 호출은 하지 않는다**(순수 dict 연산).
- **bounded / known-limitation**: 캐시는 `OrderedDict` + maxlen으로 무한 증가·stale 누적을 막는다. **in-process 한정**이라 재기동 시 캐시가 소실되며, 그 경우 miss로 처리되어 필드를 생략한다(추정값을 전송하지 않으므로 안전). cross-process/외부주문 취소의 원천 확보는 영속화(Option A) 또는 검증된 조회 원천을 별도 이슈로 다룬다.

> 출처: [KIS open-trading-api `order_rvsecncl.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_rvsecncl/order_rvsecncl.py) 및 공식 레거시/Postman PAPER 샘플(`VTTC0803U`/`TTTC0803U`에서 `KRX_FWDG_ORD_ORGNO`를 원주문별 값으로 전송). 취소 tr_id `0803U→0013U` 마이그레이션과 `EXCG_ID_DVSN_CD`는 별도 live-gated 이슈(#2346) 범위다.

### inquire-daily-ccld TR ID 매핑 (#2349)

주문/체결 이력 조회(`inquire-daily-ccld`, `get_order_history`)는 `is_paper` × **3개월 경계**(inner/before) 조합으로 아래 KIS 공식 현행 TR ID를 전송한다. **inquire-daily-ccld 한정**이며, order-cash·취소·잔고·현재가 등 다른 엔드포인트 TR ID는 이 표의 범위 밖이다.

| 구분 | 실전 | 모의 |
|------|------|------|
| 3개월 이내 (inner) | `TTTC0081R` | `VTTC0081R` |
| 3개월 이전 (before) | `CTSC9215R` | `VTSC9215R` |

- **3개월 경계 판정 (ante 로컬 normative 정책)**: 공식 예제는 `pd_dv=inner\|before`를 호출자 인자로 받을 뿐 경계를 계산하지 않으므로, ante가 경계 정책을 소유한다(공식 산식 미러 아님). **cutoff = KST 오늘 기준 달력 3개월 전 동일 일자**(예: KST 2026-06-11 → cutoff 2026-03-11). 대상 월에 동일 일자가 없으면 그 월 말일로 보정한다(예: 2026-05-31 → cutoff 2026-02-28). **판정은 `INQR_STRT_DT`(start-date) 단독 기준**: `>= cutoff`이면 inner(cutoff 당일 포함), `< cutoff`이면 before. 기본 `from_date`(now-7d)는 항상 inner다(레거시 `VTTC8001R`/`TTTC8001R` 단일 코드 대신 inner `0081R` 계열로 교체). 레거시 before `VTSC9115R`/`CTSC9115R`은 비채택이다.
- **교차 구간(`from < cutoff <= to`) bounded known-limitation**: cutoff를 가로지르는 창은 split query 없이 start-date 기준 before 단일 쿼리로 처리한다(완전성은 known-limitation). 현행 호출자(`FillReconcileScheduler`)는 항상 ≤7일 창이라 실제 운영 경로는 inner 고정이며, before 분기는 caller가 3개월 이전 `from_date`를 줄 때만 활성화된다.
- **`EXCG_ID_DVSN_CD`는 hard-required가 아님 (hygiene)**: 이 엔드포인트에서 `EXCG_ID_DVSN_CD`(`'KRX'`, 모듈 상수 `DEFAULT_EXCG_ID_DVSN_CD` 재사용)는 데이터 완전성/NXT 누락 방지를 위한 **optional hygiene**으로 주입한다. 공식 예제도 조건부 append이며 `ValueError` 가드가 없다. 이는 order-cash의 `40910000` 거절-fix(#2342/#2345)와 **다른 프레임**이다(거절-fix가 아닌 데이터 완전성 보강).
- **신 tr_id 효과**: 레거시 `VTTC8001R`은 모의 당일 체결을 반환하지 못하나(0행), 신 `VTTC0081R`은 당일 체결을 반환함이 #2317 라이브 A/B로 확인됐다(`docs/specs/broker-adapter/18-fill-recovery.md` §2.1).

> 출처: [KIS open-trading-api `inquire_daily_ccld.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py)(공식 예제가 inner/before별 4코드와 조건부 `EXCG_ID_DVSN_CD` append를 정의) + #2314 근본원인 조사 + #2317 라이브 측정.

### KIS 주문 유형 매핑

KISDomesticAdapter는 `order_type` 문자열을 KIS ORD_DVSN 코드로 매핑한다. `stop`/`stop_limit`이 전달되면 `ValueError`를 발생시킨다 (상위 계층에서 변환 후 호출해야 함).

| order_type | ORD_DVSN | 설명 |
|------------|----------|------|
| `'market'` | `'01'` | 시장가 |
| `'limit'` | `'00'` | 지정가 |
| `'conditional'` | `'02'` | 조건부지정가 |
| `'best'` | `'03'` | 최유리지정가 |
| `'priority'` | `'04'` | 최우선지정가 |

> KIS는 추가로 `05` 장전시간외, `06` 장후시간외, `07` 시간외단일가, `11`~`16` IOC/FOK 변형(실전투자 전용)을 지원한다.

**시장가 매수와 Treasury reserve estimate 분리 (#1333)**: 시장가 매수 시 KIS
주문 파라미터는 `ORD_DVSN="01"`, `ORD_UNPR="0"` 계약을 그대로 유지한다.
Treasury 가 reserve estimate 를 위해 `get_current_price` 로 현재가를 조회해
보수적으로 자금을 잠그더라도, 그 quote 는 reserve 산정 입력일 뿐이며 KIS 에
전달되는 주문 자체는 limit 으로 변환되지 않는다.

### KIS 주문 상태 코드 매핑

| KIS 상태 코드 | Ante 상태 | 설명 |
|--------------|----------|------|
| `'10'` | `'pending'` | 주문접수 |
| `'11'` | `'confirmed'` | 확인 |
| `'20'` | `'partial_filled'` | 일부체결 |
| `'30'` | `'filled'` | 전부체결 |
| `'40'` | `'cancelled'` | 취소 |
| `'50'` | `'rejected'` | 거부 |
