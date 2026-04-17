# API Gateway 모듈 세부 설계

> ⚠️ 이 문서는 설계 의도와 인터페이스 계약을 기술합니다. 구현 코드는 `src/ante/gateway/` 를 참조하세요.

> 참조: [architecture.md](../../architecture/README.md) API 관리, [broker-adapter.md](../broker-adapter/broker-adapter.md) BrokerAdapter 인터페이스, [account.md](../account/account.md) Account 모델

## 개요

API Gateway는 **증권사 API 호출을 중앙에서 관리하는 요청 중개 계층**이다.
복수 봇이 같은 증권사 API를 호출할 때, rate limit 준수·요청 캐싱·큐잉을 통해
API 호출을 최적화하고 안정적인 거래 실행을 보장한다.

Account 모델 도입에 따라, 단일 BrokerAdapter가 아닌 **AccountService를 통해 계좌별 BrokerAdapter를 라우팅**한다. 모든 주문·조회 요청은 `account_id`를 기반으로 올바른 브로커 인스턴스를 선택한다.

**주요 기능**:
- **Rate Limiter**: 계좌(어댑터)별 호출 제한 준수 (KIS: 분당 20회 실전, 초당 5회 모의)
- **Request Queue**: 복수 봇의 요청을 중앙 큐에서 스케줄링
- **Response Cache**: 계좌별 네임스페이스로 동일 데이터 요청 중복 호출 방지 (시세 데이터 등)
- **요청 우선순위**: 주문 > 잔고 조회 > 시세 조회 순서
- **계좌별 라우팅**: `account_id` 기반 BrokerAdapter 선택

## 설계 결정

### Rate Limiter

> 소스: [`src/ante/gateway/rate_limiter.py`](../../../src/ante/gateway/rate_limiter.py)

슬라이딩 윈도우 기반 토큰 버킷 방식. `asyncio.Lock`으로 복수 봇의 동시 요청을 직렬화한다. **계좌(어댑터) 단위로 독립 인스턴스를 유지**하여, KIS 국내와 해외 등 서로 다른 rate limit 정책을 안전하게 분리한다.

| 클래스 | 메서드 | 설명 |
|--------|--------|------|
| `RateLimitConfig` | — | `max_requests: int`, `window_seconds: float` |
| `RateLimiter` | `acquire()` | 요청 슬롯 확보. 제한 초과 시 대기 |

**계좌별 Rate Limiter 조회**:

```python
def _get_rate_limiter(self, account_id: str) -> RateLimiter:
    if account_id not in self._rate_limiters:
        broker = self._account_service.get_broker(account_id)
        self._rate_limiters[account_id] = broker.rate_limiter
    return self._rate_limiters[account_id]
```

**근거**:
- 슬라이딩 윈도우 방식으로 정확한 rate limit 준수
- asyncio.Lock으로 복수 봇의 동시 요청 직렬화
- KIS 실전(분당 20회)과 모의(초당 5회)에 동일 로직 적용
- 계좌별 독립 rate limiter로 서로 다른 증권사/시장의 제한 정책 분리

### Request Queue — 우선순위 기반 요청 스케줄링

> 소스: [`src/ante/gateway/queue.py`](../../../src/ante/gateway/queue.py)

`asyncio.PriorityQueue` 기반. 동일 우선순위 시 FIFO 보장.

**요청 우선순위 (`RequestPriority`)**:

| 값 | 이름 | 설명 |
|----|------|------|
| 0 | `ORDER` | 주문 (최우선) |
| 1 | `ORDER_CANCEL` | 주문 취소 |
| 10 | `BALANCE` | 잔고/포지션 조회 |
| 20 | `PRICE` | 시세 조회 |
| 30 | `HISTORY` | 이력 조회 |

**APIRequest 핵심 필드**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `priority` | `RequestPriority` | 요청 우선순위 |
| `method` | `str` | `"GET"` / `"POST"` |
| `endpoint` | `str` | API 엔드포인트 경로 |
| `params` | `dict \| None` | 쿼리 파라미터 |
| `data` | `dict \| None` | 요청 바디 |
| `requester_id` | `str` | bot_id 또는 모듈명 |
| `future` | `asyncio.Future` | 응답 전달용 |

| 클래스 | 메서드 | 설명 |
|--------|--------|------|
| `RequestQueue` | `put(request) → Future` | 요청을 큐에 추가, Future 반환 |
| `RequestQueue` | `get() → APIRequest` | 우선순위 순으로 요청 꺼내기 |

### Response Cache — 동일 요청 중복 호출 방지

> 소스: [`src/ante/gateway/cache.py`](../../../src/ante/gateway/cache.py)

TTL 기반 응답 캐시. 동일 시세 조회 등 중복 API 호출을 방지한다. **캐시 키에 `account_id`를 네임스페이스로 포함**하여 계좌별로 캐시를 분리한다.

**캐시 키 형식**: `{account_id}:{endpoint}:{symbol}` (예: `acc-001:price:005930`)

**엔드포인트별 기본 TTL**:

| 엔드포인트 | TTL (초) | 설명 |
|-----------|----------|------|
| `price` | 5 | 현재가 |
| `ohlcv` | 60 | OHLCV 봉 데이터 |
| `balance` | 30 | 잔고 |
| `positions` | 30 | 포지션 |

| 클래스 | 메서드 | 설명 |
|--------|--------|------|
| `ResponseCache` | `get(key) → Any \| None` | 캐시 조회. 만료 시 None |
| `ResponseCache` | `set(key, data, ttl)` | 캐시 저장 |
| `ResponseCache` | `make_key(endpoint, params)` | 요청을 캐시 키로 변환 |
| `ResponseCache` | `invalidate(pattern)` | 패턴 매칭 캐시 무효화. 빈 문자열이면 전체 초기화 |

**근거 — 복수 봇 동일 종목 모니터링 시나리오**:
- 봇A와 봇B가 같은 종목 시세를 요청 → 캐시 TTL(5초) 내 1회만 API 호출
- 주문/체결은 캐싱하지 않음 (항상 최신 상태 필요)
- 잔고/포지션은 30초 캐싱 — 체결 이벤트 수신 시 해당 account_id 범위 내 `invalidate()` 호출
- 계좌별 네임스페이스로 서로 다른 계좌의 시세·잔고 캐시가 충돌하지 않음

### APIGateway — 통합 게이트웨이 클래스

> 소스: [`src/ante/gateway/gateway.py`](../../../src/ante/gateway/gateway.py)

증권사 API 호출 중앙 관리. `AccountService`, `EventBus`, `RateLimiter`, `ResponseCache`를 조합한다. 생성 시 `StopOrderManager`를 선택적으로 주입하여 stop/stop_limit 주문을 라우팅한다.

**생성자 파라미터**:
- `account_service: AccountService` — 계좌 서비스 (계좌별 BrokerAdapter 조회)
- `eventbus: EventBus` — 이벤트 버스
- `rate_config: RateLimitConfig | None` — rate limit 설정 (기본: max_requests=20, window_seconds=60)
- `stop_order_manager: Any | None` — 스탑 주문 매니저 (선택)

**브로커 라우팅**:

```python
def _get_broker(self, account_id: str) -> BrokerAdapter:
    return self._account_service.get_broker(account_id)
```

**공개 메서드**:

| 메서드 | 설명 |
|--------|------|
| `start()` | 이벤트 구독 시작 |
| `stop()` | 중지 |
| `get_current_price(symbol, account_id) → float` | 현재가 조회 (캐시 TTL 5초). account_id로 브로커 라우팅 |
| `get_positions(account_id) → list[dict]` | 포지션 조회 (캐시 TTL 30초). account_id로 브로커 라우팅 |
| `get_account_balance(account_id) → dict[str, float]` | 잔고 조회 (캐시 TTL 30초). account_id로 브로커 라우팅 |
| `submit_order(bot_id, symbol, side, quantity, order_type, price, account_id) → str` | 주문 제출. 캐시 미사용, rate limit만 적용 |
| `cancel_order(order_id, account_id) → bool` | 주문 취소. account_id로 브로커 라우팅 |

**주문 처리 라우팅**: `OrderApprovedEvent` 수신 시 `event.account_id`로 올바른 BrokerAdapter를 조회한 뒤 주문을 실행한다.

```python
async def _on_order_approved(self, event: OrderApprovedEvent) -> None:
    broker = self._get_broker(event.account_id)
    rate_limiter = self._get_rate_limiter(event.account_id)
    await rate_limiter.acquire()
    order_id = await broker.place_order(...)
```

**취소/정정 설계 근거**: 취소·정정은 리스크를 줄이는 행위이므로 RuleEngine 경유 불필요. `OrderCancelEvent`, `OrderModifyEvent` 수신 시 `event.account_id`로 브로커를 선택하여 직접 전달.

**Stop Order 라우팅**: `OrderApprovedEvent`의 `order_type`이 `stop` 또는 `stop_limit`이면 `StopOrderManager.register()`로 라우팅한다. `StopOrderManager`가 설정되지 않은 상태에서는 일반 주문으로 처리.

### 이벤트 연동

**구독하는 이벤트**:

| 이벤트 | 설명 |
|--------|------|
| `OrderApprovedEvent` | Treasury 자금 확보 후 주문 실행. `event.account_id`로 브로커 라우팅 |
| `OrderCancelEvent` | 주문 취소 요청 → `event.account_id`로 브로커 선택 후 전달 (룰 검증 생략) |
| `OrderModifyEvent` | 주문 정정 요청 → `event.account_id`로 브로커 선택 후 전달 (룰 검증 생략) |
| `OrderFilledEvent` | 체결 시 해당 `account_id` 범위 내 캐시 무효화 (`{account_id}:balance`, `{account_id}:positions`, `{account_id}:price:{symbol}`) |

**발행하는 이벤트**:

| 이벤트 | 설명 |
|--------|------|
| `OrderSubmittedEvent` | 증권사에 주문 전송 완료 |
| `OrderFailedEvent` | 주문 제출 실패 또는 스탑 주문 등록 실패 |
| `OrderCancelledEvent` | 주문 취소 완료 |
| `OrderCancelFailedEvent` | 주문 취소 실패 |

## DataProvider — 전략에 노출되는 데이터 접근 계층

> 소스: [`src/ante/gateway/data_provider.py`](../../../src/ante/gateway/data_provider.py)

StrategyContext에 주입되어 전략이 데이터를 조회할 때 사용.
내부적으로 APIGateway의 캐시를 활용하여 중복 API 호출 방지. `account_id`를 기반으로 올바른 브로커를 통해 데이터를 조회한다.

| 클래스 | 메서드 | 설명 |
|--------|--------|------|
| `LiveDataProvider` | `get_current_price(symbol) → float` | 현재가 조회 (APIGateway 캐시 활용, account_id 기반 라우팅) |
| `LiveDataProvider` | `get_ohlcv(symbol, timeframe, limit) → list[dict]` | OHLCV 데이터 조회 (추후 DataPipeline 연동 시 확장, 현재 빈 리스트 반환) |
| `LiveDataProvider` | `get_indicator(symbol, indicator, params) → dict[str, Any]` | 기술 지표 계산 (추후 구현, 현재 빈 dict 반환) |

> 파일 구조: [docs/architecture/generated/project-structure.md](../../architecture/generated/project-structure.md) 참조

## StopOrderManager — 스탑 주문 에뮬레이션

> 소스: [`src/ante/gateway/stop_order.py`](../../../src/ante/gateway/stop_order.py)

KRX는 네이티브 스탑 주문을 지원하지 않으므로, 실시간 시세를 모니터링하여 트리거 조건 충족 시 시장가/지정가 주문으로 변환한다. `account_id`를 추적하여 계좌별로 스탑 주문을 관리한다.

**StopOrder 데이터 구조**:

| 필드 | 타입 | 설명 |
|------|------|------|
| `stop_order_id` | `str` | 스탑 주문 고유 ID (`stop-{uuid12}`) |
| `order_id` | `str` | 원본 주문 ID |
| `account_id` | `str` | 계좌 ID |
| `bot_id` | `str` | 봇 ID |
| `strategy_id` | `str` | 전략 ID |
| `symbol` | `str` | 종목코드 |
| `side` | `str` | `"buy"` / `"sell"` |
| `quantity` | `float` | 수량 |
| `order_type` | `str` | `"stop"` / `"stop_limit"` |
| `stop_price` | `float` | 트리거 가격 |
| `limit_price` | `float \| None` | stop_limit 시 지정가 |
| `trading_session` | `str` | `"regular"` / `"extended"` |
| `exchange` | `str` | 거래소 코드 (기본 `"KRX"`) |

**공개 메서드**:

| 메서드 | 설명 |
|--------|------|
| `start()` | 매니저 시작 |
| `stop()` | 매니저 중지 (활성 주문 모두 만료 처리) |
| `register(order_id, account_id, bot_id, ...) → str` | 스탑 주문 등록, stop_order_id 반환. account_id 필수 |
| `cancel(stop_order_id) → bool` | 스탑 주문 취소 |
| `get_order(stop_order_id) → StopOrder \| None` | 스탑 주문 조회 |
| `get_orders_for_bot(bot_id) → list[StopOrder]` | 봇의 활성 스탑 주문 목록 |
| `get_orders_for_account(account_id) → list[StopOrder]` | 계좌의 활성 스탑 주문 목록 |
| `on_price_update(symbol, price)` | 실시간 시세 수신 시 트리거 판단 |
| `check_session_expiry()` | 세션 종료 시 미트리거 주문 만료 처리 |

**트리거 조건**:
- 매수 스탑: 현재가 >= stop_price
- 매도 스탑: 현재가 <= stop_price

**주문 변환**: stop → market, stop_limit → limit (limit_price 사용)

**세션 관리**: 정규 세션(09:00-15:30 KST), 확장 세션(08:30-18:00 KST). 세션 외 시간에는 트리거하지 않음.

**발행 이벤트**: `StopOrderRegisteredEvent`, `StopOrderTriggeredEvent`, `StopOrderExpiredEvent`. 트리거 시 변환된 `OrderRequestEvent`를 발행하여 기존 주문 흐름에 주입.

## 실시간 시세 연동 (stream_integration)

> 소스: [`src/ante/gateway/stream_integration.py`](../../../src/ante/gateway/stream_integration.py)

KISStreamClient로부터 수신된 실시간 시세를 ResponseCache에 반영한다. 캐시 키는 `account_id` 기반 네임스페이스를 사용한다.

```python
# 기존: cache_key = f"price:KRX:{symbol}" (하드코딩)
# 변경: cache_key = f"{account_id}:price:{symbol}" (account_id 기반)
```

## 타 모듈 설계 시 참고

- **Bot 스펙**: DataProviderFactory.create_live()가 LiveDataProvider 생성
- **Backtest 스펙**: BacktestDataProvider는 APIGateway를 거치지 않고 Parquet 직접 읽기
- **Data Pipeline 스펙**: 수집된 데이터를 Parquet에 적재하는 별도 경로
