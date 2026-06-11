# Broker Adapter 모듈 세부 설계 - CommissionInfo

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)

# CommissionInfo

> 소스: `src/ante/broker/models.py`

```python
@dataclass(frozen=True)
class CommissionInfo:
    buy_commission_rate: float = 0.00015    # 매수 수수료율 (예: 0.015%)
    sell_commission_rate: float = 0.00195   # 매도 수수료율 (세금 포함, 예: 0.195%)

    def calculate(self, side: str, filled_value: float) -> float:
        """체결 금액 기반 수수료 계산.
        매수: filled_value × buy_commission_rate
        매도: filled_value × sell_commission_rate
        """
```

> **변경 이유**: 기존 `commission_rate + sell_tax_rate` 분리 방식은 국내주식 전용이었다. 해외주식은 매도 세금 구조가 다르므로, 매수/매도 총비용을 각각 단일 필드로 표현하여 시장에 무관하게 동일한 인터페이스를 제공한다.

### CircuitBreaker

> 소스: `src/ante/broker/circuit_breaker.py`

API 장애 시 연쇄 호출을 방지하는 서킷 브레이커. CLOSED → OPEN → HALF_OPEN 상태 머신.

| 메서드 | 설명 |
|--------|------|
| `check()` | OPEN이면 `CircuitOpenError` 발생 |
| `record_success()` | 성공 기록, HALF_OPEN → CLOSED 전환 |
| `record_failure()` | 실패 기록, 임계치 도달 시 OPEN 전환 |

상태 전환 시 `CircuitBreakerEvent`를 EventBus에 발행한다.

**공유 범위 (normative, #2350)**: 차단기는 **어댑터 인스턴스(=계좌)당 단일**
(`name="kis"`)이며, 주문·조회 모든 경로가 공유하는 `_request()`/`_request_with_cont()`
흐름에 통합된다. 이 단일 차단기는 주문 연쇄 호출 방지(주문 경로 보호)를 1차
목적으로 한다. 단일 인스턴스이므로 한 concern 의 실패 누적이 OPEN 을 유발하면 같은
어댑터의 다른 concern(잔고/포지션 조회, 주문 등)도 `check()` 단계에서 함께 차단된다
(blast radius 경계는 [15-reconciliation.md](15-reconciliation.md) §대사 참조).

**late-ccld TimeoutError 회계 제외 (normative, #2350)**: 체결이력 조회
(`get_order_history` → `inquire-daily-ccld`)의 `TimeoutError` 계열(aiohttp timeout
포함, `TimeoutError` 하위)은 **차단기 회계에 기록되지 않는다**(호출측 opt-out
`cb_exempt_timeout=True`). late-ccld 조회 타임아웃이 어댑터 전역 단일 차단기를
OPEN 시켜 무관한 treasury 잔고/포지션 동기화·주문 경로까지 broker-wide 로 차단하는
cross-concern 결합을 끊기 위함이다. 회계 제외는 **`get_order_history` 경로의
`TimeoutError` 에 한정**되며, HTTP 5xx/`APIError` 등 다른 실패는 기존대로 기록한다
(실제 KIS 서버 장애 보호 유지). 차단기 상태 머신·에러 분류(`KISErrorClassifier`)
자체는 무변경이고, `check()` 통과는 그대로라 다른 concern 이 연 차단기에는 종속한다.
체결 폴 루프의 steady-state cooldown 은 [18-fill-recovery.md](18-fill-recovery.md)
참조.

### 에러 코드 분류

> 소스: `src/ante/broker/error_codes.py`

KIS API 응답 코드를 영구 에러(재시도 불필요)와 일시 에러(재시도 필요)로 분류.

| 상수 | 설명 |
|------|------|
| `PERMANENT_MSG_CODES` | 재시도 불필요 코드 frozenset |
| `TRANSIENT_MSG_CODES` | 재시도 필요 코드 frozenset |
| `RETRYABLE_HTTP_STATUS_CODES` | 500, 502, 503, 429 |

### 에러 처리 및 재시도

KISBaseAdapter는 지수 백오프 방식의 재시도 로직을 내장한다. 인증 토큰 만료 감지 시 자동 재인증을 수행하며, 토큰 만료 5분 전에 선제적으로 재발급한다. 모든 API 응답에서 `rt_cd != '0'`이면 `APIError`를 발생시킨다. CircuitBreaker가 `_request()` 흐름에 통합되어, 연속 실패 시 자동으로 요청을 차단한다. 회계 판정은 `to_api_error()` 변환 **전 raw 예외** 기준이며, 재시도 루프에서 `record_failure` 분류이면서 호출측 `cb_exempt_timeout`+`TimeoutError` 조합이 아닐 때만 `record_failure()`를 호출한다(#2350). 단, **late-ccld(`get_order_history`) 경로의 `TimeoutError`는 차단기 회계에서 제외**된다(위 CircuitBreaker 절·[18-fill-recovery.md](18-fill-recovery.md) 참조).

**오퍼레이션별 기본값**:

| 설정 | config 키 | 기본값 | 설명 |
|------|-----------|--------|------|
| 주문 재시도 | `retry.max_retries_order` | 3 | 주문 API 최대 재시도 |
| 조회 재시도 | `retry.max_retries_query` | 2 | 조회 API 최대 재시도 |
| 인증 재시도 | `retry.max_retries_auth` | 2 | 인증 API 최대 재시도 |
| 백오프 기준 | `retry.backoff_base_seconds` | 1.0 | 지수 백오프 기본 대기 시간 |
| 주문 타임아웃 | `timeout.order` | 10초 | 주문 API 타임아웃 |
| 조회 타임아웃 | `timeout.query` | 5초 | 조회 API 타임아웃 |
| 인증 타임아웃 | `timeout.auth` | 10초 | 인증 API 타임아웃 |
| CB 실패 임계치 | `circuit_breaker.failure_threshold` | 5 | OPEN 전환까지 연속 실패 횟수 |
| CB 복구 대기 | `circuit_breaker.recovery_timeout` | 60 | OPEN → HALF_OPEN 대기 시간(초) |

### ~~실시간 스트리밍 — KISStreamClient~~ (스펙 아웃)

> **스펙 아웃**: 오픈 시점에는 실시간 WebSocket 스트리밍을 포함하지 않는다. `KISStreamClient` 및 관련 코드는 별도 스펙으로 재설계 시 반영한다.
