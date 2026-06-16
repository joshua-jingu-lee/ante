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
| 주문 취소·정정 (정정 v1=price-only, #2391) | `/uapi/domestic-stock/v1/trading/order-rvsecncl` | POST |
| 미체결 조회 | `/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl` | GET |
| 매수가능 조회 | `/uapi/domestic-stock/v1/trading/inquire-psbl-order` | GET |

> **매수가능 조회 행은 구현 #2384 merge 후 실행 가능**하다. 본 행은 계약(spec) 선반영이며, `inquire-balance`(잔고/평가/보유)와 `inquire-psbl-order`(주문가능)는 KIS가 공식적으로 분리한 두 엔드포인트다(아래 §inquire-psbl-order 계약 참조).

> **`order-rvsecncl`은 KIS API 레벨에서 정정·취소를 모두 지원**하며, Ante 어댑터는 **취소(`cancel_order`, `RVSE_CNCL_DVSN_CD='02'`)와 정정 v1(`modify_order`, `RVSE_CNCL_DVSN_CD='01'`, price-only, #2391)을 모두 구현**한다(아래 §order-rvsecncl 취소/정정 바디 계약 참조). 정정 v1은 `open` 주문의 가격 정정(수량 불변)만 지원하며, 수량 변경·예산증가 buy·부분체결/터미널·동시성 등 고급 케이스는 Gateway가 broker 호출 전 fail-closed로 거부한다(후속 #2393). **live A/B(실전 KIS) 정정 분기 검증은 사용자 oracle 후속(pending)** — 현재는 mock+모의 매핑/분기만 검증된 상태다.

### order-cash TR ID 매핑

주문 접수(`order-cash`) 호출 시 `place_order`는 `is_paper` × `side` 조합으로 아래 KIS 공식 현행 TR ID를 전송한다. **order-cash 한정**이며, 취소/정정(`order-rvsecncl`, `VTTC0013U`/`TTTC0013U`)·잔고·현재가 등 다른 TR ID는 이 표의 범위 밖이다.

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
- **`40910000` 인과 caveat**: 2026-06-11 KST 모의 smoke에서 #2342 TR ID 갱신 후에도 모의 매수가 `40910000 모의투자 주문이 불가한 계좌입니다`로 실패했다. 본 계약 정합이 그 실패의 직접 원인인지는 **미확정**이며, 머지 후 다음 거래일 모의 smoke(`buy 1 → fill/position → sell 1 → flatten`)로 검증한다. 지속 실패 시 계좌 자격/provisioning 가설은 별도 이슈로 분리한다(본 이슈는 contract drift 해소로 종결). 한편 `40910000`은 계좌 자격/모의 신청 상태 거절이라 재시도해도 결과가 동일하므로 PERMANENT(`is_retryable_msg_code → False`)로 분류한다(#2361: 3세션 일관 관측, 무익 재시도 차단).
- **비목표(`SLL_TYPE`/`CNDT_PRIC`)**: 공식 예제 바디에는 `SLL_TYPE`(매도유형)·`CNDT_PRIC`(조건가격)이 존재하나, 필수 `ValueError` 가드는 `EXCG_ID_DVSN_CD`에만 있고 거절 근거 관측이 없어 본 PR 비목표다. 추측성 빈 문자열 필드 추가는 행동 변화 위험만 있으므로 제외하며, 거절 근거가 관측되면 후속 이슈로 다룬다.

### order-rvsecncl 취소 바디 계약 (#2345, #2346)

주문 취소(`order-rvsecncl`, `cancel_order`)는 신세대 TR ID `VTTC0013U`(모의)/`TTTC0013U`(실전)로 아래 바디를 전송한다(레거시 `VTTC0803U`/`TTTC0803U`에서 마이그레이션 — #2346). 신세대 body는 `EXCG_ID_DVSN_CD`를 `[필수]`로 요구하며, 모듈 레벨 공유 상수 `DEFAULT_EXCG_ID_DVSN_CD="KRX"`로 주입한다(에픽 #2354 일관성 목표의 공유 단일 출처 — order-cash(#2344)·inquire-daily-ccld(#2349)와 동일 상수 재사용). **취소 한정**이며 정정(modify)·order-cash·잔고 등은 이 표의 범위 밖이다.

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
| `EXCG_ID_DVSN_CD` | `'KRX'` | 거래소ID구분코드(신세대 필수·국내 KRX 기본·NXT/SOR 미지원) |
| `KRX_FWDG_ORD_ORGNO` | 원주문 캡처값(조건부) | 한국거래소전송주문조직번호 |

`KRX_FWDG_ORD_ORGNO`(한국거래소전송주문조직번호)는 원주문별 값으로, 누락 시 mis-route/거절 위험이 있다. ante는 이 값을 다음 규칙으로 처리한다:

- **원천**: 원주문 접수(`order-cash`) 성공 응답 `output`의 동일 필드명 `KRX_FWDG_ORD_ORGNO`를 직접 캡처한다(공식 order-cash 결과 컬럼에 `ODNO`/`ORD_TMD`와 함께 정의). `inquire-psbl-rvsecncl` 조회의 `ord_gno_brno`(주문채번지점번호)는 동일성 미보장(오값 위험)이라 **사용하지 않는다**.
- **캐시 키 scope**: 어댑터 인스턴스(=계좌, `gateway._get_broker(account_id)`로 계좌별 분리) + 제출 KST 영업일(YYYYMMDD). KIS `odno`는 영업일 재사용이 가능하므로 영업일까지 키에 포함해 재사용 odno에 과거 조직번호를 붙이는 오값을 차단한다.
- **주입/생략**: `cancel_order`는 캐시 hit & 영업일 일치 시에만 `KRX_FWDG_ORD_ORGNO`를 주입한다. 캐시 miss(인메모리 미보존)·응답에 필드 없음·영업일 불일치 시에는 **필드를 생략**(고정 9필드 — 8필드 + `EXCG_ID_DVSN_CD`)하고 debug 로그를 남긴다. 취소 경로에서 **추가 조회/네트워크 호출은 하지 않는다**(순수 dict 연산).
- **신세대(0013U) 호환**: 2026-06-12 라이브 A/B에서 `VTTC0013U + EXCG_ID_DVSN_CD=KRX + KRX_FWDG_ORD_ORGNO`(cache-hit 경로)가 정상 접수(`40630000 취소 완료`)됨을 확인했다. 따라서 **cache-hit 경로의 신세대 정상 동작은 라이브 검증됨**이며, cache miss/stale 시 `KRX_FWDG_ORD_ORGNO` 생략은 기존 #2345 known-limitation을 그대로 유지한다(생략 시에도 신세대 0013U 자체는 정상 — '완전 호환' 단정이 아니라 cache-hit 정상 + miss/stale 기존 한계).
- **bounded / known-limitation**: 캐시는 `OrderedDict` + maxlen으로 무한 증가·stale 누적을 막는다. **in-process 한정**이라 재기동 시 캐시가 소실되며, 그 경우 miss로 처리되어 필드를 생략한다(추정값을 전송하지 않으므로 안전). cross-process/외부주문 취소의 원천 확보는 영속화(Option A) 또는 검증된 조회 원천을 별도 이슈로 다룬다.

> 출처: [KIS open-trading-api `order_rvsecncl.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/order_rvsecncl/order_rvsecncl.py)의 demo 분기가 `VTTC0013U`(실전 `TTTC0013U`)를 사용하고 신세대 body에서 `EXCG_ID_DVSN_CD`를 `[필수]`로 가드한다. `KRX_FWDG_ORD_ORGNO`는 레거시였던 `VTTC0803U`/`TTTC0803U` 시절부터 원주문별 값으로 전송하던 필드로, 신세대 0013U body에서도 동일하게 사용한다. 취소 tr_id `0803U→0013U` 마이그레이션과 `EXCG_ID_DVSN_CD` 동반은 2026-06-12 라이브 A/B(both_ok — (A) 레거시 `0803U` 정상 / (B) 신세대 `0013U + EXCG_ID_DVSN_CD=KRX` 정상)로 검증해 단일 신세대 경로를 채택했다(#2346 — 레거시 fallback 이중화는 YAGNI 기각).

### order-rvsecncl 정정 바디 계약 (#2391, v1=price-only)

주문 정정(`order-rvsecncl`, `modify_order`)은 취소와 **동일 엔드포인트**를 공유하며, 신세대 TR ID `VTTC0013U`(모의)/`TTTC0013U`(실전)로 아래 바디를 전송한다. 취소와의 유일한 의미 차이는 `RVSE_CNCL_DVSN_CD='01'`(정정)이며, **v1은 가격 정정(price-only)만** 지원한다(수량 불변).

| 필드 | 값 | 설명 |
|------|------|------|
| `CANO` | `account_no[:8]` | 종합계좌번호 |
| `ACNT_PRDT_CD` | `account_no[8:10]` | 계좌상품코드 |
| `KRX_FWDG_ORD_ORGNO` | 원주문 캡처값(필수) | 한국거래소전송주문조직번호 |
| `ORGN_ODNO` | `order_id` | 원주문번호(ODNO) |
| `ORD_DVSN` | `'00'` | 주문구분(`_map_order_type("limit")` — 지정가) |
| `RVSE_CNCL_DVSN_CD` | `'01'` | 정정취소구분(01=정정) |
| `ORD_QTY` | `str(int(quantity))` | 원주문 수량(불변 — Gateway가 `record.ordered_qty` 전달) |
| `ORD_UNPR` | `str(int(price))` | 신규 정정 가격(Gateway가 finite `price>0` 보장) |
| `QTY_ALL_ORD_YN` | `'Y'` | 잔량전부주문여부(전량·수량 불변) |
| `EXCG_ID_DVSN_CD` | `'KRX'` | 거래소ID구분코드(신세대 필수·국내 KRX 기본) |

- **`CNDT_PRIC`(조건가) 미전송**: v1 지정가 정정은 조건가를 사용하지 않는다.
- **`KRX_FWDG_ORD_ORGNO` fail-closed**: 정정은 취소와 달리 캐시 miss/영업일 불일치(stale) 시 필드를 생략하지 않고 **`ModifyOrgnoUnavailableError`를 raise해 전송을 차단**한다(오값 전송 금지). Gateway가 이를 `modify_orgno_unavailable` 거부 사유로 매핑한다. 캐시 원천·scope·bounded 규칙은 취소(§위)와 동일하다(`order-cash` 응답 캡처, 계좌+영업일 키, in-process 한정).
- **수량 불변 invariant**: v1은 `ORD_QTY`를 원주문 수량으로 고정하고 `QTY_ALL_ORD_YN='Y'`로 전량 유지한다. 수량 변경 정정은 Gateway가 broker 호출 전 `modify_qty_change_unsupported`로 거부(후속 #2393).
- **live A/B pending caveat**: 정정(`RVSE_CNCL_DVSN_CD='01'`) 분기의 실전 KIS A/B 검증은 **사용자 oracle 후속(pending)**이다. 현재는 mock+모의 매핑/분기(RVSE_CNCL_DVSN_CD='01'·ORD_UNPR·QTY_ALL_ORD_YN='Y'·orgno hit/miss typed error)만 검증됐다. tr_id·EXCG·KRX_FWDG 호환은 취소(0013U) 라이브 검증(2026-06-12)과 동일 패밀리이나, 정정 고유의 응답 코드(예: `40650000` 정정 완료)는 oracle에서 확인 예정이다.

### inquire-daily-ccld TR ID 매핑 (#2349)

주문/체결 이력 조회(`inquire-daily-ccld`, `get_order_history`)는 `is_paper` × **3개월 경계**(inner/before) 조합으로 아래 KIS 공식 현행 TR ID를 전송한다. **inquire-daily-ccld 한정**이며, order-cash·취소·잔고·현재가 등 다른 엔드포인트 TR ID는 이 표의 범위 밖이다.

| 구분 | 실전 | 모의 |
|------|------|------|
| 3개월 이내 (inner) | `TTTC0081R` | `VTTC0081R` |
| 3개월 이전 (before) | `CTSC9215R` | `VTSC9215R` |

- **3개월 경계 판정 (ante 로컬 normative 정책)**: 공식 예제는 `pd_dv=inner\|before`를 호출자 인자로 받을 뿐 경계를 계산하지 않으므로, ante가 경계 정책을 소유한다(공식 산식 미러 아님). **cutoff = KST 오늘 기준 달력 3개월 전 동일 일자**(예: KST 2026-06-11 → cutoff 2026-03-11). 대상 월에 동일 일자가 없으면 그 월 말일로 보정한다(예: 2026-05-31 → cutoff 2026-02-28). **판정은 `INQR_STRT_DT`(start-date) 단독 기준**: `>= cutoff`이면 inner(cutoff 당일 포함), `< cutoff`이면 before. 기본 `from_date`(now-7d)는 항상 inner다(레거시 `VTTC8001R`/`TTTC8001R` 단일 코드 대신 inner `0081R` 계열로 교체). 레거시 before `VTSC9115R`/`CTSC9115R`은 비채택이다.
- **교차 구간(`from < cutoff <= to`) bounded known-limitation**: cutoff를 가로지르는 창은 split query 없이 start-date 기준 before 단일 쿼리로 처리한다(완전성은 known-limitation). 현행 호출자(`FillReconcileScheduler`)는 항상 ≤7일 창이라 실제 운영 경로는 inner 고정이며, before 분기는 caller가 3개월 이전 `from_date`를 줄 때만 활성화된다.
- **`EXCG_ID_DVSN_CD`는 hard-required가 아님 (hygiene)**: 이 엔드포인트에서 `EXCG_ID_DVSN_CD`(`'KRX'`, 모듈 상수 `DEFAULT_EXCG_ID_DVSN_CD` 재사용)는 데이터 완전성/NXT 누락 방지를 위한 **optional hygiene**으로 주입한다. 공식 예제도 조건부 append이며 `ValueError` 가드가 없다. 이는 order-cash의 `40910000` 거절-fix(#2342/#2345)와 **다른 프레임**이다(거절-fix가 아닌 데이터 완전성 보강).
- **신 tr_id 효과 (모의 한정)**: 레거시 `VTTC8001R`은 모의 당일 체결을 반환하지 못하나(0행), 신 `VTTC0081R`은 **모의** 당일 체결을 반환함이 모의 라이브(#2317 A/B + #2353 측정)로 확인됐다 — **모의 한정 관측이며 KIS 공식 보증이 아니다**. 실전 `TTTC0081R`의 당일 반영은 **미검증**이며, KIS 공식 일별 원장 지연 경고는 tr_id 세대 무관 잔존한다(`docs/specs/broker-adapter/18-fill-recovery.md` §2.1/§11.6/§11.7).

> 출처: [KIS open-trading-api `inquire_daily_ccld.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_daily_ccld/inquire_daily_ccld.py)(공식 예제가 inner/before별 4코드와 조건부 `EXCG_ID_DVSN_CD` append를 정의) + #2314 근본원인 조사 + #2317 라이브 측정.

### inquire-psbl-order TR ID·바디·응답 계약 (#2384)

매수가능 조회(`inquire-psbl-order`, `get_buyable`)는 `is_paper` 조합으로 아래 KIS 공식 현행 TR ID를 전송한다. **inquire-psbl-order 한정**이며, order-cash·취소·inquire-balance·현재가 등 다른 엔드포인트 TR ID는 이 표의 범위 밖이다. 본 계약은 **구현 #2384 merge 후 실행 가능**하다.

| 환경 | TR ID |
|------|-------|
| 모의 | `VTTC8908R` |
| 실전 | `TTTC8908R` |

**요청 파라미터**(GET query):

| 필드 | 값 | 설명 |
|------|------|------|
| `CANO` | `account_no[:8]` | 종합계좌번호 |
| `ACNT_PRDT_CD` | `account_no[8:10]` | 계좌상품코드 |
| `PDNO` | `normalize_symbol(symbol)` (6자리) | 종목코드 |
| `ORD_UNPR` | **실가(필수, '0' 아님)**: 시장가/`price=None`이면 대표종목 현재가(`get_current_price(symbol)` 1회 조회)를 단가로 사용 / 지정가 `str(int(price))` — KIS 공식 샘플 확정 | 주문단가 |
| `ORD_DVSN` | `order_type` 매핑(`_map_order_type` 재사용, 시장가 → **`'01'`**) — KIS 공식 샘플 확정 | 주문구분 |
| `CMA_EVLU_AMT_ICLD_YN` | `'N'` | CMA평가금액포함여부 |
| `OVRS_ICLD_YN` | `'N'` | 해외포함여부 |

**응답 필드 → `get_buyable()` 반환 dict 키 매핑**(전부 float):

| 응답 필드 | dict 키 | 설명 |
|-----------|---------|------|
| `nrcvb_buy_amt` | `order_buyable_amount` | 미수 미사용 매수가능금액(계좌 현금 기반, **purchasable_amount SSOT — 보수값**) |
| `max_buy_amt` | `max_buyable_amount` | 미수 포함 최대 매수가능금액 |
| `ord_psbl_cash` | `order_cash` | 주문가능현금(종목 의존성 최소 — 종목무관 폴백 SSOT 후보) |
| `nrcvb_buy_qty` | `order_buyable_qty` | 미수 미사용 매수가능수량(**종목/단가 의존** — 시장가 probe에서는 계좌수준 의미 없음) |
| `max_buy_qty` | `max_buyable_qty` | 최대 매수가능수량(**종목/단가 의존** — 동일) |

- **계좌 대표 매수가능액 입력 규약**: 계좌 대표 매수가능액은 종목 무관한 미수없는 매수가능금액(`nrcvb_buy_amt`)을 얻기 위한 probe다. 대표 종목은 항시 거래되는 유효 국내 종목 코드(기본 하드코딩 `005930`, config override는 구현 옵션)를 시장가(`ORD_DVSN='01'`, `ORD_UNPR=대표종목 현재가` — KIS 공식 샘플 확정, '0' 아님)로 전송한다. 시장가 probe 시 `get_buyable`은 `get_current_price(symbol)`를 1회 호출해 `ORD_UNPR`로 사용한다(Treasury 등 호출처에 별도 현재가 조회를 추가하지 않는다). 시장가 probe 호출에서 반환되는 종목/단가 의존 수량 값(`order_buyable_qty`/`max_buyable_qty`)은 '대표종목을 현재가로 살 때의 수량'이라는 **종목 종속 값이라 계좌수준 의미가 없다**. Treasury 동기화 경로는 금액 필드(`order_buyable_amount`)만 소비하고 수량 필드는 계좌 대표 컨텍스트에서 소비·영속화하지 않는다.
- **종목무관 전제 — bounded assumption + 검증 게이트**: `nrcvb_buy_amt`가 종목/단가 무관한 계좌수준 현금값이라는 전제는 본 계약의 load-bearing 가정이나, #2384 모의 단일 실측(`nrcvb_buy_amt=9998235.0`, `nrcvb_buy_qty=59.0`)만으로는 종목 불변성을 입증하지 못한다. 라이브 검증 전 **bounded assumption**으로 lock하며, **구현 전 모의 다종목 A/B 검증 게이트**(고가 `005930` vs 저가주, `ORD_UNPR='0'` vs 지정가)로 `nrcvb_buy_amt`/`ord_psbl_cash`의 종목 불변성을 확인한다. 검증 실패(종목별 상이) 시 `purchasable_amount` SSOT를 `ord_psbl_cash`(주문가능현금, 종목 의존성 최소)로 폴백한다(known-limitation 사전 선언).
- **ORD_DVSN/ORD_UNPR 고정 — 공식 샘플 확정**: KIS 공식 샘플(`inquire_psbl_order.py`)이 `pdno="005930"`, `ord_unpr="55000"`, `ord_dvsn="01"`로 호출한다. 따라서 inquire-psbl-order 시장가 probe는 `ORD_DVSN='01'`(order-cash `_map_order_type`('market'→'01') 재사용)이며 `ORD_UNPR`은 실제 1주당 가격이다('0'/빈값 아님). 시장가/`price=None`이면 `get_current_price(symbol)`로 조회한 현재가를 `ORD_UNPR`로 전달한다. 남은 경험적 항목(`nrcvb_buy_amt` 종목 불변성)은 구현 후 oracle A/B 검증 대기(검증 실패 시 `ord_psbl_cash` 폴백 — 코드의 필드 SSOT 상수 한 곳 교체).
- **Rate-limit 분리(모의 5req/min)**: 매수가능 조회는 잔고조회(`get_account_balance`)·포지션조회(`get_positions`)와 **별도 메서드로 분리**해 호출 빈도를 호출처가 독립 제어한다. Treasury Live 동기화는 cycle당 1회만 호출한다(04-treasury-interface 참조). 단기 TTL 캐시는 허용하며 TTL 값은 구현 결정(bounded known-limitation).
- **`psbl_sbst_amt`(대용가능금액)와의 구분**: 기존 `inquire-balance`의 `psbl_sbst_amt`(예수금 대용가능금액 = 대용증권 평가 기반)는 현금-only 모의계좌에서 정상적으로 0이며 주문가능액과 의미가 다르다. 이는 `get_account_balance()`의 별도 키 `substitute_amount`로 보존하고 `purchasable_amount`로 덮어쓰지 않는다(04-broker-adapter-interface 참조). 실전 대용증권 보유 계좌는 `psbl_sbst_amt>0`일 수 있어 별도 키 보존이 의미를 가진다.
- **결제일(T+2) 비반영**: 본 계약은 `account/11-scope-out.md:11`의 결제일 반영 매수가능금액을 **포함하지 않는다**. 결제일 미반영 단순 주문가능액(`nrcvb_buy_amt`)만 노출한다.

> 출처: [KIS open-trading-api `inquire_psbl_order.py`](https://github.com/koreainvestment/open-trading-api/blob/main/examples_llm/domestic_stock/inquire_psbl_order/inquire_psbl_order.py) — 매수가능조회[v1_국내주식-007]. `nrcvb_buy_amt`(미수 미사용 매수가능금액)·`max_buy_amt`(최대)·요청 파라미터(CANO/ACNT_PRDT_CD/PDNO/ORD_UNPR/ORD_DVSN/CMA_EVLU_AMT_ICLD_YN/OVRS_ICLD_YN) 확인. **공식 샘플이 `pdno="005930"`, `ord_unpr="55000"`, `ord_dvsn="01"`로 호출하므로 시장가 probe의 `ORD_DVSN='01'` + `ORD_UNPR=실가(대표종목 현재가)`를 확정한다('0'/빈값 아님)** — 잠정 `ORD_UNPR='0'` 문구를 supersede(#2384 G0). + 이슈 #2384 KIS 모의 direct preflight 실측 1건(`nrcvb_buy_amt=9998235.0`, `nrcvb_buy_qty=59.0` — 단일종목 단일관측, 종목무관성 미입증). **남은 경험적 항목인 `nrcvb_buy_amt` 종목 불변성은 구현 후 사용자 oracle A/B로 검증**한다(검증 실패 시 `ord_psbl_cash` 폴백).

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
