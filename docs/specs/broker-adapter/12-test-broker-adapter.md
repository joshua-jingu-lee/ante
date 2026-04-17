# Broker Adapter 모듈 세부 설계 - TestBrokerAdapter — 개발/검증용 테스트 브로커

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# TestBrokerAdapter — 개발/검증용 테스트 브로커

> 소스: [`src/ante/broker/test.py`](../../../src/ante/broker/test.py)

KIS 실전 API 없이 시스템 전체 흐름을 검증할 수 있는 테스트 브로커. GBM(Geometric Brownian Motion) 기반 현실적 가격 시뮬레이션, 슬리피지, 부분 체결을 지원하며, 시드 기반으로 동일한 시나리오를 재현할 수 있다.

`exchange`, `currency`는 config에서 수신하며, 다양한 시장 환경을 시뮬레이션할 수 있다.

```python
class TestBrokerAdapter(BrokerAdapter):
    broker_id = "test"
    broker_name = "테스트 브로커"
    broker_short_name = "TEST"
```

### MockBrokerAdapter와의 차이

| 특성 | TestBrokerAdapter | MockBrokerAdapter |
|------|-------------------|-------------------|
| **용도** | 개발/검증 (현실적 시뮬레이션) | E2E 테스트 (제어 가능한 체결) |
| **가격** | GBM 기반 랜덤 시뮬레이션 | 정적 가격 (수동 설정) |
| **슬리피지** | 0.1~0.3% 자동 적용 | 없음 |
| **부분 체결** | 확률적 (수량 ≥ 100 시 30% 확률) | FillMode enum으로 결정적 제어 |
| **종목** | 가상 종목 6개 프리셋 | 하드코딩 2개 |
| **재현성** | 시드 기반 동일 시퀀스 | 시드 불필요 |

### 생성자 파라미터

| 파라미터 | 타입 | 기본값 | 설명 |
|----------|------|--------|------|
| `seed` | int | 42 | 시뮬레이션 시드 (재현 가능한 결과) |
| `initial_cash` | float | 100,000,000 | 초기 계좌 잔고 |
| `tick_interval` | float | 1.0 | 스트리밍 가격 갱신 간격 (초) |
| `exchange` | str | `"TEST"` | 거래소 코드 (config에서 수신) |
| `currency` | str | `"KRW"` | 통화 코드 (config에서 수신) |

### PriceSimulator — GBM 기반 가격 시뮬레이션

> 소스: [`src/ante/broker/test.py`](../../../src/ante/broker/test.py) `PriceSimulator` 클래스

GBM 모델로 현실적 가격 변동을 시뮬레이션한다. 일별 변동성을 틱 단위로 변환(`σ_tick = σ_daily / √23,400`)하고, exchange에 따라 호가 단위를 분기한다.

**가상 종목 프리셋** (`VIRTUAL_STOCK_PRESETS`):

| 종목코드 | 종목명 | 기준가 | 일변동성 |
|----------|--------|--------|----------|
| 000001 | 알파전자 | 72,000 | 1.8% |
| 000002 | 베타반도체 | 160,000 | 2.5% |
| 000003 | 감마소프트 | 210,000 | 2.2% |
| 000004 | 델타플랫폼 | 48,000 | 2.8% |
| 000005 | 엡실론모터스 | 230,000 | 1.5% |
| 000006 | 제타에너지 | 390,000 | 2.0% |

### 체결 시뮬레이션

- **시장가 주문**: 슬리피지 0.1~0.3% 자동 적용 (매수 시 가격 상승, 매도 시 가격 하락)
- **지정가 주문**: 슬리피지 없이 지정 가격으로 체결
- **부분 체결**: 수량 100주 이상 시 30% 확률로 발생 (체결 비율 30~90%)
- **잔고 부족**: 매수 시 잔고 부족이면 주문 거부
