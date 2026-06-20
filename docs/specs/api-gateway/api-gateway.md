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

**주문 처리 라우팅**: `OrderApprovedEvent` 수신 시 `event.account_id`로 올바른 BrokerAdapter를 조회한 뒤 주문을 실행한다. 단 **LIVE 계좌만** broker.place_order 경로를 탄다(아래 "Virtual 주문 라우팅" 참조).

```python
async def _on_order_approved(self, event: OrderApprovedEvent) -> None:
    broker = self._get_broker(event.account_id)
    rate_limiter = self._get_rate_limiter(event.account_id)
    await rate_limiter.acquire()
    order_id = await broker.place_order(...)
```

### Virtual 주문 라우팅 — broker 미경유 (#2396 R1, normative)

> 계약 확정: #2396. 라우팅 정합 구현은 #2398(축 ii). 본 절은 스펙 계약만 정의한다.

가상(`trading_mode=VIRTUAL`) 계좌 주문은 **`VirtualExecutor`**(`src/ante/bot/providers/virtual.py`)가 `OrderApprovedEvent`를 priority=50으로 구독해 **즉시 가상 체결**한다(`broker.place_order` 미경유). APIGateway는 **LIVE 계좌만** broker.place_order를 호출하고, virtual은 `VirtualExecutor` 경로로 처리되어야 한다.

- **`_on_order_approved`는 `trading_mode != LIVE`이면 직접 `broker.place_order` 실행만 deterministic하게 skip한다**(account_service에서 trading_mode 조회). EventBus 동일 priority(=50) 구독순서에 의존하는 'VirtualExecutor consume' 방식은 **금지**(APIGateway가 먼저 등록되면 consume marker 전에 `place_order` 호출되는 race로 `kis-domestic+virtual` 회귀 락이 깨짐). **단 skip은 일반 주문의 `broker.place_order` 경로에만 적용하고, stop/stop_limit 주문의 StopOrderManager 등록 분기는 보존한다** — virtual stop/stop_limit은 VirtualExecutor가 즉시체결하지 않고 StopOrderManager로 등록되어야 trigger 가능하므로(트리거 시 변환 OrderRequestEvent가 계층1 재평가), non-LIVE를 `_on_order_approved` 초입에서 통째 skip하면 어느 핸들러에도 등록되지 않는 회귀가 생긴다. 현 gateway가 virtual approval도 `place_order`를 호출하는 불일치를 이 skip으로 해소한다(#2398 요구).
- 이 라우팅 덕분에 runtime readiness 면제 매트릭스([account/02-design-decisions.md — D-ACC-09](../account/02-design-decisions.md#d-acc-09-runtime-readiness-축은-accountstatus와-직교한다))에서 virtual의 broker / fill / reconcile 면제가 정합적이다 — 가상 체결은 broker backstop이 불요하다.
- **#2398 회귀 락**: `kis-domestic + virtual` 주문이 `broker.place_order`를 미호출함을 회귀 테스트로 보장한다.
- **virtual 시장가 가격 안전(#2398)**: `VirtualExecutor`의 시장가 체결가는 `APIGateway.get_current_price()`(broker 의존)로 조회하며 `OrderApprovedEvent.price`는 시장가 매수에서 `None`이다. broker 장애 중 가격 조회 실패가 `event.price or 0.0` 폴백으로 **0원 체결**되지 않도록, 가격 조회 실패 시 **`OrderFailedEvent`(bot_id/order_id/account_id 보존)로 종결한다(0원 체결 금지)** — 이 지점은 `OrderApprovedEvent` 이후라 시장가 매수 reserve가 잡혀 있을 수 있고 Treasury는 reserve를 **`OrderFailedEvent`로만** 해제하므로, `OrderRejectedEvent`/예외로 끝내면 reserve가 고착된다(계층3 정합과 동일). virtual broker_ready 면제는 이 가격 안전 요구와 짝을 이룬다.
- **virtual SUSPENDED in-flight 최종 backstop(#2398 attempt5 P2)**: APIGateway가 virtual 주문을 **silent skip**하므로, 계층3 gateway의 `account_suspended` in-flight 재확인은 **virtual 주문에 도달하지 않는다**. 따라서 virtual 경로의 SUSPENDED in-flight 차단 **최종 backstop은 `VirtualExecutor`**다(LIVE 경로는 계층3 gateway — 경로별 비대칭, [account/02-design-decisions.md — D-ACC-09 §8](../account/02-design-decisions.md#8-accountstatussuspended와-직교-normative) "final backstop은 경로별로 비대칭" 참조). `VirtualExecutor`는 `apply_fill`/`OrderFilledEvent` **직전**, 기존 G9 readiness 차단과 **동일 지점·동일 단일 fetch**에서 **status(SUSPENDED)도 함께** 재확인한다 — verified SUSPENDED → `account_suspended`, `STATUS_UNAVAILABLE`(소스 present + 조회 예외/미상) → `account_status_unavailable` fail-closed, `None`(account_service 미구성)/verified non-SUSPENDED → status 축 통과. 차단 시 `OrderFailedEvent`(reserve 정확 해제, G3) + G6 운영자 알림 1회로 종결하며 0원 체결은 발생하지 않는다(G8). status 3-state 도출은 계층1·계층3와 **동일 공유 헬퍼**(`ante.account.gate.derive_account_status`)를 쓴다(SSOT).

**취소/정정 설계 근거**: 취소는 리스크를 줄이는 행위이므로 RuleEngine 경유 불필요 — `OrderCancelEvent` 수신 시 `event.account_id`로 브로커를 선택하여 직접 전달한다. **`OrderModifyEvent`(주문 정정)는 v1=price-only로 지원한다(#2391).** `OrderModifyEvent`는 EventBus 우선순위상 RuleEngine(priority=100)이 먼저 처리하며, 룰 위반·룰 평가 예외·v1 가격 preflight 실패(`modify_invalid_args`) 시 RuleEngine이 사유 `OrderModifyRejectedEvent`를 발행하고 `_consumed` 마커를 설정한다(이 경우 Gateway는 발행하지 않는다). 룰을 통과하면 Gateway(priority=50)가 OrderTracker로 `order_id → broker_order_id`를 변환하고 **broker 호출 전 fail-closed 게이트**를 적용한다: (a) finite `price>0` 아니면 `modify_invalid_args`; (b0) `record.bot_id != event.bot_id`(같은 계좌 내 타 봇 주문)=`modify_not_owner`(봇 격리); (b) `event.quantity==0.0`=price-only(허용), `>0 && != ordered_qty`=`modify_qty_change_unsupported`(#2393), `<0`=`modify_invalid_args`; (c) record status≠`open`(부분체결/터미널/미발견)=`modify_partial_or_terminal_unsupported`; (c') `record.order_type != "limit"`(비지정가/시장가 주문)=`modify_unsupported_order_type`(#2393); (d) buy면 신규가 `≤ order_price` 아니면(예산 증가) `modify_budget_increase_unsupported`(`order_price` 부재 시 buy fail-closed), sell 통과; (e) broker `ModifyOrgnoUnavailableError`=`modify_orgno_unavailable`. 게이트 통과 시 `broker.modify_order(order_id, quantity=ordered_qty, price=new_price, order_type="limit")`(수량 불변) 위임 → 성공 시 `OrderModifyExecutedEvent`(quantity=원주문 수량, price=신규), broker `False`=`modify_failed`, 기타 예외=`str(e)`. OrderTracker `ordered_qty`는 변경하지 않는다(price-only). 수량 변경·예산증가 buy·부분체결·동시성 등 고급 케이스는 후속(#2393). 실 KIS 정정(`order-rvsecncl` `RVSE_CNCL_DVSN_CD='01'`) live A/B 검증은 사용자 oracle 후속(pending).

**Stop Order 라우팅**: `OrderApprovedEvent`의 `order_type`이 `stop` 또는 `stop_limit`이면 `StopOrderManager.register()`로 라우팅한다. `StopOrderManager`가 설정되지 않은 상태에서는 일반 주문으로 처리.

### 이벤트 연동

**구독하는 이벤트**:

| 이벤트 | 설명 |
|--------|------|
| `OrderApprovedEvent` | Treasury 자금 확보 후 주문 실행. `event.account_id`로 브로커 라우팅 |
| `OrderCancelEvent` | 주문 취소 요청 → `event.account_id`로 브로커 선택 후 전달 (룰 검증 생략) |
| `OrderModifyEvent` | 주문 정정 요청 → **v1=price-only 지원(#2391)**. RuleEngine(priority=100) 선처리(룰 위반/예외/`modify_invalid_args` 시 `_consumed` 설정), 룰 통과 시 Gateway(priority=50)가 fail-closed 게이트 후 broker 위임 → `OrderModifyExecutedEvent`(price-only 성공) 또는 거부 사유별 `OrderModifyRejectedEvent`. 고급(수량변경 등)=#2393 |
| `OrderFilledEvent` | 체결 시 해당 `account_id` 범위 내 캐시 무효화 (`{account_id}:balance`, `{account_id}:positions`, `{account_id}:price:{symbol}`) |

**발행하는 이벤트**:

| 이벤트 | 설명 |
|--------|------|
| `OrderSubmittedEvent` | 증권사에 주문 전송 완료 (원주문 지정가 단가 `price?` 포함 — OrderTracker `order_price` seed, #2391) |
| `OrderFailedEvent` | 주문 제출 실패 또는 스탑 주문 등록 실패 |
| `OrderCancelledEvent` | 주문 취소 완료 |
| `OrderCancelFailedEvent` | 주문 취소 실패 |
| `OrderModifyExecutedEvent` | 주문 정정 완료 (v1=price-only, broker 위임 성공, #2391) |
| `OrderModifyRejectedEvent` | 주문 정정 거부 (v1 fail-closed 사유별, #2391) |

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

#### 세션 만료 의미론 (A2, #2405) — normative

`check_session_expiry()`는 **그 세션에 진입했던 미트리거 주문만** 세션 종료 시 `session_ended`로 만료한다. 세션에 한 번도 진입한 적 없는 주문(예: 장 전 미리 등록분, 휴장일 사전 등록분)은 **만료되지 않고 보존**된다 — 세션 외 시각에 등록한 stop 이 다음 sweep 에서 즉시 만료되던 부작용(A1)을 제거한다.

**틱-거래일 근사 (tick-as-trading-day-proxy)**: `src/ante`에는 거래일/휴장일 캘린더가 없고 `_is_in_session`은 시각(09:00–15:30 KST 등)만 본다. 시각만으로는 거래일과 휴장일의 "시장 시간대"를 구분할 수 없으므로, **실시간 시세 틱(`on_price_update`)을 거래일 개장의 신호로 근사한다**. `StopOrder`는 per-order 세션 멤버십 플래그 `entered_session`(기본 `False`)을 가진다. `on_price_update`는 틱의 **종목·계좌와 무관하게(market-wide)** 그 시점 자신의 세션 안에 있는 **모든** active 주문의 `entered_session`을 `True`로 표시한다(트리거 판단은 종래대로 틱이 들어온 종목·계좌 한정). 따라서 한 종목이라도 틱이 흐르면 그 세션의 무틱 종목까지 멤버십을 얻어, 세션 종료 시 함께 `session_ended`로 만료된다. `entered_session`은 주문당 한 번 set 되고, `_expire_order`가 만료 주문을 `active_orders`에서 제외(소비)하므로 별도 reset 이 없다(다음 거래일 신규 주문은 `entered_session=False`로 시작해 그날 첫 틱에 다시 마킹). 휴장일에는 전종목 무틱이라 어떤 주문도 마킹되지 않아 사전 등록분이 보존된다. per-order 멤버십이라 세션 경계 race(일부 주문이 한 sweep 에서 미만료돼도 다음 sweep 에서 만료)·세션 종료 후 등록(in-session 틱 부재로 보존)의 타이밍 엣지가 없다.

**마킹 신호 출처 한정 (source chokepoint, attempt5 P2)**: 거래일 멤버십 마킹은 **실 WebSocket 틱(`is_exchange_tick=True`)에 한정**한다. `on_price_update`는 keyword-only `is_exchange_tick: bool = True` 파라미터로 호출자가 가격 출처를 구분해 전달하며, 마킹 루프는 `is_exchange_tick=True`일 때만 수행한다. 스트림 해제 시 동작하는 **REST fallback poll(`is_exchange_tick=False`)**은 KIS `inquire-price`가 휴장일에도 직전 종가를 **성공 반환**하므로 거래일을 보증하지 못한다 — 만약 fallback poll 가격이 마킹을 유발하면, 스트림 끊김 상태에서 휴장일/주말의 **시계상 세션 시간**에 fallback 성공이 사전 등록 stop 을 `entered_session=True`로 마킹하고 장종료 sweep 에서 `session_ended`로 오만료시켜 A2 가 보존하려던 무틱 휴장일 주문이 사라진다. 따라서 fallback poll 은 마킹을 **유발하지 않는다**. 반면 **트리거 평가(`_should_trigger`/`_trigger_order`)는 출처와 무관하게 항상 수행한다** — 스트림 hiccup 중에도 실거래일이면 fallback 가격으로 stop 이 발동돼야 한다(#2405 scope=만료, 트리거 아님). 호출부: `StreamIntegration._on_price`(실 WS) → `is_exchange_tick=True`, `StreamIntegration._fallback_poll_loop`(REST poll) → `is_exchange_tick=False`.

**bounded known-limitation (캘린더 부재의 구조적 하한)**: "거래일인데 모니터 대상 전 종목이 세션 내내 무틱"(예: 전종목 거래정지)인 경우, 어떤 주문도 `entered_session`이 표시되지 않아 해당 주문이 그 세션에는 만료되지 않는다(다음 세션 생존). 이는 거래일/휴장일 캘린더 부재에서 비롯된 의도된 하한이며, 거래일 캘린더 도입 시 해소된다.

**bounded known-limitation (fallback poll 트리거의 거래일 staleness, 비목표)**: 트리거 평가는 출처와 무관하게 수행되므로, 스트림 끊김 상태의 REST fallback poll 이 휴장일/주말의 시계상 세션 시간에 반환한 직전 종가(last-close)가 우연히 stop 조건을 충족하면 stop 이 트리거될 수 있다. 이는 트리거 경로에 거래일 캘린더가 없는 데서 비롯된 의도된 하한으로 **#2405 비목표**이며, 거래일 캘린더 도입 또는 별도 이슈에서 다룬다. fallback 가격 트리거 자체를 게이트하는 것은 스트림 hiccup 중 실거래일 stop 발동을 막아 더 큰 위험(미발동)을 만들므로 채택하지 않는다.

**발행 이벤트**: `StopOrderRegisteredEvent`, `StopOrderTriggeredEvent`, `StopOrderExpiredEvent`. 트리거 시 변환된 `OrderRequestEvent`를 발행하여 기존 주문 흐름에 주입. 세 이벤트 모두 account-scoped (`account_id` 필드 + `_requires_account_id` 마커, #1336) 이며, 발행 시 `StopOrderManager`가 `account_id`를 명시 채운다.

**등록 거부 (Fix A, #2405)**: 매니저가 stopped(`_running=False`, shutdown 진행 중 또는 start 전) 상태에서 `register`가 호출되면 `StopOrderManagerStoppedError`를 raise 한다(이전의 빈 문자열 반환은 호출자가 인지하지 못하는 silent loss 였다). 호출자(`APIGateway._on_order_approved`)는 이 예외를 잡아 `OrderFailedEvent`(`bot_id`/`order_id`/`account_id` 보존)로 terminal 종결하므로(:187 참조), in-flight 주문이 terminal 이벤트 없이 inert 로 남지 않는다. `account_id` invalid 거부(`InvalidAccountIdError`)는 이 가드보다 **먼저** 적용된다.

### StopOrderManager — 전략 통보 정책 (#1336)

스탑 주문(`stop` / `stop_limit`)의 등록·발동·만료 세 시점은 모두 일반 주문과 동일한 통보 채널인 `Strategy.on_order_update`로 전달된다. 별도 콜백(`on_stop_order_update` 등)은 신설하지 않는다 — 시장 표준 패턴(IBKR / Alpaca 등)과 전략 작성자 부담 최소화를 따른다.

| 시점 | 발행 이벤트 | `Bot.on_order_update` 변환 status | 비고 |
|------|-------------|-----------------------------------|------|
| 등록 (`StopOrderManager.register`) | `StopOrderRegisteredEvent` | `"stop_registered"` | dict에 `stop_order_id`, `stop_price`, `limit_price` 포함. 전략은 이 시점에 후속 취소에 쓸 식별자를 획득(식별자 획득 자체는 유효). 단, **stop 주문 자체의 정정(`modify`)은 미지원**(아직 broker에 접수되지 않아 `broker_order_id`/OrderTracker record가 없음)이라 취소만 가능. broker-level 정정 v1(price-only, #2391)은 이미 접수된 `open` 일반 주문에만 적용된다(고급=#2393). |
| 발동 (`_trigger_order`) | `StopOrderTriggeredEvent` (+ 별도 `OrderRequestEvent`) | `"stop_triggered"` | 변환된 일반 주문은 자체 라이프사이클(`OrderSubmittedEvent` 등)을 별도로 통보한다. `StopOrderTriggeredEvent`는 stop 식별 단위(`stop_order_id`, `trigger_price`, `converted_order_type`)를 보존한다. |
| 만료 (`_expire_order`) | `StopOrderExpiredEvent` | `"stop_expired"` | `reason` 허용 값: `"session_ended"` (세션 종료) / `"manager_stopped"` (매니저 stop). |

**dict shape 호환**:

- 스탑 알림에서 `order_id` 키에는 `stop_order_id`를 그대로 채워 일반 주문 알림과 dict shape를 맞춘다 (외부 채널 / 전략의 후속 cancel 호환). `stop_order_id` 키도 명시 식별자로 함께 노출한다. 식별자 획득·dict shape 호환 자체는 `cancel`/`modify` 모두에 유효하나, **stop 주문 자체의 `modify` 실행은 미지원**(broker 미접수 — record 없음)이므로 후속 정정은 취소(`cancel`) 후 재주문으로 대체한다. (이미 접수된 `open` 일반 주문의 가격 정정은 broker-level v1=price-only로 지원, #2391.)
- `SignalChannel`도 외부 채널에 동일한 `{type:"order_update", order_id, status, reason}` 메시지로 전달한다 — `type` 값을 새로 만들지 않아 외부 소비자(stdin/stdout 기반 에이전트)의 파싱 분기를 추가 강제하지 않는다.

**비포함 정보** (#1337 정책 직교):

- 스탑 알림에는 자금 reserve 정보가 포함되지 않는다 (매수 stop은 등록 시점 자금 잠금 없음, 트리거 시점 잠금이며 변환 주문이 자체 통보).

### StopOrderManager — 자금 처리 정책 (#1337)

매수 stop / stop_limit 주문의 자금 처리는 한국 증권사 예약주문 표준과 일치한다. 본 정책은 GitHub 이슈 #1337 사용자 승인(2026-05-08) 결정에 따른다.

| 단계 | Treasury 호출 | 동작 |
|------|---------------|------|
| 등록 (`OrderApprovedEvent` 수신 → `StopOrderManager.register`) | **없음** | Treasury는 매수 stop/stop_limit `OrderValidatedEvent`에서 자금 잠금 없이 `OrderApprovedEvent(reserved_amount=0.0)`를 즉시 발행한다. StopOrderManager는 가격 조건만 등록한다. |
| 트리거 (`stop_price` 도달 → 변환된 `OrderRequestEvent` 발행) | **있음** | 변환된 일반 매수 주문(market/limit)이 일반 RuleEngine → Treasury 경로를 그대로 탄다. 그때 처음 `reserve_for_order(...)`가 호출되며, 자금 부족이면 일반 매수 주문 실패와 동일하게 `OrderRejectedEvent`로 거부된다. |
| 취소 / 만료 (`StopOrderManager.cancel` / `check_session_expiry`) | **없음** | 등록 시점에 자금을 잠그지 않았으므로 별도 자금 해제 불필요. StopOrderManager는 stop 주문 목록에서 항목 제거만 수행한다. |

**Invariant**:

- 트리거 변환 이벤트는 일반 `OrderRequestEvent`와 구분되지 않는다. RuleEngine과 Treasury는 변환 주문을 stop이 아닌 일반 주문으로 인식해 한 번만 reserve를 수행한다 (double reserve 방지).
- StopOrderManager는 Treasury를 직접 호출하지 않는다. 자금 처리는 항상 변환 주문의 일반 흐름을 통해 일어난다.
- 매도 stop은 자금 reserve와 무관하므로 본 정책 영향 밖이다 (매도 reserve invariant 자체가 별도).

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
