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
| 주문 파라미터 | `ORD_DVSN`, `PDNO` (6자리 종목코드) |
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

### KIS 주문 상태 코드 매핑

| KIS 상태 코드 | Ante 상태 | 설명 |
|--------------|----------|------|
| `'10'` | `'pending'` | 주문접수 |
| `'11'` | `'confirmed'` | 확인 |
| `'20'` | `'partial_filled'` | 일부체결 |
| `'30'` | `'filled'` | 전부체결 |
| `'40'` | `'cancelled'` | 취소 |
| `'50'` | `'rejected'` | 거부 |
