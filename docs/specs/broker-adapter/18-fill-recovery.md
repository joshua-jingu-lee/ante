# Broker Adapter 모듈 세부 설계 - 체결 반영 경로 (Fill Recovery)

> 인덱스: [README.md](README.md) | 호환 문서: [broker-adapter.md](broker-adapter.md)
> 참조: [11-order-flow.md](11-order-flow.md) 주문 처리 흐름, [15-reconciliation.md](15-reconciliation.md) 대사, [trade/03-08-fill-recovery.md](../trade/03-08-fill-recovery.md) OrderTracker/FillApplier 권위

# 체결 반영 경로 (Fill Recovery)

## 1. 문제 정의

ante가 제출한 주문은 (모의투자·실전투자, 스트림 유무와 무관하게) 내부 체결·
포지션에 일관되게 반영되어야 한다. 그렇지 않으면 `positions`가 0으로 고정되고, 전략이
보유를 인지하지 못해 동일 주문을 반복 제출하며, 대사(reconciler)가 미복구
체결을 "외부 매수"로 오분류하는 연쇄가 발생한다 (#1945 인시던트).

기존 설계는 체결→`OrderFilledEvent`를 **실시간 체결 통보 스트림(KIS `H0STCNI0`)
경로로만** 발행했다. 스트림 구독이 실패하거나(HTS ID 부재 등) 모의투자 환경에서
체결 통보가 오지 않으면 체결이 영구히 내부에 반영되지 않았다. REST 폴백은
가격만 복구하고 체결은 복구하지 않았다.

## 2. 설계 원칙

체결 반영은 **여러 경로를 가진 단일 멱등 수렴 모델**이다.

- **빠른 경로 (fast path)**: 실시간 체결 통보 스트림 (`H0STCNI0`). 저지연. 선택적.
- **백스톱 경로 (backstop)**: REST `get_order_history` 폴. **체결기준 원장이
  당일 반영되는 환경에서 정합성 보증.** 항상.
- **잔고-역도출 fallback (position-derived bounded fallback)**: 백스톱이 당일
  0건을 줄 때만, 잔고(`get_positions`, 체결기준 즉시반영) 증분에서 self-submitted
  체결을 보수적으로 역도출. **KIS paper 한정 기본 활성**, bounded. 상세는 §11.

세 경로는 모두 **단일 멱등 choke point(`FillApplier`)** 로 수렴한다. 어느
경로로 같은 체결을 몇 번 관측하든 포지션은 **정확히 한 번** 반영된다.

### 2.1 백스톱 보증의 모의 당일 예외 (#2314)

§2의 "REST 백스톱(`get_order_history`)이 정합성을 보증한다"는 단정은 **체결기준
원장이 당일 반영되는 환경을 전제로 한다**. **KIS 모의투자(`is_paper=true`)에서는
이 전제가 거짓이다**:

- KIS 모의 `inquire-daily-ccld`(`get_order_history`)는 **일별 정산/결제기준
  원장**이라 잠재적 당일 지연 반영 위험이 KIS 공식 근거로 남아 있다(KIS 공식
  POSTMAN v1.6: *"일별 조회로, 당일 주문내역은 지연될 수 있습니다"* + 한국투자증권
  attention_23). 다만 **이 지연은 tr_id 세대에 의존한다**: 레거시 `VTTC8001R`은
  모의 당일 체결을 0건으로 반환하나(#2317 라이브 A/B로 장중·마감후·D+6 3시점
  일관 입증), 현행 신 tr_id `VTTC0081R`(#2349)은 **당일 체결을 반환함이 #2317
  라이브로 확인**됐다. 레거시 경로에서는 `recorded_filled_qty=0`이 고정되어
  #1945류 미반영 캐스케이드 위험이 재현되었다.
- 반면 잔고(`inquire-balance`/`get_positions`, tr_id `VTTC8434R`)는 **체결기준
  이라 당일 즉시 반영**된다.

따라서 모의 당일 체결에 한해 백스톱은 **유일 SSOT가 아니다**. 백스톱(확정 정합)
+ 잔고-역도출 fallback(당일 보수적 수렴, bounded)의 **이중 입력 모델**로
보강한다(§11). fallback은 본 §의 FillApplier 멱등 모델을 재사용하며 **새 권위자를
만들지 않는다**. 근거: KIS open-trading-api POSTMAN v1.6(`inquire-daily-ccld`
요청 *"일별 조회로, 당일 주문내역은 지연될 수 있습니다"*) + 한국투자증권
실시간 체결/미체결 주의사항(attention_23) + #2314 근본원인 조사.

```
OrderApproved → submit_order → place_order(broker_order_id)
  → OrderSubmittedEvent → OrderTracker.open(order_id, broker_order_id, …)

빠른경로 : H0STCNI0 → StreamIntegration._on_execution ─┐
백스톱   : FillReconcileScheduler (open 있을 때만,        ├→ FillApplier.apply_cumulative(
           get_order_history 1콜/사이클)              ─┘     account_id, broker_order_id,
                                                              observed_cumulative, avg_price,
                                                              submitted_date)

FillApplier (단일 인스턴스 · asyncio.Lock):
  lookup_order_id(account_id, broker_order_id, submitted_date) → order_id | None
    └ None 이면 무시 (self/external 경계 — 추적되지 않는 주문)
  Database.transaction() 안에서:
    (a) CAS advance: UPDATE … SET recorded_filled_qty=:c WHERE order_id=:oid AND recorded_filled_qty<:c
        → applied_delta = observed_cumulative - 이전 recorded
    (b) delta<=0 이면 no-op
    (c) delta>0 이면 TradeRecord insert + PositionHistory.on_trade(=positions)
    → commit
  commit 이후: OrderFilledEvent(quantity=delta, price=avg_price, order_id/bot_id/
               strategy_id/account_id 는 tracker 에서 복원) 1회 발행
  → TradeRecorder(알림) · Treasury(정산) · Bot.on_fill(전략) 수신
```

## 3. 컴포넌트

체결 반영의 코어 컴포넌트는 **브로커 무관(broker-agnostic)** 이며, 브로커별
차이는 기존 `BrokerAdapter` 인터페이스(`get_order_history`, 정규화 dict 반환)로
흡수한다. 신규 어댑터 추상화는 도입하지 않는다.

| 컴포넌트 | 위치 | 역할 |
|---|---|---|
| `OrderTracker` | `trade/order_tracker.py` | 추적 주문 영속(DB `order_tracker`), 누적 체결 단조 advance(CAS), 매핑 조회, EOD 만료 |
| `FillApplier` | `trade/fill_applier.py` | 단일 멱등 choke point. 관측 누적 → delta 산출 → 단일 트랜잭션 적용 → 이벤트 발행 |
| `FillReconcileScheduler` | `broker/fill_scheduler.py` | 계좌별 event-gated 백스톱 폴러. open 있을 때만 `get_order_history` 1콜/사이클 → `FillApplier` |

`OrderTracker`와 `FillApplier`는 `trade/` 모듈에 둔다. 체결의 durable 적용
(recorded + trade + position)은 FillApplier가 단일 권위자로 수행하므로,
포지션 소유가 Trade 모듈 내에 유지된다 (position ownership invariant).

## 4. OrderTracker

### 4.1 identity (구조적 종결)

KIS `odno`(broker_order_id)는 **시스템 전역 유일 키가 아니다** — 계좌 간 /
paper·live 간 / 영업일 재사용으로 충돌할 수 있다. 따라서:

- **PK = 내부 `order_id`** (`OrderSubmittedEvent`의 ante `uuid4` 주문 ID — 생성상
  전역 유일). CAS는 `WHERE order_id=:oid` 단일 행이라 모호성이 없다.
- `(account_id, broker_order_id, submitted_date)` = **UNIQUE 인덱스 + 조회 키**
  (poll/stream 관측 → 내부 `order_id` 매핑용). 조회는 non-terminal(또는 동일
  영업일) scope로 한정해 영업일 재사용 충돌을 닫는다.

이 구조로 cross-account / paper·live / 일자 재사용 충돌이 **구조적으로 불가**하다.

### 4.2 컬럼

| 컬럼 | 의미 |
|---|---|
| `order_id` (PK) | 내부 주문 ID (ante uuid4) |
| `account_id` | 계좌 |
| `bot_id`, `strategy_id` | 라우팅 정체성 (이벤트 복원용) |
| `broker_order_id` | 브로커 주문번호 (KIS `odno`) |
| `symbol`, `side`, `order_type` | 주문 메타 |
| `ordered_qty` | 주문 수량 |
| `recorded_filled_qty` | 내부 반영 완료된 누적 체결량 (**단조 비감소**) |
| `avg_fill_price` | 최근 관측 평균 체결가 |
| `status` | `open` \| `partially_filled` \| `filled` \| `cancelled` \| `rejected` \| `failed` \| `expired` |
| `submitted_at`, `submitted_date` | 제출 시각·영업일 |
| `last_polled_at` | 마지막 폴 관측 시각 |
| `terminal_at` | 종료 시각 |

### 4.3 메서드

- `open(order_id, account_id, bot_id, strategy_id, broker_order_id, symbol, side, order_type, ordered_qty, submitted_date)`:
  `OrderSubmittedEvent`로 추적 주문 seed.
- `record_fill(order_id, new_cumulative, avg_price) → RecordFillResult(delta, confirmed_cumulative)`:
  원자 CAS advance. `delta = new_cumulative - 이전 recorded`. `delta<=0`이면
  `delta=0` no-op(`confirmed_cumulative`=직전 recorded), `delta>0`이면
  `recorded=new_cumulative`로 갱신하고 status를 부분/완료로 전이한 뒤
  **CAS `RETURNING recorded_filled_qty`로 확정된 누적값**을 `confirmed_cumulative`로
  반환한다. **FillApplier의 트랜잭션 안에서만 호출**. `confirmed_cumulative`는
  체결 이벤트 outbox의 결정적 `fill_dedup_key` 산출 기준이다(§10, #1949) —
  입력 `observed_cumulative`가 아니라 DB가 RETURNING으로 확정한 값을 쓴다.
- `mark_terminal(order_id, status)`: 취소·거부·실패·만료 종료 표기.
- `get_open_orders(account_id)`: 계좌의 non-terminal(open/partially_filled) 주문.
- `lookup_order_id(account_id, broker_order_id, submitted_date) → order_id | None`:
  관측 → 내부 주문 매핑(non-terminal/same-day scope).
- `expire_stale(...)`: EOD 경과한 open 주문을 `expired`로 표기.

### 4.4 멱등 불변식

- `recorded_filled_qty`는 order별 **단조 비감소**.
- 각 증가(delta>0)는 **정확히 1개 `OrderFilledEvent(delta)`** 와 1쌍.
- 포지션 = Σdelta = 최종 누적 체결량.

## 5. FillApplier — 단일 멱등 choke point

`FillApplier`는 단일 인스턴스이며 `asyncio.Lock`이 **read → delta → txn →
publish 전체**를 감싼다.

`apply_cumulative(account_id, broker_order_id, observed_cumulative, avg_price, submitted_date)`:

1. `lookup_order_id`로 추적 주문 확인. 없으면 **무시**(self/external 경계 —
   진짜 외부 포지션은 reconciler 영역).
2. `Database.transaction()` 단일 트랜잭션 안에서:
   - (a) CAS advance `recorded_filled_qty` (`WHERE order_id=:oid AND
     recorded_filled_qty<:c`) → `applied_delta` 산출.
   - (b) `applied_delta <= 0`이면 no-op (이미 반영됨/관측 역전).
   - (c) `applied_delta > 0`이면 `TradeRecord` insert + `PositionHistory.on_trade`
     적용.
   - → commit.
3. **commit 이후** `OrderFilledEvent`(quantity=delta, price=avg_price,
   order_id/bot_id/strategy_id/account_id는 tracker에서 복원) 1회 발행.

### 5.1 crash 원자성 (positions exactly-once)

`recorded_filled_qty` advance(CAS)와 TradeRecord insert·position update가 **단일
`Database.transaction()`** 으로 묶인다. 적용 도중 프로세스가 crash하면 rollback이
되어 recorded가 advance되지 않으므로, 재기동 후 다음 폴이 **동일 delta를 재적용**
한다. → positions/trades는 **crash-safe exactly-once**.

`asyncio.Lock`은 프로세스 내 동시성만 막는다. crash 원자성은 단일 트랜잭션이
보장한다.

### 5.2 이벤트 전달 durability (#1949 — R4 한계 해소)

이전에는 `OrderFilledEvent`가 **commit 이후** 발행되어, commit ↔ event-publish
사이 narrow crash window에서 다운스트림 이벤트 전달(Treasury 정산·strategy
`on_fill` 알림)이 유실될 수 있었다(#1946 R4 bounded-limitation).

**#1949 transactional outbox로 이 crash window를 닫는다(이벤트 무손실)**: §3의
체결 적용 트랜잭션 **안**에서 `OrderFilledEvent` payload를 `fill_outbox`
테이블에 함께 INSERT한다(recorded advance + trade + position과 동일 원자 커밋).
commit 성공 = 이벤트 영속 보장이므로, commit-후-crash에서도 재기동 시
`FillOutboxPublisher`가 미발행 row를 재전달한다(§10). 상세는 §10과
`docs/specs/eventbus/eventbus.md`(전달 시맨틱).

전달 시맨틱은 **at-least-once(무손실)**다. publish↔mark 사이 micro-window에서
같은 이벤트가 두 번 발행될 수 있으나, 각 이벤트는 결정적 `fill_dedup_key`를 실어
보낸다. #1949는 outbox 무손실 전달 + 결정적 키 제공까지 책임진다.
**positions durability는 #1946에서, 이벤트 전달 durability는 #1949에서 종결**한다.

**소비자 멱등화 (#1957 완료)**: at-least-once 재전달 시 비멱등 소비자의
이중처리는 #1957에서 `fill_dedup_key`를 소비해 소비자별로 해소했다.

- **Treasury = 진짜 exactly-once-effect**: 전용 `treasury_fill_dedup`
  테이블(PK=`fill_dedup_key`)에 `INSERT OR IGNORE ... RETURNING`으로
  dedup-insert를 정산 `Database.transaction()` 안에서 **가장 먼저** 수행하고,
  신규일 때만 정산한다(재전달=정산 0회 추가). dedup-insert ⟺ 정산이 단일
  트랜잭션으로 원자 결합되고, rollback 시 인메모리 예산/예약을 진입 전 snapshot
  으로 복원해 split-brain을 막는다. DB-persisted라 재기동 후에도 동작.
- **Bot / SignalChannel / TradeRecorder = bounded dedup (best-effort)**:
  전략 follow-up·외부 JSON write·NotificationEvent 재발행을 공유
  `FillDedupGuard`(in-memory `deque(maxlen=512)`)로 억제한다.
  **known-limitation**: 프로세스 재기동 시 가드 소실, `maxlen` 윈도우를 벗어난
  재전달은 식별 못 함. DB-persisted exactly-once 승격은 #1957 비목표이며
  **follow-up 후보**다. TradeRecorder의 `trades` insert(`INSERT OR IGNORE`)는
  이미 DB-멱등이나 `NotificationEvent` 재발행이 effect 비멱등이라 가드 대상이다.
- **Gateway = 무변경**(cache invalidate 멱등). **빈키(`""`) = dedup 비대상**
  (VirtualProvider 직접발행·outbox 미주입 fallback = 재전달 없는 단발 경로).

## 6. FillReconcileScheduler — 백스톱 폴러

- 계좌별 인스턴스. running 동안 동작.
- **event-gated**: `OrderTracker.get_open_orders(account_id)`가 비면 폴하지 않고
  idle(0콜). open이 있을 때만 `get_order_history`를 **사이클당 1콜** 호출.
- cadence **≥60s**. KIS rate budget(paper 5/min·live 20/min, 주문제출·가격
  fallback·잔고 reconcile·fill poll이 동일 큐 공유)을 보호한다. 주문 제출이
  starve되지 않도록 가격 fallback 루프와 우선순위/상호배타를 둔다.
- `get_order_history` window는 **EOD 만료 전** 추적 open 주문의 가장 이른
  `submitted_date` 이후를 덮도록 잡고 pagination·당일 필터를 처리한다
  (stream-before-seed race도 폴이 멱등 흡수). 만료가 이 open을 먼저 제거해
  window를 좁히지 않는다 (§6.1 poll-first, §8 참조).

### 6.1 기동 카치업 (catch_up_once)

재기동 시 `OrderTracker`는 영속이므로 open/partial 주문이 생존한다. 계좌별
`catch_up_once()`는 open이 있으면 `get_order_history`(submitted_at 이후,
pagination)를 **1회** 폴해 다운타임 중 발생한 체결을 `FillApplier`로 멱등
따라잡는다.

#### poll-first 순서 (복구가 EOD 만료보다 선행 — 정합성 invariant)

폴 사이클(`catch_up_once`·주기 루프 공통 코어 `_poll_and_apply`)은 **반드시**
다음 순서를 지킨다:

1. `get_open_orders`로 추적 open(non-terminal)을 **EOD 만료 전에** 읽고,
   `from_date`를 그 중 가장 이른 `submitted_date`로 잡는다(전일 open이 있으면
   window가 그 영업일까지 거슬러 올라간다 — §8 window invariant).
2. open이 있으면 `get_order_history` 1콜로 다운타임 체결을 `FillApplier`로 멱등
   **복구**한다. 복구된 주문은 `filled`/`partially_filled`로 전이된다.
3. **2의 복구가 끝난 뒤**, 남아 있는 open buy capacity(`Σ(ordered_qty -
   recorded_filled_qty) > 0`)에 대해서만 §11 **잔고-역도출 fallback**을 적용한다
   (KIS paper 한정 기본 활성). ccld가 체결을 주면 capacity가 advance되어 fallback
   대상이 없으므로 자동으로 건너뛴다.
4. **2·3이 끝난 뒤에만** §8의 EOD 만료(`expire_stale`)를 돌린다.

순서 invariant: `get_order_history` 적용 → 잔여 open buy capacity에 한정한
`get_positions` fallback → `expire_stale`. fallback은 ccld 복구 **뒤**, 만료
**앞**에 위치해야 한다(§11.5). 만료를 fallback 앞에 두면 모의 당일 미반영 체결을
가진 open이 복구 전에 `expired`로 전이되어 fallback이 대상을 잃는다(§8 poll-first
회귀와 동형).

이 순서는 §7 barrier(fill 복구가 reconcile보다 선행)와 **하나의 순서
invariant**다. EOD 만료를 폴 **앞**에 두면, 전일 open이 다운타임 중 체결됐어도
복구 전에 `expired`로 전이되어 폴이 0콜로 끝나고, `catch_up_once`가
`succeeded=True`(applied=0)를 반환해 barrier의 external-buy 차단이 무력화된다.
그 결과 미복구 ante 체결(internal=0, broker>0)이 reconciler 의 self/external 분류로
**오귀속**된다(#1945 회귀). poll-first는 이를 구조적으로 막는다. `succeeded=True`는
폴이 실제 실행돼 다운타임 체결을 흡수했음을 의미하며, "만료로 open이 비어 0콜"은
성공으로 취급하지 않는다.

> 참고(#2352): 위 회귀에서 매칭 open 주문이 `expired`(terminal)로 사라지면
> reconciler 입장에서 `internal_qty == 0 && capacity == 0` 이 되어, 그 보유는
> "외부 매수" force-write 가 아니라 **미귀속 보유 detect-only**(보정 skip · critical
> 알림)로 분류된다([../trade/03-07-position-reconciler.md](../trade/03-07-position-reconciler.md)
> 미귀속 보유 절). 따라서 barrier 무력화의 잔여 위험은 "잘못된 force-write/자동
> 매도"가 아니라 "복구 지연된 보유의 오귀속 알림"으로 좁혀진다 — poll-first 순서
> invariant 가 근본 차단을 담당한다는 사실은 변하지 않는다.

### 6.2 steady-state 폴 루프 cooldown · late-ccld 차단기 회계 제외 (#2350)

체결이력 폴(`get_order_history` → `inquire-daily-ccld`)은 어댑터 전역 단일
`CircuitBreaker`를 주문·잔고 조회와 공유한다. 폴 타임아웃 누적이 차단기를 OPEN
시키면 같은 어댑터를 공유하는 treasury 잔고/포지션 동기화·주문 경로까지
broker-wide 로 차단된다(cross-concern 결합). 이를 끊기 위해 두 normative 규칙을
둔다.

**late-ccld `TimeoutError` 차단기 회계 제외 (normative)**: `get_order_history`
경로의 `TimeoutError` 계열(aiohttp timeout 포함, `TimeoutError` 하위)은 차단기
`record_failure()`에 **기록되지 않는다**(호출측 opt-out). 따라서 체결이력 폴이
반복 타임아웃해도 차단기는 OPEN 되지 않으며, **차단기 상태 변경 이벤트/알림도
발생하지 않는다**(`CircuitBreakerEvent`/`NotificationEvent`의 발생 조건을 좁힐 뿐
스키마/종류는 무변경 — [16-eventbus-integration.md](16-eventbus-integration.md)·
[17-notification-events.md](17-notification-events.md) unchanged). 회계 제외는
**late-ccld `TimeoutError` 에 한정**되며, HTTP 5xx/`APIError` 등 다른 실패는
기존대로 차단기에 기록된다(실제 KIS 서버 장애 보호 유지). 차단기 `check()` 통과는
그대로라 다른 concern 이 연 차단기에는 종속한다(주문 경로 보호 무변경). 어댑터 측
계약은 [10-commission-info.md](10-commission-info.md)·[07-kis-base-adapter.md](07-kis-base-adapter.md)
참조.

**steady-state cooldown (normative)**: 주기 루프(`_loop`)는 정상 사이클에서
`poll_interval` 고정 주기를 유지하되, **연속 broker-transient 실패** 시 다음 사이클
대기를 backoff 로 늘려 OPEN 갱신/타임아웃 연타를 흡수한다.

- **sequence**: n번째 연속 실패 직후 다음 사이클 sleep = `poll_interval × min(2^n,
  8)`. 즉 첫 실패 후 ×2, 이후 ×4, ×8(cap).
- **cap 근거**: 기본 `poll_interval` 60s 기준 상한 480s(=60×8). 이는 CB
  `recovery_timeout`(60s)·reconciler 주기(1800s)보다 짧아 복구 관측을 놓치지
  않으면서 OPEN 을 60s 주기로 갱신·연장하지 않는다. fill 반영 지연 상한도 480s 로
  bounded.
- **reset**: `_poll_and_apply`가 예외 없이 정상 완료되면 연속 실패 카운터를 0 으로
  리셋해 `poll_interval` 고정 주기로 복귀한다(성공 경로 주기 불변).
- **실패 집계 범위**: broker-transient 예외(`TimeoutError`·`CircuitOpenError`·
  `APIError`·`ConnectionError`/`OSError`)만 카운트한다. 그 외 예외(내부 버그류)는
  cooldown 으로 은폐하지 않고 기존대로 즉시 다음 주기 + 경고 로그를 유지한다(현행
  동작 보존).
- **적용 범위**: cooldown 은 `_loop` steady-state 한정이다. 기동 카치업
  `catch_up_once`의 bounded backoff(§6.1, `CATCH_UP_MAX_ATTEMPTS`)는 **무변경·
  비간섭**이며, 기동 barrier(§7) 결정에 영향을 주지 않는다.

## 7. barrier ordering (재기동 무오분류)

기존 `ReconcileScheduler.start()`는 즉시 `run_once()`로 position 대사를 돈다.
fill 복구가 position reconcile보다 **반드시 선행**해야, reconciler가 미복구
ante 체결을 "외부 매수"로 오분류하지 않는다.

main 기동에서 각 계좌 `FillReconcileScheduler.catch_up_once()` **await 완료
후에만** `ReconcileScheduler.start()`를 시작한다. 단순 순서가 아니라 **awaited
hard barrier**다.

## 8. EOD 만료

유효기간이 지난 open 주문(일중 주문이 EOD 경과, pending에도 없고 **history
체결도 없는** genuinely-dead 주문)만 `mark_terminal(expired)`로 표기한다. 무한
폴과 phantom pending을 방지한다.

만료 조건과 순서를 다음으로 못박는다(§6.1 poll-first의 한 축):

- **대상은 `open` 상태만**이다. 부분 체결(`partially_filled`)은 체결이 관측·진행
  중이므로 genuinely-dead가 아니며 만료하지 않는다.
- 만료는 같은 폴 사이클에서 **history 폴(복구)이 끝난 뒤에** 실행한다. 다운타임
  중 체결된 open은 그 폴에서 `filled`/`partially_filled`로 전이되어 이 만료에서
  **자동 제외**된다. 즉 "EOD 경과 open 중 history 체결이 관측되지 않은" 주문만
  남아 만료되므로, 미복구 체결분을 영구 만료하거나 "외부 매수"로 오분류하지
  않는다.
- 만료가 폴 window를 좁히지 않는다: window의 `from_date`는 만료 **전** open의
  가장 이른 `submitted_date`로 잡혀, 전일 open의 다운타임 체결을 덮는다(§6.1
  window invariant). 폴이 실패하면 만료도 실행되지 않아, 미복구 체결분은 다음
  성공 사이클의 폴 window에 그대로 남는다.

## 9. 경계 (out of scope)

- tracker에 없는 broker 포지션(DB wipe·기능 배포 이전 주문)은 본 복구 대상이
  아니다 → reconciler 영역.
- 부분 체결의 Treasury **비례 정산**(filled 비용만 차감)은 pre-existing 한계로
  별도 후속 이슈. 본 스펙은 단일/전량 체결 정산을 정상 유지하며 이를 악화시키지
  않는다.
- 전략 `ctx.get_open_orders()`(live) 백엔드 연결은 별도 후속 이슈(유저스토리 #2).
- 스트림 `H0STCNI0` HTS ID 복원은 선택적 지연 최적화 — **체결기준 원장이 당일
  반영되는 환경에서** 정합성은 REST 백스톱이 보장한다. **단 KIS 모의투자
  (`is_paper=true`) 당일 체결은 예외**다: 백스톱(`get_order_history`)이 일별
  결제기준이라 당일 0건을 주므로 백스톱만으로 정합성이 보장되지 않는다(§2.1).
  이 모의 당일 gap은 §11 잔고-역도출 fallback(체결기준 잔고 즉시반영)으로 닫는다.
  라이브의 잔여 의존(지연 폭·EXCG_ID_DVSN_CD·신 tr_id 효과 확인)은 #2317에서
  검증한다(known-limitation).
- **소비자 멱등화**(Treasury txn-dedup·Bot/SignalChannel bounded)는 #1949 범위
  밖이며 별도 이슈(#1957)에서 해소한다. #1949는 소비자 무변경이다.

## 10. 체결 이벤트 transactional outbox (#1949)

commit↔publish crash window(§5.2)를 닫는 durability/at-least-once 메커니즘.
구현체: `src/ante/trade/fill_outbox.py`(`FillOutbox`, `FillOutboxPublisher`).

### 10.1 outbox 테이블 (`fill_outbox`)

| 컬럼 | 설명 |
|------|------|
| `id` | PK (AUTOINCREMENT, 발행 순서 보존) |
| `fill_dedup_key` | **UNIQUE**. 결정적 체결 식별자 = `order_id:canonical(confirmed_cumulative)` |
| `payload` | `OrderFilledEvent` 생성자 인자 JSON (`event_id`/`timestamp` 제외 — 발행 시 생성) |
| `created_at` | 생성 시각 |
| `published` | 발행 여부 (0/1) |
| `published_at` | 발행 시각 |

`UNIQUE(fill_dedup_key)` + `ON CONFLICT DO NOTHING`으로 같은 체결의 중복 outbox
row 생성을 막는다(같은 fill을 두 번 관측해도 row 1개).

### 10.2 결정적 `fill_dedup_key`

`fill_dedup_key = f"{order_id}:{canonical(confirmed_cumulative)}"`.

- `confirmed_cumulative`는 §4.3 `record_fill`이 CAS `RETURNING
  recorded_filled_qty`로 **확정**한 누적값이다(입력 `observed_cumulative`가
  아니다). 같은 advance 경계는 항상 같은 확정값을 내므로 키가 결정적이다.
- `canonical(value)` = `repr(float(value))`. SQLite REAL·Python `float`은 모두
  IEEE754 double이며 `repr`은 round-trip을 보장하는 최단 표현이라, 재전달 시
  키 비결정성이 없다. 고정 소수 포맷(`f"{:.Nf}"`)은 유효 자릿수를 잘라 서로 다른
  체결량이 같은 키로 충돌할 수 있어 쓰지 않는다.

### 10.3 원자 INSERT (FillApplier)

`FillApplier._apply_locked`의 체결 적용 `Database.transaction()` **안**에서
recorded advance + `TradeRecord` insert + `PositionHistory.on_trade`와 함께
outbox row를 INSERT한다. commit 성공 = 이벤트 영속 보장. (outbox 미주입
fallback 경로는 #1949 이전과 동일하게 commit 직후 직접 1회 발행하며, 이 경로는
crash window가 잔존하고 빈 `fill_dedup_key`를 쓴다.)

### 10.4 퍼블리셔 워커 (`FillOutboxPublisher`)

- **순서 불변식**: row마다 **publish 성공 → mark_published** 순서를 지킨다
  (역순 금지). publish가 실패(예외)하면 마킹하지 않아 다음 사이클·기동에 재전달
  한다(at-least-once).
- **기동 재전달**: `catch_up_once()`가 미발행 row를 id 오름차순으로 한 번 드레인
  한다. main 기동에서 소비자 구독·체결 catch-up 이후 await하여, commit-후-crash로
  미발행된 이벤트를 재전달한다.
- **드레인 트리거**: `FillApplier`가 enqueue 직후 `notify()`로 워커를 깨운다.
  주기 루프(`start()`)는 통지 누락에 대한 백스톱이다.
- **graceful stop**: `stop()`은 루프를 취소한다. 미발행 row는 outbox에 durable
  하게 남아 다음 기동의 `catch_up_once`가 재전달한다(무손실).

### 10.5 VirtualProvider 빈키 정책

`VirtualExecutor`(`src/ante/bot/providers/virtual.py`)는 가상 체결을 즉시 1회
직접 발행하며 FillApplier/OrderTracker(CAS)·outbox를 거치지 않는다. 결정적 키의
산출 기반(CAS 확정 누적값)이 없고 at-least-once 재전달도 없으므로 dedup 비대상
이다 → `fill_dedup_key`는 **빈키(`""`)**로 발행한다. 소비자(#1957)는 빈키를
"dedup 비대상"으로 본다.

## 11. position-derived bounded fallback (모의 당일 체결, #2314)

§2.1에서 본 모의 당일 gap(백스톱 `get_order_history`가 0건, 잔고는 즉시반영)을
닫는 **세 번째 입력 경로**다. 백스톱이 당일 체결을 주지 못할 때, 잔고
(`get_positions`, 체결기준 즉시반영) 증분에서 self-submitted 체결을 **보수적으로
역도출**해 `FillApplier.apply_cumulative`로 멱등 수렴한다. fallback은 **새 권위자를
만들지 않으며**, §5 FillApplier 단일 멱등 choke point를 그대로 재사용한다.

본 절의 normative 문장은 **KIS paper(`is_paper=true`) 한정 기본 활성**을 전제로
한다(§11.6). live 적용 범위는 §11.6·#2317에 따른다.

### 11.1 account-level excess 산식 (overfill 금지)

fallback의 관측 누적량 산출 기준은 **계좌 수준 excess**다:

- `excess = broker_qty(get_positions) - internal_account_qty`.
- `internal_account_qty` = 해당 `(account_id, symbol)`에 대한 **전체 내부 포지션
  합**(특정 bot이 아닌 계좌 전 bot 포지션의 합). 이렇게 해야 기존 보유·타 bot
  포지션·외부 매수가 broker_qty에 혼입돼 있어도 그 분을 차감해 **self 미반영분만
  남긴다**.
- `excess`는 **self-order capacity 한도로 clamp**하되, fallback 적용 자체는 아래
  §11.3의 **full-fill 정확매칭 조건**(`excess == ordered_qty`인 유일 미복구 open
  buy)으로 더 협소화한다. broker_qty에 숨은 외부 매수가 섞여 있어도 정확매칭이
  아닌 excess는 fallback이 **취하지 않아 overfill을 구조적으로 금지**한다.
- `excess ≤ 0`이면 fallback 대상이 없다(no-op).

### 11.2 적용 순서 (§6.1 poll-first 확장)

§6.1 폴 사이클은 **반드시** 다음 순서를 지킨다(순서 invariant):

1. `get_order_history` 적용(§6.1-2). ccld가 체결을 주면 capacity가 advance된다.
2. **남은 open buy capacity(`Σ(ordered_qty - recorded_filled_qty) > 0`)에
   대해서만** `get_positions` 기반 fallback(본 §)을 적용한다. ccld가 이미 채운
   주문은 capacity가 0이라 자동 제외된다.
3. **그 다음에** §8 `expire_stale`을 실행한다.

ccld가 당일 체결을 주는 정상 환경에서는 ccld가 `recorded_filled_qty`를 advance해
잔고 excess(`broker_qty - internal_account_qty`)가 **0**으로 수렴하므로 fallback이
**본질적으로 no-op**이다(부분 체결로 open이 남아도 그 잔량만큼 `excess`도 함께
줄어 `excess == 0` → no-op이다 — no-op의 실제 조건은 `capacity == 0`이 아니라
`excess == 0`이다; 부분 체결된 open 주문은 capacity>0이어도 excess가 0이면
fallback이 취하지 않는다). 즉 fallback은 모의 당일 0건 gap에서만 실효한다.

### 11.3 self-order capacity 매칭 — full-fill 정확매칭 한정 (비귀속 보수)

fallback의 귀속 대상은 OrderTracker의 self-order capacity로 한정하되, **잔고
excess가 그 유일 주문의 주문 수량과 정확히 일치하는 full-fill 케이스에만**
적용한다(#1950 self/external 경계 재사용):

- `capacity = Σ(ordered_qty - recorded_filled_qty)` — `(account_id, symbol,
  side="buy")`의 **non-terminal**(`open`·`partially_filled`) 추적 주문 미체결 잔량.
- fallback은 다음 조건을 **모두** 만족할 때만 적용한다(결정적 full fill 귀속):
  1. 그 `(account_id, symbol, side="buy")`에 대한 **추적 open buy 주문이 정확히
     하나**다.
  2. 그 유일 주문이 **미복구 상태**(`recorded_filled_qty == 0`)다. 즉 ccld가 부분
     도 반영하지 않은, 잔고에서만 관측되는 주문이다.
  3. 그 symbol의 잔고 excess(`broker_qty(symbol) - internal_qty(symbol)`)가 그
     주문의 **`ordered_qty`와 정확히 일치**한다(`excess == ordered_qty`).
- 위 세 조건을 모두 만족하면 **full fill로만** advance한다:
  `observed_cumulative = ordered_qty`. 이 절대 누적값을 그 주문의
  `broker_order_id`로 `FillApplier.apply_cumulative`에 넘긴다(§5 계약은 절대
  누적값을 받으며, CAS가 delta를 산출한다).
- **부분 체결·모호한 excess(`excess != ordered_qty`)는 fallback을 적용하지
  않는다**(미적용). 부분 분량 귀속(`min(excess, capacity)`)은 **본 스펙 비채택**
  이다 — 잔고는 총량만 주므로 partial excess가 self 부분 + 동시 외부 매수의
  혼재인지 결정할 수 없고, partial 귀속은 그 외부분을 self로 **비가역 흡수**할 수
  있기 때문이다(CAS 단조 → late ccld가 실제 self 누적을 줘도 no-op, §11.4·§11.7).
  미적용분은 **D+1 ccld 백스톱이 결제기준 원장으로 반영될 때까지 대기**(지연
  반영)하며, 그 동안 동일 미반영 체결에 §03-07 reconciler 의 self_submitted 분기
  (보정 skip · 원장 미advance · 재검출 가능, #1950)가 적용 가능한 경로면 그쪽을
  우선한다.
- **다중 self-order(같은 symbol에 둘 이상의 open buy) 또는 다중 bot 동일 symbol
  은 fallback을 적용하지 않는다**(미적용). 잔고는 총량만 주므로 excess를 어느
  주문에 얼마씩 귀속할지 결정할 수 없어, 보수적으로 외부/혼재 위험을 회피한다.
  이는 §11.7 **bounded known-limitation**이다. FIFO·비례 배분 등 다중 귀속 규칙은
  **본 스펙 비채택**이며 라이브 확인(#2317) 후 재검토한다.

이 full-fill 정확매칭 조건은 partial 귀속이 동시 외부 매수를 self로 흡수하는
경로(예: ante 미체결 100, self 부분 미기록 50, 숨은 외부 매수 10 → partial
`excess 60`)를 **fallback 대상에서 제외**한다(`60 != 100` → 미적용). 이 케이스는
D+1 ccld 백스톱으로 반영되며, fallback이 외부분을 흡수하지 않는다. 단 외부 매수가
**정확히** 주문 수량을 채우는 협소 케이스(self 부분 + 외부 = ordered_qty)는
§11.7 bounded known-limitation으로 남는다.

### 11.4 멱등성과 avg_price 한계 (late-ccld no-op)

- **멱등**: fallback이 `apply_cumulative`로 누적을 advance한 뒤, 나중에
  `get_order_history`가 같은 체결을 반환해도 `record_fill` CAS의 단조성
  (`recorded_filled_qty < :c`)으로 **no-op**이 된다(§4.4·§5). 같은 체결을 잔고
  경로·ccld 경로로 몇 번 관측하든 포지션은 정확히 1회 반영된다.
- **late-ccld 불일치 reconcile alert (over-attribution 관측, normative)**:
  fallback이 full fill(`observed_cumulative = ordered_qty`)로 advance한 뒤, D+1
  ccld가 그 주문에 대해 **더 낮은 절대 누적**(`recorded_filled_qty`보다 작은 실
  체결 누적)을 반환하면 CAS 단조성으로 **no-op**이라 잔고가 흡수했던 분(예:
  §11.7의 협소 외부 매수)을 사후 정정할 수 없다. 이는 비가역이므로 정정은 못
  하나, **`PositionMismatchEvent`/`NotificationEvent` reconcile alert로
  surface**해 잠재 over-attribution을 침묵 흡수하지 않고 관측 가능하게 한다.
  alert는 `(account_id, broker_order_id)`, fallback이 advance한 누적
  (`recorded_filled_qty`), ccld가 반환한 더 낮은 절대 누적, 차이를 싣는다. 이
  경보는 §11.7 bounded known-limitation(협소 외부 흡수)을 **운영 관측 가능**하게
  만드는 백스톱이다.
- **bounded fallback-verification 폴 (alert 도달성, normative)**: fallback이
  주문을 full fill(`recorded_filled_qty = ordered_qty`)로 올리면 그 주문은
  `filled`(terminal)가 되어 다음 사이클 `get_open_orders`에서 빠진다. 이때
  §6.1·§11.2의 event-gated 폴이 open만 게이트로 삼으면 ccld를 더 폴하지 않아 위
  late-ccld alert가 **도달 불가(dead code)** 가 된다. 따라서 fallback이 advance한
  주문을 **in-memory verify set**(`broker_order_id → {fallback이 advance한
  recorded, submitted_date}`)에 등록하고, 폴 게이트를 **open이 있거나 verify set이
  비어있지 않으면** ccld를 폴하도록 확장한다(open·verify가 둘 다 없으면 여전히
  미폴 — §11.2 rate budget 유지). 폴 window의 `from_date`는 verify 항목의
  `submitted_date`까지 거슬러 덮어 ccld가 그 주문을 관측할 수 있게 한다. ccld가
  verify 주문에 대해 `recorded`보다 **낮은 양수 누적**을 주면 위 alert를 발행하고
  그 항목을 verify에서 제거하며, 동일/높은 누적(정상 advance/멱등)이면 조용히
  제거한다. verify set은 **bounded**다: ccld 1회 관측 시 제거되고, 그 전이라도
  영업일 경계(`submitted_date < today`, §8 `expire_stale`과 같은 D+1 경계)에
  정리되어 무한 누적되지 않는다. verify set은 **in-memory 보조 상태일 뿐**이며
  OrderTracker/positions/trades/outbox를 직접 수정하지 않는다(§11.8 단일 권위
  보존).
- **avg_price 근거**: fallback의 평균 체결가는 **잔고 평단(`get_positions`)**을
  근거로 쓴다(잔고가 제공하는 유일한 가격 정보). 주문가가 아니다.
- **known-limitation(정정 없음)**: fallback이 먼저 쓴 `avg_fill_price`는 나중에
  ccld가 실체결가를 반환해도 **정정되지 않는다**. late-ccld가 같은 누적량을
  주면 §11.4 멱등으로 no-op이라 가격 update 경로를 타지 않기 때문이다(잔고 평단
  근거가 유지된다). 가격 정밀도 정정은 라이브 체결-level 데이터 계약이 필요한
  out-of-scope(§11.7).

### 11.5 EOD/terminal 상호작용

- **terminal 제외**: `cancelled`·`rejected`·`failed`·`expired` 등 terminal로 전이
  된 주문은 fallback 대상이 아니다(non-terminal capacity만 대상).
- **expire_stale은 fallback 후**: §11.2 순서대로 `expire_stale`은 fallback이
  끝난 뒤 실행한다. 만료를 fallback 앞에 두면 모의 당일 미반영 체결을 가진 open이
  복구 전에 `expired`로 전이되어 fallback이 대상을 잃고, §8 poll-first 회귀
  (미복구 체결의 "외부 매수" 오분류)가 재현된다.
- **verify set EOD 정리**: §11.4 bounded fallback-verification의 in-memory verify
  set은 `expire_stale`과 같은 영업일 경계에서, `submitted_date < today`(D+1 이후)인
  항목을 정리한다. 당일 항목은 그날의 late-ccld 검증을 위해 유지하며, ccld가 한 번
  관측되면 그 전이라도 즉시 제거된다(bounded — 무한 누적 방지).

### 11.6 적용 범위 (모의 기본 · 실전 분리)

- **KIS paper(`is_paper=true`) 한정 기본 활성**. 모의 당일 ccld 지연이 확정된
  환경이므로 기본 켠다.
- **live는 capability/config flag로 분리**한다. `EXCG_ID_DVSN_CD`·신
  tr_id(`VTTC0081R`)의 **당일 반영 효과는 #2317 라이브 A/B로 확인됐다**(레거시
  `VTTC8001R` 0행 vs 신 `VTTC0081R` 당일 반영, #2349 적용). 다만 라이브 ccld
  지연 폭(D+1 vs 장중 분 단위) 등 잔여 라이브 의존 항목은 여전히 닫히지 않아,
  라이브 활성은 그 잔여 검증 뒤에만 허용한다(known-limitation §11.7).

### 11.7 bounded known-limitation

본 fallback은 잔고가 **총량(누적)만** 제공한다는 한계 위에서 보수적으로
설계됐고, 다음은 **bounded known-limitation**으로 선언한다:

- **협소 외부 흡수(paper-only, 정직한 한계 선언)**: 본 fallback은 "외부 매수를
  self로 흡수하지 않는다"를 **단정하지 않는다**. full-fill 정확매칭
  (`excess == ordered_qty`, §11.3)은 partial 혼재(`excess != ordered_qty`)를
  제외하지만, **외부 매수가 정확히 주문 수량을 보충하는 협소 케이스**(self 부분
  미기록 + 동시 외부 매수의 합이 우연히 `ordered_qty`와 같아 `excess ==
  ordered_qty`가 되는 경우)에서는 fallback이 그 **외부분까지 self로 비가역
  흡수**할 수 있다(CAS 단조 → late ccld가 실제 더 낮은 self 누적을 줘도 no-op).
  이를 **paper-only bounded known-limitation**으로 명시한다. 위험창이 협소한
  근거: ① paper는 테스트 환경이라 동일 symbol 동시 외부 매수가 드물다, ②
  full-fill 정확매칭 조건이 위험창을 `excess == ordered_qty` 정확 일치로
  협소화한다(임의 partial은 §11.3에서 제외), ③ §11.4 late-ccld reconcile alert가
  사후 over-attribution을 **관측 가능**하게 한다(침묵 흡수 아님). 같은 미반영
  체결에 #1950의 **가역 skip**(보정 skip · 원장 미advance · 재검출 가능, §03-07)이
  적용 가능한 경로에서는 그 가역 경로를 **우선**한다(비가역 fallback보다 안전).
  live 확장은 §11.6·#2317 검증 뒤에만 허용한다.
- **다중 self-order/다중 bot 동일 symbol 미적용**(§11.3): 유일 open buy일 때만
  귀속. 다중이면 fallback 미적용(외부 검출 지연 = 매칭 주문 해소 시점 ≤ EOD,
  reconciler §03-07 경계와 동형). 다중 귀속(FIFO 등)은 비채택.
- **partial-fill 추적 한계**: 잔고는 누적만 주므로 부분 체결의 중간 경로를
  재구성하지 못한다. fallback은 `recorded_filled_qty == 0`인 미복구 주문에
  한해 `excess == ordered_qty`일 때만 full fill로 advance하며, 그 외 partial
  excess는 D+1 ccld 백스톱에 위임한다(미적용).
- **avg_price 정정 없음**(§11.4): 잔고 평단 근거 유지, ccld 실체결가로 사후
  정정 안 함.
- **Treasury 비례 정산**: §9의 pre-existing 한계(부분 체결 비례 정산 미지원)는
  fallback이 악화시키지 않으며 별도 후속 이슈로 둔다.
- **라이브 의존(#2317)**: `EXCG_ID_DVSN_CD`·신 tr_id(`VTTC0081R`, #2349)의 당일
  반영 효과는 **#2317 라이브 A/B로 확인 완료**다(레거시 `8001R` 0행 vs 신
  `0081R` 당일 반영). 다만 지연 폭 확정, multi-order/partial 식별 가능성(#2353),
  live 활성·다중 귀속 완화는 **여전히 라이브 의존**으로 남으며 #2317 결과 뒤
  재검토한다.

### 11.8 FillApplier 단일 권위 (직접 수정 금지)

fallback도 **반드시 `FillApplier.apply_cumulative` 경로로만 수렴**한다. fallback이
`OrderTracker`(`recorded_filled_qty` CAS)·`positions`·`trades`·`fill_outbox`를
**직접 수정해서는 안 된다**. 산출한 `(account_id, broker_order_id,
observed_cumulative=ordered_qty, avg_price=잔고평단,
submitted_date)`(§11.3 full-fill 정확매칭)를 `apply_cumulative`에 넘기면, §5의 단일 트랜잭션
(CAS advance + TradeRecord +
PositionHistory.on_trade + outbox INSERT)과 commit-후 1회 이벤트 발행, §5.1 crash
원자성, §10 결정적 `fill_dedup_key`가 그대로 적용된다. 이로써 fallback은 새
권위자를 만들지 않고 position ownership invariant(Trade 모듈 단일 소유)를
보존한다.
